import psycopg2
import json

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

# Query configs
# cur.execute("""
#     SELECT trial_id, value_json
#     FROM trial_user_attributes
#     WHERE key = 'config'
#     LIMIT 1;
# """)


query = """
SELECT
  t.trial_id,
  tv.value,
  tua.value_json
FROM trials t
JOIN trial_values tv ON t.trial_id = tv.trial_id
JOIN trial_user_attributes tua ON t.trial_id = tua.trial_id
WHERE t.study_id = 582
  AND tua.key = 'config'
  AND tv.value > 0
  ORDER BY value DESC
"""
#  AND tv.value > 1.0

cur.execute(query)


fields_to_extract = ["ema_fast","ema_slow", "srsi_smoothing", "srsi_length",  "rsi_ma_length", "hma_diff_ma_length","hma_slow", "hma_fast", "natr_length","time_limit", "tp_natr_factor", "sl_natr_factor", ]


parameters_list = []
# Process each row
for trial_id, value, raw_value_json in cur.fetchall():
    try:
        # If the value is an escaped JSON string (e.g. '{"ema_fast": 30, ...}')
        # psycopg2 may already return it as a string
        parsed_json = json.loads(json.loads(raw_value_json))

        # print(parsed_json)
        parameters = {key: parsed_json.get(key) for key in fields_to_extract}
        parameters["sharpe"] = value
        parameters["trial_id"] = trial_id
        # print(f"Trial {trial_id} → {parameters}")

        # print(parameters)
        parameters_list.append(parameters)
        # print(f"Trial {trial_id} → ema_fast: {parsed_json.get('ema_fast')}, ema_slow: {parsed_json.get('ema_slow')}")
    except Exception as e:
        print(f"[!] Failed to parse trial {trial_id}: {e}")


# print(parameters_list)
from collections import OrderedDict

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
    fieldnames = ["trial_id", "sharpe" ] + list(fields_to_extract)
    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
    
    writer.writeheader()
    for row in unique_params:
        writer.writerow(row)

cur.close()
conn.close()
