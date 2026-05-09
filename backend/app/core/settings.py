import os
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
VERSION_FILE = PROJECT_ROOT / "VERSION"


def read_app_version() -> str:
    env_version = os.getenv("APP_VERSION", "").strip()
    if env_version:
        return env_version

    try:
        file_version = VERSION_FILE.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return "v0.0.0"

    return file_version or "v0.0.0"


def env_flag(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def env_bool_or_auto(name: str, default: str = "auto") -> str:
    value = os.getenv(name, default).strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return "true"
    if value in {"0", "false", "no", "off"}:
        return "false"
    return "auto"


def normalize_panel_path(value: str | None) -> str:
    raw = (value or "").strip()
    if raw in {"", "/"}:
        return ""

    if not raw.startswith("/"):
        raw = f"/{raw}"

    path = "/" + "/".join(segment for segment in raw.split("/") if segment)
    path = path.rstrip("/")

    if not re.fullmatch(r"/[A-Za-z0-9._~!$&'()*+,;=:@/-]+", path):
        raise ValueError(
            "PANEL_PATH can only contain URL path characters. Example: /my-secret-panel"
        )

    reserved_paths = {"/api", "/health", "/static", "/_app", "/favicon.ico"}
    reserved_prefixes = ("/api/", "/health/", "/static/", "/_app/")
    if path in reserved_paths or path.startswith(reserved_prefixes):
        raise ValueError(
            "PANEL_PATH cannot use reserved paths such as /api, /health, /static, or /_app"
        )

    return path

DEFAULT_API_URL = os.getenv("DEFAULT_API_URL", "")
DEFAULT_API_KEY = os.getenv("DEFAULT_API_KEY", "")
DEFAULT_API_PATH = os.getenv("DEFAULT_API_PATH", "/v1/images/generations")
DEFAULT_RESPONSES_MODEL = os.getenv("DEFAULT_RESPONSES_MODEL", "gpt-5.4")
APP_VERSION = read_app_version()
GITHUB_REPO = os.getenv("GITHUB_REPO", "Z1rconium/gpt-image-linux").strip()
PANEL_PATH = normalize_panel_path(os.getenv("PANEL_PATH", ""))
ACCESS_KEY = os.getenv("ACCESS_KEY", "").strip()
ALLOW_UNAUTHENTICATED = env_flag("ALLOW_UNAUTHENTICATED")
ACCESS_KEY_SESSION_MINUTES = 180
ACCESS_KEY_COOKIE_NAME = os.getenv("ACCESS_KEY_COOKIE_NAME", "gpt_image_access")
ACCESS_COOKIE_SECURE = env_bool_or_auto("ACCESS_COOKIE_SECURE", "auto")
ACCESS_MAX_FAILURES = int(os.getenv("ACCESS_MAX_FAILURES", "5"))
ACCESS_LOCKOUT_SECONDS = int(os.getenv("ACCESS_LOCKOUT_SECONDS", "300"))
IP_ALLOWLIST = os.getenv("IP_ALLOWLIST", "")
TRUST_PROXY_HEADERS = env_flag("TRUST_PROXY_HEADERS")
UPSTREAM_HOST_ALLOWLIST = os.getenv("UPSTREAM_HOST_ALLOWLIST", "").strip()
WEBHOOK_HOST_ALLOWLIST = os.getenv("WEBHOOK_HOST_ALLOWLIST", "").strip()
WEBHOOK_SIGNING_SECRET = os.getenv("WEBHOOK_SIGNING_SECRET", "").strip()
WEBHOOK_TIMEOUT_SECONDS = float(os.getenv("WEBHOOK_TIMEOUT_SECONDS", "5"))
WEBHOOK_MAX_ATTEMPTS = int(os.getenv("WEBHOOK_MAX_ATTEMPTS", "3"))
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "50"))
IMAGES_DIR = os.getenv("IMAGES_DIR", "./images")
DATA_DIR = os.getenv("DATA_DIR", "./data")
DATABASE_FILE = os.getenv("DATABASE_FILE", os.path.join(DATA_DIR, "app.sqlite3"))
GALLERY_FILE = os.path.join(DATA_DIR, "gallery.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
