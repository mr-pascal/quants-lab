# How to backtest

```sh

# Start the DBs
docker compose up -d

# Activate python env
conda activate quants-lab

# Start optuna dashboard (async process)
cd _CUSTOM
python optuna_dashboard.py

# Kill optuna dashboard
./kill_optuna.sh

# Run the backtest
cd _CUSTOM
python optimize_pz_scalper.py

```
