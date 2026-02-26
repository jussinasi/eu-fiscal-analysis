from pathlib import Path

import pandas as pd
import requests

BASE = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"


def fetch(dataset: str, params: dict) -> dict:
    r = requests.get(f"{BASE}/{dataset}", params=params, timeout=60)
    if not r.ok:
        try:
            print("Eurostat error payload:", r.json())
        except Exception:
            print("Eurostat error text:", r.text[:500])
        r.raise_for_status()
    return r.json()


def eurostat_to_long(js: dict) -> pd.DataFrame:
    dims = js["dimension"]
    dim_order = js["id"]

    dim_codes = {}
    for d in dim_order:
        cat = dims[d]["category"]
        inv_index = {v: k for k, v in cat["index"].items()}
        dim_codes[d] = [inv_index[i] for i in range(len(inv_index))]

    values = js.get("value", {})
    mi = pd.MultiIndex.from_product([dim_codes[d] for d in dim_order], names=dim_order)

    s = pd.Series(index=mi, dtype="float64")
    for k, v in values.items():
        s.iloc[int(k)] = float(v)

    return s.reset_index().rename(columns={0: "value"})


def print_dim_samples(js: dict, max_items: int = 15) -> None:
    print("Returned dimensions:", js.get("id"))
    for d in js.get("id", []):
        cats = js["dimension"][d]["category"]
        keys = list(cats["index"].keys())
        print(f"{d} n={len(keys)} sample={keys[:max_items]}")


def main():
    dataset = "gov_10dd_edpt1"

    # Base filters: gross debt (% GDP), general government, annual
    params_base = {
        "unit": "PC_GDP",
        "sector": "S13",
        "sinceTimePeriod": "2010",
        "untilTimePeriod": "2024",
        "na_item": "GD",
    }

    geos = ["FI", "DE", "FR", "IT", "ES"]  # add more if you want

    all_rows = []
    for geo in geos:
        params = dict(params_base)
        params["geo"] = geo

        js = fetch(dataset, params)
        df = eurostat_to_long(js)
        out = df[["geo", "time", "value"]].copy()
        out["time"] = out["time"].astype(int)
        out = out.sort_values(["geo", "time"])
        all_rows.append(out)

    combined = pd.concat(all_rows, ignore_index=True)

    Path("data/raw").mkdir(parents=True, exist_ok=True)
    out_path = Path("data/raw/eu5_gross_debt_pc_gdp.csv")
    combined.to_csv(out_path, index=False)

    # Chart: multi-country comparison
    import matplotlib.pyplot as plt

    Path("output/charts").mkdir(parents=True, exist_ok=True)
    plt.figure()

    for geo in geos:
        sub = combined[combined["geo"] == geo].sort_values("time")
        plt.plot(sub["time"], sub["value"], label=geo)

    plt.title("General government gross debt (% of GDP): FI, DE, FR, IT, ES")
    plt.xlabel("Year")
    plt.ylabel("% of GDP")
    plt.legend()
    plt.tight_layout()
    fig_path = Path("output/charts/eu5_gross_debt_pc_gdp.png")
    plt.savefig(fig_path, dpi=150)
    plt.close()

    print(f"Saved: {out_path} (rows={len(combined)})")
    print(f"Chart saved: {fig_path}")
    print(combined.tail())

if __name__ == "__main__":
    main()
