import json
from pathlib import Path

import pandas as pd
import requests

# Eurostat JSON API helper (no external eurostat package needed)
BASE = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"


def fetch_eurostat(dataset: str, params: dict) -> dict:
    """Fetch a Eurostat dataset as JSON."""
    r = requests.get(f"{BASE}/{dataset}", params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def eurostat_json_to_long(js: dict) -> pd.DataFrame:
    """
    Convert Eurostat JSON response to a long DataFrame with columns:
    time, value, plus dimension columns.
    """
    dims = js["dimension"]
    dim_order = js["id"]              # e.g. ["geo","unit","na_item","time"]
    size = js["size"]                 # length per dimension

    # Build labels per dimension (code -> label)
    dim_codes = {}
    for d in dim_order:
        cat = dims[d]["category"]
        # "index" preserves the order used in the value vector
        inv_index = {v: k for k, v in cat["index"].items()}
        dim_codes[d] = [inv_index[i] for i in range(len(inv_index))]

    # Values are stored in a sparse dict: position -> value
    values = js.get("value", {})
    # Create multi-index for all combinations
    mi = pd.MultiIndex.from_product([dim_codes[d] for d in dim_order], names=dim_order)

    s = pd.Series(index=mi, dtype="float64")
    for k, v in values.items():
        s.iloc[int(k)] = float(v)

    df = s.reset_index().rename(columns={0: "value"})
    return df


def main():
    # Example dataset: gov_10dd_edpt1 = Government deficit/surplus, debt and associated data
    # We'll pull GENERAL GOVERNMENT GROSS DEBT (Maastricht debt), % of GDP, annual.
    dataset = "gov_10dd_edpt1"
    params = {
        "na_item": "GD",   # Gross debt
        "sector": "S13",   # General government
        "unit": "PC_GDP",  # % of GDP
        "time": "2010-2024",
        "geo": "FI",       # Finland as a start (change later)
    }

    js = fetch_eurostat(dataset, params)
    df = eurostat_json_to_long(js)

    # Keep only what we need and tidy time to int
    out = df[["geo", "time", "value"]].copy()
    out["time"] = out["time"].astype(int)
    out = out.sort_values(["geo", "time"])

    Path("data/raw").mkdir(parents=True, exist_ok=True)
    out_path = Path("data/raw/fi_debt_pct_gdp.csv")
    out.to_csv(out_path, index=False)

    print(f"Saved: {out_path}  (rows={len(out)})")
    print(out.tail())


if __name__ == "__main__":
    main()