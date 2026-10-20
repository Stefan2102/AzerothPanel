"""Filesystem locations of the panel itself (never of the AzerothCore install)."""
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent   # repo root
DATA_DIR = ROOT_DIR / "data"
BACKUP_DIR = ROOT_DIR / "backups"
FRONTEND_DIST = ROOT_DIR / "frontend" / "dist"

SETTINGS_FILE = DATA_DIR / "settings.json"
AUTH_FILE = DATA_DIR / "auth.json"
SECRET_FILE = DATA_DIR / "secret.key"
CONTROL_TOKEN_FILE = DATA_DIR / "control.token"
PANEL_LOG_FILE = DATA_DIR / "panel.log"
PANEL_PID_FILE = DATA_DIR / "panel.pid"
AUDIT_FILE = DATA_DIR / "audit.log"
TLS_DIR = DATA_DIR / "tls"
BUILD_STATE_FILE = DATA_DIR / "build.json"
BUILD_LOG_DIR = DATA_DIR / "build-logs"


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
