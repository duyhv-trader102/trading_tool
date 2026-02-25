"""
S3 Storage — Upload / download / sync the local ``data/`` directory to S3.

The S3 layout **mirrors** the local tree::

    s3://{bucket}/{prefix}/mt5/AUDCADm_D1.parquet
    s3://{bucket}/{prefix}/binance/BTC_USDT_H4.parquet
    s3://{bucket}/{prefix}/vnstock/FPT_D1.parquet

Environment variables (loaded from ``.env`` via ``settings_loader``):

    S3_ACCESS_KEY_ID
    S3_SECRET_ACCESS_KEY
    S3_BUCKET
    S3_REGION        (default: ap-southeast-1)
    S3_PREFIX        (default: market_regime_scanner/data)

Usage — CLI::

    python -m infra.s3_storage upload              # local → S3  (only newer)
    python -m infra.s3_storage upload --force       # local → S3  (all files)
    python -m infra.s3_storage download             # S3 → local  (only missing)
    python -m infra.s3_storage download --force     # S3 → local  (overwrite)
    python -m infra.s3_storage sync                 # bi-directional newest-wins
    python -m infra.s3_storage ls                   # list S3 objects
    python -m infra.s3_storage ls binance           # list S3 objects in subdir

Usage — Python::

    from infra.s3_storage import S3Storage

    s3 = S3Storage()
    s3.upload_file("mt5/AUDCADm_D1.parquet")       # single file
    s3.download_file("mt5/AUDCADm_D1.parquet")     # single file
    s3.upload_all()                                 # full upload
    s3.download_all()                               # full download
"""
from __future__ import annotations

import logging
import os
import re
import time
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parent.parent          # market_regime_scanner/
_DATA_ROOT    = _PROJECT_ROOT / "data"                          # local data/

# Sub-directories we sync (skip detection_logs — tiny, local-only)
_SYNC_DIRS = ["mt5", "binance", "vnstock"]

# Only sync these extensions
_SYNC_EXTENSIONS = {".parquet", ".json"}


# ── Singleton helper ─────────────────────────────────────────────────────────
_singleton: Optional["S3Storage"] = None
_singleton_checked: bool = False


def _get_singleton() -> Optional["S3Storage"]:
    """Return a shared S3Storage instance, or None if S3 is disabled."""
    global _singleton, _singleton_checked
    if _singleton_checked:
        return _singleton
    _singleton_checked = True
    try:
        _singleton = S3Storage()
    except Exception:
        pass
    return _singleton


def ensure_local(path) -> bool:
    """If *path* does not exist locally, try to download it from S3.

    Works for any file under ``data/`` — resolves the relative key
    automatically.  Returns True if the file exists after the call
    (either it was already there or successfully downloaded).

    Safe to call anywhere — no-op when S3 is disabled or the path
    is outside the ``data/`` tree.

    Usage::

        from infra.s3_storage import ensure_local
        ensure_local("D:/code/.../data/mt5/XAUUSDm_H4.parquet")
    """
    p = Path(path)
    if p.exists():
        return True
    s3 = _get_singleton()
    if s3 is None:
        return False
    try:
        rel = str(p.relative_to(_DATA_ROOT)).replace("\\", "/")
    except ValueError:
        return False
    try:
        return s3.download_file(rel, overwrite=False)
    except Exception as exc:
        logger.debug("ensure_local failed for %s: %s", rel, exc)
        return False


def ensure_dir_local(dirpath, pattern: str = "*.parquet") -> int:
    """Download all S3 files matching *pattern* under *dirpath* that are
    missing locally.  Returns the count of newly-downloaded files.

    Usage::

        from infra.s3_storage import ensure_dir_local
        ensure_dir_local("D:/code/.../data/binance", "*_USDT_H4.parquet")
    """
    d = Path(dirpath)
    s3 = _get_singleton()
    if s3 is None:
        return 0
    try:
        rel_dir = str(d.relative_to(_DATA_ROOT)).replace("\\", "/")
    except ValueError:
        return 0
    remote = s3.list_remote(rel_dir)
    if not remote:
        return 0
    import fnmatch
    downloaded = 0
    for rel_key in remote:
        fname = rel_key.rsplit("/", 1)[-1] if "/" in rel_key else rel_key
        if not fnmatch.fnmatch(fname, pattern):
            continue
        local = _DATA_ROOT / rel_key
        if local.exists():
            continue
        try:
            if s3.download_file(rel_key, overwrite=False):
                downloaded += 1
        except Exception:
            pass
    return downloaded


