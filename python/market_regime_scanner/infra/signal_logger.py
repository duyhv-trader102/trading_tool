"""
Signal Logger — Persistent log of scanner results.

Stores every scanner scan result, deduplicated by (date, market, symbol).
Re-scanning the same symbol on the same day updates the existing entry.

Storage: markets/logs/YYYY-MM-DD.csv  (one file per day, flat columns)

Usage:
    from infra.signal_logger import SignalLogger

    logger = SignalLogger()
    logger.log_scan_results("FX", results)   # results from scanner
    logger.print_history()                     # show all logged signals
    logger.print_date("2025-01-15")           # show specific date
"""

import csv
import os
from datetime import datetime, date
from pathlib import Path
from typing import List, Dict, Any, Optional

# Flat column order for the CSV file
CSV_COLUMNS = [
    "market", "symbol", "signal", "scanned_at", "entry_price",
    "m_status", "m_trend", "m_range_low", "m_range_high",
    "m_mother_date", "m_continuity", "m_is_ready", "m_ready_direction", "m_ready_reason",
    "w_status", "w_trend", "w_range_low", "w_range_high",
    "w_mother_date", "w_continuity", "w_is_ready", "w_ready_direction", "w_ready_reason",
]

# Aggregate file: all daily signals merged into one CSV with a log_date column.
# This avoids O(N) file opens when scanning history (e.g. _find_exit_info).
AGGREGATE_COLUMNS = ["log_date"] + CSV_COLUMNS
AGGREGATE_FILE = "signals_all.csv"


