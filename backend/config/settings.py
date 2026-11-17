"""
Django settings for Evolving Cook (Phase 0 skeleton).

Env-driven via EnvironmentFile / .env (see scripts/deploy.sh).
Timezone: Europe/London. Bind target: 127.0.0.1:8000.
"""
from pathlib import Path
import os

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load local .env if present (systemd also injects EnvironmentFile)
load_dotenv(BASE_DIR / ".env")


def env(key: str, default: str | None = None) -> str | None:
    return os.environ.get(key, default)


def env_bool(key: str, default: bool = False) -> bool:
    raw = os.environ.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_list(key: str, default: list[str] | None = None) -> list[str]:
    raw = os.environ.get(key)
    if raw is None or raw.strip() == "":
        return list(default or [])
    return [part.strip() for part in raw.split(",") if part.strip()]


def env_int(key: str, default: int) -> int:
    """Positive integer from the environment. Unset uses default.

    A present but invalid value fails startup so a typo cannot silently
    leave a longer token lifetime than the operator asked for.
    """
    raw = os.environ.get(key)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise RuntimeError(f"{key} must be an integer number of seconds") from exc
    if value <= 0:
        raise RuntimeError(f"{key} must be a positive number of seconds")
    return value


SECRET_KEY = env("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("DJANGO_SECRET_KEY is required")

DEBUG = env_bool("DJANGO_DEBUG", False)

ALLOWED_HOSTS = env_list(
    "DJANGO_ALLOWED_HOSTS",
    default=["api.apidiscoverysolution.uk"],
)

# Exact host in production; local loopback kept for curl/systemd checks
if "127.0.0.1" not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append("127.0.0.1")
if "localhost" not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append("localhost")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "corsheaders",
    "django_q",
    "core",
    "catalog",
    "walks",
    "purchasing",
    "inventory",
    "planning",
    "assist",
    "api",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "catalog" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("PGDATABASE", "evolving_cook"),
        "USER": env("PGUSER", "evolving_cook_app"),
        "PASSWORD": env("PGPASSWORD", ""),
        "HOST": env("PGHOST", "127.0.0.1"),
        "PORT": env("PGPORT", "5432"),
        "CONN_MAX_AGE": 60,
        "OPTIONS": {"connect_timeout": 10},
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-gb"
TIME_ZONE = "Europe/London"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Cache backend for django-ratelimit (Phase 0: file-based so multi-worker shares counters; no Redis)
_CACHE_DIR = BASE_DIR / ".cache" / "django"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
        "LOCATION": str(_CACHE_DIR),
    }
}

# --- CORS (§6) ---
CORS_ALLOWED_ORIGIN_REGEXES = [
    r"^https://.*\.grok-sandbox\.com$",
]
CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", default=[])
CORS_ALLOW_CREDENTIALS = False
CORS_PREFLIGHT_MAX_AGE = 86400
CORS_ALLOW_HEADERS = [
    "accept",
    "authorization",
    "content-type",
    "origin",
    "user-agent",
    "x-requested-with",
]

# --- Security (public API posture) ---
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
# Behind Cloudflare tunnel TLS terminates at the edge; app speaks HTTP on loopback.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = False  # tunnel hits plain HTTP on 127.0.0.1

# --- App / contract versions ---
APP_VERSION = env("APP_VERSION", "0.1.20")
CONTRACT_VERSION = env("CONTRACT_VERSION", "0.1.20")

# Phase 3 / D13: |counted − theoretical| at or below this → unexplained variance 0.
# Absolute base-unit floor (not a percentage). Override via env if needed.
VARIANCE_NOISE_FLOOR = env("VARIANCE_NOISE_FLOOR", "0.001")

# Auth token (Django signing; no JWT lib).
# 30 days covers a cold-room walk (30–60 min offline) and a phone left
# overnight. AUTH_TOKEN_MAX_AGE_SECONDS overrides it. Lowering the value
# expires tokens already older than the new window on their next use.
AUTH_TOKEN_SALT = "evolving-cook.auth.v1"
AUTH_TOKEN_MAX_AGE = env_int("AUTH_TOKEN_MAX_AGE_SECONDS", 30 * 24 * 3600)