def read_parquet_s3(rel_path: str) -> "Optional[pl.DataFrame]":
    """Read a parquet file directly from S3 into memory (no local download).

    *rel_path* is relative to ``data/`` — e.g. ``mt5/XAUUSDm_H4.parquet``.
    Returns the DataFrame or None on failure.
    """
    import io
    s3 = _get_singleton()
    if s3 is None:
        return None
    key = s3._s3_key(rel_path)
    try:
        resp = s3.client.get_object(Bucket=s3._bucket, Key=key)
        buf = io.BytesIO(resp["Body"].read())
        import polars as pl
        return pl.read_parquet(buf)
    except Exception as exc:
        logger.debug("read_parquet_s3 failed for %s: %s", rel_path, exc)
        return None


def write_parquet_s3(rel_path: str, df) -> bool:
    """Write a Polars DataFrame to S3 as parquet — no local file created.

    *rel_path* is relative to ``data/`` — e.g. ``mt5/XAUUSDm_H4.parquet``.
    Returns True on success, False on failure / S3 disabled.
    """
    import io
    s3 = _get_singleton()
    if s3 is None:
        return False
    key = s3._s3_key(rel_path)
    try:
        buf = io.BytesIO()
        df.write_parquet(buf)
        buf.seek(0)
        s3.client.put_object(Bucket=s3._bucket, Key=key, Body=buf.getvalue())
        logger.info("write_parquet_s3 → %s (%d rows)", rel_path, len(df))
        return True
    except Exception as exc:
        logger.warning("write_parquet_s3 FAILED for %s: %s", rel_path, exc)
        return False


def smart_read_parquet(local_path, *, allow_download: bool = False) -> "Optional[pl.DataFrame]":
    """Read a parquet from *local_path* if it exists, else stream from S3.

    This is the recommended read function for the entire codebase.
    **No local file is created** when reading from S3 — the data is
    streamed directly into memory.

    Parameters
    ----------
    local_path : str | Path
        Absolute path under ``data/`` (e.g. ``data/mt5/XAUUSDm_H4.parquet``).
    allow_download : bool
        If True **and** S3 streaming fails, fall back to ``ensure_local()``
        (downloads the file to disk, then reads).  Default False.

    Returns
    -------
    polars.DataFrame | None
        The DataFrame, or None if the file could not be found anywhere.

    Usage::

        from infra.s3_storage import smart_read_parquet
        df = smart_read_parquet("D:/code/.../data/mt5/XAUUSDm_H4.parquet")
    """
    import polars as pl

    p = Path(local_path).resolve()

    # 1. Fast path: local file exists
    if p.exists():
        return pl.read_parquet(p)

    # 2. Stream from S3 (no local file written)
    try:
        rel = str(p.relative_to(_DATA_ROOT)).replace("\\", "/")
    except ValueError:
        return None

    df = read_parquet_s3(rel)
    if df is not None:
        return df

    # 3. Optional: download to local as last resort
    if allow_download and ensure_local(p):
        return pl.read_parquet(p)

    return None


