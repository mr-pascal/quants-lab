import yaml
from datetime import datetime, date

# Load YAML file
with open("config.yaml", "r") as file:
    config = yaml.safe_load(file)

# Extract trading pair (only the uncommented one)
trading_pairs = config['trading_pairs']

# Extract and convert dates
start_date_str = config['timeframe']['start']
end_date_str = config['timeframe']['end']

# Convert to datetime if they are date objects
if isinstance(start_date_str, date):
    start_date = datetime.combine(start_date_str, datetime.min.time())
else:
    start_date = datetime.strptime(start_date_str, "%Y-%m-%d")

if isinstance(end_date_str, date):
    end_date = datetime.combine(end_date_str, datetime.min.time())
else:
    end_date = datetime.strptime(end_date_str, "%Y-%m-%d")

# Extract candle interval
candle_intervals = config['candle_intervals']

# Extract DB configuration
db_config = config['db']
db_host = db_config['host']
db_port = db_config['port']
db_user = db_config['user']
db_password = db_config['password']
db_name = db_config['database']

# Print variables (optional)
print(f"Trading Pair: {trading_pairs}")
print(f"Timeframe: {start_date} to {end_date}")
print(f"Candle Intervals: {candle_intervals}")
print(f"DB Host: {db_host}, Port: {db_port}, User: {db_user}, Database: {db_name}")