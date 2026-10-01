"""
Central configuration — loads from environment variables or a .env file.
All secrets live here. Nothing is hardcoded.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default


def _env_bool(key: str, default: bool = False) -> bool:
    return os.getenv(key, str(default)).lower() in ("1", "true", "yes")


# ---------------------------------------------------------------------------
# Auto-load .env if present (works without python-dotenv via manual parse)
# ---------------------------------------------------------------------------
def _load_dotenv(path: str = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key   = key.strip()
        value = value.strip().strip('"').strip("'")
        # Strip inline comments — e.g. "25  # Alert when VIX crosses this" → "25"
        if " #" in value:
            value = value[:value.index(" #")].strip()
        # Override if key is absent OR if the existing value is empty
        # (empty shell env vars would otherwise shadow .env values)
        if key and (key not in os.environ or not os.environ[key]):
            os.environ[key] = value


_load_dotenv()


# ---------------------------------------------------------------------------
# Config dataclass
# ---------------------------------------------------------------------------
@dataclass
class Config:
    # ── AI providers ─────────────────────────────────────────────────────
    ai_provider: str    = field(default_factory=lambda: _env("AI_PROVIDER", "auto"))
    ai_model: str       = field(default_factory=lambda: _env("AI_MODEL", ""))

    anthropic_api_key:    str = field(default_factory=lambda: _env("ANTHROPIC_API_KEY"))
    openai_api_key:       str = field(default_factory=lambda: _env("OPENAI_API_KEY"))
    gemini_api_key:       str = field(default_factory=lambda: _env("GEMINI_API_KEY"))
    ollama_url:           str = field(default_factory=lambda: _env("OLLAMA_URL", "http://localhost:11434/api/generate"))

    # ── News API keys ────────────────────────────────────────────────────
    newsapi_key:          str = field(default_factory=lambda: _env("NEWSAPI_KEY"))
    finnhub_key:          str = field(default_factory=lambda: _env("FINNHUB_KEY"))
    alpha_vantage_key:    str = field(default_factory=lambda: _env("ALPHA_VANTAGE_KEY"))

    # ── Sectors to analyse ───────────────────────────────────────────────
    # Comma-separated in env: SECTORS=technology,artificial_intelligence,crypto
    # Leave blank to analyse ALL sectors
    sectors: List[str] = field(default_factory=lambda: (
        [s.strip() for s in _env("SECTORS").split(",") if s.strip()]
        or []
    ))

    # ── News fetching ────────────────────────────────────────────────────
    max_articles_total:   int  = field(default_factory=lambda: _env_int("MAX_ARTICLES", 200))
    max_per_feed:         int  = field(default_factory=lambda: _env_int("MAX_PER_FEED", 15))
    fetch_rss:            bool = field(default_factory=lambda: _env_bool("FETCH_RSS", True))
    fetch_newsapi:        bool = field(default_factory=lambda: _env_bool("FETCH_NEWSAPI", True))
    fetch_finnhub:        bool = field(default_factory=lambda: _env_bool("FETCH_FINNHUB", True))
    fetch_alpha_vantage:  bool = field(default_factory=lambda: _env_bool("FETCH_ALPHA_VANTAGE", True))

    # ── Market data ──────────────────────────────────────────────────────
    market_top_n_tickers: int  = field(default_factory=lambda: _env_int("MARKET_TOP_N", 5))
    fetch_macro_context:  bool = field(default_factory=lambda: _env_bool("FETCH_MACRO", True))

    # ── Output ───────────────────────────────────────────────────────────
    output_dir:           str  = field(default_factory=lambda: _env("OUTPUT_DIR", "reports"))
    export_json:          bool = field(default_factory=lambda: _env_bool("EXPORT_JSON", True))
    export_html:          bool = field(default_factory=lambda: _env_bool("EXPORT_HTML", True))
    open_html_in_browser: bool = field(default_factory=lambda: _env_bool("OPEN_BROWSER", False))

    # ── Notifications ────────────────────────────────────────────────────
    slack_webhook_url:    str  = field(default_factory=lambda: _env("SLACK_WEBHOOK_URL"))
    email_to:             str  = field(default_factory=lambda: _env("EMAIL_TO"))
    smtp_host:            str  = field(default_factory=lambda: _env("SMTP_HOST", "smtp.gmail.com"))
    smtp_port:            int  = field(default_factory=lambda: _env_int("SMTP_PORT", 587))
    smtp_user:            str  = field(default_factory=lambda: _env("SMTP_USER"))
    smtp_password:        str  = field(default_factory=lambda: _env("SMTP_PASSWORD"))
    desktop_notify:       bool = field(default_factory=lambda: _env_bool("DESKTOP_NOTIFY", False))
    resend_api_key:       str  = field(default_factory=lambda: _env("RESEND_API_KEY"))
    telegram_bot_token:   str  = field(default_factory=lambda: _env("TELEGRAM_BOT_TOKEN"))
    telegram_chat_id:     str  = field(default_factory=lambda: _env("TELEGRAM_CHAT_ID"))

    # ── Run settings ─────────────────────────────────────────────────────
    max_opportunities:    int  = field(default_factory=lambda: _env_int("MAX_OPPORTUNITIES", 10))
    log_level:            str  = field(default_factory=lambda: _env("LOG_LEVEL", "INFO"))

    # ── Helpers ──────────────────────────────────────────────────────────
    def provider_kwargs(self) -> dict:
        """Return provider credential kwargs for AI calls."""
        return {
            "anthropic_key":   self.anthropic_api_key,
            "openai_key":      self.openai_api_key,
            "gemini_key":      self.gemini_api_key,
            "ollama_url":      self.ollama_url,
        }

    def has_any_ai_key(self) -> bool:
        return bool(
            self.anthropic_api_key
            or self.openai_api_key
            or self.gemini_api_key
        )

    def report_stem(self) -> str:
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


# Singleton
_config: Optional[Config] = None

def get_config() -> Config:
    global _config
    if _config is None:
        _config = Config()
    return _config
