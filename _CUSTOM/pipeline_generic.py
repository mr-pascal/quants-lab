
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
from controllers.directional_trading.pz_ema_ribbon_trend import PZEmaRibbonTrendControllerConfig

### GLOBALS
# maker_fee = Decimal(0.0002)
taker_fee = Decimal(0.0006)
# Worst case, MKT entry and Stop via MKT order + slippage
trade_cost: Decimal = 3*taker_fee


## Study Parameters
study_id = 223
controller_name="pz_scalper"

# Times
train_start_date = datetime.datetime(2024,1,1)
train_end_date = datetime.datetime(2025,1,1)
test_start_date = train_end_date # datetime.datetime(2025,1,1)
test_end_date = datetime.datetime(2025,3,30)
whole_start_date= train_start_date
whole_end_date= test_end_date
####

DB_CONFIG = {
    'dbname': 'optimization_database',
    'user': 'admin',
    'password': 'admin',
    'host': 'localhost',
    'port': 5432,
}

COMMON_FIELDS = [ "trading_pair", "connector_name","interval", ]
CONTROLLER_CLASS_MAPPING = {
        "pz_scalper": {
            "class": PZScalperControllerConfig,
            "fields": ["ema_fast", "ema_slow", "srsi_smoothing", "srsi_length", "rsi_ma_length","hma_diff_ma_length","hma_slow", "hma_fast", "natr_length", "time_limit", "tp_natr_factor", "sl_natr_factor","cooldown_time","max_executors_per_side","leverage"]
        },
        "pz_ema_ribbon_trend": {
            "class": PZEmaRibbonTrendControllerConfig,
            "fields": ["ema_1", "ema_2", "ema_3", "ema_4"],
        },
    }


def get_time_limit_step(input):
    minutes = int(input.split("m")[0])
    return minutes * 60

def fetch_trials(study_id: int, dynamic_fields):
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
    AND tua.key IN ('config', 'interval', 'total_positions', 'accuracy_long', 'accuracy_short', 'max_drawdown_pct', 'net_pnl')
    AND tv.value > -2
    ORDER BY value DESC
    """
    cur.execute(query)

    # FIXME: create extra method for this
    parameters_list = []
    
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
                for field in dynamic_fields:
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

def cluster_data(trials_df, variable_fields):
    """
    Use DBSCAN clustering to get an optimal configuration

    Args:
        TODO
    Returns:
        A optimal configuration 
    
    """
    df = trials_df

    # Drop rows with missing values in parameter columns
    X = df[variable_fields].dropna()

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
    param_median = df[df['cluster'] == best_cluster][variable_fields].median()
    print("\n📌 Median hyperparameters from best cluster:")
    print(param_median)
    return param_median


def generate_controller_config(df, controller_class, dynamic_fields):

    total_amount_quote = Decimal(1000)

    # Assemble dynamic kwargs
    dynamic_kwargs = {field: df[field] for field in dynamic_fields if field in df}

    # Combine with fixed kwargs
    config = controller_class(
        total_amount_quote=total_amount_quote,
        take_profit=Decimal(5), # UNREALISTIC VALUE
        stop_loss=Decimal(5), # UNREALISTIC VALUE
        **dynamic_kwargs
    )

    return config


from hummingbot.strategy_v2.controllers.directional_trading_controller_base import (
    DirectionalTradingControllerConfigBase,
)
from core.data_structures.backtesting_result import (BacktestingResult)

import traceback

def _run_backtest_task(args):
    """
    Helper function to be launched in multiprocessing. Includes detailed logging.
    """
    config_serialized, start_ts, end_ts, trade_cost_value, dataset_label = args

    start_dt = datetime.datetime.fromtimestamp(start_ts, tz=datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    end_dt = datetime.datetime.fromtimestamp(end_ts, tz=datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    try:
        print(f"[{multiprocessing.current_process().name}] 🚀 Starting {dataset_label} backtest from {start_dt} to {end_dt}...")

        from core.backtesting import BacktestingEngine
        engine = BacktestingEngine(root_path=root_path, load_cached_data=True)
        result = asyncio.run(engine.run_backtesting(config_serialized, start_ts, end_ts, "1m", trade_cost=trade_cost_value))

        print(f"[{multiprocessing.current_process().name}] ✅ Finished {dataset_label} backtest from {start_dt} to {end_dt}.")
        return result

    except Exception as e:
        print(f"[{multiprocessing.current_process().name}] ❌ Error during {dataset_label} backtest: {e}")
        traceback.print_exc()
        return None

async def test_optimal_controller_configuration(
    config: DirectionalTradingControllerConfigBase,
    train_start_date: datetime.datetime,
    train_end_date: datetime.datetime,
    test_start_date: datetime.datetime,
    test_end_date: datetime.datetime,
    whole_start_date: datetime.datetime,
    whole_end_date: datetime.datetime
) -> Dict[str, 'BacktestingResult']:
    """
    Runs whole, train, test backtests in parallel processes.
    """
    trade_cost_value = float(trade_cost)

    args_list = [
        (config, int(whole_start_date.timestamp()), int(whole_end_date.timestamp()), trade_cost_value, "WHOLE"),
        (config, int(train_start_date.timestamp()), int(train_end_date.timestamp()), trade_cost_value, "TRAIN"),
        (config, int(test_start_date.timestamp()), int(test_end_date.timestamp()), trade_cost_value, "TEST"),
    ]

    with multiprocessing.Pool(processes=3) as pool:
        results = pool.map(_run_backtest_task, args_list)

    return {
        "whole": results[0],
        "train": results[1],
        "test": results[2],
    }

async def main():



    controller_info = CONTROLLER_CLASS_MAPPING[controller_name]
    controller_class = controller_info["class"]
    variable_fields = controller_info["fields"]
    dynamic_fields = COMMON_FIELDS + controller_info["fields"]

  
    # FIXME: create check for study_id != NONE
    trials = fetch_trials(study_id, dynamic_fields=dynamic_fields)
    # Only trades over 100 occurences per year sound reasonable in terms of
    # statistically significant
    trials = [t for t in trials if t["total_positions"] > 50] # TODO: could be part of the SQL Query
    # print(trials)

    df_trials = pd.DataFrame(trials)
    optimal_configuration = cluster_data(trials_df=df_trials, variable_fields=variable_fields)

    optimal_configuration["trading_pair"] = df_trials["trading_pair"].unique()[0]
    optimal_configuration["interval"] = df_trials["interval"].unique()[0]
    optimal_configuration["connector_name"] = df_trials["connector_name"].unique()[0]
    
    print("====== OPTIMAL CONFIG ======")
    print(optimal_configuration)
    print("====== ============== ======")
    
    optimal_controller_configuration = generate_controller_config(df=optimal_configuration, controller_class=controller_class, dynamic_fields=dynamic_fields)

    results = await test_optimal_controller_configuration(
        optimal_controller_configuration,
        train_start_date = train_start_date,
        train_end_date= train_end_date,
        test_start_date= test_start_date,
        test_end_date= test_end_date,
        whole_start_date= whole_start_date,
        whole_end_date= whole_end_date
        )

    # Check for Sharpes, and number of trades 
    print()
    print("====== TRAIN ======")
    print(results["train"].get_results_summary())
    print("===================")
    print("====== TEST ======")
    print(results["test"].get_results_summary())
    print("===================")
    print("====== WHOLE ======")
    print(results["whole"].get_results_summary())
    print("===================")


if __name__ == "__main__":
    asyncio.run(main())