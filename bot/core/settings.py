"""
Settings for the DiscordBot. All browser flags live in Settings.browser (see BrowserConfig).
"""

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings


class BrowserConfig(BaseModel):
    headless: bool = False  # default is *not* headless
    visible: bool = True  # visible by default
    read_only: bool = False  # <‑‑ NEW – block mutating actions when True
    launch_timeout_ms: int = 60000
    proxy_enabled: bool = False
    worker_idle_timeout_sec: float = 120.0  # Seconds before an idle worker shuts down
    slow_mo: int = 0  # Milliseconds to slow down Playwright operations, 0 to disable

    model_config = {"extra": "ignore"}

    @field_validator("visible")
    @classmethod
    def _exclusive_with_headless(cls, v: bool, info: ValidationInfo) -> bool:  # noqa: D401
        """Prevent `visible` and `headless` from both being True."""
        if v and info.data.get("headless"):
            raise ValueError("`visible=True` and `headless=True` cannot both be set")
        return v


class RedisConfig(BaseModel):
    enabled: bool = False
    url: str | None = None

    model_config = {"extra": "ignore"}


class QueueConfig(BaseModel):
    inbound: int = 500  # inbound frames (proxy)
    outbound: int = 200  # outbound frames (AI → server)
    command: int = 100  # browser command queue per channel
    alerts: int = 200  # lifecycle → owner DM

    model_config = {"extra": "ignore"}


class Settings(BaseSettings):
    if TYPE_CHECKING:  # pragma: no cover

        def __init__(self, **data: Any) -> None: ...

    """
    Settings for the DiscordBot.
    
    Browser session config:
        chrome_profile_dir (env: CHROME_PROFILE_DIR)
        chrome_profile_name (env: CHROME_PROFILE_NAME)
        chromedriver_path (env: CHROMEDRIVER_PATH)
        browser_download_dir (env: BROWSER_DOWNLOAD_DIR)
    Browser flags live in Settings.browser (see BrowserConfig).
    """
    discord_token: str

    gemini_api_key: str | None = None
    openai_api_key: str | None = None

    # Bot owner Discord user ID – used for restricted personas
    owner_id: int | None = None

    # --- Tunable bot behaviour ---
    # Redis history backend config (nested)
    redis: RedisConfig = RedisConfig()

    conversation_max_turns: int = 8  # Rolling chat history length per channel + persona
    discord_chunk_size: int = 1900  # Characters per Discord message chunk
    # gemini_model: str = "gemini-2.5-flash"  # Backup Gemini model name, quota is shared 500 per day.
    gemini_model: str = "gemini-2.5-flash-preview-04-17"  # Default Gemini model name

    # Optional external JSON for additional personalities
    personalities_file: str | None = None

    # --- Proxy settings ---
    proxy_enabled: bool = False
    proxy_port: int | None = None
    proxy_cert_dir: str | None = ".mitm_certs"  # Default cert directory for mitmproxy

    # --- Browser session config ---
    chrome_profile_dir: str | None = None
    chrome_profile_name: str | None = "Profile 1"
    chromedriver_path: str | None = None
    browser_download_dir: str | None = None
    browser_version_main: int | None = (
        None  # Allow overriding Chrome major version (None = auto-detect)
    )

    browser: BrowserConfig = BrowserConfig()
    queues: QueueConfig = QueueConfig()

    # --- URL guard-rails ---
    allowed_hosts: list[str] = []  # e.g. ["github.com", "docs.python.org"]

    # --- observability ---
    metrics_port: int = 9200  # Prometheus exporter port (0 = disabled)

    @field_validator("allowed_hosts", mode="before")
    @classmethod
    def _split_csv(cls, v: Any) -> list[str]:  # noqa: D401
        """
        Allow simple comma‑separated strings in .env:

            ALLOWED_HOSTS=github.com,docs.python.org
        """
        if isinstance(v, str):
            return [h.strip() for h in v.split(",") if h.strip()]
        if isinstance(v, list):
            # Ensure all items are strings
            return [str(item) for item in v]
        # Default to empty list for unexpected types
        return []

    model_config = {
        "env_file": ".env",
        "case_sensitive": False,
        "extra": "allow",
        "env_nested_delimiter": "__",  # Enable nested env vars like REDIS__URL
    }

    @field_validator("discord_token")
    @classmethod
    def _must_exist(cls, v: str) -> str:
        # Reject only truly empty/placeholder tokens
        placeholder = {"", "YOUR_TOKEN_HERE"}
        if v in placeholder:
            raise ValueError("DISCORD_TOKEN is required")
        return v


# Export a singleton but fall back to a dummy token during static analysis
try:
    settings: "Settings" = Settings()  # real env-driven instance
except ValueError:  # DISCORD_TOKEN missing under CI / mypy
    settings = Settings(discord_token="dummy")

# ---------------------------------------------------------------------------
# Global constants
# ---------------------------------------------------------------------------
# Unified Discord message length limit (characters).  This value should be used
# by all helpers/cogs when checking or chunking content for Discord messages so
# that limits remain consistent across the codebase.
DISCORD_LIMIT: int = settings.discord_chunk_size

__all__ = [
    "Settings",
    "BrowserConfig",
    "QueueConfig",
    "RedisConfig",
    "DISCORD_LIMIT",
]
