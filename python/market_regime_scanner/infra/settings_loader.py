"""
Settings loader — reads credentials from environment variables (.env file)
and non-sensitive config from settings.yaml.

Priority: ENV vars > .env file > settings.yaml (legacy fallback).
"""

import os
import yaml
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent  # market_regime_scanner/
_settings = None


def _load_dotenv() -> None:
    """Load .env file into os.environ (no third-party dependency)."""
    env_path = _PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if key and key not in os.environ:  # don't override real env vars
                os.environ[key] = value


# Load .env on import so all subsequent os.environ reads see the values
_load_dotenv()


def get_settings(path=None):
    """Load non-sensitive settings from YAML file."""
    global _settings
    if _settings is not None and path is None:
        return _settings
    settings_path = Path(path) if path else (Path(__file__).parent / "settings.yaml")
    with open(settings_path, "r", encoding="utf-8") as f:
        _settings = yaml.safe_load(f)
    return _settings


def get_mt5_config() -> dict:
    """
    Get MT5 connection settings from environment variables.
    Falls back to settings.yaml only if env vars are not set.
    """
    username = os.environ.get("MT5_USERNAME")
    password = os.environ.get("MT5_PASSWORD")
    server = os.environ.get("MT5_SERVER")
    pathway = os.environ.get("MT5_PATHWAY")

    if username and password and server and pathway:
        return {
            "username": username,
            "password": password,
            "server": server,
            "mt5Pathway": pathway,
        }

    # Legacy fallback — will be removed once .env is set up
    cfg = get_settings().get("mt5", {})
    if not cfg:
        raise RuntimeError(
            "MT5 credentials not found. "
            "Set MT5_USERNAME, MT5_PASSWORD, MT5_SERVER, MT5_PATHWAY "
            "in environment or .env file."
        )
    return cfg


def get_tpo_config() -> dict:
    """Get TPO analysis settings."""
    return get_settings().get("tpo", {})


def get_s3_config() -> dict:
    """
    Get S3 storage settings from environment variables.

    Returns dict with keys: bucket, region, prefix, access_key_id, secret_access_key.
    Any missing key will be an empty string.
    """
    return {
        "bucket": os.environ.get("S3_BUCKET", ""),
        "region": os.environ.get("S3_REGION", "ap-southeast-1"),
        "prefix": os.environ.get("S3_PREFIX", "market_regime_scanner/data"),
        "access_key_id": os.environ.get("S3_ACCESS_KEY_ID", ""),
        "secret_access_key": os.environ.get("S3_SECRET_ACCESS_KEY", ""),
    }

