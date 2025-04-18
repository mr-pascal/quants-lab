
import os
import sys

## Set Path
root_path = os.path.abspath(os.path.join(os.getcwd(), '../'))
sys.path.append(root_path)
###
import asyncio

import psycopg2
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import DBSCAN
# import matplotlib.pyplot as plt
import seaborn as sns
import json
import multiprocessing
from typing import Optional,  Dict
from core.backtesting.optimizer import BacktestingConfig, BaseStrategyConfigGenerator
from decimal import Decimal
import datetime
from controllers.directional_trading.pz_scalper import PZScalperControllerConfig

"""
TODO: reduce parameters to max 6
"""

### GLOBALS
# maker_fee = Decimal(0.0002)
taker_fee = Decimal(0.0006)
# Worst case, MKT entry and Stop via MKT order + slippage
trade_cost: Decimal = 3*taker_fee
####

DB_CONFIG = {
    'dbname': 'optimization_database',
    'user': 'admin',
    'password': 'admin',
    'host': 'localhost',
    'port': 5432,
}


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
        connector_name = "binance_perpetual" # FIXME: make into global!

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



# def run_optimizer_worker(trials: int, start_date:datetime.datetime, end_date:datetime.datetime, trading_pair:str, interval:str) -> int:
#     import asyncio
#     from core.backtesting.optimizer import StrategyOptimizer
#     config_generator = PZMMConfigGenerator(
#         start_date=start_date, 
#         end_date=end_date,
#         trading_pair=trading_pair,
#         interval=interval
#         )

#     storage_name = StrategyOptimizer.get_storage_name(
#             engine="postgres",
#             **DB_CONFIG)
#     optimizer = StrategyOptimizer(
#         storage_name=storage_name,
#         load_cached_data=True,
#         root_path=root_path,
#         resolution="1m")

#     start_date_day = start_date.strftime('%Y-%m-%d')
#     end_date_day = end_date.strftime('%Y-%m-%d')
#     study = asyncio.run(optimizer.optimize(
#         study_name = f"pz_scalper_{trading_pair}_{interval}_{start_date_day}_{end_date_day}",
#         config_generator=config_generator,
#         n_trials=trials,
#     ))
#     return study._study_id

# def create_optimizations(trading_pair: str, interval: str, start_date: datetime.datetime, end_date: datetime.datetime, num_trials: int, num_processes: int) -> int:
#     """
#     Run optuna optimizations and save to database

#     Args:
#         trading_pair (str): The trading pair to test, e.g. "SOL-USDT"
#         interval (str): The interval to test on, e.g. "5m", "15m", "30m"
#         start_date (datetime.datetime): The start date of the backtesting period.
#         end_date (datetime.datetime): The end date of the backtesting period.
#         num_trials (int): The number of trials to run
#         num_processes (int): The number of processes to start on the system
#     Returns:
#         int: The ID of the study

#     """
   
#     trials_per_proc = num_trials // num_processes

#     print(f"Starting optimization for {trading_pair} @ {interval}")
    
#     # Prepare a task for each process, which collectively run all trials in parallel
#     tasks = [
#         (trials_per_proc, start_date, end_date, trading_pair, interval)
#         for _ in range(num_processes)
#     ]

#     study_id = None
#     # Create a pool for the current pair/interval combination
#     with multiprocessing.Pool(processes=num_processes) as pool:
#         # pool.starmap blocks until all processes have finished their tasks
#         my_list = pool.starmap(run_optimizer_worker, tasks)
#         study_id = my_list[0]

#     print(f"Finished optimization for {trading_pair} @ {interval}\n")
#     return study_id

