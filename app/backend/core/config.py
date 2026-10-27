from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    jwt_secret_key: str = Field(min_length=32)
    access_token_expire_minutes: int = 30
    cookie_secure: bool = False
    allowed_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    rag_enabled: bool = False
    rag_service_url: str = "http://127.0.0.1:8001/recommend"
    public_app_url: str = "http://localhost:5173"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = "Clinical Compass <notifications@localhost>"
    smtp_security: str = "starttls"  # starttls, ssl, or none (local Mailpit only)

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
