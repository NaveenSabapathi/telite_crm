from starlette.responses import JSONResponse


class BodyLimitMiddleware:
    """Bound JSON request bytes even when Transfer-Encoding is chunked."""

    def __init__(self, app, limit=65536):
        self.app = app
        self.limit = limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        events = []
        size = 0
        while True:
            event = await receive()
            if event["type"] == "http.disconnect":
                return
            size += len(event.get("body", b""))
            if size > self.limit:
                return await JSONResponse({"error": {"code": "BODY_TOO_LARGE"}}, status_code=413)(scope, receive, send)
            events.append(event)
            if not event.get("more_body", False):
                break

        async def replay():
            return events.pop(0) if events else await receive()

        await self.app(scope, replay, send)