def fetch_trials(study_id: int):
    """
    Fetch trials for study ID from Database

    Args:
        study_id: The ID of the study of which to fetch its trials
    Returns:
        list of objects with parameters and backtest results FIXME add type to function declaration
    """

    # Connect to the database
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    query = f"""
    SELECT
    t.trial_id,
    tv.value,
    tua.key,
    tua.value_json
    FROM trials t
    JOIN trial_values tv ON t.trial_id = tv.trial_id
    JOIN trial_user_attributes tua ON t.trial_id = tua.trial_id
    WHERE t.study_id = {study_id}
    AND tua.key IN ('config', 'total_positions', 'accuracy_long', 'accuracy_short', 'max_drawdown_pct', 'net_pnl')
    AND tv.value > -2
    ORDER BY value DESC
    """
    cur.execute(query)

    # FIXME: create extra method for this
    parameters_list = []

    # FIXME: make the fields dynamic, based on the strategy!
    fields_to_extract = ["ema_fast","ema_slow", "srsi_smoothing", "srsi_length",  "rsi_ma_length", "hma_diff_ma_length","hma_slow", "hma_fast", "natr_length","time_limit", "tp_natr_factor", "sl_natr_factor" ]
    # Process each row and merge rows by trial_id
    parameters_by_trial = {}

    for trial_id, value, attr_key, raw_value_json in cur.fetchall():
        if trial_id not in parameters_by_trial:
            parameters_by_trial[trial_id] = {"trial_id": trial_id}
        entry = parameters_by_trial[trial_id]
        try:
            if attr_key == "config":
                # The config field contains the JSON with the parameters to extract (double-encoded)
                parsed_json = json.loads(json.loads(raw_value_json))
                for field in fields_to_extract:
                    entry[field] = parsed_json.get(field)
                entry["sharpe"] = value
            elif attr_key == "total_positions":
                entry["total_positions"] = json.loads(raw_value_json)
            elif attr_key == "accuracy_long":
                entry["accuracy_long"] = json.loads(raw_value_json)
            elif attr_key == "accuracy_short":
                entry["accuracy_short"] = json.loads(raw_value_json)
            elif attr_key == "max_drawdown_pct":
                entry["max_drawdown_percentage"] = json.loads(raw_value_json)
            elif attr_key == "net_pnl":
                entry["pnl_percentage"] = json.loads(raw_value_json)
        except Exception as e:
            print(f"[!] Failed to process trial {trial_id}, attribute {attr_key}: {e}")

    # Convert merged dictionary to a list of parameter dicts
    parameters_list = list(parameters_by_trial.values())
    # FIXME: don#t define this inside another method
    def deduplicate_with_float_tolerance(parameters_list, precision=5):
        def normalize_value(val):
            if isinstance(val, float):
                return round(val, precision)
            return val

        dedup_keys = {
            tuple(sorted((k, normalize_value(v)) for k, v in d.items() if k != "trial_id")): d
            for d in parameters_list
        }

        return list(dedup_keys.values())

    # Usage
    unique_params = deduplicate_with_float_tolerance(parameters_list)
    return unique_params

def cluster_data(trials_df):
    """
    Use DBSCAN clustering to get an optimal configuration

    Args:
        TODO
    Returns:
        A optimal configuration 
    
    """
    df = trials_df
    # Select only numeric hyperparameters (adjust if your strategy changes)
    # FIXME: depends on the strategy!
    param_cols = [
        'ema_fast', 'ema_slow', 'srsi_smoothing', 'srsi_length',
        'rsi_ma_length', 'hma_diff_ma_length', 'hma_slow', 'hma_fast',
        'natr_length', 'time_limit', 'tp_natr_factor', 'sl_natr_factor'
    ]
    # Drop rows with missing values in parameter columns
    X = df[param_cols].dropna()

    # Standardize parameter values
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # Apply DBSCAN clustering
    db = DBSCAN(eps=1.5, min_samples=3)
    labels = db.fit_predict(X_scaled)

    # Assign cluster labels back to original DataFrame
    df['cluster'] = -1  # default to outlier
    df.loc[X.index, 'cluster'] = labels

    # Print cluster sizes
    print("Cluster Sizes:")
    print(df['cluster'].value_counts().sort_index())

    # Analyze performance per cluster
    cluster_summary = df.groupby('cluster').agg({
        'sharpe': ['mean', 'std'],
        'pnl_percentage': 'mean',
        'max_drawdown_percentage': 'mean',
        'total_positions': 'mean',
        'cluster': 'count'
    }).rename(columns={'cluster': 'count'})

    print("\nCluster Performance Summary:")
    print(cluster_summary)

    # Find best cluster based on mean Sharpe ratio
    valid_clusters = cluster_summary[cluster_summary.index != -1]
    best_cluster = valid_clusters['sharpe']['mean'].idxmax()
    print(f"\n✅ Best cluster by Sharpe ratio: {best_cluster}")

    # Extract median configuration from best cluster
    param_median = df[df['cluster'] == best_cluster][param_cols].median()
    print("\n📌 Median hyperparameters from best cluster:")
    print(param_median)
    return param_median


