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


# Extract best configs
# Adjust trial_id in "_db.py"
python _db.py



```

## Ask ChatGPT for robustness check

```txt
You are a trading strategy assistant with expertise in quantitative research, Optuna-based hyperparameter optimization, and live-to-backtest robustness evaluation.

I’ll give you a CSV file exported from an Optuna study. The file contains:

The trial_id

The sharpe ratio (objective metric)

The parameters for each strategy configuration tested

Drawdowns, PnL (%), number of positions, etc

Your task is to:

Analyze the parameters for robustness and stability (e.g., clustering, performance plateaus, sensitivity)

Evaluate whether the strategy appears curve-fit or if it should generalize well to out-of-sample or live data

Visualize correlations and parameter distributions if useful

Recommend a single best parameter configuration, either:

The median of top N performing trials

Or the best trial if performance is highly stable

Make sure your recommendation is ready to use in production.
Explain any trade-offs or assumptions behind it.
If the strategy seems fragile or overfit, suggest validation techniques (e.g. walk-forward, parameter smoothing).
```
