import requests
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="EU Fiscal Dashboard",
    page_icon="🇪🇺",
    layout="wide",
)

# ── Constants ──────────────────────────────────────────────────────────────────
BASE = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"

INDICATORS = {
    "Gross debt (% GDP)":             {"dataset": "gov_10dd_edpt1", "na_item": "GD", "unit": "PC_GDP"},
    "Budget deficit (% GDP)":         {"dataset": "gov_10dd_edpt1", "na_item": "B9", "unit": "PC_GDP"},
    "Government revenue (% GDP)":     {"dataset": "gov_10a_main",   "na_item": "TR", "unit": "PC_GDP"},
    "Government expenditure (% GDP)": {"dataset": "gov_10a_main",   "na_item": "TE", "unit": "PC_GDP"},
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
            pass
    if not rows:
        return pd.DataFrame(columns=["geo", "time", "value"])
    combined = pd.concat(rows, ignore_index=True).sort_values(["geo", "time"])
    combined = combined[combined["geo"].isin(EU_COUNTRIES.keys())]
    combined["country"] = combined["geo"].map(EU_COUNTRIES)
    return combined

@st.cache_data(show_spinner=False)
def load_fiscal_health(geo: str) -> dict:
    result = {"debt": None, "deficit": None, "debt_trend": None, "deficit_trend": None}
    try:
        js = fetch("gov_10dd_edpt1", {"unit": "PC_GDP", "sector": "S13", "na_item": "GD", "geo": geo, "sinceTimePeriod": "2018", "untilTimePeriod": "2023"})
        df = eurostat_to_long(js)
        df = df[df["geo"] == geo][["time", "value"]].dropna()
        df["time"] = df["time"].astype(int)
        df = df.sort_values("time")
        if not df.empty:
            result["debt"] = df[df["time"] == df["time"].max()]["value"].values[0]
            if len(df) >= 3:
                result["debt_trend"] = df["value"].iloc[-1] - df["value"].iloc[-3]
    except Exception:
        pass
    try:
        js = fetch("gov_10dd_edpt1", {"unit": "PC_GDP", "sector": "S13", "na_item": "B9", "geo": geo, "sinceTimePeriod": "2018", "untilTimePeriod": "2023"})
        df = eurostat_to_long(js)
        df = df[df["geo"] == geo][["time", "value"]].dropna()
        df["time"] = df["time"].astype(int)
        df = df.sort_values("time")
        if not df.empty:
            result["deficit"] = df[df["time"] == df["time"].max()]["value"].values[0]
            if len(df) >= 3:
                result["deficit_trend"] = df["value"].iloc[-1] - df["value"].iloc[-3]
    except Exception:
        pass
    return result

def fiscal_health_card(geo: str, country: str):
    data = load_fiscal_health(geo)
    debt = data["debt"]
    deficit = data["deficit"]
    debt_trend = data["debt_trend"]
    deficit_trend = data["deficit_trend"]

    debt_ok = debt is not None and debt < 60
    deficit_ok = deficit is not None and deficit > -3

    def trend_arrow(val, lower_is_better=True):
        if val is None:
            return "→ n/a"
        improving = val < -0.5 if lower_is_better else val > 0.5
        worsening = val > 0.5 if lower_is_better else val < -0.5
        if improving:
            return "↓ improving"
        elif worsening:
            return "↑ worsening"
        return "→ stable"

    debt_trend_str = trend_arrow(debt_trend, lower_is_better=True)
    deficit_trend_str = trend_arrow(deficit_trend, lower_is_better=False)

    if debt_ok and deficit_ok:
        verdict = "✅ COMPLIANT"
        verdict_color = "#1a7f37"
        bg_color = "#f0fdf4"
        border_color = "#86efac"
    elif not debt_ok and not deficit_ok:
        verdict = "❌ NON-COMPLIANT"
        verdict_color = "#b91c1c"
        bg_color = "#fef2f2"
        border_color = "#fca5a5"
    else:
        verdict = "⚠️ PARTIAL"
        verdict_color = "#92400e"
        bg_color = "#fffbeb"
        border_color = "#fcd34d"

    debt_str = f"{debt:.1f}% GDP" if debt is not None else "n/a"
    deficit_str = f"{deficit:.1f}% GDP" if deficit is not None else "n/a"
    debt_rule = "✅ below 60%" if debt_ok else "❌ above 60%"
    deficit_rule = "✅ within −3%" if deficit_ok else "❌ exceeds −3%"

    st.markdown(f"""
    <div style="background:{bg_color};border:1.5px solid {border_color};border-radius:10px;padding:14px 18px;margin-bottom:8px;">
        <div style="font-size:1em;font-weight:700;color:#1e293b;">{country}</div>
        <div style="font-size:1.2em;font-weight:800;color:{verdict_color};margin:4px 0 10px 0;">{verdict}</div>
        <div style="display:flex;gap:24px;">
            <div>
                <div style="font-size:0.7em;color:#64748b;text-transform:uppercase;letter-spacing:.05em;">Gross Debt</div>
                <div style="font-size:1.05em;font-weight:600;">{debt_str}</div>
                <div style="font-size:0.78em;color:#475569;">{debt_rule}</div>
                <div style="font-size:0.72em;color:#94a3b8;">{debt_trend_str}</div>
            </div>
            <div>
                <div style="font-size:0.7em;color:#64748b;text-transform:uppercase;letter-spacing:.05em;">Budget Balance</div>
                <div style="font-size:1.05em;font-weight:600;">{deficit_str}</div>
                <div style="font-size:0.78em;color:#475569;">{deficit_rule}</div>
                <div style="font-size:0.72em;color:#94a3b8;">{deficit_trend_str}</div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/b/b7/Flag_of_Europe.svg", width=80)
    st.title("EU Fiscal Dashboard")
    st.caption("Data: Eurostat")

    selected_indicator = st.selectbox("Indicator", list(INDICATORS.keys()))

    country_options = [f"{k} – {v}" for k, v in EU_COUNTRIES.items()]
    default_display = [f"{k} – {EU_COUNTRIES[k]}" for k in DEFAULT_COUNTRIES]
    selected_display = st.multiselect("Countries", country_options, default=default_display)
    selected_geos = tuple(s.split(" – ")[0] for s in selected_display)

    year_from, year_to = st.slider("Year range", 2000, 2023, (2010, 2023))

    st.divider()
    st.markdown("Built with [Streamlit](https://streamlit.io) · [Source](https://github.com/jussinasi/eu-fiscal-analysis)")

# ── Main ───────────────────────────────────────────────────────────────────────
st.title("🇪🇺 EU Fiscal Analysis")

if not selected_geos:
    st.warning("Select at least one country from the sidebar.")
    st.stop()

# ── Fiscal Health Cards ────────────────────────────────────────────────────────
st.subheader("Fiscal Health · EU Stability & Growth Pact compliance (2023)")
st.caption("SGP rules: Gross debt < 60% GDP · Budget deficit < 3% GDP")

n = len(selected_geos)
cols = st.columns(min(n, 3))
for i, geo in enumerate(selected_geos):
    with cols[i % 3]:
        fiscal_health_card(geo, EU_COUNTRIES.get(geo, geo))

st.divider()

# ── Chart ──────────────────────────────────────────────────────────────────────
st.caption(f"**{selected_indicator}** · General government · {year_from}–{year_to}")

with st.spinner("Fetching data from Eurostat…"):
    df = load_indicator(selected_indicator, selected_geos, year_from, year_to)

if df.empty:
    st.error("No data returned. Try different parameters.")
    st.stop()

fig = px.line(
    df, x="time", y="value", color="country",
    markers=True,
    labels={"time": "Year", "value": selected_indicator, "country": "Country"},
    title=selected_indicator,
)
if "debt" in selected_indicator.lower():
    fig.add_hline(y=60, line_dash="dash", line_color="red",
                  annotation_text="SGP limit: 60%", annotation_position="bottom right")
elif "deficit" in selected_indicator.lower():
    fig.add_hline(y=-3, line_dash="dash", line_color="red",
                  annotation_text="SGP limit: −3%", annotation_position="top right")

fig.update_layout(
    hovermode="x unified",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    plot_bgcolor="white",
    yaxis=dict(gridcolor="#eee"),
)
st.plotly_chart(fig, use_container_width=True)

# ── Latest snapshot ────────────────────────────────────────────────────────────
latest_year = df["time"].max()
latest = df[df["time"] == latest_year].sort_values("value", ascending=False)
eu_avg = latest["value"].mean()

col1, col2 = st.columns([2, 1])
with col1:
    fig2 = px.bar(
        latest, x="country", y="value", color="value",
        color_continuous_scale="RdYlGn_r",
        labels={"value": selected_indicator, "country": ""},
        title=f"Latest snapshot ({latest_year})",
    )
    fig2.add_hline(y=eu_avg, line_dash="dot", line_color="#3b82f6",
                   annotation_text=f"Avg: {eu_avg:.1f}%", annotation_position="top right")
    fig2.update_layout(coloraxis_showscale=False, plot_bgcolor="white", yaxis=dict(gridcolor="#eee"))
    st.plotly_chart(fig2, use_container_width=True)

with col2:
    st.subheader(f"Rankings {latest_year}")
    ranked = latest[["country", "value"]].reset_index(drop=True)
    ranked["vs avg"] = (ranked["value"] - eu_avg).round(1).apply(lambda x: f"+{x}" if x > 0 else str(x))
    ranked["value"] = ranked["value"].round(1)
    ranked.index += 1
    ranked.columns = ["Country", selected_indicator, "vs avg"]
    st.dataframe(ranked, use_container_width=True, hide_index=False)

with st.expander("📄 Raw data"):
    st.dataframe(
        df[["country", "geo", "time", "value"]].rename(columns={"time": "Year", "value": selected_indicator}),
        use_container_width=True, hide_index=True,
    )
    csv = df.to_csv(index=False).encode()
    st.download_button("⬇ Download CSV", csv, "eu_fiscal_data.csv", "text/csv")
