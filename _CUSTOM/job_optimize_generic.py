import os
import sys
import yaml
import argparse
import asyncio
import multiprocessing
import datetime
from decimal import Decimal, getcontext
from typing import Optional, Dict
# Force set correct PATH and CONDA env manually inside all multiprocessing workers
os.environ["PATH"] = "/opt/miniconda/envs/quants-lab/bin:" + os.environ["PATH"]
os.environ["CONDA_DEFAULT_ENV"] = "quants-lab"
os.environ["CONDA_PREFIX"] = "/opt/miniconda/envs/quants-lab"
# Set path
root_path = os.path.abspath(os.path.join(os.getcwd(), '../'))
sys.path.append(root_path)

# Local imports AFTER sys.path adjustment
from core.backtesting.optimizer import BacktestingConfig, BaseStrategyConfigGenerator, StrategyOptimizer
from controllers.directional_trading.pz_scalper import PZScalperControllerConfig
from controllers.directional_trading.pz_ema_ribbon_trend import PZEmaRibbonTrendControllerConfig

getcontext().prec = 4

# Global constants
taker_fee = Decimal(0.0006)
trade_cost: Decimal = 3 * taker_fee

# Controller Mapping
CONTROLLER_MAPPING = {
    "pz_scalper": {
        "config_class": PZScalperControllerConfig,
        "generator_class": None  # If needed in future
    },
    "pz_ema_ribbon_trend": {
        "config_class": PZEmaRibbonTrendControllerConfig,
        "generator_class": None  # Overridden below
    }
}

def get_time_limit_step(interval_str: str) -> int:
    minutes = int(interval_str.rstrip('m'))
    return minutes * 60

class PZEmaRibbonTrendConfigGenerator(BaseStrategyConfigGenerator):
    """
    Config generator for PZ EMA Ribbon Trend optimization.
    """
    def __init__(self, start_date: datetime.datetime, end_date: datetime.datetime, trading_pair: str, interval: str, config: Optional[Dict] = None):
        self.start = int(start_date.timestamp())
        self.end = int(end_date.timestamp())
        self.interval = interval
        self.trading_pair = trading_pair
        self.config = config or {}

    async def generate_config(self, trial) -> BacktestingConfig:
        total_amount_quote = Decimal(1000)
        cooldown_time = get_time_limit_step(self.interval)

        ema_1 = trial.suggest_int("ema_1", 10, 40, step=5)
        ema_2 = trial.suggest_int("ema_2", ema_1 + 5, 50, step=5)
        ema_3 = trial.suggest_int("ema_3", ema_2 + 5, 80, step=5)
        ema_4 = trial.suggest_int("ema_4", ema_3 + 5, 120, step=5)

        controller_config = PZEmaRibbonTrendControllerConfig(
            connector_name="binance_perpetual",
            trading_pair=self.trading_pair,
            interval=self.interval,
            total_amount_quote=total_amount_quote,
            cooldown_time=cooldown_time,
            ema_1=ema_1,
            ema_2=ema_2,
            ema_3=ema_3,
            ema_4=ema_4,
        )

        return BacktestingConfig(config=controller_config, start=self.start, end=self.end, trade_cost=float(trade_cost))

# Attach generator class into mapping
CONTROLLER_MAPPING["pz_ema_ribbon_trend"]["generator_class"] = PZEmaRibbonTrendConfigGenerator

def run_optimizer_worker(trials: int, start_date, end_date, trading_pair, interval, algorithm_name, db_kwargs):
    """
    Worker function to run optimizer process.
    """
    config_generator_class = CONTROLLER_MAPPING[algorithm_name]["generator_class"]

    config_generator = config_generator_class(
        start_date=start_date,
        end_date=end_date,
        trading_pair=trading_pair,
        interval=interval,
    )

    storage_name = StrategyOptimizer.get_storage_name(
        engine="postgres",
        **db_kwargs
    )

    optimizer = StrategyOptimizer(
        storage_name=storage_name,
        load_cached_data=True,
        root_path=root_path,
        resolution="1m"
    )

    start_date_str = start_date.strftime('%Y-%m-%d')
    end_date_str = end_date.strftime('%Y-%m-%d')

    asyncio.run(optimizer.optimize(
        study_name=f"{algorithm_name}_{trading_pair}_{interval}_{start_date_str}_{end_date_str}",
        config_generator=config_generator,
        n_trials=trials,
    ))

def main():
    if sys.platform == "win32":
        multiprocessing.set_start_method("spawn", force=True)
    else:
        multiprocessing.set_start_method("forkserver", force=True)

    parser = argparse.ArgumentParser(description="Generic Strategy Optimizer")
    parser.add_argument("config", help="The path to the YAML job config file")

    args = parser.parse_args()
    config_path = args.config

    # Load config
    with open(config_path, "r") as file:
        config = yaml.safe_load(file)

    # General Settings
    algorithm_name = config["algorithm"]
    trading_pairs = config["trading_pairs"]
    candle_intervals = config["candle_intervals"]
    number_trials = config["number_trials"]

    db_kwargs = {
        "db_host": config["db"]["host"],
        "db_port": config["db"]["port"],
        "db_user": config["db"]["user"],
        "db_pass": config["db"]["password"],
        "database_name": config["db"]["database"],
    }

    # Timeframe
    start_raw = config["timeframe"]["start"]
    end_raw = config["timeframe"]["end"]

    if isinstance(start_raw, datetime.date) and not isinstance(start_raw, datetime.datetime):
        start_date = datetime.datetime.combine(start_raw, datetime.time.min)
    else:
        start_date = datetime.datetime.strptime(start_raw, "%Y-%m-%d")

    if isinstance(end_raw, datetime.date) and not isinstance(end_raw, datetime.datetime):
        end_date = datetime.datetime.combine(end_raw, datetime.time.min)
    else:
        end_date = datetime.datetime.strptime(end_raw, "%Y-%m-%d")

    num_processes = multiprocessing.cpu_count()
    trials_per_proc = number_trials // num_processes

    for trading_pair in trading_pairs:
        for interval in candle_intervals:
            print(f"Starting optimization for {trading_pair} @ {interval} ({algorithm_name})")

            tasks = [
                (trials_per_proc, start_date, end_date, trading_pair, interval, algorithm_name, db_kwargs)
                for _ in range(num_processes)
            ]

            with multiprocessing.Pool(processes=num_processes) as pool:
                pool.starmap(run_optimizer_worker, tasks)

            print(f"✅ Finished optimization for {trading_pair} @ {interval}\n")

if __name__ == "__main__":
    main()
