"""Centralised application configuration.

All secrets/configuration are read from environment variables once
(backend/.env via python-dotenv) and imported from a single place. Dev
defaults are safe for local development only; production validation is
enforced when APP_ENV=production.

No sensitive values are ever logged.
"""

import os
import sys
import logging
from typing import Optional

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - imported only after deps installed
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

APP_ENV = os.getenv("APP_ENV", "development")

# Database locations
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./govrisk.db")
AUTH_DATABASE_URL = os.getenv("AUTH_DATABASE_URL", "sqlite:///./auth.db")

# JWT
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "govrisk-dev-secret-key-change-in-production")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))

# Authentication brute-force protection / rate limiting
# (must be positive integers; defaults are safe for a demo deployment)
AUTH_MAX_FAILED_ATTEMPTS = int(os.getenv("AUTH_MAX_FAILED_ATTEMPTS", "5"))
AUTH_LOCKOUT_MINUTES = int(os.getenv("AUTH_LOCKOUT_MINUTES", "15"))
AUTH_RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("AUTH_RATE_LIMIT_WINDOW_SECONDS", "300"))
AUTH_MAX_REQUESTS_PER_WINDOW = int(os.getenv("AUTH_MAX_REQUESTS_PER_WINDOW", "20"))

# AI / LLM layer (`AI_PROVIDER` may be empty to run deterministic-only)
AI_PROVIDER = os.getenv("AI_PROVIDER", "").strip().lower()
AI_API_KEY = os.getenv("AI_API_KEY", "").strip()
AI_MODEL = os.getenv("AI_MODEL", "").strip()
AI_API_BASE = os.getenv("AI_API_BASE", "").strip()  # optional custom endpoint
AI_TIMEOUT_SECONDS = float(os.getenv("AI_TIMEOUT_SECONDS", "30"))
AI_MAX_RETRIES = int(os.getenv("AI_MAX_RETRIES", "1"))  # bounded retries - never infinite
AI_ANALYSIS_TTL_HOURS = int(os.getenv("AI_ANALYSIS_TTL_HOURS", "6"))  # cached-analysis freshness
AI_ALERT_DEDUP_HOURS = int(os.getenv("AI_ALERT_DEDUP_HOURS", "168"))  # 7 days dedup window


def is_llm_available() -> bool:
    """True when a concrete LLM provider + key are configured."""
    return bool(AI_PROVIDER and AI_API_KEY)


def validate_config() -> None:
    """Bail loudly in production if required secrets are missing.

    Development defaults exist so the app runs out-of-the-box for the demo;
    they are never acceptable for production.
    """
    missing = []
    if not JWT_SECRET_KEY or "change-this" in JWT_SECRET_KEY or JWT_SECRET_KEY.startswith("govrisk-dev"):
        missing.append("JWT_SECRET_KEY (set a strong, unique value)")
    auth_limits = {
        "AUTH_MAX_FAILED_ATTEMPTS": AUTH_MAX_FAILED_ATTEMPTS,
        "AUTH_LOCKOUT_MINUTES": AUTH_LOCKOUT_MINUTES,
        "AUTH_RATE_LIMIT_WINDOW_SECONDS": AUTH_RATE_LIMIT_WINDOW_SECONDS,
        "AUTH_MAX_REQUESTS_PER_WINDOW": AUTH_MAX_REQUESTS_PER_WINDOW,
    }
    for name, value in auth_limits.items():
        if value <= 0:
            missing.append(f"{name} (must be a positive integer)")
    if APP_ENV == "production":
        if missing:
            raise SystemExit(
                "Refusing to start in production with insecure/incomplete "
                f"configuration. Missing: {', '.join(missing)}"
            )
        if is_llm_available() and not AI_MODEL:
            raise SystemExit("AI_MODEL is required when AI_PROVIDER is set")


# --------------------------------------------------------------------------
# Structured logging
# --------------------------------------------------------------------------
_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_FORMAT))
    root = logging.getLogger()
    root.handlers = [h for h in root.handlers if not isinstance(h, logging.StreamHandler)]
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    logging.getLogger("govrisk.ai").setLevel(logging.DEBUG)
    logging.getLogger("uvicorn").setLevel(logging.INFO)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"govrisk.ai.{name}")


ai_logger = get_logger("service")