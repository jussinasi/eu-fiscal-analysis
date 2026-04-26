import requests
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

st.set_page_config(page_title="EU Fiscal Dashboard", page_icon="🇪🇺", layout="wide")

BASE = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"

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

INDICATORS = {
    "Gross debt (% GDP)":             {"dataset": "gov_10dd_edpt1", "na_item": "GD", "unit": "PC_GDP"},
    "Budget deficit (% GDP)":         {"dataset": "gov_10dd_edpt1", "na_item": "B9", "unit": "PC_GDP"},
    "Government revenue (% GDP)":     {"dataset": "gov_10a_main",   "na_item": "TR", "unit": "PC_GDP"},
    "Government expenditure (% GDP)": {"dataset": "gov_10a_main",   "na_item": "TE", "unit": "PC_GDP"},
}

# ── Eurostat helpers ───────────────────────────────────────────────────────────
def fetch(dataset, params):
    r = requests.get(f"{BASE}/{dataset}", params=params, timeout=60)
    r.raise_for_status()
    return r.json()

def eurostat_to_long(js):
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
def load_indicator(indicator_key, geos, year_from, year_to):
    cfg = INDICATORS[indicator_key]
    rows = []
    for geo in geos:
        try:
            js = fetch(cfg["dataset"], {"unit": cfg["unit"], "sector": "S13", "na_item": cfg["na_item"],
                                        "geo": geo, "sinceTimePeriod": str(year_from), "untilTimePeriod": str(year_to)})
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
def load_rev_exp(geo, year_from, year_to):
    """Load both revenue and expenditure for one country."""
    rows = {}
    for key, na_item in [("revenue", "TR"), ("expenditure", "TE")]:
        try:
            js = fetch("gov_10a_main", {"unit": "PC_GDP", "sector": "S13", "na_item": na_item,
                                        "geo": geo, "sinceTimePeriod": str(year_from), "untilTimePeriod": str(year_to)})
            df = eurostat_to_long(js)
            df = df[df["geo"] == geo][["time", "value"]].dropna()
            df["time"] = df["time"].astype(int)
            rows[key] = df.set_index("time")["value"]
        except Exception:
            pass
    if "revenue" not in rows or "expenditure" not in rows:
        return pd.DataFrame()
    combined = pd.DataFrame(rows).dropna()
    combined["gap"] = combined["revenue"] - combined["expenditure"]
    combined.index.name = "year"
    return combined.reset_index()

@st.cache_data(show_spinner=False)
def load_fiscal_health(geo):
    result = {"debt": None, "deficit": None, "debt_trend": None, "deficit_trend": None}
    for key, na_item in [("debt", "GD"), ("deficit", "B9")]:
        try:
            js = fetch("gov_10dd_edpt1", {"unit": "PC_GDP", "sector": "S13", "na_item": na_item,
                                          "geo": geo, "sinceTimePeriod": "2018", "untilTimePeriod": "2023"})
            df = eurostat_to_long(js)
            df = df[df["geo"] == geo][["time", "value"]].dropna()
            df["time"] = df["time"].astype(int)
            df = df.sort_values("time")
            if not df.empty:
                result[key] = df["value"].iloc[-1]
                if len(df) >= 3:
                    result[f"{key}_trend"] = df["value"].iloc[-1] - df["value"].iloc[-3]
        except Exception:
            pass
    return result

