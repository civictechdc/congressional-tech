import pandas as pd
import requests
from datetime import datetime
from pathlib import Path

script_dir = Path(__file__).resolve().parent
output_dir = script_dir / "data"

def fetch_cpi_range(start_year, end_year):
    url = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
    payload = {
        "seriesid": ["CUUR0000SA0"],
        "startyear": str(start_year),
        "endyear": str(end_year),
    }
    headers = {"Content-Type": "application/json"}
    r = requests.post(url, json=payload, headers=headers)
    r.raise_for_status()
    return r.json()["Results"]["series"][0]["data"]

def get_recent_cpi_data():
    current_year = datetime.now().year
    start_year = current_year - 9
    print(f"Fetching CPI data from {start_year} to {current_year}...")
    return fetch_cpi_range(start_year, current_year)

# Load existing CPI baseline and drop index column
baseline_path = output_dir / "historical-cpi.csv"
df_baseline = pd.read_csv(baseline_path)
df_baseline.index = df_baseline.index.astype(int)

# Fetch and process recent CPI data
raw_data = get_recent_cpi_data()
df_recent = pd.DataFrame(raw_data)
df_recent["value"] = df_recent["value"].astype(float)
df_recent["year"] = df_recent["year"].astype(int)

# Pivot to wide format
df_pivot = df_recent.pivot(index="year", columns="periodName", values="value")

# Ensure correct month order
month_order = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"
]
df_pivot = df_pivot[month_order]

# Append only new rows
df_combined = pd.concat([df_baseline, df_pivot])
df_combined = df_combined[~df_combined.index.duplicated(keep='last')]
df_combined = df_combined.sort_index()

# Save updated data
csv_path = output_dir / "historical-cpi.csv"
df_combined.to_csv(csv_path)
print(f"Saved {csv_path}")