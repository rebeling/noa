from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator
from typing import Optional, List

# Generate a fresh random secret with:
#   python -c "import secrets; print(secrets.token_urlsafe(48))"
# and set it in .env as SECRET_KEY=... — there is no insecure default.
_INSECURE_DEFAULTS = {"", "YOUR_SUPER_SECRET_KEY", "changeme", "secret"}


class Settings(BaseSettings):
    PROJECT_NAME: str = "Voice-Driven Dialogue Assistant"
    API_V1_STR: str = "/api/v1"

    # SECRET_KEY is mandatory — no default. Startup fails if unset so a
    # forgeable JWT signing key can never reach a running deployment.
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # Explicit CORS allowlist. Wildcard is rejected (see validator) because
    # it is unsafe combined with credentialed requests.
    CORS_ORIGINS: List[str] = ["http://localhost:8000"]

    OPENAI_API_KEY: Optional[str] = None

    # Bootstrap admin (Phase 1, no DB). Password is stored only as a
    # bcrypt hash; login fails closed if either is unset.
    BOOTSTRAP_ADMIN_USERNAME: Optional[str] = None
    BOOTSTRAP_ADMIN_PASSWORD_HASH: Optional[str] = None

    # Cognee Settings
    ENABLE_BACKEND_ACCESS_CONTROL: bool = True
    REQUIRE_AUTHENTICATION: bool = True

    # extra="ignore": .env also carries BOOTSTRAP_ADMIN_* read directly via
    # os.getenv in auth.py — those are not Settings fields.
    model_config = SettingsConfigDict(
        env_file=".env", case_sensitive=True, extra="ignore"
    )

    @field_validator("SECRET_KEY")
    @classmethod
    def _reject_insecure_secret(cls, v: str) -> str:
        if v.strip() in _INSECURE_DEFAULTS or len(v) < 32:
            raise ValueError(
                "SECRET_KEY must be set to a strong random value (>=32 chars). "
                "Generate one with: python -c \"import secrets; "
                "print(secrets.token_urlsafe(48))\""
            )
        return v

    @field_validator("CORS_ORIGINS")
    @classmethod
    def _reject_wildcard_origin(cls, v: List[str]) -> List[str]:
        if "*" in v:
            raise ValueError(
                "CORS_ORIGINS must not contain '*' — list explicit origins."
            )
        return v


settings = Settings()
