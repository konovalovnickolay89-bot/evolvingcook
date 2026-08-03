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
        "DIRS": [],
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
APP_VERSION = env("APP_VERSION", "0.0.0")
CONTRACT_VERSION = env("CONTRACT_VERSION", "0.0.0")

# Auth token (Django signing; no JWT lib)
AUTH_TOKEN_SALT = "evolving-cook.auth.v1"
AUTH_TOKEN_MAX_AGE = 30 * 24 * 3600  # 30 days

# Login rate limit: django-ratelimit keys (see api.auth)
# 10 attempts / 5 minutes per IP — public posture; edge WAF may add more
AUTH_LOGIN_RATELIMIT = env("AUTH_LOGIN_RATELIMIT", "10/5m")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