def publish_report(local_path, *, expires_in: int = 300) -> Optional[str]:
    """Upload an HTML report to S3, rewrite linked .html → presigned URLs.

    Returns the presigned URL for the main file, or ``None`` if S3 is
    disabled.  The **local file is not modified** — only the S3 copy has
    rewritten links.

    Parameters
    ----------
    local_path : str | Path
        Absolute path to the HTML file.
    expires_in : int
        Presigned URL lifetime in seconds (default 300 = 5 minutes).

    Usage::

        from infra.s3_storage import publish_report
        url = publish_report("markets/output/2025-02-25/dashboard.html")
    """
    s3 = _get_singleton()
    if s3 is None:
        return None

    p = Path(local_path).resolve()
    if not p.exists():
        logger.warning("publish_report: file not found — %s", p)
        return None

    html_dir = p.parent
    content = p.read_text(encoding="utf-8")

    # ── Upload linked .html files & collect URL mapping ──────────────
    href_re = re.compile(r'href="([^"]+\.html)"')
    url_map: Dict[str, str] = {}

    for m in href_re.finditer(content):
        href = m.group(1)
        if href.startswith(("http", "//", "#", "data:")):
            continue
        linked = (html_dir / href).resolve()
        if not linked.exists():
            continue
        key = s3._report_key(linked)
        try:
            s3.client.put_object(
                Bucket=s3._bucket, Key=key,
                Body=linked.read_bytes(),
                ContentType="text/html",
            )
            url = s3.presigned_url(key, expires_in=expires_in)
            if url:
                url_map[href] = url
        except Exception as exc:
            logger.debug("Linked file upload failed %s: %s", href, exc)

    # ── Rewrite links in the main HTML ───────────────────────────────
    patched = content
    for href, presigned in url_map.items():
        patched = patched.replace(f'href="{href}"', f'href="{presigned}"')

    # ── Upload main file (with rewritten links) ─────────────────────
    main_key = s3._report_key(p)
    ok = s3.upload_content(main_key, patched.encode("utf-8"), content_type="text/html")
    if not ok:
        return None

    url = s3.presigned_url(main_key, expires_in=expires_in)
    if url:
        logger.info("Published report → %s  (expires in %ds)", main_key, expires_in)
        if url_map:
            logger.info("  Linked files uploaded: %d", len(url_map))
    return url


def backup_report_dir(local_dir) -> int:
    """Upload an entire output directory to S3, mirroring the local tree.

    Unlike ``publish_report`` this does **not** rewrite any links or
    generate presigned URLs — it is a pure backup for archival purposes.
    The local files are kept untouched.

    Parameters
    ----------
    local_dir : str | Path
        Absolute path to the output directory
        (e.g. ``markets/output/daily/2026-02-25``).

    Returns
    -------
    int
        Number of files successfully uploaded.

    Usage::

        from infra.s3_storage import backup_report_dir
        n = backup_report_dir("markets/output/daily/2026-02-25")
    """
    s3 = _get_singleton()
    if s3 is None:
        return 0

    d = Path(local_dir).resolve()
    if not d.is_dir():
        logger.warning("backup_report_dir: not a directory — %s", d)
        return 0

    _MIME = {
        ".html": "text/html",
        ".css":  "text/css",
        ".js":   "application/javascript",
        ".json": "application/json",
        ".png":  "image/png",
        ".jpg":  "image/jpeg",
        ".svg":  "image/svg+xml",
        ".csv":  "text/csv",
    }

    uploaded = 0
    for f in d.rglob("*"):
        if not f.is_file():
            continue
        key = s3._report_key(f)
        ct = _MIME.get(f.suffix.lower(), "application/octet-stream")
        try:
            s3.client.put_object(
                Bucket=s3._bucket, Key=key,
                Body=f.read_bytes(),
                ContentType=ct,
            )
            uploaded += 1
        except Exception as exc:
            logger.debug("backup_report_dir upload failed %s: %s", f.name, exc)

    if uploaded:
        logger.info("backup_report_dir: %d files → s3://%s/%s/…",
                     uploaded, s3._bucket, s3._report_prefix)
    return uploaded


def open_report(local_path, *, expires_in: int = 300) -> Optional[str]:
    """Upload HTML report to S3 and open the presigned URL in the browser.

    Falls back to opening the local file if S3 is unavailable.

    Returns the presigned URL (or ``None`` if opened locally).
    """
    url = publish_report(local_path, expires_in=expires_in)
    if url:
        webbrowser.open(url)
        return url
    else:
        webbrowser.open(f"file:///{Path(local_path).resolve()}")
        return None


