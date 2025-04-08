import os
import sys

root_path = os.path.abspath(os.path.join(os.getcwd(), '../'))
sys.path.append(root_path)


from core.backtesting.optimizer import BacktestingConfig, BaseStrategyConfigGenerator
from hummingbot.strategy_v2.executors.position_executor.data_types import TrailingStop
from decimal import Decimal
import datetime
from controllers.directional_trading.pz_scalper import PZScalperControllerConfig


backtest_resolution = "1m"
interval = "5m"
start_date = datetime.datetime(2025, 3, 20)
end_date = datetime.datetime(2025, 3, 30)


class PZMMConfigGenerator(BaseStrategyConfigGenerator):
    """
    Strategy configuration generator for PZ MM optimization.
    """
    async def generate_config(self, trial) -> BacktestingConfig:

        # Controller configuration
        connector_name = "binance_perpetual"
        trading_pair = "WLD-USDT"

        # Don't matter
        take_profit = 5 # trial.suggest_float("take_profit", 0.01, 0.03, step=0.01)
        stop_loss = 5  #trial.suggest_float("stop_loss", 0.01, 0.05, step=0.01)
        trailing_stop_activation_price = 1.0
        trailing_stop_trailing_delta = 0.05
        cooldown_time = 1 #trial.suggest_int("cooldown_time", 60, 60 * 5, step=60)

        # General
        total_amount_quote = 1000
        max_executors_per_side = 2
       
        # Indicator Values
        hma_slow = trial.suggest_int("hma_slow", 20, 50, step = 5)
        hma_fast = trial.suggest_int("hma_fast", 10, 30, step = 5)
        natr_length = trial.suggest_int("natr_length", 7, 21, step = 2)

        # Triple Barrier

        time_limit = trial.suggest_int("time_limit", 300, 300 * 5, step=300)
        tp_natr_factor = trial.suggest_float("tp_natr_factor", 0.25, 3, step=0.25)
        sl_natr_factor = trial.suggest_float("sl_natr_factor", 0.5, 3, step=0.5)
        ts_activation_natr_factor = trial.suggest_float("ts_activation_natr_factor", 0.25, 1, step=0.25)
        ts_delta_natr_factor = trial.suggest_float("ts_delta_natr_factor", 0.25, 1, step=0.25)


        # Creating the instance of the configuration and the controller
        config = PZScalperControllerConfig(
            connector_name=connector_name,
            trading_pair=trading_pair,
            interval=interval,
            take_profit=Decimal(take_profit),
            stop_loss=Decimal(stop_loss),
            trailing_stop=TrailingStop(activation_price=Decimal(trailing_stop_activation_price), trailing_delta=Decimal(trailing_stop_trailing_delta)),
            total_amount_quote=Decimal(total_amount_quote),
            time_limit=time_limit,
            max_executors_per_side=max_executors_per_side,
            cooldown_time=cooldown_time,
            natr_length = natr_length,
            sl_natr_factor=sl_natr_factor,
            ts_activation_natr_factor = ts_activation_natr_factor,
            ts_delta_natr_factor = ts_delta_natr_factor,
            tp_natr_factor=tp_natr_factor,
            hma_fast=hma_fast,
            hma_slow=hma_slow,
        )

        # Return the configuration encapsulated in BacktestingConfig
        return BacktestingConfig(config=config, start=self.start, end=self.end)

def run_optimizer_worker(trials: int, start_date, end_date, kwargs):
    import asyncio
    from core.backtesting.optimizer import StrategyOptimizer
    # from your_config_module import PZMMConfigGenerator  # adjust import

    # root_path = os.path.abspath(os.path.join(os.getcwd(), '../'))
    config_generator = PZMMConfigGenerator(start_date=start_date, end_date=end_date)

    storage_name = StrategyOptimizer.get_storage_name(
            engine="postgres",
            **kwargs)
    optimizer = StrategyOptimizer(
        storage_name=storage_name,
        load_cached_data=True,
        root_path=root_path,
        resolution=backtest_resolution)

    asyncio.run(optimizer.optimize(
        study_name="pz_scalper",
        config_generator=config_generator,
        n_trials=trials,
    ))

import multiprocessing
import datetime

if __name__ == "__main__":

    kwargs = {
        "db_host": os.getenv("OPTUNA_HOST", "localhost"),
        "db_port":os.getenv("OPTUNA_PORT", 5432),
        "db_user": os.getenv("OPTUNA_USER", "admin"),
        "db_pass": os.getenv("OPTUNA_PASSWORD", "admin"),
        "database_name": os.getenv("OPTUNA_DB", "optimization_database")
    }


    total_trials = 100
    num_processes = multiprocessing.cpu_count()
    trials_per_proc = total_trials // num_processes

    processes = []
    for _ in range(num_processes):
        p = multiprocessing.Process(target=run_optimizer_worker,
                                    args=(trials_per_proc, start_date, end_date, kwargs))
        p.start()
        processes.append(p)

    for p in processes:
        p.join()

