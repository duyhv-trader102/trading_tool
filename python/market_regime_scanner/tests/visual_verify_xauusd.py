"""
Visual verification test — generates a TPO chart for XAUUSDm H4.

Run manually to visually inspect TPO output:
    python tests/visual_verify_xauusd.py

Auto-skipped by pytest when parquet data is absent.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "data" / "mt5" / "XAUUSDm_H4.parquet"


@pytest.mark.skipif(not DATA_PATH.exists(), reason="XAUUSDm_H4.parquet not found")
def test_xauusd_tpo_sessions_non_empty():
    """TPO engine must produce sessions from XAUUSDm H4 data."""
    import polars as pl
    from core.tpo import TPOProfile

    df = pl.read_parquet(DATA_PATH)
    tpo_engine = TPOProfile(va_percentage=0.7, ib_bars=2)
    sessions = tpo_engine.analyze_dynamic(df, session_type="D", target_rows=40)
    assert sessions, "TPO engine returned empty session list"
    assert len(sessions) >= 10


def run_visual_test():
    """Generate a full TPO chart HTML for manual review."""
    if not DATA_PATH.exists():
        print(f"[!] Data file not found: {DATA_PATH}")
        return

    import polars as pl
    from core.tpo import TPOProfile
    from viz.tpo_visualizer import visualize_tpo_blocks

    print(f"Loading XAUUSDm H4 …")
    df = pl.read_parquet(DATA_PATH)

    tpo_engine = TPOProfile(va_percentage=0.7, ib_bars=2)
    sessions = tpo_engine.analyze_dynamic(df, session_type="D", target_rows=40)
    sessions = sessions[-20:]

    print(f"Sessions: {len(sessions)}")
    for s in sessions:
        dist = s.distribution_type or ""
        print(f"  {s.session_start.date()}  POC={s.poc:.2f}  VA={s.val:.2f}–{s.vah:.2f}  {dist}")

    output_file = ROOT / "viz" / "output" / "xauusd_regime_verify.html"
    os.makedirs(output_file.parent, exist_ok=True)
    visualize_tpo_blocks(sessions, target_rows=40, n_sessions=len(sessions), filename=str(output_file))
    print(f"\nChart → {output_file}")


if __name__ == "__main__":
    run_visual_test()
