import os
import sys
from typing import Optional,  Dict
root_path = os.path.abspath(os.path.join(os.getcwd(), '../'))
sys.path.append(root_path)
import yaml
import argparse


from core.backtesting.optimizer import BacktestingConfig, BaseStrategyConfigGenerator
from decimal import Decimal, getcontext
import datetime
from controllers.directional_trading.pz_scalper import PZScalperControllerConfig
getcontext().prec = 4  # set desired precision

# maker_fee = Decimal(0.0002)
taker_fee = Decimal(0.0006)
# Worst case, MKT entry and Stop via MKT order + slippage
trade_cost: Decimal = 3*taker_fee

def get_time_limit_step(input):
    minutes = int(input.split("m")[0])
    return minutes * 60
    
class PZMMConfigGenerator(BaseStrategyConfigGenerator):
    trading_pair: str = None
    interval: str = None

    def __init__(self, start_date: datetime.datetime, end_date: datetime.datetime, trading_pair: str, interval: str,  config: Optional[Dict] = None):
        """
        Initialize with common parameters for backtesting.

        Args:
            start_date (datetime.datetime): The start date of the backtesting period.
            end_date (datetime.datetime): The end date of the backtesting period.
        """
        self.start = int(start_date.timestamp())
        self.end = int(end_date.timestamp())
        self.interval = interval
        self.trading_pair = trading_pair
        if config:
            self.config = config
        else:
            self.config = {}



    """
    Strategy configuration generator for PZ MM optimization.
    """
    async def generate_config(self, trial) -> BacktestingConfig:

        # Controller configuration
        connector_name = "binance_perpetual"

        # Don't matter
        # take_profit = 5 # trial.suggest_float("take_profit", 0.01, 0.03, step=0.01)
        # stop_loss = 5  #trial.suggest_float("stop_loss", 0.01, 0.05, step=0.01)
        # trailing_stop_activation_price = 1.0
        # trailing_stop_trailing_delta = 0.05

        # General
        total_amount_quote = 1000
        max_executors_per_side = 1
       
        # Indicator Values
        ema_fast = trial.suggest_int("ema_fast", 20, 70, step = 10)
        ema_slow = trial.suggest_int("ema_slow", 50, 120, step = 10)
        srsi_smoothing: int = trial.suggest_int("srsi_smoothing", 3, 6, step = 1)
        srsi_length: int = trial.suggest_int("srsi_length", 6, 15, step = 3)
        rsi_ma_length: int  = trial.suggest_int("rsi_ma_length", 6, 15, step = 3)
        hma_diff_ma_length: int = trial.suggest_int("hma_diff_ma_length", 6, 20, step = 2)
        hma_slow = trial.suggest_int("hma_slow", 20, 50, step = 5)
        hma_fast = trial.suggest_int("hma_fast", 10, 30, step = 5)
        natr_length = trial.suggest_int("natr_length", 7, 21, step = 2)

        # Triple Barrier

        time_limit = trial.suggest_int("time_limit", get_time_limit_step(self.interval), get_time_limit_step(self.interval) * 10, step=get_time_limit_step(self.interval))
        cooldown_time = get_time_limit_step(self.interval)

        tp_natr_factor = trial.suggest_float("tp_natr_factor", 0.25, 3, step=0.25)
        sl_natr_factor = trial.suggest_float("sl_natr_factor", 0.5, 3, step=0.5)
        # ts_activation_natr_factor = trial.suggest_float("ts_activation_natr_factor", 0.25, 1, step=0.25)
        # ts_delta_natr_factor = trial.suggest_float("ts_delta_natr_factor", 0.25, 1, step=0.25)


        # Creating the instance of the configuration and the controller
        config = PZScalperControllerConfig(
            connector_name=connector_name,
            trading_pair=self.trading_pair,
            interval=self.interval,
            total_amount_quote=Decimal(total_amount_quote),
            time_limit=time_limit,
            max_executors_per_side=max_executors_per_side,
            cooldown_time=cooldown_time,
            natr_length = natr_length,
            sl_natr_factor=sl_natr_factor,
            ema_fast=ema_fast,
            ema_slow=ema_slow,
            rsi_ma_length=rsi_ma_length,
            srsi_length=srsi_length,
            srsi_smoothing=srsi_smoothing,
            hma_diff_ma_length=hma_diff_ma_length,
            tp_natr_factor=tp_natr_factor,
            hma_fast=hma_fast,
            hma_slow=hma_slow,
        )

        # Return the configuration encapsulated in BacktestingConfig
        return BacktestingConfig(config=config, start=self.start, end=self.end, trade_cost =float(trade_cost))

