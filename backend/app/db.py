from contextlib import contextmanager
from functools import lru_cache
from uuid import UUID
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, DeclarativeBase, Mapped, mapped_column, with_loader_criteria
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from .config import settings


class Base(DeclarativeBase):
    pass


class TenantRow:
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)


class TenantSession(Session):
    """Never usable outside one immutable tenant context, including raw SQL."""

    def __init__(self, *args, tenant_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._tenant_id = UUID(str(tenant_id)) if tenant_id else None


@event.listens_for(TenantSession, "after_begin")
def bind_context(session, transaction, connection):
    if session._tenant_id is None:
        raise PermissionError("Tenant context required")
    connection.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(session._tenant_id)})


@event.listens_for(TenantSession, "do_orm_execute")
def scope_query(state):
    tid = state.session._tenant_id
    if tid is None:
        raise PermissionError("Tenant context required")
    if state.is_orm_statement:
        if state.is_select:
            state.statement = state.statement.options(
                with_loader_criteria(TenantRow, lambda row: row.tenant_id == tid, include_aliases=True)
            )
        else:
            raise PermissionError("Use unit-of-work writes or reviewed tenant repositories")


@event.listens_for(TenantSession, "before_flush")
def scope_write(session, *_):
    if session._tenant_id is None:
        raise PermissionError("Tenant context required")
    for obj in session.new | session.dirty | session.deleted:
        if not isinstance(obj, TenantRow) or obj.tenant_id != session._tenant_id:
            raise PermissionError("Foreign tenant write rejected")


@lru_cache
def engine(kind="tenant"):
    cfg = settings()
    url = cfg.database_url if kind == "tenant" else cfg.control_database_url
    if not url:
        raise RuntimeError("Control database URL is not configured")
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)


@contextmanager
def tenant_db(tenant_id, kind="tenant"):
    with TenantSession(engine(kind), tenant_id=tenant_id) as session:
        with session.begin():
            yield session


@contextmanager
def control_db():
    with Session(engine("control")) as session:
        with session.begin():
            yield session


def one(db, query, **params):
    return db.execute(text(query), params).mappings().first()


def many(db, query, **params):
    return list(db.execute(text(query), params).mappings())


def run(db, query, **params):
    return db.execute(text(query), params)


def verify_runtime_role(kind):
    with engine(kind).connect() as conn:
        row = conn.execute(text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user")).one()
        owns = conn.execute(
            text("SELECT count(*) FROM pg_tables WHERE schemaname IN ('app','control') AND tableowner=current_user")
        ).scalar_one()
        if row.rolsuper or row.rolbypassrls or owns:
            raise RuntimeError("Runtime DB user must not be owner/superuser/BYPASSRLS")
