"""
auth.py — GradeOps Authentication & Role-Based Access Control
Implements JWT token auth with Instructor vs TA role enforcement.

Endpoints:
    POST /api/v1/auth/register
    POST /api/v1/auth/login
    GET  /api/v1/auth/me

FastAPI dependencies:
    require_instructor  — raises 403 if caller is not an Instructor
    require_ta_or_above — raises 403 if caller is neither TA nor Instructor
    get_current_user    — returns the logged-in UserORM row (any role)

Users are now stored in PostgreSQL via SQLAlchemy async (see database.py).
The old in-memory _user_db dict has been removed.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import UserORM, get_db
from models import UserRole

logger = logging.getLogger(__name__)

auth_router = APIRouter(prefix="/auth", tags=["auth"])


# ─────────────────────────────────────────────
# Password hashing
# ─────────────────────────────────────────────

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_context.verify(plain, hashed)


# ─────────────────────────────────────────────
# Pydantic schemas
# ─────────────────────────────────────────────

class UserCreate(BaseModel):
    email:     EmailStr
    password:  str
    full_name: str
    # Role is NOT accepted from the payload.
    # All self-registered users are TAs.
    # Only an existing Instructor can elevate a role via an admin endpoint.


class UserOut(BaseModel):
    user_id:    str
    email:      str
    full_name:  str
    role:       UserRole
    created_at: datetime

    model_config = {"from_attributes": True}   # allow construction from ORM objects


class UserInDB(UserOut):
    hashed_password: str

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    token_type:   str = "bearer"
    user:         UserOut


# ─────────────────────────────────────────────
# JWT helpers
# ─────────────────────────────────────────────

def _create_access_token(data: dict) -> str:
    payload = data.copy()
    expire  = datetime.now(timezone.utc) + timedelta(hours=settings.jwt_expire_hours)
    payload.update({"exp": expire})
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


# ─────────────────────────────────────────────
# FastAPI OAuth2 scheme
# ─────────────────────────────────────────────

_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


async def get_current_user(
    token: Annotated[str, Depends(_oauth2_scheme)],
    db:    AsyncSession = Depends(get_db),
) -> UserORM:
    """Decode JWT, look up user in PostgreSQL, return the ORM row."""
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        email: str | None = payload.get("sub")
        if email is None:
            raise credentials_exc
    except JWTError:
        raise credentials_exc

    result = await db.execute(select(UserORM).where(UserORM.email == email))
    user = result.scalar_one_or_none()
    if user is None:
        raise credentials_exc
    return user


async def require_instructor(
    current_user: Annotated[UserORM, Depends(get_current_user)],
) -> UserORM:
    """Dependency: only Instructors may proceed."""
    if current_user.role != UserRole.INSTRUCTOR:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Instructor role required",
        )
    return current_user


async def require_ta_or_above(
    current_user: Annotated[UserORM, Depends(get_current_user)],
) -> UserORM:
    """Dependency: TAs and Instructors may proceed."""
    if current_user.role not in (UserRole.TA, UserRole.INSTRUCTOR):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="TA or Instructor role required",
        )
    return current_user


# ─────────────────────────────────────────────
# Auth routes
# ─────────────────────────────────────────────

@auth_router.post("/register", response_model=UserOut, status_code=201)
async def register(body: UserCreate, db: AsyncSession = Depends(get_db)):
    """
    Register a new user.
    All self-registered users receive the TA role.
    Instructor accounts must be promoted by an admin.
    """
    existing = await db.execute(select(UserORM).where(UserORM.email == body.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Email already registered")

    user = UserORM(
        user_id=str(uuid.uuid4()),
        email=body.email,
        full_name=body.full_name,
        role=UserRole.TA,          # hard-coded — callers cannot self-assign INSTRUCTOR
        hashed_password=hash_password(body.password),
        created_at=datetime.now(timezone.utc),
    )
    db.add(user)
    await db.flush()   # get DB-generated defaults without committing yet
    logger.info("New user registered: %s (%s)", user.email, user.role)
    return UserOut.model_validate(user)


@auth_router.post("/login", response_model=TokenResponse)
async def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: AsyncSession = Depends(get_db),
):
    """
    Authenticate with email + password. Returns a JWT bearer token.

    Demo credentials (seeded automatically on first startup):
        instructor@gradeops.dev / instructor123
        ta@gradeops.dev         / ta123
    """
    result = await db.execute(select(UserORM).where(UserORM.email == form_data.username))
    user = result.scalar_one_or_none()

    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = _create_access_token({"sub": user.email, "role": user.role})
    logger.info("Login: %s (%s)", user.email, user.role)
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@auth_router.get("/me", response_model=UserOut)
async def me(current_user: Annotated[UserORM, Depends(get_current_user)]):
    """Return the currently authenticated user's profile."""
    return UserOut.model_validate(current_user)