def generate_controller_config(df):
    # FIXME types, arguments, parameters, return values
    """
    Generates a controller configuration based on inputted config data

    Args:
        df: 
        ema_fast               50
        ema_slow              110
        srsi_smoothing          4
        srsi_length             9
        rsi_ma_length          15
        hma_diff_ma_length     18
        hma_slow               30
        hma_fast               15
        natr_length            19
        time_limit           9000
        tp_natr_factor       0.25
        sl_natr_factor        2.5
        dtype: float64
    """




    # FIXME: Just as an idea, to make this configurable based on some inital configuraiton,a lso regarding the fields?
    # MY_VAR_1 = "pz_scalper"
    # MY_VAR_2 = "PZConfigController"

    # # This is the string of the full module path (like a dotted import)
    # module_path = f"controllers.directional_trading.{MY_VAR_1}"
    # import importlib

    # # Import the module
    # module = importlib.import_module(module_path)

    # # Get the class from the module
    # my_class = getattr(module, MY_VAR_2)

    # # Now you can use it like a normal class
    # instance = my_class()

    # try:
    #     module = importlib.import_module(module_path)
    #     my_class = getattr(module, MY_VAR_2)
    # except (ImportError, AttributeError) as e:
    #     print(f"Failed to import: {e}")
    from controllers.directional_trading.pz_scalper import PZScalperControllerConfig
    # FIXME: take values from "config" parameter

    # Controller configuration
    # FIXME: get controller_name, trading_pair and interval as input!
    connector_name = "binance_perpetual"
    trading_pair = "XRP-USDT"
    interval = "30m"

    # Don't matter
    cooldown_time = get_time_limit_step(interval) #60 * 15
    take_profit = 5 # 100%, -> Disable Take profit, let the trailing do it's job
    stop_loss = 5

    # General
    total_amount_quote: int = 1000
    max_executors_per_side: int = 1 # TODO: get this also from "df"


    # Indicator Values
    ema_fast: int = df["ema_fast"]
    ema_slow: int = df["ema_slow"]
    srsi_smoothing: int = df["srsi_smoothing"]
    srsi_length: int = df["srsi_length"]
    rsi_ma_length: int  = df["rsi_ma_length"]
    hma_diff_ma_length: int = df["hma_diff_ma_length"]
    hma_fast: int = df["hma_fast"]
    hma_slow: int = df["hma_slow"]
    natr_length: int = df["natr_length"]

    # Triple Barrier
    time_limit: int = df["time_limit"]
    tp_natr_factor = df["tp_natr_factor"]
    sl_natr_factor = df["sl_natr_factor"]
    ###


    # Creating the instance of the configuration and the controller
    return PZScalperControllerConfig(
        connector_name=connector_name,
        leverage=20,
        trading_pair=trading_pair,
        interval=interval,
        take_profit=Decimal(take_profit),
        stop_loss=Decimal(stop_loss),
        total_amount_quote=Decimal(total_amount_quote),
        time_limit=time_limit,
        max_executors_per_side=max_executors_per_side,
        cooldown_time=cooldown_time,
        natr_length = natr_length,
        sl_natr_factor=sl_natr_factor,
        tp_natr_factor=tp_natr_factor,
        ema_fast=ema_fast,
        ema_slow=ema_slow,
        rsi_ma_length=rsi_ma_length,
        srsi_length=srsi_length,
        srsi_smoothing=srsi_smoothing,
        hma_diff_ma_length=hma_diff_ma_length,
        hma_fast=hma_fast,
        hma_slow=hma_slow
    )

from hummingbot.strategy_v2.controllers.directional_trading_controller_base import (
    DirectionalTradingControllerConfigBase,
)
from core.data_structures.backtesting_result import (BacktestingResult)

