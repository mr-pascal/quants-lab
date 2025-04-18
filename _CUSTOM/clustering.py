import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import DBSCAN
import matplotlib.pyplot as plt
import seaborn as sns

# Load your optimization results CSV
df = pd.read_csv("top_configs.csv")

# Select only numeric hyperparameters (adjust if your strategy changes)
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

# Optional: Plot Sharpe distribution by cluster
# plt.figure(figsize=(10, 6))
# sns.boxplot(x='cluster', y='sharpe', data=df[df['cluster'] != -1])
# plt.title("Sharpe Ratio Distribution by Cluster")
# plt.grid(True)
# plt.show()