# ── Log-file S3 sync (CSV signals/tracker) ───────────────────────────────────

def upload_log(local_path) -> bool:
    """Upload a CSV log file to S3 (private, under reports prefix).

    *local_path* must be under ``_PROJECT_ROOT`` (resolved automatically).
    Safe to call anywhere — no-op when S3 is disabled.

    Usage::

        from infra.s3_storage import upload_log
        upload_log("markets/logs/2026-02-24.csv")
    """
    s3 = _get_singleton()
    if s3 is None:
        return False
    p = Path(local_path).resolve()
    if not p.exists():
        return False
    key = s3._report_key(p)
    try:
        s3.client.put_object(
            Bucket=s3._bucket, Key=key,
            Body=p.read_bytes(),
            ContentType="text/csv",
        )
        logger.debug("upload_log %s → %s", p.name, key)
        return True
    except Exception as exc:
        logger.debug("upload_log failed %s: %s", p.name, exc)
        return False


def download_log(local_path) -> bool:
    """Download a CSV log file from S3 if it does not exist locally.

    Returns True if the file exists after the call.
    Only works for paths under the project root (skips temp/test dirs).

    Usage::

        from infra.s3_storage import download_log
        download_log("markets/logs/2026-02-24.csv")
    """
    p = Path(local_path).resolve()
    if p.exists():
        return True
    # Only download if path is inside the project tree
    try:
        p.relative_to(_PROJECT_ROOT)
    except ValueError:
        return False
    s3 = _get_singleton()
    if s3 is None:
        return False
    key = s3._report_key(p)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        s3.client.download_file(s3._bucket, key, str(p))
        logger.debug("download_log %s → %s", key, p)
        return True
    except Exception:
        return False


def _rmdir_if_empty(directory: Path):
    """Remove *directory* and empty ancestors up to ``_PROJECT_ROOT``."""
    try:
        d = directory.resolve()
        while d != _PROJECT_ROOT and d.is_dir() and not any(d.iterdir()):
            d.rmdir()
            d = d.parent
    except Exception:
        pass


def upload_and_clean(local_path) -> bool:
    """Upload file to S3, then delete local copy + empty parent dirs.

    Only deletes if the path is under ``_PROJECT_ROOT`` (skips test/tmp dirs).
    No-op when S3 is disabled.  Returns True if upload succeeded.
    """
    p = Path(local_path).resolve()
    ok = upload_log(p)
    if ok:
        try:
            if p.is_relative_to(_PROJECT_ROOT):
                p.unlink(missing_ok=True)
                _rmdir_if_empty(p.parent)
        except Exception:
            pass
    return ok


def download_read_clean(local_path, reader):
    """Download file from S3 → call ``reader(path)`` → clean up local copy.

    If the file already exists locally, reads it *without* cleanup.
    Returns *reader*'s result, or ``None`` if the file was not found
    (neither locally nor on S3).
    """
    p = Path(local_path).resolve()
    was_local = p.exists()
    if not was_local:
        if not download_log(p):
            return None
    try:
        return reader(p)
    finally:
        if not was_local:
            try:
                if p.is_relative_to(_PROJECT_ROOT):
                    p.unlink(missing_ok=True)
                    _rmdir_if_empty(p.parent)
            except Exception:
                try:
                    p.unlink(missing_ok=True)
                except Exception:
                    pass


def publish_and_clean(local_path, *, expires_in: int = 300) -> Optional[str]:
    """Upload HTML report to S3 then delete local copy + empty parent dirs.

    Returns the presigned URL, or ``None`` if S3 is disabled.
    Falls back to opening the local file when S3 is unavailable.
    """
    url = publish_report(local_path, expires_in=expires_in)
    if url:
        p = Path(local_path).resolve()
        try:
            if p.is_relative_to(_PROJECT_ROOT):
                p.unlink(missing_ok=True)
                # Also clean linked html files in the same directory
                for child in p.parent.glob("*.html"):
                    child.unlink(missing_ok=True)
                _rmdir_if_empty(p.parent)
        except Exception:
            pass
    return url


