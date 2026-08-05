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
APP_VERSION = env("APP_VERSION", "0.1.15")
CONTRACT_VERSION = env("CONTRACT_VERSION", "0.1.15")

# Phase 3 / D13: |counted − theoretical| at or below this → unexplained variance 0.
# Absolute base-unit floor (not a percentage). Override via env if needed.
VARIANCE_NOISE_FLOOR = env("VARIANCE_NOISE_FLOOR", "0.001")

# Auth token (Django signing; no JWT lib)
AUTH_TOKEN_SALT = "evolving-cook.auth.v1"
AUTH_TOKEN_MAX_AGE = 30 * 24 * 3600  # 30 days

# Login rate limit: django-ratelimit keys (see api.auth)
# 10 attempts / 5 minutes per IP — public posture; edge WAF may add more
AUTH_LOGIN_RATELIMIT = env("AUTH_LOGIN_RATELIMIT", "10/5m")

# Media (catalog ingest photo uploads); not public-facing beyond admin
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# LLM provider D10 — Mistral via httpx (catalog.llm_provider). Live ingest blocked when unset.
MISTRAL_API_KEY = env("MISTRAL_API_KEY", "") or ""
LLM_MODEL = env("LLM_MODEL", "mistral-medium-latest")

# Phase 5 / D11 — Hermes A2A assist (loopback only). Secrets in .env only.
A2A_BASE_URL = env("A2A_BASE_URL", "http://127.0.0.1:9900") or "http://127.0.0.1:9900"
A2A_TOKEN = env("A2A_TOKEN", "") or ""
WEBHOOK_SECRET = env("WEBHOOK_SECRET", "") or ""
A2A_PUSH_CALLBACK_URL = env(
    "A2A_PUSH_CALLBACK_URL",
    "http://127.0.0.1:8000/api/internal/agent-events",
) or "http://127.0.0.1:8000/api/internal/agent-events"
A2A_SEND_TIMEOUT = int(env("A2A_SEND_TIMEOUT", "60") or "60")
# Reject non-loopback REMOTE_ADDR on agent-events when True (production default).
A2A_INTERNAL_LOOPBACK_ONLY = env_bool("A2A_INTERNAL_LOOPBACK_ONLY", True)

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
