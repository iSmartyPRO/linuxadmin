from collections.abc import AsyncGenerator

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings
from app.core.setup_state import is_setup_complete


class Base(DeclarativeBase):
    pass


engine = None
AsyncSessionLocal = None


def configure_engine() -> None:
    """(Re)create the async SQLAlchemy engine from current settings."""
    global engine, AsyncSessionLocal
    get_settings.cache_clear()
    settings = get_settings()
    if engine is not None:
        # dispose synchronously via sync API when event loop may be running
        try:
            engine.sync_engine.dispose()
        except Exception:
            pass
    engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)
    AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


# Eager configure when settings already point at a DB (normal boot)
try:
    if get_settings().db_password or is_setup_complete():
        configure_engine()
except Exception:
    engine = None
    AsyncSessionLocal = None


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    if not is_setup_complete():
        raise HTTPException(status_code=503, detail="Initial setup required")
    if AsyncSessionLocal is None:
        configure_engine()
    assert AsyncSessionLocal is not None
    async with AsyncSessionLocal() as session:
        yield session


async def init_db() -> None:
    from app import models  # noqa: F401

    if engine is None:
        configure_engine()
    assert engine is not None
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
