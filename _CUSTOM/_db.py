import psycopg2
import json

## TO BE EDITED
study_id = "938"
fields_to_extract = ["ema_fast","ema_slow", "srsi_smoothing", "srsi_length",  "rsi_ma_length", "hma_diff_ma_length","hma_slow", "hma_fast", "natr_length","time_limit", "tp_natr_factor", "sl_natr_factor", "interval", "max_executors_per_side", "trading_pair" ]
###############


# --- Update these with your actual DB credentials ---
DB_CONFIG = {
    'dbname': 'optimization_database',
    'user': 'admin',
    'password': 'admin',
    'host': 'localhost',
    'port': 5432,
}

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
  AND tv.value > 0
  ORDER BY value DESC
"""
#  AND tv.value > 1.0

cur.execute(query)




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


# print(unique_params)
import csv
with open("top_configs.csv", "w", newline="") as csvfile:
    fieldnames = unique_params[0].keys() # ["trial_id", "sharpe" ] + list(fields_to_extract)
    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
    
    writer.writeheader()
    for row in unique_params:
        writer.writerow(row)

cur.close()
conn.close()
