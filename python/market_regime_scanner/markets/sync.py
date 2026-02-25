"""
markets/sync.py — Data freshness utilities for all markets.

Responsible for ensuring each market's parquet files are up-to-date
before scanning.  Called by ``markets/daily_scan.py`` (and usable
independently from any other script).

  sync_mt5_data(markets, skip_update)   — H4/D1/W1 for MT5-backed markets
  sync_vnstock_data(symbols)            — D1 for VN stocks (60s rate-limit delay)
  sync_binance_data(symbols)            — H4 + D1 + W1 for Binance
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import List

from markets.utils.constants import MT5_MARKETS

logger = logging.getLogger("markets.sync")


# ─────────────────────────────────────────────────────────────────────────────
# MT5
# ─────────────────────────────────────────────────────────────────────────────

def sync_mt5_data(markets: List[str], skip_update: bool = False) -> None:
    """
    Ensure H4 + D1 + W1 parquet files are fresh for all MT5-backed markets.

    Scanner reads:
      Monthly session → W1 bars
      Weekly  session → D1 bars
      Daily   session → H4 bars

    - Missing files  → full fetch
    - Existing files → incremental update unless skip_update=True
    """
    from markets.registry import MarketRegistry
    from infra.parquet_manager import fetch_and_store_data, update_parquet
    from infra import mt5 as _mt5
    from infra.settings_loader import get_mt5_config
    from infra.s3_storage import s3_dir_mtimes

    mt5_markets = [m for m in markets if m.upper() in MT5_MARKETS]
    if not mt5_markets:
        return

    symbols: List[str] = []
    for m in mt5_markets:
        symbols.extend(MarketRegistry.get_symbols(m))
    symbols = list(dict.fromkeys(symbols))  # dedup, preserve order

    if not symbols:
        return

    FETCH_BARS  = {"H4": 5000, "D1": 1500, "W1": 300}
    UPDATE_BARS = {"H4": 500,  "D1": 200,  "W1": 100}

    missing:   list = []
    to_update: list = []

    # ── S3 is the source of truth for freshness ──────────────────────
    s3_mt5 = s3_dir_mtimes("mt5")

    for sym in symbols:
        for tf in ("H4", "D1", "W1"):
            fname = f"{sym}_{tf}.parquet"
            s3_mtime = s3_mt5.get(fname)
            if s3_mtime is None:
                # Not on S3 → full fetch
                missing.append((sym, tf, FETCH_BARS[tf]))
            elif not skip_update:
                # Exists on S3 → incremental update
                to_update.append((sym, tf, UPDATE_BARS[tf]))

    if not missing and not to_update:
        print("  Data: all files up-to-date — skipping MT5 sync")
        return

    parts = []
    if missing:   parts.append(f"{len(missing)} missing")
    if to_update: parts.append(f"{len(to_update)} to update")
    print(f"\n  Data sync: {', '.join(parts)} — connecting to MT5…")

    try:
        config = get_mt5_config()
        _mt5.start_mt5(
            username=int(config["username"]),
            password=config["password"],
            server=config["server"],
            mt5Pathway=config["mt5Pathway"],
        )
    except Exception as e:
        print(f"  [WARN] MT5 unavailable — scanning with existing data ({e})")
        return

    for sym, tf, bars in missing:
        print(f"    [NEW] {sym} {tf}…", end=" ", flush=True)
        try:
            fetch_and_store_data(sym, tf, bars)
            print("OK")
        except Exception as exc:
            print(f"FAILED — {exc}")

    for sym, tf, bars in to_update:
        print(f"    [UPD] {sym} {tf}…", end=" ", flush=True)
        try:
            update_parquet(sym, tf, bars)
            print("OK")
        except Exception as exc:
            print(f"FAILED — {exc}")

    # Scanner reads from S3 directly via load_from_parquet → read_parquet_s3.
    # No local data/ files needed.


# ─────────────────────────────────────────────────────────────────────────────
# VNStock
# ─────────────────────────────────────────────────────────────────────────────

_VN_BATCH_SIZE  = 20    # VNStock API allows ~20 calls per burst
_VN_BATCH_DELAY = 60   # seconds to wait between batches (avoid throttle)
_VN_FRESH_HRS   = 20    # hours — don't re-download if file is fresher than this


def _sync_vnstock_generic(
    symbols: List[str],
    tf_suffix: str,
    label: str,
    download_fn,
) -> None:
    """
    Generic batch-download for VNStock data.

    Parameters
    ----------
    symbols   : list of ticker strings
    tf_suffix : file suffix, e.g. ``"D1"`` or ``"H1"``
    label     : display label for logs, e.g. ``"VNStock"`` or ``"VNStock 1H"``
    download_fn : callable(downloader, symbol) → None
    """
    import time
    from markets.vnstock.data_provider import VNStockDataProvider
    from markets.vnstock.downloader import VNStockDownloader
    from infra.s3_storage import s3_dir_mtimes

    if not symbols:
        return

    fresh_thr = _VN_FRESH_HRS * 3600

    # ── S3 is the source of truth for freshness ───────────────────────────────
    s3_vn = s3_dir_mtimes("vnstock")
    now = time.time()

    stale: List[str] = []
    for sym in symbols:
        fname = f"{sym}_{tf_suffix}.parquet"
        s3_mtime = s3_vn.get(fname)
        if s3_mtime is None:
            stale.append(sym)
        elif (now - s3_mtime) > fresh_thr:
            stale.append(sym)

    if not stale:
        print(f"  {label}: all {len(symbols)} files fresh — skipping sync")
        return

    print(f"\n  {label} sync: {len(stale)}/{len(symbols)} stale"
          f" (batch={_VN_BATCH_SIZE}, delay={_VN_BATCH_DELAY}s between batches)")

    dl     = VNStockDownloader()
    total  = len(stale)
    done   = 0
    errors = 0

    tag = f"[{label.replace('VNStock', 'VN').strip()}]"  # "[VN]" or "[VN 1H]"
    for batch_start in range(0, total, _VN_BATCH_SIZE):
        batch = stale[batch_start: batch_start + _VN_BATCH_SIZE]
        batch_num = batch_start // _VN_BATCH_SIZE + 1
        batch_total = (total + _VN_BATCH_SIZE - 1) // _VN_BATCH_SIZE

        suffix = f" ({tf_suffix})" if tf_suffix != "D1" else ""
        print(f"\n  [Batch {batch_num}/{batch_total}] {len(batch)} symbols{suffix}")
        for sym in batch:
            print(f"    {tag} {sym}…", end=" ", flush=True)
            try:
                download_fn(dl, sym)
                done += 1
                print("OK")
            except Exception as exc:
                errors += 1
                print(f"FAILED — {exc}")

        # Pause between batches (skip after last batch)
        if batch_start + _VN_BATCH_SIZE < total:
            print(f"  … waiting {_VN_BATCH_DELAY}s before next batch …", flush=True)
            time.sleep(_VN_BATCH_DELAY)

    print(f"\n  {label} sync done: {done} OK, {errors} errors")


def sync_vnstock_data(symbols: List[str]) -> None:
    """Batch-download VNStock D1 data for a list of symbols."""
    _sync_vnstock_generic(
        symbols, "D1", "VNStock",
        lambda dl, sym: dl.download_symbol(sym),
    )


def sync_vnstock_1h_data(symbols: List[str]) -> None:
    """Batch-download VNStock 1H (intraday) data for a list of symbols."""
    _sync_vnstock_generic(
        symbols, "H1", "VNStock 1H",
        lambda dl, sym: dl.download_symbol_1h(sym),
    )


def sync_vnstock_w1_data(symbols: List[str]) -> None:
    """Generate VNStock W1 data by resampling existing D1 parquets."""
    _sync_vnstock_generic(
        symbols, "W1", "VNStock W1",
        lambda dl, sym: dl.download_symbol_w1(sym),
    )




# ─────────────────────────────────────────────────────────────────────────────
# Binance
# ─────────────────────────────────────────────────────────────────────────────

def sync_binance_data(symbols: List[str]) -> None:
    """
    Ensure Binance parquet files (H4 + D1 + W1) are fresh.

    Native D1 and W1 are fetched directly from the exchange for accuracy.
    Resample from H4 is the fallback used at scan-time by UnifiedDataProvider
    if a native file is missing.

    Uses a single BinanceDownloader instance (ccxt with enableRateLimit=True).
    """
    import time
    from markets.binance.downloader import BinanceDownloader
    from infra.s3_storage import s3_dir_mtimes

    if not symbols:
        return

    fresh_thr  = 4 * 60 * 60  # 4 hours

    # ── S3 is the source of truth for freshness ───────────────────────────────
    s3_bn = s3_dir_mtimes("binance")
    now = time.time()

    stale: List[str] = []
    for sym in symbols:
        fn = sym.replace("/", "_").replace(":", "_")
        fname = f"{fn}_H4.parquet"
        s3_mtime = s3_bn.get(fname)
        if s3_mtime is None or (now - s3_mtime) > fresh_thr:
            stale.append(sym)

    if not stale:
        print("  Binance: all files up-to-date — skipping sync")
        return

    print(f"\n  Binance sync: {len(stale)}/{len(symbols)} stale — connecting…")
    try:
        dl = BinanceDownloader()
    except Exception as exc:
        print(f"  [WARN] Binance unavailable: {exc}")
        return

    TF_MAP = {"4h": "H4", "1d": "D1", "1w": "W1"}

    for sym in stale:
        for ccxt_tf, label in TF_MAP.items():
            print(f"    [BNC] {sym} {label}…", end=" ", flush=True)
            try:
                dl.download_symbol(sym, timeframe=ccxt_tf, years=10)
                print("OK")
            except Exception as exc:
                print(f"FAILED — {exc}")
