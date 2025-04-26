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
from controllers.directional_trading.pz_ema_ribbon_trend import PZEmaRibbonTrendControllerConfig
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
        connector_name = "binance_perpetual" # TODO: get from job file

        # Don't matter
        # take_profit = 5 # trial.suggest_float("take_profit", 0.01, 0.03, step=0.01)
        # stop_loss = 5  #trial.suggest_float("stop_loss", 0.01, 0.05, step=0.01)
        # trailing_stop_activation_price = 1.0
        # trailing_stop_trailing_delta = 0.05

        # General
        total_amount_quote = 1000
        max_executors_per_side = 1
       
        # Indicator Values
        ema_1 = trial.suggest_int("ema_1", 10, 40, step = 10)
        ema_2 = trial.suggest_int("ema_2", 20, 50, step = 10)
        ema_3 = trial.suggest_int("ema_3", 30, 80, step = 10)
        ema_4 = trial.suggest_int("ema_4", 40, 100, step = 10)

        # Triple Barrier

        time_limit = None #trial.suggest_int("time_limit", get_time_limit_step(self.interval), get_time_limit_step(self.interval) * 10, step=get_time_limit_step(self.interval))
        cooldown_time = get_time_limit_step(self.interval)

        # TODO: Check maybe trailing stop?

        # Creating the instance of the configuration and the controller
        config = PZEmaRibbonTrendControllerConfig(
            connector_name=connector_name,
            trading_pair=self.trading_pair,
            interval=self.interval,
            total_amount_quote=Decimal(total_amount_quote),
            time_limit=time_limit,
            max_executors_per_side=max_executors_per_side,
            cooldown_time=cooldown_time,
            # natr_length = natr_length,
            ema_1=ema_1,
            ema_2=ema_2,
            ema_3=ema_3,
            ema_4=ema_4,
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
        study_name = f"pz_ema_ribbon_trend_{trading_pair}_{interval}_{start_date_day}_{end_date_day}",
        config_generator=config_generator,
        n_trials=trials,
    ))

import multiprocessing

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
        start_date = datetime.datetime.combine(start_date_str, datetime.datetime.min.time())
    else:
        start_date = datetime.datetime.strptime(start_date_str, "%Y-%m-%d")

    if isinstance(end_date_str, datetime.date):
        end_date = datetime.datetime.combine(end_date_str, datetime.datetime.min.time())
    else:
        end_date = datetime.datetime.strptime(end_date_str, "%Y-%m-%d")

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

    total_trials = 200
    num_processes = multiprocessing.cpu_count() - 2
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

