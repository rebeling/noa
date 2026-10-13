from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_DEFAULTS = {"", "YOUR_SUPER_SECRET_KEY", "changeme", "secret"}


class Settings(BaseSettings):
    PROJECT_NAME: str = "Noa"
    API_V1_STR: str = "/api/v1"

    # Required. Signs the JWTs; startup fails if unset or weak.
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # Explicit allowlist; "*" is rejected because requests carry credentials.
    CORS_ORIGINS: list[str] = ["http://localhost:8000"]

    OPENAI_API_KEY: str | None = None
    ANTHROPIC_API_KEY: str | None = None
    # A "claude-*" id routes to Anthropic, anything else to OpenAI.
    LLM_MODEL: str = "gpt-4o-mini"

    # Single bootstrap admin for the login endpoint. Password is stored only
    # as a bcrypt hash; login fails closed if either is unset.
    BOOTSTRAP_ADMIN_USERNAME: str | None = None
    BOOTSTRAP_ADMIN_PASSWORD_HASH: str | None = None

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")

    @field_validator("SECRET_KEY")
    @classmethod
    def _reject_insecure_secret(cls, v: str) -> str:
        if v.strip() in _INSECURE_DEFAULTS or len(v) < 32:
            raise ValueError(
                "SECRET_KEY must be a random value of at least 32 chars. Generate one with: "
                'python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
        return v

    @field_validator("CORS_ORIGINS")
    @classmethod
    def _reject_wildcard_origin(cls, v: list[str]) -> list[str]:
        if "*" in v:
            raise ValueError("CORS_ORIGINS must not contain '*' — list explicit origins.")
        return v


settings = Settings()
