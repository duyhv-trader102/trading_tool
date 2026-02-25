import os
import logging
import sys
import polars as pl
from typing import List, Optional

try:
    import ccxt
except ImportError:
    print("Error: 'ccxt' library not found. Please install it using 'pip install ccxt'.")
    sys.exit(1)

from markets.binance.config import DEFAULT_SYMBOLS
from infra.s3_storage import write_parquet_s3

logger = logging.getLogger(__name__)

class BinanceDownloader:
    def __init__(self, exchange_id='binance'):
        exchange_class = getattr(ccxt, exchange_id)
        self.exchange = exchange_class({
            'enableRateLimit': True,
        })
        self.exchange.load_markets()

    def download_symbol(self, symbol: str, timeframe: str = '4h', years: int = 10):
        """
        Download OHLCV data from Binance and save to parquet.
        Fetches as much historical data as possible up to `years` ago.
        
        Args:
            symbol: e.g., "BTC/USDT"
            timeframe: e.g., "4h", "1d"
            years: Number of years to go back
        """
        # Normalize symbol for filename
        filename_symbol = symbol.replace("/", "_").replace(":", "_")
        
        # CCXT timeframe to standard label for filename
        tf_label = timeframe.upper()
        if tf_label == "1D": tf_label = "D1"
        if tf_label == "4H": tf_label = "H4"
        if tf_label == "1W": tf_label = "W1"

        s3_key = f"binance/{filename_symbol}_{tf_label}.parquet"

        logger.info(f"Downloading {symbol} ({timeframe}) from Binance (up to {years} years)...")
        
        since = self.exchange.milliseconds() - years * 365 * 24 * 60 * 60 * 1000
        all_ohlcv = []
        
        try:
            while True:
                ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=1000)
                if not ohlcv:
                    break
                
                all_ohlcv.extend(ohlcv)
                # Update since to the timestamp of the last candle + 1ms
                new_since = ohlcv[-1][0] + 1
                if new_since == since: # Prevent infinite loops
                    break
                since = new_since
                
                # Sleep briefly to respect rate limits if needed (ccxt usually handles it)
                if len(ohlcv) < 1000: # We reached the end
                    break

            if not all_ohlcv:
                logger.error(f"No data returned for {symbol}")
                return

            # ccxt structure: [timestamp, open, high, low, close, volume]
            # Some symbols return float values (e.g. 1.0) for timestamp/volume;
            # don't enforce Int64 schema at construction — cast explicitly after.
            df = pl.DataFrame(
                all_ohlcv,
                schema={
                    "time": pl.Float64,   # accept float (1.0) → cast to Int64 below
                    "open": pl.Float64,
                    "high": pl.Float64,
                    "low": pl.Float64,
                    "close": pl.Float64,
                    "volume": pl.Float64,
                },
                orient="row",
            )
            df = df.with_columns(
                pl.col("time").cast(pl.Int64).cast(pl.Datetime("ms"))
            )
            
            # Sort by time and drop duplicates
            df = df.unique("time", keep="last").sort("time")

            # Write directly to S3 — no local file created
            ok = write_parquet_s3(s3_key, df)
            if ok:
                logger.info(f"Uploaded {symbol} ({tf_label}) → s3:{s3_key} ({len(df)} rows)")
            else:
                logger.error(f"S3 upload failed for {symbol} {tf_label}")

        except Exception as e:
            logger.error(f"Failed to download {symbol}: {e}")

    def get_all_spot_symbols(self, quote_currency: Optional[str] = 'USDT') -> List[str]:
        """Get all spot symbols from Binance, optionally filtered by quote currency."""
        symbols = []
        for symbol, market in self.exchange.markets.items():
            if market.get('type') == 'spot' and market.get('active'):
                if quote_currency:
                    if market.get('quote') == quote_currency.upper():
                        symbols.append(symbol)
                else:
                    symbols.append(symbol)
        return sorted(symbols)

    def download_default_symbols(self, timeframe: str = '4h', years: int = 10):
        """Download data for all default symbols."""
        logger.info(f"Downloading data for {len(DEFAULT_SYMBOLS)} default symbols ({timeframe}, {years} years)...")
        for symbol in DEFAULT_SYMBOLS:
            self.download_symbol(symbol, timeframe=timeframe, years=years)
        logger.info("Batch download complete.")

if __name__ == "__main__":
    downloader = BinanceDownloader()
    if len(sys.argv) > 1:
        arg1 = sys.argv[1]
        if arg1.lower() == "all":
            downloader.download_default_symbols()
        elif arg1.lower() == "list_spot":
            # Optional quote filter
            quote = sys.argv[2] if len(sys.argv) > 2 else 'USDT'
            symbols = downloader.get_all_spot_symbols(quote_currency=quote)
            print(f"\nBinance Spot Symbols ({quote if quote else 'ALL'}):")
            print(", ".join(symbols))
            print(f"\nTotal: {len(symbols)} symbols")
        else:
            # Support comma-separated symbols (case sensitive for symbols)
            symbols = arg1.split(",")
            for s in symbols:
                downloader.download_symbol(s.strip(), timeframe='4h', years=10)
    else:
        # Default to downloading BTC/USDT if no arg provided
        downloader.download_symbol("BTC/USDT", timeframe='4h', years=10)
