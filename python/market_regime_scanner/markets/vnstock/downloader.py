from vnstock import Vnstock
from datetime import datetime
import pandas as pd
import polars as pl
import os
import logging

from markets.vnstock.config import VNSTOCK_API_KEY, VN30_SYMBOLS, VN100_SYMBOLS
from infra.s3_storage import write_parquet_s3, read_parquet_s3

logger = logging.getLogger(__name__)

# Configure API Key if library supports it via env or global config
os.environ["VNSTOCK_API_KEY"] = VNSTOCK_API_KEY

class VNStockDownloader:
    def __init__(self):
        pass  # no local data directory — all data stored on S3

    # ── internal helpers ──────────────────────────────────────────────────

    @staticmethod
    def _normalize_and_save(df: pd.DataFrame, s3_rel_key: str, sort: bool = False) -> pl.DataFrame:
        """Normalize pandas df → polars, ensure 'time' column, write directly to S3."""
        df.columns = [c.lower() for c in df.columns]
        pl_df = pl.from_pandas(df)
        if 'time' in pl_df.columns:
            pl_df = pl_df.with_columns(pl.col("time").cast(pl.Datetime))
        elif 'date' in pl_df.columns:
            pl_df = pl_df.rename({"date": "time"}).with_columns(pl.col("time").cast(pl.Datetime))
        if sort and 'time' in pl_df.columns:
            pl_df = pl_df.sort("time")

        # Write directly to S3 — no local file created
        ok = write_parquet_s3(s3_rel_key, pl_df)
        if not ok:
            logger.warning("S3 upload failed for %s", s3_rel_key)

        return pl_df

    def _fetch_vci(self, symbol: str, start_date: str, end_date: str,
                   interval: str = '1D') -> pd.DataFrame | None:
        """Fetch data from VCI source; returns pandas DataFrame or None."""
        stock = Vnstock().stock(symbol=symbol, source='VCI')
        df = stock.quote.history(start=start_date, end=end_date, interval=interval)
        if df is None or df.empty:
            return None
        return df

    # ── public download methods ───────────────────────────────────────────

    def download_symbol(self, symbol="VNM", start_date="2000-01-01", end_date=None):
        if end_date is None:
            end_date = datetime.now().strftime("%Y-%m-%d")

        logger.info(f"Downloading {symbol} from {start_date} to {end_date}...")
        s3_key = f"vnstock/{symbol}_D1.parquet"

        try:
            df = self._fetch_vci(symbol, start_date, end_date)
            if df is None:
                logger.error(f"No data returned for {symbol}")
                return
            self._normalize_and_save(df, s3_key)
            logger.info(f"Uploaded {symbol} D1 → s3:{s3_key}")

        except Exception as e:
            logger.error(f"Failed to download {symbol} (VCI): {e}")
            # Fallback to TCBS source
            try:
                logger.info("Retrying with TCBS source...")
                stock = Vnstock().stock(symbol=symbol, source='TCBS')
                df = stock.quote.history(start=start_date, end=end_date)
                if df is not None and not df.empty:
                    self._normalize_and_save(df, s3_key)
                    logger.info(f"Uploaded {symbol} D1 (TCBS) → s3:{s3_key}")
            except Exception as e2:
                logger.error(f"Retry failed for {symbol}: {e2}")

    def download_symbol_w1(self, symbol="VNM"):
        """Generate W1 (weekly) data by resampling the existing D1 parquet.

        VCI API does not support a weekly interval, so we read D1 from S3,
        resample it to W1 via ``core.resampler``, and upload W1 back to S3.
        The D1 data must already exist on S3 — call ``download_symbol`` first.
        """
        d1_key = f"vnstock/{symbol}_D1.parquet"
        df = read_parquet_s3(d1_key)
        if df is None:
            logger.warning(f"D1 not found on S3 for {symbol} ({d1_key}), skipping W1 generation")
            return

        try:
            from core.resampler import resample_data
            df.columns = [c.lower() for c in df.columns]
            if "time" not in df.columns and "date" in df.columns:
                df = df.rename({"date": "time"})
            df = df.sort("time")
            w1 = resample_data(df, "1W")
            w1_key = f"vnstock/{symbol}_W1.parquet"
            ok = write_parquet_s3(w1_key, w1)
            if ok:
                logger.info(f"Uploaded {symbol} W1 ({len(w1)} bars) → s3:{w1_key}")
            else:
                logger.error(f"S3 upload failed for {symbol} W1")
        except Exception as e:
            logger.error(f"Failed to generate {symbol} W1: {e}")

    def download_symbol_1h(self, symbol="VNM", start_date="2020-01-01", end_date=None):
        """Download 1H (intraday) data for a single VN stock.

        VN market trades ~5 hours/day (09-11:30, 13-14:45) so 1H bars
        give ~5 bars per trading day — ideal for Daily TPO sessions.
        VCI source typically provides ~2.5 years of 1H history.
        """
        if end_date is None:
            end_date = datetime.now().strftime("%Y-%m-%d")

        logger.info(f"Downloading {symbol} 1H from {start_date} to {end_date}...")

        try:
            df = self._fetch_vci(symbol, start_date, end_date, interval='1H')
            if df is None:
                logger.error(f"No 1H data returned for {symbol}")
                return
            s3_key = f"vnstock/{symbol}_H1.parquet"
            pl_df = self._normalize_and_save(df, s3_key, sort=True)
            logger.info(f"Uploaded {symbol} H1 ({len(pl_df)} bars) → s3:{s3_key}")

        except Exception as e:
            logger.error(f"Failed to download {symbol} 1H: {e}")

    # ── list helpers ──────────────────────────────────────────────────────

    def get_vn30_list(self):
        """Get list of VN30 symbols dynamically using vnstock."""
        try:
            stock = Vnstock().stock(symbol='VNM', source='VCI')
            res = stock.listing.symbols_by_group('VN30')
            if hasattr(res, 'tolist'):
                return res.tolist()
            return res['symbol'].tolist()
        except Exception as e:
            logger.error(f"Failed to fetch VN30 list: {e}")
            return list(VN30_SYMBOLS)   # fallback from config (single source)

    def get_vn100_list(self):
        """Get list of VN100 symbols dynamically."""
        try:
            stock = Vnstock().stock(symbol='VNM', source='VCI')
            res = stock.listing.symbols_by_group('VN100')
            if hasattr(res, 'tolist'):
                return res.tolist()
            return res['symbol'].tolist()
        except Exception as e:
            logger.error(f"Failed to fetch VN100 list: {e}")
            return list(VN100_SYMBOLS)  # fallback from config (single source)

    # ── batch download ────────────────────────────────────────────────────

    def download_index(self, index_name="VN30"):
        """Download D1 data for all symbols in a given index."""
        symbols = self._get_index_symbols(index_name)
        if symbols is None:
            return
        logger.info(f"Downloading data for {len(symbols)} {index_name} symbols...")
        for symbol in symbols:
            self.download_symbol(symbol=symbol)
        logger.info(f"{index_name} download complete.")

    def download_index_1h(self, index_name="VN30"):
        """Download 1H intraday data for all symbols in a given index."""
        symbols = self._get_index_symbols(index_name)
        if symbols is None:
            return
        logger.info(f"Downloading 1H data for {len(symbols)} {index_name} symbols...")
        for symbol in symbols:
            self.download_symbol_1h(symbol=symbol)
        logger.info(f"{index_name} 1H download complete.")

    def download_index_w1(self, index_name="VN30"):
        """Generate W1 data (from D1) for all symbols in a given index."""
        symbols = self._get_index_symbols(index_name)
        if symbols is None:
            return
        logger.info(f"Generating W1 data for {len(symbols)} {index_name} symbols...")
        for symbol in symbols:
            self.download_symbol_w1(symbol=symbol)
        logger.info(f"{index_name} W1 generation complete.")

    def _get_index_symbols(self, index_name: str):
        if index_name == "VN30":
            return self.get_vn30_list()
        elif index_name == "VN100":
            return self.get_vn100_list()
        else:
            logger.error(f"Unsupported index: {index_name}")
            return None

if __name__ == "__main__":
    downloader = VNStockDownloader()
    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()
        if cmd == "vn30":
            downloader.download_index("VN30")
        elif cmd == "vn100":
            downloader.download_index("VN100")
        elif cmd == "vn30-1h":
            downloader.download_index_1h("VN30")
        elif cmd == "vn100-1h":
            downloader.download_index_1h("VN100")
        elif cmd == "vn30-w1":
            downloader.download_index_w1("VN30")
        elif cmd == "vn100-w1":
            downloader.download_index_w1("VN100")
        elif cmd.endswith("-1h"):
            downloader.download_symbol_1h(cmd[:-3].upper())
        else:
            downloader.download_symbol(sys.argv[1])
    else:
        downloader.download_symbol("VNM")
