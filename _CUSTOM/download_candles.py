# This is necessary to recognize the modules
import os
import sys
from decimal import Decimal
import warnings
import asyncio
warnings.filterwarnings("ignore")

root_path = os.path.abspath(os.path.join(os.getcwd(), '../'))
sys.path.append(root_path)

from core.data_sources.clob import CLOBDataSource


async def main():
    # Get trading rules and candles
    clob = CLOBDataSource()
    # Constants
    CONNECTOR_NAME = "binance_perpetual"
    INTERVALS = [
        
        # "1m", "5m", "15m", 
        "30m"
        ]
    trading_pairs = [
        # "BTC-USDT", "WLD-USDT", "ETH-USDT", "XRP-USDT", "BNB-USDT",
                    "SOL-USDT"]

    DAYS = 2
    # Download Data
    BATCH_CANDLES_REQUEST = 1
    SLEEP_REQUEST = 1

    all_candles = {
        interval: await clob.get_candles_batch_last_days(CONNECTOR_NAME, trading_pairs, interval, DAYS, BATCH_CANDLES_REQUEST,
                                                    SLEEP_REQUEST) for interval in INTERVALS
    }
    clob.dump_candles_cache(root_path)

if __name__ == "__main__":
    asyncio.run(main()) 