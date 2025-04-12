import os
import sys

root_path = os.path.abspath(os.path.join(os.getcwd(), '../'))
sys.path.append(root_path)


from hummingbot.strategy_v2.utils.distributions import Distributions
from controllers.market_making.pz_mm import PZMMControllerConfig
from core.backtesting.optimizer import BacktestingConfig, BaseStrategyConfigGenerator
from hummingbot.strategy_v2.executors.position_executor.data_types import TrailingStop
from decimal import Decimal
import datetime
from typing import List

backtest_resolution = "1m"
interval = "5m"
start_date = datetime.datetime(2025, 3, 25)
end_date = datetime.datetime(2025, 3, 26)


class PZMMConfigGenerator(BaseStrategyConfigGenerator):
    """
    Strategy configuration generator for PZ MM optimization.
    """
    async def generate_config(self, trial) -> BacktestingConfig:

        # Those doesn't matter, they are dyncamically calculated inside the controller anyway
        take_profit = 5 # trial.suggest_float("take_profit", 0.01, 0.03, step=0.01)
        stop_loss = 5  #trial.suggest_float("stop_loss", 0.01, 0.05, step=0.01)
        # TODO: the trailing stuff, also with a factor, instead of a fixed value!
        # TODO: "start spread" also as part of NATR?

        # Controller configuration
        connector_name = "binance_perpetual"
        trading_pair = "WLD-USDT"
        total_amount_quote = 1000
 
        # levels = trial.suggest_int("levels", 2, 4)
        # start_spread = trial.suggest_float("start_spread", 0.25, 2, step=0.25)
        # step_spread = trial.suggest_float("step_spread", 0.1, 0.5, step=0.1)
        # spreads = Distributions.arithmetic(levels, start_spread, step_spread)

        # levels = trial.suggest_int("levels", 3, 5)
        # start_spread = 0.002 # trial.suggest_float("start_spread", 0.002, 0.005, step=0.001)
        # step_spread = 0.002 # trial.suggest_float("step_spread", 0.001, 0.002, step=0.001)
        # spreads = Distributions.arithmetic(levels, start_spread, step_spread)
        spreads = Distributions.arithmetic(2, 1, 0.5)
        buy_amounts_pct: List[Decimal] = [0.01, 0.02]
        sell_amounts_pct: List[Decimal] = [0.01, 0.02]

        # trailing_stop_activation_price = trial.suggest_float("trailing_stop_activation_price", 0.015, 0.02, step=0.01)
        # trailing_delta_ratio = trial.suggest_float("trailing_delta_ratio", 0.05, 0.1, step=0.01)
        # trailing_stop_trailing_delta = trailing_stop_activation_price * trailing_delta_ratio
        time_limit = trial.suggest_int("time_limit", 60*5, 60 * 30, step=60*5)
        executor_refresh_time = trial.suggest_int("executor_refresh_time", 60, 300, step=60)
        cooldown_time = 1 ##trial.suggest_int("cooldown_time", 60, 60 * 5, step=60)
        
        tp_natr_factor = trial.suggest_float("tp_natr_factor", 0.25, 1, step=0.25)
        sl_natr_factor = trial.suggest_float("sl_natr_factor", 0.5, 3, step=0.5)
        # hma_very_slow = trial.suggest_int("hma_very_slow", 30, 50, step = 5)
        hma_slow = trial.suggest_int("hma_slow", 15, 30, step = 5)
        hma_fast = trial.suggest_int("hma_fast", 5,15, step = 5)
        hma_diff_ma = trial.suggest_int("hma_diff_ma", 6,16, step = 2)
        # rsi_length = trial.suggest_int("rsi_length", 5, 13, step = 2)
        stoch_rsi_smoothing = trial.suggest_int("stoch_rsi_smoothing", 2, 6, step = 1)
        stoch_rsi_length = trial.suggest_int("stoch_rsi_length", 5, 13, step = 2)
        natr_length = trial.suggest_int("natr_length", 7, 21, step = 2)




        # Creating the instance of the configuration and the controller
        config = PZMMControllerConfig(
            connector_name=connector_name,
            trading_pair=trading_pair,
            interval=interval,
            sell_spreads=spreads,
            buy_spreads=spreads,
            buy_amounts_pct=buy_amounts_pct,
            sell_amounts_pct=sell_amounts_pct,
            total_amount_quote=Decimal(total_amount_quote),
            take_profit=Decimal(take_profit),
            stop_loss=Decimal(stop_loss),
            # trailing_stop=TrailingStop(activation_price=Decimal(trailing_stop_activation_price), trailing_delta=Decimal(trailing_stop_trailing_delta)),
            time_limit=time_limit,
            cooldown_time=cooldown_time,
            executor_refresh_time=executor_refresh_time,
            # hma_very_slow = hma_very_slow,
            hma_slow = hma_slow,
            hma_fast = hma_fast,
            hma_diff_ma=hma_diff_ma,
            # rsi_length = rsi_length,
            stoch_rsi_smoothing = stoch_rsi_smoothing,
            stoch_rsi_length =stoch_rsi_length,
            natr_length = natr_length,
            sl_natr_factor=sl_natr_factor,
            tp_natr_factor=tp_natr_factor,
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
        study_name="pz_mm",
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
    num_processes = 15 #multiprocessing.cpu_count()
    trials_per_proc = total_trials // num_processes

    # start_date = datetime.datetime(2025, 3, 30)
    # end_date = datetime.datetime(2025, 3, 31)

    processes = []
    for _ in range(num_processes):
        p = multiprocessing.Process(target=run_optimizer_worker,
                                    args=(trials_per_proc, start_date, end_date, kwargs))
        p.start()
        processes.append(p)

    for p in processes:
        p.join()
