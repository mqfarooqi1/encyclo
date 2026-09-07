"""Application configuration.

Values come from (in order of precedence): explicit constructor arguments,
environment variables, a local .env file, then safe defaults. The application
must be fully functional with no configuration at all -- every optional
capability degrades to a clearly-labelled "unavailable" state rather than
silently failing or, worse, faking a result.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

AIProvider = Literal["none", "anthropic", "openai", "local"]

_TRUE = {"1", "true", "yes", "on"}


def _load_dotenv(path: Path) -> None:
    """Populate os.environ from a .env file without overriding real env vars."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def is_frozen() -> bool:
    """True when running from a PyInstaller bundle rather than a checkout."""
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def project_root() -> Path:
    """Where the application's *read-only* files live.

    In a source checkout this is the repository root. In a packaged build it is
    the bundle's extraction directory, which is read-only and thrown away when
    the process exits — so nothing may be written here.
    """
    if is_frozen():
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parents[2]


def default_data_dir() -> Path:
    """Where the databases belong when nobody has said otherwise.

    A checkout keeps `data/` beside the code, which is convenient and easy to
    delete. An installed or packaged build must not: the bundle directory is
    read-only, and `site-packages` is the wrong place for a person's bookmarks
    and notes. Those go to the platform's own per-user location, so a reinstall
    or an upgrade leaves them untouched.
    """
    if not is_frozen():
        root = project_root()
        # An editable checkout has its content packs alongside; an installed
        # wheel does not, and should use the per-user location instead.
        if (root / "content" / "packs").is_dir():
            return root / "data"

    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "ModernEncarta"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "ModernEncarta"
    base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "modern-encarta"


@dataclass(frozen=True, slots=True)
class Config:
    data_dir: Path
    content_dir: Path
    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "INFO"
    ai_provider: AIProvider = "none"
    ai_model: str = ""
    local_ai_base_url: str = "http://127.0.0.1:11434"
    allow_network: bool = False
    # Secrets are read on demand and never stored on this object, so they cannot
    # be accidentally serialised into a log line or an API response.
    _secret_env: dict[str, str] = field(default_factory=dict, repr=False)

    @property
    def content_db(self) -> Path:
        return self.data_dir / "encarta-content.db"

    @property
    def user_db(self) -> Path:
        return self.data_dir / "encarta-user.db"

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"

    def api_key(self) -> str | None:
        """Return the API key for the configured provider, or None."""
        env_var = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}.get(
            self.ai_provider
        )
        return os.environ.get(env_var) if env_var else None

    @classmethod
    def load(cls, data_dir: Path | str | None = None) -> Config:
        root = project_root()
        _load_dotenv(root / ".env")
        resolved_data = Path(
            data_dir or os.environ.get("ENCARTA_DATA_DIR") or default_data_dir()
        ).expanduser()
        provider = os.environ.get("ENCARTA_AI_PROVIDER", "none").strip().lower()
        if provider not in ("none", "anthropic", "openai", "local"):
            provider = "none"
        return cls(
            data_dir=resolved_data,
            content_dir=Path(os.environ.get("ENCARTA_CONTENT_DIR") or (root / "content")),
            host=os.environ.get("ENCARTA_HOST", "127.0.0.1"),
            port=int(os.environ.get("ENCARTA_PORT", "8000")),
            log_level=os.environ.get("ENCARTA_LOG_LEVEL", "INFO").upper(),
            ai_provider=provider,  # type: ignore[arg-type]
            ai_model=os.environ.get("ENCARTA_AI_MODEL", ""),
            local_ai_base_url=os.environ.get(
                "ENCARTA_LOCAL_AI_BASE_URL", "http://127.0.0.1:11434"
            ),
            allow_network=os.environ.get("ENCARTA_ALLOW_NETWORK", "0").lower() in _TRUE,
        )

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.media_dir.mkdir(parents=True, exist_ok=True)