def upload_log_dir(local_dir, pattern: str = "*.csv") -> int:
    """Upload all CSV files in *local_dir* to S3.  Returns count uploaded."""
    d = Path(local_dir)
    if not d.is_dir():
        return 0
    import fnmatch
    count = 0
    for f in sorted(d.rglob("*")):
        if not f.is_file():
            continue
        if not fnmatch.fnmatch(f.name, pattern):
            continue
        if upload_log(f):
            count += 1
    return count


def s3_dir_mtimes(data_subdir: str) -> Dict[str, float]:
    """Return ``{filename: epoch_seconds}`` for every S3 file in ``data/{data_subdir}/``.

    Makes a single ``list_objects_v2`` call (paginated) per subdirectory,
    so it is fast even for hundreds of files.

    Usage::

        from infra.s3_storage import s3_dir_mtimes
        mtimes = s3_dir_mtimes("mt5")  # {"XAUUSDm_H4.parquet": 1740..., ...}
    """
    s3 = _get_singleton()
    if s3 is None:
        return {}
    remote = s3.list_remote(data_subdir)
    if not remote:
        return {}
    result: Dict[str, float] = {}
    for rel_key, dt in remote.items():
        fname = rel_key.rsplit("/", 1)[-1] if "/" in rel_key else rel_key
        result[fname] = dt.timestamp()
    return result


def list_remote_files(dirpath, pattern: str = "*.parquet") -> "list[str]":
    """Return list of filenames matching *pattern* on S3 under *dirpath*.

    Useful to replace ``os.listdir()`` when local dir may be empty.

    Usage::

        from infra.s3_storage import list_remote_files
        files = list_remote_files("D:/code/.../data/binance", "*_H4.parquet")
    """
    d = Path(dirpath)
    s3 = _get_singleton()
    if s3 is None:
        return []
    try:
        rel_dir = str(d.relative_to(_DATA_ROOT)).replace("\\", "/")
    except ValueError:
        return []
    remote = s3.list_remote(rel_dir)
    if not remote:
        return []
    import fnmatch
    result = []
    for rel_key in remote:
        fname = rel_key.rsplit("/", 1)[-1] if "/" in rel_key else rel_key
        if fnmatch.fnmatch(fname, pattern):
            result.append(fname)
    return sorted(result)


# ── S3 client wrapper ────────────────────────────────────────────────────────