def run_optimizer_worker(trials: int, start_date, end_date, trading_pair, interval, kwargs):
    import asyncio
    from core.backtesting.optimizer import StrategyOptimizer
    # from your_config_module import PZMMConfigGenerator  # adjust import

    # root_path = os.path.abspath(os.path.join(os.getcwd(), '../'))
    config_generator = PZMMConfigGenerator(
        start_date=start_date, 
        end_date=end_date,
        trading_pair=trading_pair,
        interval=interval
        )

    storage_name = StrategyOptimizer.get_storage_name(
            engine="postgres",
            **kwargs)
    optimizer = StrategyOptimizer(
        storage_name=storage_name,
        load_cached_data=True,
        root_path=root_path,
        resolution="1m")

    start_date_day = start_date.strftime('%Y-%m-%d')
    end_date_day = end_date.strftime('%Y-%m-%d')
    asyncio.run(optimizer.optimize(
        study_name = f"pz_scalper_{trading_pair}_{interval}_{start_date_day}_{end_date_day}",
        config_generator=config_generator,
        n_trials=trials,
    ))

import multiprocessing
import datetime

if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="A optimizer script")
    parser.add_argument("config", help="The file path to the config file")

    args = parser.parse_args()
    config_path = args.config

    # Load YAML file
    with open(config_path, "r") as file:
        config = yaml.safe_load(file)

    # Extract trading pair (only the uncommented one)
    trading_pairs = config['trading_pairs']

    # Extract and convert dates
    start_date_str = config['timeframe']['start']
    end_date_str = config['timeframe']['end']

    # Convert to datetime if they are date objects
    if isinstance(start_date_str, datetime.date):
        start_date = datetime.combine(start_date_str, datetime.min.time())
    else:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d")

    if isinstance(end_date_str, datetime.date):
        end_date = datetime.combine(end_date_str, datetime.min.time())
    else:
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d")

    # Extract candle interval
    candle_intervals = config['candle_intervals']

    # Extract DB configuration
    db_config = config['db']
    db_host = db_config['host']
    db_port = db_config['port']
    db_user = db_config['user']
    db_password = db_config['password']
    db_name = db_config['database']

    kwargs = {
        "db_host": db_host,
        "db_port": db_port,
        "db_user": db_user,
        "db_pass": db_password,
        "database_name": db_name,
    }
    # trading_pairs = [
    #     # "BTC-USDT", 
    #     "WLD-USDT", 
    #     # "ETH-USDT", 
    #     "XRP-USDT",
    #     #  "BNB-USDT", 
    #     "SOL-USDT"]
    # intervals = [
    #     # "5m", 
    #     "15m",
    #       "30m"
    #       ]
    # start_date = datetime.datetime(2025, 1, 1)
    # end_date = datetime.datetime(2025, 3, 30)
    # start_date = datetime.datetime(2024, 1, 1)
    # end_date = datetime.datetime(2025, 1, 1)

    total_trials = 100
    num_processes = 10 # multiprocessing.cpu_count()
    trials_per_proc = total_trials // num_processes


    for trading_pair in trading_pairs:
        for interval in candle_intervals:
            print(f"Starting optimization for {trading_pair} @ {interval}")
            
            # Prepare a task for each process, which collectively run all trials in parallel
            tasks = [
                (trials_per_proc, start_date, end_date, trading_pair, interval, kwargs)
                for _ in range(num_processes)
            ]

            # Create a pool for the current pair/interval combination
            with multiprocessing.Pool(processes=num_processes) as pool:
                # pool.starmap blocks until all processes have finished their tasks
                pool.starmap(run_optimizer_worker, tasks)

            print(f"Finished optimization for {trading_pair} @ {interval}\n")

