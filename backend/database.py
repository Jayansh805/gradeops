"""
database.py — GradeOps SQLAlchemy Async Database Layer
Provides the async engine, session factory, Base, and a declarative
User ORM model that backs auth.py.

Requires:
    DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/gradeops
    (set in .env — see .env.example)

Usage:
    from database import get_db, UserORM

    async def my_route(db: AsyncSession = Depends(get_db)):
        user = await db.get(UserORM, some_id)
"""

import uuid
import logging
from datetime import datetime, timezone
from typing import AsyncGenerator

from sqlalchemy import (
    Column, String, Boolean, DateTime, Enum as SAEnum, text,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from config import settings
from models import UserRole

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Engine & session factory
# ─────────────────────────────────────────────

_engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,          # log SQL when DEBUG=true
    pool_pre_ping=True,           # verify connections before use
    pool_size=10,
    max_overflow=20,
)

AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=_engine,
    expire_on_commit=False,       # avoids lazy-load errors after commit
    autoflush=False,
)


# ─────────────────────────────────────────────
# ORM Base
# ─────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


# ─────────────────────────────────────────────
# User ORM model  (maps to `users` table)
# ─────────────────────────────────────────────

class UserORM(Base):
    __tablename__ = "users"

    user_id         = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email           = Column(String(255), unique=True, nullable=False, index=True)
    full_name       = Column(String(255), nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role            = Column(SAEnum(UserRole), nullable=False, default=UserRole.TA)
    is_active       = Column(Boolean, default=True, nullable=False)
    created_at      = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<UserORM {self.email!r} role={self.role}>"


# ─────────────────────────────────────────────
# FastAPI dependency
# ─────────────────────────────────────────────

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a database session; roll back on error, always close."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ─────────────────────────────────────────────
# Table creation helper (called from main.py on startup)
# ─────────────────────────────────────────────

async def init_db() -> None:
    """Create all tables and seed demo users if they don't exist."""
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables verified / created.")

    await _seed_demo_users()


async def _seed_demo_users() -> None:
    """Insert demo instructor + TA accounts when the DB is empty."""
    # Import here to avoid circular imports
    from auth import hash_password  # noqa: PLC0415

    demos = [
        ("instructor@gradeops.dev", "instructor123", "Dr. Demo Instructor", UserRole.INSTRUCTOR),
        ("ta@gradeops.dev",         "ta123",          "TA Demo",             UserRole.TA),
    ]

    async with AsyncSessionLocal() as session:
        for email, pw, name, role in demos:
            existing = await session.execute(
                text("SELECT 1 FROM users WHERE email = :e"),
                {"e": email},
            )
            if existing.scalar() is None:
                session.add(UserORM(
                    user_id=str(uuid.uuid4()),
                    email=email,
                    full_name=name,
                    role=role,
                    hashed_password=hash_password(pw),
                    created_at=datetime.now(timezone.utc),
                ))
        await session.commit()
        logger.info("Demo users seeded.")
