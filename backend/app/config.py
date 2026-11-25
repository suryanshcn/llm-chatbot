import os
from dataclasses import dataclass, field


def _csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


@dataclass(frozen=True)
class Settings:
    api_keys: list[str] = field(default_factory=list)
    model: str = "gemini/gemini-2.5-flash-lite"
    database_url: str = "sqlite:////data/app.db"
    allowed_origins: list[str] = field(default_factory=list)
    enable_failure_simulation: bool = False
    default_system_prompt: str = "You are a helpful, concise assistant."

    @property
    def db_path(self) -> str:
        # sqlite:////data/app.db -> /data/app.db ; sqlite:///rel.db -> rel.db
        return self.database_url.removeprefix("sqlite:///")


def load_settings() -> Settings:
    """Read env at call time (not import time) so tests can override it."""
    return Settings(
        api_keys=_csv(os.getenv("LLM_API_KEYS", "")),
        model=os.getenv("LLM_MODEL", "gemini/gemini-2.5-flash-lite"),
        database_url=os.getenv("DATABASE_URL", "sqlite:////data/app.db"),
        allowed_origins=_csv(os.getenv("ALLOWED_ORIGINS", "http://localhost:3000")),
        enable_failure_simulation=os.getenv("ENABLE_FAILURE_SIMULATION", "false").lower() == "true",
        default_system_prompt=os.getenv(
            "DEFAULT_SYSTEM_PROMPT", "You are a helpful, concise assistant."
        ),
    )
