import os
import polars as pl
from typing import Optional, List
from .config import DATA_DIR
from data_providers.base import BaseDataProvider
from data_providers.parquet_data_provider import ParquetDataProvider

# Self-register this market's data directory so UnifiedDataProvider can find Binance files.
# stored_tf="H4" is the fallback when only H4 exists; native D1/W1 files are found by exact match.
ParquetDataProvider.register_fallback(DATA_DIR, "H4")

class BinanceDataProvider(BaseDataProvider):

    def __init__(self, data_dir: str = DATA_DIR):
        self.data_dir = data_dir

    def get_data(self, symbol: str = "BTC/USDT", timeframe: str = '4h', bars: Optional[int] = None, *, has_weekend: bool = False) -> Optional[pl.DataFrame]:
        """
        Load data for symbol. Resample from H4 storage to requested timeframe.
        Returns Polars DataFrame with columns: time, open, high, low, close, volume.
        """
        # Normalize symbol for filename: replace / with _ and : with _
        filename_symbol = symbol.replace("/", "_").replace(":", "_")
        
        # Determine frequency for filename
        # Default is H4 (the storage resolution)
        stored_tf = 'H4'
        from infra.s3_storage import smart_read_parquet

        path_h4 = os.path.join(self.data_dir, f"{filename_symbol}_H4.parquet")
        df = smart_read_parquet(path_h4)

        if df is None:
            # Fallback to D1 if H4 doesn't exist
            path_d1 = os.path.join(self.data_dir, f"{filename_symbol}_D1.parquet")
            stored_tf = 'D1'
            df = smart_read_parquet(path_d1)
            if df is None:
                print(f"Data file not found: {path_d1} (tried H4 and D1)")
                return None
        
        try:
            
            # Ensure columns are lower case
            df.columns = [c.lower() for c in df.columns]
            
            # Sort by time
            if "time" in df.columns:
                df = df.sort("time")
            
            # Resample if requested timeframe differs from stored
            req_tf = timeframe.upper()
            if req_tf in ['1D', 'D1']:
                req_tf = 'D1'
            elif req_tf in ['1W', 'W1']:
                req_tf = 'W1'
            elif req_tf in ['4H', 'H4']:
                req_tf = 'H4'
                
            if req_tf != stored_tf:
                from core.resampler import resample_data
                df = resample_data(df, req_tf, has_weekend=True)

            # Apply bar limit (take most recent N bars)
            if bars and len(df) > bars:
                df = df.slice(-bars, bars)

            return df
        except Exception as e:
            print(f"Error loading {symbol}: {e}")
            return None

    def get_all_symbols(self) -> List[str]:
        """Get all symbols available (S3 primary, local fallback)."""
        from infra.s3_storage import s3_dir_mtimes
        # S3 is the primary store after migration
        s3_fnames = [
            f for f in s3_dir_mtimes("binance")
            if f.endswith("_H4.parquet") or f.endswith("_D1.parquet")
        ]
        # Merge with any local files
        local_fnames: list = []
        if os.path.exists(self.data_dir):
            local_fnames = [
                f for f in os.listdir(self.data_dir)
                if f.endswith("_H4.parquet") or f.endswith("_D1.parquet")
            ]
        files = list(set(s3_fnames) | set(local_fnames))
        # Convert filenames to canonical BASE/USDT format, then deduplicate via set.
        # Two filename styles exist:
        #   BTC_USDT_H4.parquet  ->  BTC_USDT  ->  BTC/USDT  (underscore-separated)
        #   BTCUSDT_H4.parquet   ->  BTCUSDT   ->  BTC/USDT  (no separator)
        symbols = set()
        for f in files:
            base = f.replace("_H4.parquet", "").replace("_D1.parquet", "")
            if "_" in base:
                # BTC_USDT or BTC_USDT_PERP etc — split on first underscore boundary
                s = base.replace("_", "/", 1)   # BTC_USDT -> BTC/USDT
            elif base.upper().endswith("USDT"):
                # BTCUSDT -> BTC/USDT
                s = base[:-4] + "/USDT"
            else:
                s = base
            symbols.add(s)
        return sorted(list(symbols))

    def get_group_symbols(self, group: str) -> List[str]:
        """Binance doesn't have native 'groups' like VN30 yet. Return all for now."""
        return self.get_all_symbols()

    def ensure_data(self, symbol: str, timeframe: str) -> bool:
        """Ensure data is present and fresh (max 4h old for H4)."""
        import time
        from .downloader import BinanceDownloader
        from infra.s3_storage import s3_dir_mtimes

        filename_symbol = symbol.replace("/", "_").replace(":", "_")
        s3_fname = f"{filename_symbol}_H4.parquet"
        fresh_threshold = 4 * 60 * 60  # 4 hours

        # Check S3 freshness (primary store)
        mtimes = s3_dir_mtimes("binance")
        if s3_fname in mtimes:
            age = time.time() - mtimes[s3_fname]
            if age <= fresh_threshold:
                return True
            print(f"Data for {symbol} is stale ({age/3600:.1f}h old), refreshing...")
        else:
            # Fall back to local file check
            path = os.path.join(self.data_dir, f"{filename_symbol}_H4.parquet")
            if os.path.exists(path):
                age = time.time() - os.path.getmtime(path)
                if age <= fresh_threshold:
                    return True
                print(f"Data for {symbol} is stale ({age/3600:.1f}h old), refreshing...")
            else:
                print(f"Data missing for {symbol}, triggering download...")

        try:
            downloader = BinanceDownloader()
            downloader.download_symbol(symbol, timeframe='4h', years=10)
            return s3_fname in s3_dir_mtimes("binance")
        except Exception as e:
            print(f"Failed to refresh data for {symbol}: {e}")
            return False
