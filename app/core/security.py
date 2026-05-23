from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Union

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from pydantic import ValidationError

from app.core.config import settings
from app.models.token import TokenPayload

# bcrypt has a hard 72-byte input limit; longer passwords are truncated.
_BCRYPT_MAX_BYTES = 72

# Tokens are obtained from the login endpoint; FastAPI extracts the
# bearer token from the Authorization header for protected routes.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login")


def create_access_token(
    subject: Union[str, Any],
    role: str = "customer",
    expires_delta: Optional[timedelta] = None,
) -> str:
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )
    to_encode = {"exp": expire, "sub": str(subject), "role": role}
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Check a plaintext password against a bcrypt hash. Never raises."""
    try:
        pw = plain_password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
        return bcrypt.checkpw(pw, hashed_password.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def get_password_hash(password: str) -> str:
    """Produce a bcrypt hash for a plaintext password."""
    pw = password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode("utf-8")


def decode_token(token: str) -> TokenPayload:
    """Decode and validate a JWT. Raises 401 on any failure."""
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        token_data = TokenPayload(**payload)
    except (JWTError, ValidationError):
        raise credentials_exc
    if token_data.sub is None:
        raise credentials_exc
    return token_data


async def get_current_user(token: str = Depends(oauth2_scheme)) -> TokenPayload:
    """FastAPI dependency: require any authenticated user."""
    return decode_token(token)


def require_role(*allowed_roles: str):
    """Build a dependency that requires one of the given RBAC roles.

    Per CLAUDE.md: Admins ingest/manage datasets; Customers query only.
    Enforce at the gateway — attach this to protected routers.
    """

    async def _checker(
        user: TokenPayload = Depends(get_current_user),
    ) -> TokenPayload:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions for this operation",
            )
        return user

    return _checker
