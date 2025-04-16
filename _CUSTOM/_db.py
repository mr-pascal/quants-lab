import psycopg2
import json

## TO BE EDITED
study_id = "910"
fields_to_extract = ["ema_fast","ema_slow", "srsi_smoothing", "srsi_length",  "rsi_ma_length", "hma_diff_ma_length","hma_slow", "hma_fast", "natr_length","time_limit", "tp_natr_factor", "sl_natr_factor", ]
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
  tua.value_json
FROM trials t
JOIN trial_values tv ON t.trial_id = tv.trial_id
JOIN trial_user_attributes tua ON t.trial_id = tua.trial_id
WHERE t.study_id = {study_id}
  AND tua.key = 'config'
  AND tv.value > 0
  ORDER BY value DESC
"""
#  AND tv.value > 1.0

cur.execute(query)




parameters_list = []
# Process each row
for trial_id, value, raw_value_json in cur.fetchall():
    try:
        parsed_json = json.loads(json.loads(raw_value_json))

        # print(parsed_json)
        parameters = {key: parsed_json.get(key) for key in fields_to_extract}
        parameters["sharpe"] = value
        parameters["trial_id"] = trial_id
        parameters_list.append(parameters)
    except Exception as e:
        print(f"[!] Failed to parse trial {trial_id}: {e}")


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