class SignalLogger:
    """Manages persistent signal logs, one JSON file per calendar day."""

    DEFAULT_DIR = "markets/logs"

    def __init__(self, log_dir: str = None):
        self.log_dir = Path(log_dir or self.DEFAULT_DIR)
        # In-memory write-through cache so that dedup works even after the
        # local CSV was deleted post-upload within the same process run.
        self._day_cache: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Core: log results
    # ------------------------------------------------------------------

    def log_scan_results(
        self,
        market: str,
        results: List[Dict[str, Any]],
        scan_date: Optional[date] = None,
    ) -> int:
        """
        Log a batch of scanner results.

        Args:
            market:    Market identifier (FX, BINANCE, COIN, …)
            results:   List of dicts returned by BaseScanner.analyze_symbol()
            scan_date: Override date (default: today)

        Returns:
            Number of new / updated entries written.
        """
        if not results:
            return 0

        today = (scan_date or date.today()).isoformat()
        file_path = self._file_for_date(today)

        # Load existing day-file (from cache if available, else disk/S3)
        day_data = self._day_cache.get(today)
        if day_data is None:
            day_data = self._load_file(file_path)

        count = 0
        removed = 0
        now_iso = datetime.now().isoformat()

        # Collect all symbols in this batch (READY + non-READY)
        # so we can remove stale READY entries for symbols no longer READY.
        batch_ready_keys: set = set()
        batch_all_keys: set = set()

        for r in results:
            if not r:
                continue
            key = f"{market.upper()}:{r['symbol']}"
            batch_all_keys.add(key)

            is_ready = (r.get("signal") or "").startswith("READY")
            if not is_ready:
                continue

            batch_ready_keys.add(key)
            entry = self._build_entry(market, r, now_iso)

            # Dedup: if same (market, symbol) already logged today with
            # identical signal → skip.  Otherwise upsert.
            existing = day_data.get(key)
            if existing and existing.get("signal") == entry["signal"]:
                continue  # duplicate — nothing changed

            day_data[key] = entry
            count += 1

        # Remove stale entries: symbols that were scanned (in batch)
        # but are NO LONGER READY — their old READY entry must go.
        stale_keys = batch_all_keys - batch_ready_keys
        for key in stale_keys:
            if key in day_data:
                del day_data[key]
                removed += 1

        self._save_file(file_path, day_data)
        # Keep aggregate in sync: replace this date's block
        self._update_aggregate(today, day_data)
        if removed:
            import logging as _log
            _log.getLogger(__name__).info(
                "Signal log %s: +%d updated, -%d stale removed", today, count, removed)
        return count

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def get_date(self, date_str: str) -> Dict[str, Any]:
        """Return the full day-data dict for a given date string (YYYY-MM-DD)."""
        cached = self._day_cache.get(date_str)
        if cached is not None:
            return cached
        return self._load_file(self._file_for_date(date_str))

    def get_ready_signals(self, date_str: str = None) -> List[Dict[str, Any]]:
        """Return only READY entries for a given date (default: today)."""
        date_str = date_str or date.today().isoformat()
        day_data = self.get_date(date_str)
        return [
            v for v in day_data.values()
            if v.get("signal") and "READY" in v["signal"]
        ]

    def list_dates(self) -> List[str]:
        """Return list of dates that have log files, sorted ascending.

        Checks local dir first; falls back to in-memory cache; finally S3
        listing when local dir is empty (e.g. after post-upload delete).
        """
        if self.log_dir.exists():
            local = [
                f.stem for f in self.log_dir.glob("*.csv")
                if f.stem != AGGREGATE_FILE.replace(".csv", "")
            ]
            if local:
                return sorted(local)
        # Check in-memory cache (always available in same process)
        if self._day_cache:
            return sorted(self._day_cache.keys())
        # Local empty / missing — enumerate from S3
        try:
            from infra.s3_storage import _get_singleton
            _PROJECT_ROOT = Path(__file__).resolve().parent.parent
            s3 = _get_singleton()
            if s3 is None:
                return []
            log_rel = str(
                Path(self.log_dir).resolve().relative_to(_PROJECT_ROOT)
            ).replace("\\", "/")
            prefix = f"{s3._report_prefix}/{log_rel}/"
            paginator = s3.client.get_paginator("list_objects_v2")
            dates = []
            for page in paginator.paginate(Bucket=s3._bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    fname = obj["Key"].rsplit("/", 1)[-1]
                    if fname.endswith(".csv") and fname != AGGREGATE_FILE:
                        dates.append(fname[:-4])
            return sorted(dates)
        except Exception:
            return []

    def get_symbol_history(self, symbol: str, market: str = None) -> List[Dict[str, Any]]:
        """
        Get signal history for a specific symbol across all dates.

        Uses the aggregate file for O(1) file-open instead of O(N).
        Falls back to per-file scan if aggregate doesn't exist.
        """
        agg = self.load_aggregate()
        if agg:
            history = []
            for entry in agg:
                if entry["symbol"] != symbol:
                    continue
                if market and entry["market"].upper() != market.upper():
                    continue
                history.append(dict(entry))
            return history

        # Fallback: per-file scan (slow)
        history = []
        for date_str in self.list_dates():
            day_data = self.get_date(date_str)
            for key, entry in day_data.items():
                if entry["symbol"] == symbol:
                    if market and entry["market"].upper() != market.upper():
                        continue
                    entry_copy = dict(entry)
                    entry_copy["log_date"] = date_str
                    history.append(entry_copy)
        return history

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def print_date(self, date_str: str = None):
        """Print a formatted table for a specific date."""
        date_str = date_str or date.today().isoformat()
        day_data = self.get_date(date_str)

        if not day_data:
            print(f"\n[!] No signal logs for {date_str}")
            return

        # Group by market
        by_market: Dict[str, List[Dict]] = {}
        for entry in day_data.values():
            mkt = entry["market"]
            by_market.setdefault(mkt, []).append(entry)

        print(f"\n{'='*130}")
        print(f"SIGNAL LOG — {date_str}  ({len(day_data)} symbols)")
        print(f"{'='*130}")

        for mkt in sorted(by_market):
            entries = sorted(by_market[mkt], key=lambda e: e["symbol"])
            print(f"\n  [{mkt.upper()}] ({len(entries)} symbols)")
            print(f"  {'SYMBOL':<14} {'SIGNAL':<20} {'M-STATUS':<14} {'M-TREND':<10} {'W-STATUS':<14} {'W-TREND':<10} {'READY DETAIL':<40}")
            print(f"  {'-'*124}")

            for e in entries:
                sig = e.get("signal") or "-"
                m_st = e.get("m_status") or "-"
                m_tr = (e.get("m_trend") or "-").upper()
                w_st = e.get("w_status") or "-"
                w_tr = (e.get("w_trend") or "-").upper()

                # Ready detail
                ready_parts = []
                for prefix, label in [("m", "M"), ("w", "W")]:
                    if e.get(f"{prefix}_is_ready"):
                        d = e.get(f"{prefix}_ready_direction") or "?"
                        dir_lbl = "Bull" if d == "bullish" else "Bear" if d == "bearish" else "?"
                        reason = e.get(f"{prefix}_ready_reason") or ""
                        short = ""
                        if "[" in reason and "]" in reason:
                            short = reason[reason.index("[") + 1 : reason.index("]")]
                        part = f"{label}:READY({dir_lbl})"
                        if short:
                            part += f" [{short}]"
                        ready_parts.append(part)
                ready_str = " | ".join(ready_parts) if ready_parts else "-"

                print(f"  {e['symbol']:<14} {sig:<20} {m_st:<14} {m_tr:<10} {w_st:<14} {w_tr:<10} {ready_str}")

        print(f"{'='*130}\n")

    def print_history(self, last_n: int = 7):
        """Print summary of logged signals over the last N dates."""
        dates = self.list_dates()
        if not dates:
            print("\n[!] No signal log history found.")
            return

        recent = dates[-last_n:]
        print(f"\n{'='*90}")
        print(f"SIGNAL LOG HISTORY  (last {len(recent)} days)")
        print(f"{'='*90}")
        print(f"  {'DATE':<14} {'TOTAL':<8} {'READY':<8} {'BULLISH':<10} {'BEARISH':<10} {'MARKETS'}")
        print(f"  {'-'*80}")

        for d in recent:
            day = self.get_date(d)
            total = len(day)
            ready = [v for v in day.values() if v.get("signal") and "READY" in v["signal"]]
            bullish = sum(1 for v in ready if "BULLISH" in (v.get("signal") or ""))
            bearish = sum(1 for v in ready if "BEARISH" in (v.get("signal") or ""))
            markets = sorted(set(v["market"] for v in day.values()))
            print(f"  {d:<14} {total:<8} {len(ready):<8} {bullish:<10} {bearish:<10} {', '.join(markets)}")

        print(f"{'='*90}\n")

    def print_ready_history(self, last_n: int = 7):
        """Print only READY signals across recent dates."""
        dates = self.list_dates()
        if not dates:
            print("\n[!] No signal log history found.")
            return

        recent = dates[-last_n:]
        print(f"\n{'='*100}")
        print(f"READY SIGNAL HISTORY  (last {len(recent)} days)")
        print(f"{'='*100}")

        for d in recent:
            ready = self.get_ready_signals(d)
            if not ready:
                continue
            print(f"\n  [{d}] — {len(ready)} READY signal(s)")
            for e in sorted(ready, key=lambda x: (x["market"], x["symbol"])):
                sig = e.get("signal", "")
                print(f"    {e['market']:<10} {e['symbol']:<14} {sig}")

        print(f"\n{'='*100}\n")

    def print_symbol_history(self, symbol: str, market: str = None):
        """Print signal history for one symbol."""
        history = self.get_symbol_history(symbol, market)
        if not history:
            print(f"\n[!] No history found for {symbol}")
            return

        print(f"\n{'='*80}")
        print(f"SIGNAL HISTORY: {symbol}")
        print(f"{'='*80}")
        print(f"  {'DATE':<14} {'SIGNAL':<20} {'M-STATUS':<14} {'W-STATUS':<14} {'W-TREND':<10}")
        print(f"  {'-'*70}")

        for e in history:
            sig = e.get("signal") or "-"
            m_st = e.get("m_status") or "-"
            w_st = e.get("w_status") or "-"
            w_tr = (e.get("w_trend") or "-").upper()
            print(f"  {e['log_date']:<14} {sig:<20} {m_st:<14} {w_st:<14} {w_tr:<10}")

        print(f"{'='*80}\n")

    # ------------------------------------------------------------------
    # Aggregate: single-file signal database
    # ------------------------------------------------------------------

    @property
    def _aggregate_path(self) -> Path:
        return self.log_dir / AGGREGATE_FILE

    def aggregate(self, *, force: bool = False) -> Path:
        """Rebuild ``signals_all.csv`` from all daily CSV files.

        Args:
            force: If True, rebuild even if aggregate already exists.

        Returns:
            Path to the aggregate file.
        """
        agg_path = self._aggregate_path
        if agg_path.exists() and not force:
            # Incremental: already up-to-date if last date in agg >= last daily file
            last_agg_date = self._last_aggregate_date()
            daily_dates = self.list_dates()
            if daily_dates and last_agg_date and last_agg_date >= daily_dates[-1]:
                return agg_path

        daily_dates = self.list_dates()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        with open(agg_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=AGGREGATE_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            for d in daily_dates:
                day_data = self._day_cache.get(d) or self._load_file(self._file_for_date(d))
                for entry in day_data.values():
                    entry["log_date"] = d
                    writer.writerow(entry)
        # Sync aggregate to S3 then remove local copy
        try:
            from infra.s3_storage import upload_and_clean
            upload_and_clean(agg_path)
        except Exception:
            pass
        return agg_path

    def load_aggregate(self) -> List[Dict[str, Any]]:
        """Load the aggregate file into a list of dicts.

        Returns empty list if aggregate doesn't exist.
        Each dict has a ``log_date`` field.
        """
        agg_path = self._aggregate_path

        def _read(p: Path) -> List[Dict[str, Any]]:
            rows: List[Dict[str, Any]] = []
            with open(p, "r", encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    self._parse_row(row)
                    rows.append(row)
            return rows

        if agg_path.exists():
            return _read(agg_path)
        try:
            from infra.s3_storage import download_read_clean
            return download_read_clean(agg_path, _read) or []
        except Exception:
            return []

    def load_aggregate_by_date(self) -> Dict[str, Dict[str, Dict[str, Any]]]:
        """Load aggregate indexed by date then key.

        Returns ``{date_str: {"MARKET:SYMBOL": entry, ...}, ...}``.
        """
        result: Dict[str, Dict[str, Dict[str, Any]]] = {}
        for entry in self.load_aggregate():
            d = entry.get("log_date", "")
            key = f"{entry['market']}:{entry['symbol']}"
            result.setdefault(d, {})[key] = entry
        return result

    def _update_aggregate(self, date_str: str, day_data: Dict[str, Any]):
        """Replace one date's block inside the aggregate file.

        If aggregate doesn't exist (locally or on S3), skip
        (will be built on first tracker run or explicit ``aggregate()`` call).
        """
        # Load existing aggregate (handles S3 download+cleanup)
        existing = self.load_aggregate()
        if not existing:
            return

        agg_path = self._aggregate_path
        kept = [r for r in existing if r.get("log_date") != date_str]
        for entry in day_data.values():
            row = dict(entry)
            row["log_date"] = date_str
            kept.append(row)
        # Sort by date for deterministic output
        kept.sort(key=lambda r: r.get("log_date", ""))

        self.log_dir.mkdir(parents=True, exist_ok=True)
        with open(agg_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=AGGREGATE_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            for r in kept:
                writer.writerow(r)
        # Sync to S3 then remove local copy
        try:
            from infra.s3_storage import upload_and_clean
            upload_and_clean(agg_path)
        except Exception:
            pass

    def _last_aggregate_date(self) -> Optional[str]:
        """Return the last log_date present in the aggregate file."""
        def _read_last_date(p: Path) -> Optional[str]:
            last = None
            with open(p, "r", encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    d = row.get("log_date", "")
                    if d and (last is None or d > last):
                        last = d
            return last

        agg_path = self._aggregate_path
        if agg_path.exists():
            return _read_last_date(agg_path)
        try:
            from infra.s3_storage import download_read_clean
            return download_read_clean(agg_path, _read_last_date)
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _file_for_date(self, date_str: str) -> Path:
        return self.log_dir / f"{date_str}.csv"

    @staticmethod
    def _parse_row(row: Dict[str, Any]):
        """In-place type coercion for a raw CSV row."""
        for col in ("entry_price", "m_range_low", "m_range_high", "w_range_low", "w_range_high"):
            v = row.get(col)
            row[col] = float(v) if v not in ("", "None", None) else None
        for col in ("m_continuity", "w_continuity"):
            v = row.get(col)
            try:
                row[col] = int(v) if v not in ("", "None", None) else 0
            except (ValueError, TypeError):
                row[col] = 0
        for col in ("m_is_ready", "w_is_ready"):
            row[col] = str(row.get(col, "")).lower() in ("true", "1", "yes")
        for col in ("m_ready_direction", "w_ready_direction",
                    "m_mother_date", "w_mother_date",
                    "m_ready_reason", "w_ready_reason"):
            if row.get(col) in ("", "None"):
                row[col] = None

    def _load_file(self, path: Path) -> Dict[str, Any]:
        def _read(p: Path) -> Dict[str, Any]:
            result: Dict[str, Any] = {}
            with open(p, "r", encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    self._parse_row(row)
                    key = f"{row['market']}:{row['symbol']}"
                    result[key] = dict(row)
            return result

        if path.exists():
            return _read(path)
        try:
            from infra.s3_storage import download_read_clean
            return download_read_clean(path, _read) or {}
        except Exception:
            return {}

    def _save_file(self, path: Path, data: Dict[str, Any]):
        self.log_dir.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            for entry in data.values():
                writer.writerow(entry)
        # Update in-memory cache so dedup works within the same run
        self._day_cache[path.stem] = data
        # Sync to S3 then remove local copy
        try:
            from infra.s3_storage import upload_and_clean
            upload_and_clean(path)
        except Exception:
            pass

    @staticmethod
    def _build_entry(market: str, result: Dict[str, Any], timestamp: str) -> Dict[str, Any]:
        """Convert a single scanner result dict into a flat CSV-compatible log entry."""
        m = result.get("monthly", {})
        w = result.get("weekly", {})
        return {
            "market": market.upper(),
            "symbol": result["symbol"],
            "signal": result.get("signal"),
            "scanned_at": timestamp,
            "entry_price": result.get("entry_price"),
            "m_status": m.get("status"),
            "m_trend": m.get("trend"),
            "m_range_low": m.get("range_low"),
            "m_range_high": m.get("range_high"),
            "m_mother_date": str(m.get("mother_date")) if m.get("mother_date") else None,
            "m_continuity": m.get("continuity", 0),
            "m_is_ready": m.get("is_ready", False),
            "m_ready_direction": m.get("ready_direction"),
            "m_ready_reason": m.get("ready_reason", ""),
            "w_status": w.get("status"),
            "w_trend": w.get("trend"),
            "w_range_low": w.get("range_low"),
            "w_range_high": w.get("range_high"),
            "w_mother_date": str(w.get("mother_date")) if w.get("mother_date") else None,
            "w_continuity": w.get("continuity", 0),
            "w_is_ready": w.get("is_ready", False),
            "w_ready_direction": w.get("ready_direction"),
            "w_ready_reason": w.get("ready_reason", ""),
        }


# ── CLI ──────────────────────────────────────────────────────────

def main():
    """CLI entry point: ``python -m infra.signal_logger [options]``."""
    import argparse

    parser = argparse.ArgumentParser(description="Signal Logger utilities")
    sub = parser.add_subparsers(dest="command")

    # aggregate
    agg_p = sub.add_parser("aggregate", help="Rebuild signals_all.csv from daily CSVs")
    agg_p.add_argument("--force", action="store_true",
                        help="Force full rebuild even if aggregate seems current")

    # print helpers (kept for convenience)
    sub.add_parser("history", help="Print signal history (last 7 days)")
    sub.add_parser("ready", help="Print recent READY signals")

    args = parser.parse_args()
    logger = SignalLogger()

    if args.command == "aggregate":
        path = logger.aggregate(force=args.force)
        n = len(logger.load_aggregate())
        print(f"Aggregate built: {path}  ({n} signal rows)")
    elif args.command == "history":
        logger.print_history()
    elif args.command == "ready":
        logger.print_ready_history()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
