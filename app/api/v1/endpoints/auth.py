"""Authentication endpoint.

There is no database. The single bootstrap admin is loaded from environment
variables holding a *bcrypt hash* of the password — the plaintext password
never lives in code or config. If the env vars are unset, login fails closed.

Seed a hash with:
    uv run python -c "from app.core.security import get_password_hash; \
        print(get_password_hash('your-password'))"
then set BOOTSTRAP_ADMIN_USERNAME and BOOTSTRAP_ADMIN_PASSWORD_HASH in .env
(loaded via app.core.config.settings).

Replace this with a real user store + RBAC table before production.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from app.core import security
from app.core.config import settings
from app.models.token import Token

router = APIRouter()


@router.post("/login", response_model=Token)
async def login(form_data: Annotated[OAuth2PasswordRequestForm, Depends()]):
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect username or password",
    )

    # Fail closed: no configured admin means no login path exists.
    if not settings.BOOTSTRAP_ADMIN_USERNAME or not settings.BOOTSTRAP_ADMIN_PASSWORD_HASH:
        raise invalid

    # Always run bcrypt verify to avoid leaking whether the username
    # matched via response timing.
    username_ok = form_data.username == settings.BOOTSTRAP_ADMIN_USERNAME
    password_ok = security.verify_password(
        form_data.password, settings.BOOTSTRAP_ADMIN_PASSWORD_HASH
    )
    if not (username_ok and password_ok):
        raise invalid

    access_token = security.create_access_token(subject=form_data.username, role="admin")
    return {"access_token": access_token, "token_type": "bearer"}
