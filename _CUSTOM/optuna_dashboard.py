
import os
import sys

root_path = os.path.abspath(os.path.join(os.getcwd(), '../'))
sys.path.append(root_path)


from core.backtesting.optimizer import StrategyOptimizer

kwargs = {
    "db_host": os.getenv("OPTUNA_HOST", "localhost"),
    "db_port":os.getenv("OPTUNA_PORT", 5432),
    "db_user": os.getenv("OPTUNA_USER", "admin"),
    "db_pass": os.getenv("OPTUNA_PASSWORD", "admin"),
    "database_name": os.getenv("OPTUNA_DB", "optimization_database")
}
storage_name = StrategyOptimizer.get_storage_name(
            engine="postgres",
            **kwargs)
optimizer = StrategyOptimizer(storage_name=storage_name, root_path=root_path)

optimizer.launch_optuna_dashboard()