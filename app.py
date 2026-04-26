import requests
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import requests

BASE = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"
r = requests.get(f"{BASE}/gov_10a3_exp", params={"unit":"PC_GDP","sector":"S13","na_item":"TR","geo":"FI","sinceTimePeriod":"2020","untilTimePeriod":"2024"}, timeout=30)
print(r.status_code)
print(r.text[:500])
# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="EU Fiscal Dashboard",
    page_icon="🇪🇺",
    layout="wide",
)

INDICATORS = {
    "Gross debt (% GDP)":             {"dataset": "gov_10dd_edpt1", "na_item": "GD",  "unit": "PC_GDP"},
    "Budget deficit (% GDP)":         {"dataset": "gov_10dd_edpt1", "na_item": "B9",  "unit": "PC_GDP"},
    "Government revenue (% GDP)":     {"dataset": "gov_10a3_exp",   "na_item": "TR",  "unit": "PC_GDP"},
    "Government expenditure (% GDP)": {"dataset": "gov_10a3_exp",   "na_item": "TE",  "unit": "PC_GDP"},
}

EU_COUNTRIES = {
    "AT": "Austria", "BE": "Belgium", "BG": "Bulgaria", "CY": "Cyprus",
    "CZ": "Czechia", "DE": "Germany", "DK": "Denmark", "EE": "Estonia",
    "ES": "Spain", "FI": "Finland", "FR": "France", "GR": "Greece",
    "HR": "Croatia", "HU": "Hungary", "IE": "Ireland", "IT": "Italy",
    "LT": "Lithuania", "LU": "Luxembourg", "LV": "Latvia", "MT": "Malta",
    "NL": "Netherlands", "PL": "Poland", "PT": "Portugal", "RO": "Romania",
    "SE": "Sweden", "SI": "Slovenia", "SK": "Slovakia",
}

DEFAULT_COUNTRIES = ["FI", "DE", "FR", "IT", "ES", "SE"]

# ── Eurostat helpers ───────────────────────────────────────────────────────────
def fetch(dataset: str, params: dict) -> dict:
    r = requests.get(f"{BASE}/{dataset}", params=params, timeout=60)
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

@st.cache_data(show_spinner=False)
def load_indicator(indicator_key: str, geos: tuple, year_from: int, year_to: int) -> pd.DataFrame:
    cfg = INDICATORS[indicator_key]
    rows = []
    for geo in geos:
        try:
            js = fetch(cfg["dataset"], {
                "unit": cfg["unit"],
                "sector": "S13",
                "na_item": cfg["na_item"],
                "geo": geo,
                "sinceTimePeriod": str(year_from),
                "untilTimePeriod": str(year_to),
            })
            df = eurostat_to_long(js)
            out = df[["geo", "time", "value"]].copy()
            out["time"] = out["time"].astype(int)
            rows.append(out)
        except Exception:
            pass  # skip countries with no data
    if not rows:
        return pd.DataFrame(columns=["geo", "time", "value"])
    combined = pd.concat(rows, ignore_index=True).sort_values(["geo", "time"])
    combined = combined[combined["geo"].isin(EU_COUNTRIES.keys())]
    combined["country"] = combined["geo"].map(EU_COUNTRIES)
    return combined

# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/b/b7/Flag_of_Europe.svg", width=80)
    st.title("EU Fiscal Dashboard")
    st.caption("Data: Eurostat · gov_10dd_edpt1")

    selected_indicator = st.selectbox("Indicator", list(INDICATORS.keys()))

    country_options = [f"{k} – {v}" for k, v in EU_COUNTRIES.items()]
    default_display = [f"{k} – {EU_COUNTRIES[k]}" for k in DEFAULT_COUNTRIES]
    selected_display = st.multiselect("Countries", country_options, default=default_display)
    selected_geos = tuple(s.split(" – ")[0] for s in selected_display)

    year_from, year_to = st.slider("Year range", 2000, 2024, (2010, 2024))

    st.divider()
    st.markdown("Built with [Streamlit](https://streamlit.io) · [Source](https://github.com/jussinasi/eu-fiscal-analysis)")

# ── Main ───────────────────────────────────────────────────────────────────────
st.title("🇪🇺 EU Fiscal Analysis")
st.caption(f"**{selected_indicator}** · General government · {year_from}–{year_to}")

if not selected_geos:
    st.warning("Select at least one country from the sidebar.")
    st.stop()

with st.spinner("Fetching data from Eurostat…"):
    df = load_indicator(selected_indicator, selected_geos, year_from, year_to)

if df.empty:
    st.error("No data returned. Try different parameters.")
    st.stop()

# ── Line chart ─────────────────────────────────────────────────────────────────
fig = px.line(
    df, x="time", y="value", color="country",
    markers=True,
    labels={"time": "Year", "value": selected_indicator, "country": "Country"},
    title=selected_indicator,
)
fig.update_layout(
    hovermode="x unified",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    plot_bgcolor="white",
    yaxis=dict(gridcolor="#eee"),
)
st.plotly_chart(fig, use_container_width=True)

# ── Latest snapshot bar chart ──────────────────────────────────────────────────
latest_year = df["time"].max()
latest = df[df["time"] == latest_year].sort_values("value", ascending=False)

col1, col2 = st.columns([2, 1])
with col1:
    fig2 = px.bar(
        latest, x="country", y="value", color="value",
        color_continuous_scale="RdYlGn_r",
        labels={"value": selected_indicator, "country": ""},
        title=f"Latest snapshot ({latest_year})",
    )
    fig2.update_layout(coloraxis_showscale=False, plot_bgcolor="white", yaxis=dict(gridcolor="#eee"))
    st.plotly_chart(fig2, use_container_width=True)

with col2:
    st.subheader(f"Rankings {latest_year}")
    ranked = latest[["country", "value"]].reset_index(drop=True)
    ranked.index += 1
    ranked.columns = ["Country", selected_indicator]
    ranked[selected_indicator] = ranked[selected_indicator].round(1)
    st.dataframe(ranked, use_container_width=True, hide_index=False)

# ── Raw data expander ──────────────────────────────────────────────────────────
with st.expander("📄 Raw data"):
    st.dataframe(
        df[["country", "geo", "time", "value"]].rename(columns={"time": "Year", "value": selected_indicator}),
        use_container_width=True,
        hide_index=True,
    )
    csv = df.to_csv(index=False).encode()
    st.download_button("⬇ Download CSV", csv, "eu_fiscal_data.csv", "text/csv")