async def test_optimal_controller_configuration(
        # TODO: Replace with general "ControllerCOnfigbase" instead of "direcitonal"
        config: DirectionalTradingControllerConfigBase,
        train_start_date: datetime.datetime,
        train_end_date: datetime.datetime,
        test_start_date: datetime.datetime,
        test_end_date: datetime.datetime,
        whole_start_date: datetime.datetime,
        whole_end_date: datetime.datetime
        ) -> BacktestingResult:
    """
        Tests the optimal configuration for
            - the whole dataset
            - the train dataset
            - the test dataset
        and evaluates the performance on each to see if it's viable to use in production

        Args:
            config (DirectionalTradingControllerConfigBase): The Controller configuration to backtest
            train_start_date (datetime.datetime): The start date of the backtesting period for the TRAIN period
            train_end_date (datetime.datetime): The end date of the backtesting period for the TRAIN period
            test_start_date (datetime.datetime): The start date of the backtesting period for the TEST period
            test_end_date (datetime.datetime): The end date of the backtesting period for the TEST period
            whole_start_date (datetime.datetime): The start date of the backtesting period for the WHOLE period
            whole_end_date (datetime.datetime): The end date of the backtesting period for the WHOLE period

        Returns:
            BacktestingResult - The result of the backtest (#FIXME: TYPINGS, object of backtesting result, also in function signature)
    """
    # FIXME: also backtest the whole dataset, the train dataset and the test dataset
    from core.backtesting import BacktestingEngine

    backtesting = BacktestingEngine(root_path=root_path, load_cached_data=True)
    print("Start backtesting for WHOLE dataset...")
    whole_backtesting_result = await backtesting.run_backtesting(config, int(whole_start_date.timestamp()), int(whole_end_date.timestamp()), "1m", trade_cost=float(trade_cost))
    print("Start backtesting for TRAIN dataset...")
    train_backtesting_result = await backtesting.run_backtesting(config, int(train_start_date.timestamp()), int(train_end_date.timestamp()), "1m", trade_cost=float(trade_cost))
    print("Start backtesting for TEST dataset...")
    test_backtesting_result = await backtesting.run_backtesting(config, int(test_start_date.timestamp()), int(test_end_date.timestamp()), "1m", trade_cost=float(trade_cost))
    
    
    return {
        "whole": whole_backtesting_result,
        "train": train_backtesting_result,
        "test": test_backtesting_result
    }

async def main():
    """
    
    """
    # FIXME: consider to remove the optimization part from this file, since this is a long runnning background task
    # and only keep the "evaluation" and finding a good configuration here.


    train_start_date = datetime.datetime(2024,1,1)
    train_end_date= datetime.datetime(2025,1,1)

    test_start_date= datetime.datetime(2025,1,1)
    test_end_date= datetime.datetime(2025,3,30)

    whole_start_date= train_start_date
    whole_end_date= test_end_date

    # num_trials = 100
    # num_processors = 8 #multiprocessing.cpu_count()

    # study_id = create_optimizations("XRP-USDT", "15m", train_start_date, train_end_date, num_trials, num_processors)

  
    study_id = 1025
    # FIXME: create check for study_id != NONE
    trials = fetch_trials(study_id)

    # Only trades over 100 occurences per year sound reasonable in terms of
    # statistically significant
    trials = [t for t in trials if t["total_positions"] > 100] # TODO: could be part of the SQL Query

    df_trials = pd.DataFrame(trials)

    optimal_configuration = cluster_data(df_trials)


    # print(optimal_configuration)

    optimal_controller_configuration = generate_controller_config(optimal_configuration)

    results = await test_optimal_controller_configuration(
        optimal_controller_configuration,
        train_start_date = train_start_date,
        train_end_date= train_end_date,
        test_start_date= test_start_date,
        test_end_date= test_end_date,
        whole_start_date= whole_start_date,
        whole_end_date= whole_end_date
        )

    # FIXME: Evaluate programmatically!
    # Check for Sharpes, and number of trades 

    print("TRAIN:")
    print(results["train"].get_results_summary())
    print("------------------")
    print("TEST:")
    print(results["test"].get_results_summary())
    print("------------------")
    print("WHOLE:")
    print(results["whole"].get_results_summary())
    print("------------------")


if __name__ == "__main__":
    asyncio.run(main())