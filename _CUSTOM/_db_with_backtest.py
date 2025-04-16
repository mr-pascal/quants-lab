import os
import sys
import json
import psycopg2
import asyncio
import datetime
from decimal import Decimal, getcontext
from typing import List, Dict

# Extend path
root_path = os.path.abspath(os.path.join(os.getcwd(), '../'))
sys.path.append(root_path)

# --- CONFIGURABLE SECTION ---
STUDY_ID = 910
FIELDS_TO_EXTRACT = [
    "ema_fast", "ema_slow", "srsi_smoothing", "srsi_length",
    "rsi_ma_length", "hma_diff_ma_length", "hma_slow", "hma_fast",
    "natr_length", "time_limit", "tp_natr_factor", "sl_natr_factor",
    "interval", "max_executors_per_side", "trading_pair"
]

DB_CONFIG = {
    'dbname': 'optimization_database',
    'user': 'admin',
    'password': 'admin',
    'host': 'localhost',
    'port': 5432,
}
getcontext().prec = 4
# ----------------------------

from core.backtesting import BacktestingEngine
from controllers.directional_trading.pz_scalper import PZScalperControllerConfig


def get_time_limit_step(interval: str) -> int:
    """Convert '15m' -> seconds."""
    return int(interval.replace("m", "")) * 60


def deduplicate_with_float_tolerance(params: List[Dict], precision=5) -> List[Dict]:
    def normalize(val):
        return round(val, precision) if isinstance(val, float) else val

    unique = {
        tuple(sorted((k, normalize(v)) for k, v in d.items() if k != "trial_id")): d
        for d in params
    }
    return list(unique.values())


def fetch_trials() -> List[Dict]:
    """Synchronous DB call to fetch trial data."""
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    query = f"""
        SELECT t.trial_id, tv.value, tua.value_json
        FROM trials t
        JOIN trial_values tv ON t.trial_id = tv.trial_id
        JOIN trial_user_attributes tua ON t.trial_id = tua.trial_id
        WHERE t.study_id = %s
        AND tua.key = 'config'
        AND tv.value > 0
        ORDER BY tv.value DESC
    """
    cur.execute(query, (STUDY_ID,))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    parsed = []
    for trial_id, sharpe, raw_json in rows:
        try:
            config_data = json.loads(json.loads(raw_json))
            entry = {key: config_data.get(key) for key in FIELDS_TO_EXTRACT}
            entry["sharpe"] = sharpe
            entry["trial_id"] = trial_id
            parsed.append(entry)
        except Exception as e:
            print(f"[!] Failed to parse trial {trial_id}: {e}")
    return deduplicate_with_float_tolerance(parsed)

async def run_backtest(trial_data: Dict):
    """Single async backtest job."""
    backtesting = BacktestingEngine(root_path=root_path, load_cached_data=True)

    config = PZScalperControllerConfig(
        connector_name="binance_perpetual",
        leverage=20,
        trading_pair=trial_data["trading_pair"],
        interval=trial_data["interval"],
        take_profit=Decimal(5),
        stop_loss=Decimal(5),
        total_amount_quote=Decimal(1000),
        time_limit=trial_data["time_limit"],
        max_executors_per_side=trial_data["max_executors_per_side"],
        cooldown_time=get_time_limit_step(trial_data["interval"]),
        natr_length=trial_data["natr_length"],
        sl_natr_factor=trial_data["sl_natr_factor"],
        tp_natr_factor=trial_data["tp_natr_factor"],
        ema_fast=trial_data["ema_fast"],
        ema_slow=trial_data["ema_slow"],
        rsi_ma_length=trial_data["rsi_ma_length"],
        srsi_length=trial_data["srsi_length"],
        srsi_smoothing=trial_data["srsi_smoothing"],
        hma_diff_ma_length=trial_data["hma_diff_ma_length"],
        hma_fast=trial_data["hma_fast"],
        hma_slow=trial_data["hma_slow"]
    )

    start = int(datetime.datetime(2024, 3, 1).timestamp())
    end = int(datetime.datetime(2025, 3, 30).timestamp())
    trade_cost = float(Decimal(2) * Decimal(0.0006))

    result = await backtesting.run_backtesting(config, start, end, "1m", trade_cost)
    
    trial_data.update(result.results)
    # Cleanup backtesting instance
    # print(result)
    # print(result.results)
    # print(trial_data)
    return trial_data

def write_csv(trials):
    import csv
    with open("top_configs.csv", "w", newline="") as csvfile:
        fieldnames = list(trials[0].keys())
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        
        writer.writeheader()
        for row in trials:
            writer.writerow(row)


import multiprocessing

# async def main():
#     trials = fetch_trials()
#     print(f"Loaded {len(trials)} unique configurations.")

#     results = []
#     for trial in trials:
#         result = await run_backtest(trial)
#         results.append(result)
    
#     print("Backtests completed.")

#     write_csv(results)


def run_backtest_process(trial_data):
    # Create a new event loop for this process if necessary
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    result = loop.run_until_complete(run_backtest(trial_data))
    loop.close()
    return result

def main():
    trials = fetch_trials()
    results = []
    for trial in trials:
        with multiprocessing.Pool(1) as pool:
            # Execute each backtest in its own process
            result = pool.apply(run_backtest_process, (trial,))
            results.append(result)
    write_csv(results)


if __name__ == "__main__":
    asyncio.run(main())
