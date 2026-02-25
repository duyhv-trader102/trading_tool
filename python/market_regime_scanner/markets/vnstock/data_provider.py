import os
import polars as pl
from typing import Optional, List
from .config import DATA_DIR
from data_providers.base import BaseDataProvider
from data_providers.parquet_data_provider import ParquetDataProvider

# Self-register this market's data directory so UnifiedDataProvider can find VNStock files
ParquetDataProvider.register_fallback(DATA_DIR, "D1")

class VNStockDataProvider(BaseDataProvider):

    def __init__(self, data_dir: str = DATA_DIR):
        self.data_dir = data_dir

    def get_data(self, symbol: str = "VNM", timeframe: str = '1D', bars: Optional[int] = None, *, has_weekend: bool = False) -> Optional[pl.DataFrame]:

        """
        Load data for symbol. If timeframe is not '1D', try native parquet first,
        then fall back to resampling from D1.
        Returns Polars DataFrame with columns: time, open, high, low, close, volume.
        """
        # Map timeframe to file suffix  (e.g. '1W'→'W1', '1D'→'D1')
        _tf_to_suffix = {'1W': 'W1', 'W1': 'W1', '1H': 'H1', 'H1': 'H1', '1D': 'D1', 'D1': 'D1'}
        suffix = _tf_to_suffix.get(timeframe.upper(), None)

        from infra.s3_storage import smart_read_parquet

        # Try native parquet for the requested timeframe first
        if suffix and suffix != 'D1':
            native_path = os.path.join(self.data_dir, f"{symbol}_{suffix}.parquet")
            try:
                df = smart_read_parquet(native_path)
                if df is not None:
                    df.columns = [c.lower() for c in df.columns]
                    if "time" in df.columns:
                        df = df.sort("time")
                    if bars and len(df) > bars:
                        df = df.slice(-bars, bars)
                    return df
            except Exception as e:
                print(f"Error loading native {suffix} for {symbol}, falling back to resample: {e}")

        # Fall back to D1 (and resample if needed)
        path = os.path.join(self.data_dir, f"{symbol}_D1.parquet")
        df = smart_read_parquet(path)
        if df is None:
            print(f"Data file not found: {path}")
            return None
        
        try:
            # Ensure columns are lower case
            df.columns = [c.lower() for c in df.columns]
            
            # Sort by time
            if "time" in df.columns:
                df = df.sort("time")
            
            # Resample if needed
            if timeframe != '1D' and timeframe != 'D1':
                from core.resampler import resample_data
                df = resample_data(df, timeframe)

            # Apply bar limit (take most recent N bars)
            if bars and len(df) > bars:
                df = df.slice(-bars, bars)

            return df
        except Exception as e:
            print(f"Error loading {symbol}: {e}")
            return None


    def get_all_symbols(self):
        """Return all available symbols (S3 primary, local fallback)."""
        from infra.s3_storage import s3_dir_mtimes
        s3_fnames = [f for f in s3_dir_mtimes("vnstock") if f.endswith("_D1.parquet")]
        local_fnames: list = []
        if os.path.exists(self.data_dir):
            local_fnames = [f for f in os.listdir(self.data_dir) if f.endswith("_D1.parquet")]
        all_files = set(s3_fnames) | set(local_fnames)
        return sorted([f.replace("_D1.parquet", "") for f in all_files])

    def get_group_symbols(self, group: str) -> List[str]:
        """Fetch symbols for a specific group (VN30, VN100, etc.) from API."""
        try:
            from vnstock import Vnstock
            # Initialize with dummy symbol to access listing
            stock = Vnstock().stock(symbol='VNM', source='VCI')
            if hasattr(stock, 'listing') and hasattr(stock.listing, 'symbols_by_group'):
                series = stock.listing.symbols_by_group(group.upper())
                return series.tolist()
        except Exception as e:
            print(f"Error fetching group {group}: {e}")
            return []
        return []

    def ensure_data(self, symbol: str, timeframe: str) -> bool:
        """
        Ensure data file exists and is fresh (max 20h old for D1).
        Checks S3 first (primary store), then local as fallback.
        NOTE: No per-symbol sleep here — rate limiting is handled at the
        batch level in markets.sync.sync_vnstock_data.
        """
        import time
        from .downloader import VNStockDownloader
        from infra.s3_storage import s3_dir_mtimes

        s3_fname = f"{symbol}_D1.parquet"
        fresh_threshold = 20 * 60 * 60  # 20 hours

        # Check S3 freshness (primary store)
        mtimes = s3_dir_mtimes("vnstock")
        if s3_fname in mtimes:
            age = time.time() - mtimes[s3_fname]
            if age <= fresh_threshold:
                return True
        else:
            # Fall back to local file check
            path = os.path.join(self.data_dir, f"{symbol}_D1.parquet")
            if os.path.exists(path) and (time.time() - os.path.getmtime(path)) <= fresh_threshold:
                return True

        try:
            downloader = VNStockDownloader()
            downloader.download_symbol(symbol)
        except Exception as e:
            print(f"Failed to refresh data for {symbol}: {e}")

        return s3_fname in s3_dir_mtimes("vnstock")

