from contextlib import asynccontextmanager
from uuid import uuid4
from fastapi import FastAPI, Request, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from .config import settings
from .db import verify_runtime_role
from .middleware import BodyLimitMiddleware


def create_app(platform=False):
    @asynccontextmanager
    async def lifespan(app):
        verify_runtime_role("control" if platform else "tenant")
        if not platform and settings().operations_database_url:
            verify_runtime_role("operations")
        yield

    if not platform and len(settings().jwt_secret) < 48:
        raise RuntimeError("JWT_SECRET is required")
    if platform and len(settings().platform_jwt_secret) < 48:
        raise RuntimeError("Independent PLATFORM_JWT_SECRET is required")

    app = FastAPI(title="Telite CRM Platform" if platform else "Telite CRM", version="0.2.0", lifespan=lifespan)
    app.state.platform = platform
    app.add_middleware(BodyLimitMiddleware)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings().allowed_hosts.split(","))

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = uuid4()
        length = request.headers.get("content-length")
        if length and (not length.isdigit() or int(length) > 65536):
            return JSONResponse({"error": {"code": "BODY_TOO_LARGE"}}, status_code=413)
        response = await call_next(request)
        response.headers["X-Request-ID"] = str(request.state.request_id)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    def error(request, status, code):
        return JSONResponse({"error": {"code": code}, "request_id": str(request.state.request_id)}, status_code=status)

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return error(request, exc.status_code, exc.detail)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Never echo input values: validation errors can otherwise disclose passwords.
        return error(request, 422, "INVALID_INPUT")

    @app.exception_handler(IntegrityError)
    async def conflict(request, exc):
        return error(request, 409, "CONSTRAINT_CONFLICT")

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, exc):
        return error(request, 503, "DATABASE_UNAVAILABLE")

    @app.get("/health/live")
    def live():
        return {"status": "alive"}

    if platform:
        from .platform import router

        app.include_router(router)
    else:
        from .auth import router as auth
        from .tenant import router as tenant

        app.include_router(auth)
        app.include_router(tenant)
        from . import workforce, service_tickets, crm, reporting, privacy

        for module in (workforce, service_tickets, crm, reporting, privacy):
            app.include_router(module.router)
    return app