# Login rate limit via django-ratelimit on the default cache (file-based;
# point CACHES at Redis and both buckets follow — no second store).
# Per IP uses CF-Connecting-IP when the tunnel set it, else REMOTE_ADDR.
# X-Forwarded-For is not a rate-limit key (the client can spoof it).
# 10 attempts / 5 minutes per IP, 10 / 15 minutes per username.
AUTH_LOGIN_RATELIMIT = env("AUTH_LOGIN_RATELIMIT", "10/5m")
AUTH_LOGIN_USERNAME_RATELIMIT = env("AUTH_LOGIN_USERNAME_RATELIMIT", "10/15m")

# Media (catalog ingest photo uploads); not public-facing beyond admin
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# LLM provider D10 — Mistral via httpx (catalog.llm_provider). Live ingest blocked when unset.
MISTRAL_API_KEY = env("MISTRAL_API_KEY", "") or ""
LLM_MODEL = env("LLM_MODEL", "mistral-medium-latest")
# D16 companion only — ingest keeps LLM_MODEL (vision); chat/brief get the flagship.
COMPANION_MODEL = env("COMPANION_MODEL", "mistral-large-latest")

# Phase 5 / D11 — Hermes A2A assist (loopback only). Secrets in .env only.
A2A_BASE_URL = env("A2A_BASE_URL", "http://127.0.0.1:9900") or "http://127.0.0.1:9900"
A2A_TOKEN = env("A2A_TOKEN", "") or ""
WEBHOOK_SECRET = env("WEBHOOK_SECRET", "") or ""
A2A_PUSH_CALLBACK_URL = env(
    "A2A_PUSH_CALLBACK_URL",
    "http://127.0.0.1:8000/api/internal/agent-events",
) or "http://127.0.0.1:8000/api/internal/agent-events"
A2A_SEND_TIMEOUT = int(env("A2A_SEND_TIMEOUT", "60") or "60")
# Retained so existing env files still load. The internal gate does not
# consult this: turning it off must not re-open /api/internal/* on the tunnel.
A2A_INTERNAL_LOOPBACK_ONLY = env_bool("A2A_INTERNAL_LOOPBACK_ONLY", True)
# Shared secret for /api/internal/intelligence/assign (header X-Internal-Token).
# Empty or shorter than 16 characters refuses every call (fail closed).
INTERNAL_API_TOKEN = env("INTERNAL_API_TOKEN", "") or ""

# Station-log intelligence (rules always available; hermes/grok assigned in env or DB)
STATION_LOG_PROVIDER = (env("STATION_LOG_PROVIDER", "rules") or "rules").strip().lower()
STATION_LOG_CLASSIFY_PROVIDER = (
    env("STATION_LOG_CLASSIFY_PROVIDER", "rules") or "rules"
).strip().lower()
GROK_ASSIST_BASE_URL = env("GROK_ASSIST_BASE_URL", "") or ""
GROK_ASSIST_TOKEN = env("GROK_ASSIST_TOKEN", "") or ""
GROK_ASSIST_TIMEOUT = int(env("GROK_ASSIST_TIMEOUT", "30") or "30")

# NOTE→ASSIST v2
ASSIST_NOTE_MIN_CHARS = int(env("ASSIST_NOTE_MIN_CHARS", "15") or "15")
ASSIST_NOTE_DEDUPE_SECONDS = int(env("ASSIST_NOTE_DEDUPE_SECONDS", "3600") or "3600")
ASSIST_NOTE_RATE_PER_LINE_HOUR = int(env("ASSIST_NOTE_RATE_PER_LINE_HOUR", "12") or "12")

# django-q2 — ORM broker only (no Redis). LLM jobs only.
Q_CLUSTER = {
    "name": "evolving-cook",
    "workers": 1,
    "timeout": 180,
    "retry": 240,
    "queue_limit": 50,
    "bulk": 5,
    "orm": "default",
    "catch_up": False,
    "label": "Evolving Cook Q",
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