class S3Storage:
    """Thin wrapper around boto3 for syncing the ``data/`` tree to S3."""

    def __init__(self):
        # Ensure .env is loaded
        from infra.settings_loader import _load_dotenv
        _load_dotenv()

        self._bucket = os.environ.get("S3_BUCKET", "")
        self._region = os.environ.get("S3_REGION", "ap-southeast-1")
        self._prefix = os.environ.get("S3_PREFIX", "market_regime_scanner/data")
        self._access_key = os.environ.get("S3_ACCESS_KEY_ID", "")
        self._secret_key = os.environ.get("S3_SECRET_ACCESS_KEY", "")

        if not self._bucket:
            raise RuntimeError(
                "S3_BUCKET not set.  Add S3_BUCKET=... to .env or environment."
            )
        if not self._access_key or not self._secret_key:
            raise RuntimeError(
                "S3 credentials not set.  Add S3_ACCESS_KEY_ID and "
                "S3_SECRET_ACCESS_KEY to .env or environment."
            )

        self._client = None  # lazily created

    # ── boto3 client (lazy) ──────────────────────────────────────────────

    @property
    def client(self):
        if self._client is None:
            import boto3
            from botocore.config import Config
            # Use path-style or virtual-hosted with regional endpoint so
            # presigned URLs resolve without redirect (required for SigV4).
            endpoint = f"https://s3.{self._region}.amazonaws.com"
            self._client = boto3.client(
                "s3",
                region_name=self._region,
                endpoint_url=endpoint,
                aws_access_key_id=self._access_key,
                aws_secret_access_key=self._secret_key,
                config=Config(
                    signature_version="s3v4",
                    request_checksum_calculation="when_required",
                ),
            )
        return self._client

    # ── Key helpers ──────────────────────────────────────────────────────

    def _s3_key(self, rel_path: str) -> str:
        """Convert a relative path (e.g. ``mt5/ABC_D1.parquet``) to S3 key."""
        # Normalize Windows backslashes
        rel = rel_path.replace("\\", "/")
        return f"{self._prefix}/{rel}" if self._prefix else rel

    def _rel_from_key(self, s3_key: str) -> str:
        """Convert S3 key back to relative path under data/."""
        prefix = f"{self._prefix}/" if self._prefix else ""
        if s3_key.startswith(prefix):
            return s3_key[len(prefix):]
        return s3_key

    def _local_path(self, rel_path: str) -> Path:
        return _DATA_ROOT / rel_path

    # ── Single file operations ───────────────────────────────────────────

    def upload_file(self, rel_path: str) -> bool:
        """Upload a single file from ``data/{rel_path}`` to S3. Returns True on success.

        Uses ``put_object(Body=bytes)`` to avoid botocore's ``AwsChunkedWrapper``
        stream-not-seekable error that occurs with ``client.upload_file()`` when
        a custom ``endpoint_url`` + SigV4 is configured.
        """
        local = self._local_path(rel_path)
        if not local.exists():
            logger.warning("Upload skip — file not found: %s", local)
            return False
        key = self._s3_key(rel_path)
        try:
            self.client.put_object(
                Bucket=self._bucket, Key=key,
                Body=local.read_bytes(),
            )
            logger.debug("Uploaded %s → s3://%s/%s", local, self._bucket, key)
            return True
        except Exception as e:
            logger.error("Upload failed %s: %s", rel_path, e)
            return False

    def download_file(self, rel_path: str, *, overwrite: bool = False) -> bool:
        """Download a single file from S3 to ``data/{rel_path}``. Returns True on success."""
        local = self._local_path(rel_path)
        if local.exists() and not overwrite:
            logger.debug("Download skip — already exists: %s", local)
            return False
        key = self._s3_key(rel_path)
        try:
            local.parent.mkdir(parents=True, exist_ok=True)
            self.client.download_file(self._bucket, key, str(local))
            logger.debug("Downloaded s3://%s/%s → %s", self._bucket, key, local)
            return True
        except Exception as e:
            logger.error("Download failed %s: %s", rel_path, e)
            return False

    # ── Report upload & presigned URLs ───────────────────────────────

    @property
    def _report_prefix(self) -> str:
        """S3 prefix for reports/logs — mirrors project directory structure.

        With _prefix = 'market_regime_scanner/data', base = 'market_regime_scanner',
        so keys become: market_regime_scanner/markets/logs/... and
        market_regime_scanner/markets/output/...
        """
        base = self._prefix.rsplit("/", 1)[0] if "/" in self._prefix else self._prefix
        return base

    def _report_key(self, local_path) -> str:
        """Compute S3 key for a report file, keeping the project-relative path."""
        p = Path(local_path).resolve()
        try:
            rel = str(p.relative_to(_PROJECT_ROOT)).replace("\\", "/")
        except ValueError:
            rel = p.name
        return f"{self._report_prefix}/{rel}"

    def upload_content(self, s3_key: str, data: bytes, *, content_type: str = "text/html") -> bool:
        """Upload in-memory *data* to S3.  Returns True on success."""
        try:
            self.client.put_object(
                Bucket=self._bucket, Key=s3_key,
                Body=data, ContentType=content_type,
            )
            return True
        except Exception as e:
            logger.error("upload_content failed %s: %s", s3_key, e)
            return False

    def presigned_url(self, s3_key: str, *, expires_in: int = 300) -> Optional[str]:
        """Generate a presigned GET URL for *s3_key*.

        Parameters
        ----------
        s3_key : str
            Full S3 object key.
        expires_in : int
            URL lifetime in seconds (default 300 = 5 minutes).
        """
        try:
            return self.client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": s3_key},
                ExpiresIn=expires_in,
            )
        except Exception as e:
            logger.error("presigned_url failed %s: %s", s3_key, e)
            return None

    # ── Listing ──────────────────────────────────────────────────────────

    def list_remote(self, sub_dir: str = "") -> Dict[str, datetime]:
        """List S3 objects under ``prefix/sub_dir``, return {rel_path: last_modified}."""
        prefix = self._s3_key(sub_dir)
        if not prefix.endswith("/"):
            prefix += "/"
        result: Dict[str, datetime] = {}
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                rel = self._rel_from_key(obj["Key"])
                if rel and not rel.endswith("/"):
                    result[rel] = obj["LastModified"]
        return result

    def list_local(self, sub_dir: str = "") -> Dict[str, datetime]:
        """List local files under ``data/sub_dir``, return {rel_path: mtime_utc}."""
        root = _DATA_ROOT / sub_dir if sub_dir else _DATA_ROOT
        result: Dict[str, datetime] = {}
        if not root.exists():
            return result
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix not in _SYNC_EXTENSIONS:
                continue
            rel = str(path.relative_to(_DATA_ROOT)).replace("\\", "/")
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            result[rel] = mtime
        return result

    # ── Batch operations ─────────────────────────────────────────────────

    def upload_all(self, *, force: bool = False, sub_dirs: Optional[List[str]] = None) -> int:
        """Upload all local data files to S3.

        Args:
            force:    If True, upload all files.  If False, skip files where
                      the local mtime <= S3 LastModified.
            sub_dirs: Restrict to these subdirectories (default: all sync dirs).

        Returns:
            Number of files uploaded.
        """
        dirs = sub_dirs or _SYNC_DIRS
        uploaded = 0
        for d in dirs:
            local_files = self.list_local(d)
            if not local_files:
                continue
            remote_files = self.list_remote(d) if not force else {}
            to_upload = []
            for rel, local_mtime in local_files.items():
                if force:
                    to_upload.append(rel)
                else:
                    remote_mtime = remote_files.get(rel)
                    if remote_mtime is None or local_mtime > remote_mtime:
                        to_upload.append(rel)

            if not to_upload:
                print(f"  [{d}] up-to-date ({len(local_files)} files)")
                continue

            print(f"  [{d}] uploading {len(to_upload)}/{len(local_files)} files ...")
            for i, rel in enumerate(to_upload, 1):
                self.upload_file(rel)
                uploaded += 1
                if i % 50 == 0 or i == len(to_upload):
                    print(f"    {i}/{len(to_upload)} uploaded", end="\r")
            print()
        return uploaded

    def download_all(self, *, force: bool = False, sub_dirs: Optional[List[str]] = None) -> int:
        """Download all S3 data files to local.

        Args:
            force:    If True, overwrite all local files.  If False, skip
                      files that already exist locally with mtime >= S3.
            sub_dirs: Restrict to these subdirectories (default: all sync dirs).

        Returns:
            Number of files downloaded.
        """
        dirs = sub_dirs or _SYNC_DIRS
        downloaded = 0
        for d in dirs:
            remote_files = self.list_remote(d)
            if not remote_files:
                print(f"  [{d}] no files on S3")
                continue
            local_files = self.list_local(d) if not force else {}
            to_download = []
            for rel, remote_mtime in remote_files.items():
                if force:
                    to_download.append(rel)
                else:
                    local_mtime = local_files.get(rel)
                    if local_mtime is None or remote_mtime > local_mtime:
                        to_download.append(rel)

            if not to_download:
                print(f"  [{d}] up-to-date ({len(remote_files)} files)")
                continue

            print(f"  [{d}] downloading {len(to_download)}/{len(remote_files)} files ...")
            for i, rel in enumerate(to_download, 1):
                self.download_file(rel, overwrite=True)
                downloaded += 1
                if i % 50 == 0 or i == len(to_download):
                    print(f"    {i}/{len(to_download)} downloaded", end="\r")
            print()
        return downloaded

    def sync(self, sub_dirs: Optional[List[str]] = None) -> dict:
        """Bi-directional sync: newest file wins.

        Returns:
            {"uploaded": int, "downloaded": int}
        """
        dirs = sub_dirs or _SYNC_DIRS
        total_up = 0
        total_down = 0
        for d in dirs:
            local_files = self.list_local(d)
            remote_files = self.list_remote(d)

            all_keys = set(local_files) | set(remote_files)
            to_upload = []
            to_download = []

            for rel in all_keys:
                local_mtime = local_files.get(rel)
                remote_mtime = remote_files.get(rel)
                if local_mtime and not remote_mtime:
                    to_upload.append(rel)
                elif remote_mtime and not local_mtime:
                    to_download.append(rel)
                elif local_mtime and remote_mtime:
                    if local_mtime > remote_mtime:
                        to_upload.append(rel)
                    elif remote_mtime > local_mtime:
                        to_download.append(rel)

            if to_upload:
                print(f"  [{d}] uploading {len(to_upload)} files ...")
                for rel in to_upload:
                    self.upload_file(rel)
                    total_up += 1

            if to_download:
                print(f"  [{d}] downloading {len(to_download)} files ...")
                for rel in to_download:
                    self.download_file(rel, overwrite=True)
                    total_down += 1

            if not to_upload and not to_download:
                print(f"  [{d}] in sync ({len(local_files)} files)")

        return {"uploaded": total_up, "downloaded": total_down}


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    import argparse
    import sys

    _PROJECT_ROOT_STR = str(_PROJECT_ROOT)
    if _PROJECT_ROOT_STR not in sys.path:
        sys.path.insert(0, _PROJECT_ROOT_STR)

    parser = argparse.ArgumentParser(
        description="S3 data storage — upload / download / sync parquet files"
    )
    sub = parser.add_subparsers(dest="command")

    up_p = sub.add_parser("upload", help="Upload local data → S3")
    up_p.add_argument("--force", action="store_true", help="Upload all (ignore timestamps)")
    up_p.add_argument("--dirs", nargs="*", help="Subdirectories (default: mt5 binance vnstock)")

    down_p = sub.add_parser("download", help="Download S3 → local data")
    down_p.add_argument("--force", action="store_true", help="Overwrite all local files")
    down_p.add_argument("--dirs", nargs="*", help="Subdirectories (default: mt5 binance vnstock)")

    sync_p = sub.add_parser("sync", help="Bi-directional sync (newest wins)")
    sync_p.add_argument("--dirs", nargs="*", help="Subdirectories (default: mt5 binance vnstock)")

    ls_p = sub.add_parser("ls", help="List S3 objects")
    ls_p.add_argument("subdir", nargs="?", default="", help="Subdirectory to list")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    t0 = time.time()
    s3 = S3Storage()
    print(f"\n  S3 bucket : {s3._bucket}")
    print(f"  S3 prefix : {s3._prefix}")
    print(f"  Local root: {_DATA_ROOT}\n")

    if args.command == "upload":
        n = s3.upload_all(force=args.force, sub_dirs=args.dirs)
        print(f"\n  Done — {n} file(s) uploaded in {time.time()-t0:.1f}s")

    elif args.command == "download":
        n = s3.download_all(force=args.force, sub_dirs=args.dirs)
        print(f"\n  Done — {n} file(s) downloaded in {time.time()-t0:.1f}s")

    elif args.command == "sync":
        result = s3.sync(sub_dirs=args.dirs)
        print(f"\n  Done — {result['uploaded']} uploaded, "
              f"{result['downloaded']} downloaded in {time.time()-t0:.1f}s")

    elif args.command == "ls":
        files = s3.list_remote(args.subdir)
        if not files:
            print(f"  No files found under '{args.subdir or '(root)'}'")
        else:
            print(f"  {len(files)} file(s):\n")
            for rel, mtime in sorted(files.items()):
                local = s3._local_path(rel)
                local_tag = " [local]" if local.exists() else ""
                print(f"    {rel:<60} {mtime:%Y-%m-%d %H:%M}{local_tag}")


if __name__ == "__main__":
    main()