def fiscal_health_card(geo, country):
    data = load_fiscal_health(geo)
    debt, deficit = data["debt"], data["deficit"]
    debt_trend, deficit_trend = data["debt_trend"], data["deficit_trend"]

    debt_ok = debt is not None and debt < 60
    deficit_ok = deficit is not None and deficit > -3

    def arrow(val, lower_is_better=True):
        if val is None: return "→ n/a"
        if lower_is_better:
            return "↓ improving" if val < -0.5 else ("↑ worsening" if val > 0.5 else "→ stable")
        return "↑ improving" if val > 0.5 else ("↓ worsening" if val < -0.5 else "→ stable")

    if debt_ok and deficit_ok:
        verdict, vc, bg, bc = "✅ COMPLIANT", "#1a7f37", "#f0fdf4", "#86efac"
    elif not debt_ok and not deficit_ok:
        verdict, vc, bg, bc = "❌ NON-COMPLIANT", "#b91c1c", "#fef2f2", "#fca5a5"
    else:
        verdict, vc, bg, bc = "⚠️ PARTIAL", "#92400e", "#fffbeb", "#fcd34d"

    st.markdown(f"""
    <div style="background:{bg};border:1.5px solid {bc};border-radius:10px;padding:14px 18px;margin-bottom:8px;">
        <div style="font-size:1em;font-weight:700;color:#1e293b;">{country}</div>
        <div style="font-size:1.2em;font-weight:800;color:{vc};margin:4px 0 10px 0;">{verdict}</div>
        <div style="display:flex;gap:24px;">
            <div>
                <div style="font-size:0.7em;color:#64748b;text-transform:uppercase;">Gross Debt</div>
                <div style="font-size:1.05em;font-weight:600;">{"n/a" if debt is None else f"{debt:.1f}% GDP"}</div>
                <div style="font-size:0.78em;color:#475569;">{"✅ below 60%" if debt_ok else "❌ above 60%"}</div>
                <div style="font-size:0.72em;color:#94a3b8;">{arrow(debt_trend, True)}</div>
            </div>
            <div>
                <div style="font-size:0.7em;color:#64748b;text-transform:uppercase;">Budget Balance</div>
                <div style="font-size:1.05em;font-weight:600;">{"n/a" if deficit is None else f"{deficit:.1f}% GDP"}</div>
                <div style="font-size:0.78em;color:#475569;">{"✅ within −3%" if deficit_ok else "❌ exceeds −3%"}</div>
                <div style="font-size:0.72em;color:#94a3b8;">{arrow(deficit_trend, False)}</div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/b/b7/Flag_of_Europe.svg", width=80)
    st.title("EU Fiscal Dashboard")
    st.caption("Data: Eurostat")

    page = st.radio("View", ["📊 Overview", "🔍 Deficit Decomposition"])

    country_options = [f"{k} – {v}" for k, v in EU_COUNTRIES.items()]
    default_display = [f"{k} – {EU_COUNTRIES[k]}" for k in DEFAULT_COUNTRIES]
    selected_display = st.multiselect("Countries", country_options, default=default_display)
    selected_geos = tuple(s.split(" – ")[0] for s in selected_display)

    year_from, year_to = st.slider("Year range", 2000, 2023, (2010, 2023))

    if page == "📊 Overview":
        selected_indicator = st.selectbox("Indicator", list(INDICATORS.keys()))

    st.divider()
    st.markdown("Built with [Streamlit](https://streamlit.io) · [Source](https://github.com/jussinasi/eu-fiscal-analysis)")

# ── Main ───────────────────────────────────────────────────────────────────────
st.title("🇪🇺 EU Fiscal Analysis")

if not selected_geos:
    st.warning("Select at least one country from the sidebar.")
    st.stop()

# ── Fiscal Health Cards (always visible) ──────────────────────────────────────
st.subheader("Fiscal Health · SGP Compliance (2023)")
st.caption("Rules: Gross debt < 60% GDP · Budget deficit < 3% GDP")
cols = st.columns(min(len(selected_geos), 3))
for i, geo in enumerate(selected_geos):
    with cols[i % 3]:
        fiscal_health_card(geo, EU_COUNTRIES.get(geo, geo))

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
if page == "📊 Overview":
# ══════════════════════════════════════════════════════════════════════════════
    st.caption(f"**{selected_indicator}** · General government · {year_from}–{year_to}")

    with st.spinner("Fetching data from Eurostat…"):
        df = load_indicator(selected_indicator, selected_geos, year_from, year_to)

    if df.empty:
        st.error("No data returned. Try different parameters.")
        st.stop()

    fig = px.line(df, x="time", y="value", color="country", markers=True,
                  labels={"time": "Year", "value": selected_indicator, "country": "Country"},
                  title=selected_indicator)
    if "debt" in selected_indicator.lower():
        fig.add_hline(y=60, line_dash="dash", line_color="red",
                      annotation_text="SGP limit: 60%", annotation_position="bottom right")
    elif "deficit" in selected_indicator.lower():
        fig.add_hline(y=-3, line_dash="dash", line_color="red",
                      annotation_text="SGP limit: −3%", annotation_position="top right")
    fig.update_layout(hovermode="x unified", plot_bgcolor="white", yaxis=dict(gridcolor="#eee"),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
    st.plotly_chart(fig, use_container_width=True)

    latest_year = df["time"].max()
    latest = df[df["time"] == latest_year].sort_values("value", ascending=False)
    eu_avg = latest["value"].mean()

    col1, col2 = st.columns([2, 1])
    with col1:
        fig2 = px.bar(latest, x="country", y="value", color="value",
                      color_continuous_scale="RdYlGn_r",
                      labels={"value": selected_indicator, "country": ""},
                      title=f"Latest snapshot ({latest_year})")
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
        st.dataframe(df[["country", "geo", "time", "value"]].rename(
            columns={"time": "Year", "value": selected_indicator}), use_container_width=True, hide_index=True)
        st.download_button("⬇ Download CSV", df.to_csv(index=False).encode(), "eu_fiscal_data.csv", "text/csv")

# ══════════════════════════════════════════════════════════════════════════════
elif page == "🔍 Deficit Decomposition":
# ══════════════════════════════════════════════════════════════════════════════
    st.subheader("Where does the deficit come from?")
    st.caption("Revenue vs. expenditure gap · % of GDP · General government")

    if len(selected_geos) == 0:
        st.warning("Select at least one country.")
        st.stop()

    # One country at a time for decomposition
    focus_options = [f"{k} – {EU_COUNTRIES[k]}" for k in selected_geos if k in EU_COUNTRIES]
    focus_display = st.selectbox("Focus country", focus_options)
    focus_geo = focus_display.split(" – ")[0]
    focus_name = EU_COUNTRIES.get(focus_geo, focus_geo)

    with st.spinner(f"Loading revenue & expenditure for {focus_name}…"):
        re_df = load_rev_exp(focus_geo, year_from, year_to)

    if re_df.empty:
        st.error("No data available for this country/period.")
        st.stop()

    latest = re_df[re_df["year"] == re_df["year"].max()].iloc[0]
    rev_val = latest["revenue"]
    exp_val = latest["expenditure"]
    gap_val = latest["gap"]
    gap_color = "#16a34a" if gap_val >= 0 else "#dc2626"
    gap_label = "SURPLUS" if gap_val >= 0 else "DEFICIT"

    # Summary metrics
    m1, m2, m3 = st.columns(3)
    m1.metric("Revenue", f"{rev_val:.1f}% GDP")
    m2.metric("Expenditure", f"{exp_val:.1f}% GDP")
    m3.metric(f"Gap ({gap_label})", f"{gap_val:+.1f}% GDP",
              delta=f"{gap_val:+.1f}pp", delta_color="normal" if gap_val >= 0 else "inverse")

    # Revenue vs expenditure area chart
    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=re_df["year"], y=re_df["expenditure"],
        name="Expenditure", fill="tozeroy",
        line=dict(color="#ef4444", width=2),
        fillcolor="rgba(239,68,68,0.15)",
    ))
    fig.add_trace(go.Scatter(
        x=re_df["year"], y=re_df["revenue"],
        name="Revenue", fill="tozeroy",
        line=dict(color="#22c55e", width=2),
        fillcolor="rgba(34,197,94,0.2)",
    ))

    # Gap shading
    fig.add_trace(go.Scatter(
        x=pd.concat([re_df["year"], re_df["year"][::-1]]),
        y=pd.concat([re_df["expenditure"], re_df["revenue"][::-1]]),
        fill="toself",
        fillcolor="rgba(239,68,68,0.25)",
        line=dict(color="rgba(0,0,0,0)"),
        name="Deficit gap",
        showlegend=True,
    ))

    fig.update_layout(
        title=f"{focus_name} · Revenue vs. Expenditure (% GDP)",
        hovermode="x unified",
        plot_bgcolor="white",
        yaxis=dict(gridcolor="#eee", title="% of GDP"),
        xaxis=dict(title="Year"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    st.plotly_chart(fig, use_container_width=True)

    # Gap over time bar chart
    fig3 = px.bar(
        re_df, x="year", y="gap",
        color="gap",
        color_continuous_scale=["#ef4444", "#f97316", "#facc15", "#86efac", "#22c55e"],
        color_continuous_midpoint=0,
        labels={"gap": "Revenue − Expenditure (pp)", "year": "Year"},
        title=f"{focus_name} · Fiscal gap over time (positive = surplus, negative = deficit)",
    )
    fig3.add_hline(y=0, line_color="black", line_width=1)
    fig3.update_layout(coloraxis_showscale=False, plot_bgcolor="white", yaxis=dict(gridcolor="#eee"))
    st.plotly_chart(fig3, use_container_width=True)

    # Narrative
    trend_3y = re_df.sort_values("year")["gap"].iloc[-1] - re_df.sort_values("year")["gap"].iloc[-3] if len(re_df) >= 3 else None
    trend_text = ""
    if trend_3y is not None:
        if trend_3y > 0.5:
            trend_text = f"The fiscal gap has **improved by {trend_3y:.1f}pp** over the past 3 years."
        elif trend_3y < -0.5:
            trend_text = f"The fiscal gap has **deteriorated by {abs(trend_3y):.1f}pp** over the past 3 years."
        else:
            trend_text = "The fiscal gap has remained **broadly stable** over the past 3 years."

    if gap_val < 0:
        narrative = f"""
**{focus_name}** recorded a fiscal **{gap_label}** of **{abs(gap_val):.1f}% of GDP** in {int(latest['year'])}.  
Revenue stood at **{rev_val:.1f}% GDP**, while expenditure reached **{exp_val:.1f}% GDP** — a gap of **{abs(gap_val):.1f}pp**.  
{trend_text}
"""
    else:
        narrative = f"""
**{focus_name}** recorded a fiscal **{gap_label}** of **{gap_val:.1f}% of GDP** in {int(latest['year'])}.  
Revenue at **{rev_val:.1f}% GDP** exceeded expenditure of **{exp_val:.1f}% GDP**.  
{trend_text}
"""
    st.info(narrative)

    with st.expander("📄 Raw data"):
        st.dataframe(re_df.rename(columns={"year": "Year", "revenue": "Revenue (% GDP)",
                                            "expenditure": "Expenditure (% GDP)", "gap": "Gap (pp)"}),
                     use_container_width=True, hide_index=True)
        st.download_button("⬇ Download CSV", re_df.to_csv(index=False).encode(), f"{focus_geo}_rev_exp.csv", "text/csv")
