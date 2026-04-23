"""Application settings loaded from environment / .env file."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Target Exchange server
    exchange_host: str
    exchange_user: str
    exchange_password: str
    exchange_email: str = ""
    ews_url: str = ""
    ssl_verify: str | bool = "false"

    # EAS-specific
    eas_device_id: str = "EAS0LEGCLIENT0001"
    eas_protocol: str = "14.1"

    # Router
    preferred_backend: str = "ews"

    # State
    state_dir: str = "/app/state"

    # MCP server
    mcp_api_key: str
    server_host: str = "0.0.0.0"
    server_port: int = 8903
    log_level: str = "INFO"
    public_url: str = ""

    @property
    def verify(self) -> bool | str:
        """Turn SSL_VERIFY into what httpx / exchangelib / requests expect."""
        v = str(self.ssl_verify).strip()
        if v.lower() in ("false", "0", "no"):
            return False
        if v.lower() in ("true", "1", "yes"):
            return True
        # path to CA bundle
        return v

    @property
    def ews_effective_url(self) -> str:
        return self.ews_url or f"https://{self.exchange_host}/EWS/Exchange.asmx"


settings = Settings()  # type: ignore[call-arg]
