import requests
import pandas as pd
import numpy as np
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
def get_latest_available_year(dataset, na_item, unit, geo="FI"):
    """Find the latest year with actual data in Eurostat."""
    try:
        js = fetch(dataset, {"unit": unit, "sector": "S13", "na_item": na_item,
                             "geo": geo, "sinceTimePeriod": "2020"})
        df = eurostat_to_long(js)
        df = df[["time", "value"]].dropna()
        df["time"] = df["time"].astype(int)
        if not df.empty:
            return int(df["time"].max())
    except Exception:
        pass
    return 2023  # fallback

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
                                          "geo": geo, "sinceTimePeriod": "2018"})
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

def debt_trajectory(d0, primary_balance, r, g, years=12):
    """Simulate debt-to-GDP ratio: Δd = (r-g)/(1+g) * d + primary_deficit"""
    trajectory = [d0]
    d = d0
    for _ in range(years):
        d = ((1 + r/100) / (1 + g/100)) * d - primary_balance
        trajectory.append(d)
    return trajectory

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

def generate_analytical_narrative(focus_name, gap_val, rev_val, exp_val, latest_year, re_df, debt):
    lines = []
    deficit_threshold = -3.0
    breach = gap_val - deficit_threshold

    if gap_val >= 0:
        lines.append(f"**{focus_name}** recorded a fiscal **surplus of {gap_val:.1f}% GDP** in {int(latest_year)}, "
                     f"with revenue ({rev_val:.1f}%) exceeding expenditure ({exp_val:.1f}%).")
    elif gap_val > deficit_threshold:
        lines.append(f"**{focus_name}** recorded a fiscal **deficit of {abs(gap_val):.1f}% GDP** in {int(latest_year)} "
                     f"(revenue: {rev_val:.1f}%, expenditure: {exp_val:.1f}%). "
                     f"✅ This remains within the EU's 3% SGP threshold.")
    else:
        lines.append(f"**{focus_name}** recorded a fiscal **deficit of {abs(gap_val):.1f}% GDP** in {int(latest_year)} "
                     f"(revenue: {rev_val:.1f}%, expenditure: {exp_val:.1f}%). "
                     f"❌ This **exceeds the EU's 3% SGP threshold by {abs(breach):.1f} percentage points**.")

    if len(re_df) >= 4:
        sorted_df = re_df.sort_values("year")
        change_3y = sorted_df["gap"].iloc[-1] - sorted_df["gap"].iloc[-3]
        years_in_deficit = (sorted_df["gap"] < -3).sum()
        total_years = len(sorted_df)

        if gap_val < -3 and years_in_deficit >= 3:
            lines.append(f"⚠️ **Persistent breach:** The deficit has exceeded 3% in {years_in_deficit} of "
                         f"the last {total_years} years — indicating a **structural, not cyclical**, fiscal problem.")
        elif change_3y > 1.0:
            lines.append(f"📈 **Improving trend:** The fiscal gap improved by **{change_3y:.1f}pp** over 3 years — active consolidation visible.")
        elif change_3y < -1.0:
            lines.append(f"📉 **Deteriorating trend:** The fiscal gap worsened by **{abs(change_3y):.1f}pp** over 3 years — no consolidation visible.")
        else:
            if gap_val < -3:
                lines.append("🔴 **No consolidation trend:** Deficit persistently above 3% with no meaningful improvement.")
            else:
                lines.append("→ The fiscal position has remained broadly stable over the past 3 years.")

    if debt is not None and gap_val < 0:
        if gap_val < -3:
            lines.append(f"💰 **Debt implication:** At this deficit level, **debt-to-GDP is likely rising** "
                         f"unless nominal GDP growth offsets it. Current debt: **{debt:.1f}% GDP** "
                         f"({'above' if debt > 60 else 'below'} the 60% SGP reference).")
        else:
            lines.append(f"💰 Current gross debt stands at **{debt:.1f}% GDP** "
                         f"({'above' if debt > 60 else 'below'} the 60% SGP reference).")

    if gap_val < deficit_threshold:
        required = abs(gap_val - deficit_threshold)
        lines.append(f"🎯 **Required adjustment:** {focus_name} needs to improve its fiscal balance by "
                     f"**{required:.1f}pp of GDP** to return to SGP compliance.")

    return "\n\n".join(lines)

@st.cache_data(show_spinner=False, ttl=3600)
def load_all_countries_dsa(r=3.5, g=1.5):
    """Run DSA model for all EU countries and return sustainability ranking."""
    results = []
    for geo, country in EU_COUNTRIES.items():
        try:
            # Debt
            js = fetch("gov_10dd_edpt1", {"unit": "PC_GDP", "sector": "S13", "na_item": "GD",
                                           "geo": geo, "sinceTimePeriod": "2020"})
            df = eurostat_to_long(js)
            df = df[df["geo"] == geo][["time", "value"]].dropna()
            df["time"] = df["time"].astype(int)
            df = df.sort_values("time")
            if df.empty:
                continue
            debt = df["value"].iloc[-1]
            debt_year = df["time"].iloc[-1]

            # Deficit
            js2 = fetch("gov_10dd_edpt1", {"unit": "PC_GDP", "sector": "S13", "na_item": "B9",
                                            "geo": geo, "sinceTimePeriod": "2020"})
            df2 = eurostat_to_long(js2)
            df2 = df2[df2["geo"] == geo][["time", "value"]].dropna()
            df2["time"] = df2["time"].astype(int)
            df2 = df2.sort_values("time")
            if df2.empty:
                continue
            deficit = df2["value"].iloc[-1]

            # Primary balance estimate
            approx_interest = 0.02 * debt
            pb = deficit + approx_interest

            # DSA
            rg = r - g
            pb_star = ((r/100 - g/100) / (1 + g/100)) * debt
            gap = pb - pb_star

            # 12-year trajectory
            traj = [debt]
            d = debt
            for _ in range(12):
                d = ((1 + r/100) / (1 + g/100)) * d - pb
                traj.append(d)
            end_debt = traj[-1]
            delta = end_debt - debt

            # Risk classification
            if gap >= 0 and end_debt < 60:
                risk = "Stable"
                risk_order = 1
            elif gap >= 0 or delta < 5:
                risk = "At risk"
                risk_order = 2
            elif delta < 20:
                risk = "Unsustainable"
                risk_order = 3
            else:
                risk = "Explosive"
                risk_order = 4

            results.append({
                "geo": geo,
                "Country": country,
                "Debt (% GDP)": round(debt, 1),
                "Deficit (% GDP)": round(deficit, 1),
                "Primary balance": round(pb, 1),
                "pb* (stabilising)": round(pb_star, 1),
                "Gap (pp)": round(gap, 1),
                "Debt 2035 (projected)": round(end_debt, 1),
                "Δ debt": round(delta, 1),
                "r−g": round(rg, 1),
                "Risk": risk,
                "risk_order": risk_order,
                "year": debt_year,
            })
        except Exception:
            continue
    return pd.DataFrame(results).sort_values(["risk_order", "Debt (% GDP)"], ascending=[True, False])

# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/b/b7/Flag_of_Europe.svg", width=80)
    st.title("EU Fiscal Dashboard")
    st.caption("Data: Eurostat")

    page = st.radio("View", ["📊 Overview", "🔍 Deficit Decomposition", "📐 Debt Sustainability", "🌍 EU Sustainability Ranking"])

    country_options = [f"{k} – {v}" for k, v in EU_COUNTRIES.items()]
    default_display = [f"{k} – {EU_COUNTRIES[k]}" for k in DEFAULT_COUNTRIES]
    selected_display = st.multiselect("Countries", country_options, default=default_display)
    selected_geos = tuple(s.split(" – ")[0] for s in selected_display)

    # Dynamically find latest available year
    latest_year_debt = get_latest_available_year("gov_10dd_edpt1", "GD", "PC_GDP")
    latest_year_revexp = get_latest_available_year("gov_10a_main", "TR", "PC_GDP")
    latest_available = min(latest_year_debt, latest_year_revexp)
    st.caption(f"Latest available data: **{latest_available}**")
    year_from, year_to = st.slider("Year range", 2000, latest_available, (2010, latest_available))

    if page == "📊 Overview":
        selected_indicator = st.selectbox("Indicator", list(INDICATORS.keys()))

    st.divider()
    st.markdown("Built with [Streamlit](https://streamlit.io) · [Source](https://github.com/jussinasi/eu-fiscal-analysis)")

# ── Main ───────────────────────────────────────────────────────────────────────
st.title("🇪🇺 EU Fiscal Analysis")

if not selected_geos:
    st.warning("Select at least one country from the sidebar.")
    st.stop()

# ── Fiscal Health Cards ────────────────────────────────────────────────────────
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
elif page == "🌍 EU Sustainability Ranking":
# ══════════════════════════════════════════════════════════════════════════════
    st.subheader("EU Debt Sustainability Ranking")
    st.caption("All 27 EU member states · DSA model · Assumptions: r = 3.5%, g = 1.5%")

    col_r, col_g, _ = st.columns([1, 1, 3])
    with col_r:
        r_all = st.slider("Interest rate r (%)", 0.0, 8.0, 3.5, 0.1, key="r_all")
    with col_g:
        g_all = st.slider("GDP growth g (%)", -2.0, 6.0, 1.5, 0.1, key="g_all")

    with st.spinner("Running DSA model for all 27 EU countries…"):
        ranking_df = load_all_countries_dsa(r_all, g_all)

    if ranking_df.empty:
        st.error("Could not load data.")
        st.stop()

    # Summary metrics
    n_stable      = (ranking_df["Risk"] == "Stable").sum()
    n_risk        = (ranking_df["Risk"] == "At risk").sum()
    n_unsust      = (ranking_df["Risk"] == "Unsustainable").sum()
    n_explosive   = (ranking_df["Risk"] == "Explosive").sum()

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("🟢 Stable",        n_stable)
    m2.metric("🟡 At risk",       n_risk)
    m3.metric("🔴 Unsustainable",  n_unsust)
    m4.metric("🔥 Explosive",     n_explosive)

    st.divider()

    # Ensure size column is positive for bubble chart
    ranking_df["bubble_size"] = ranking_df["Debt 2035 (projected)"].clip(lower=1)

    # Bubble chart: debt vs deficit, sized by projected 2035 debt
    fig = px.scatter(
        ranking_df,
        x="Deficit (% GDP)", y="Debt (% GDP)",
        size="bubble_size", color="Risk",
        text="geo",
        color_discrete_map={
            "Stable": "#16a34a",
            "At risk": "#d97706",
            "Unsustainable": "#dc2626",
            "Explosive": "#7c2d12",
        },
        hover_data={"Country": True, "Debt (% GDP)": True, "Deficit (% GDP)": True,
                    "Debt 2035 (projected)": True, "Gap (pp)": True},
        title="EU Fiscal Sustainability Map · Debt vs. Deficit (bubble = projected 2035 debt)",
        size_max=60,
    )
    fig.add_vline(x=-3, line_dash="dash", line_color="red", line_width=1,
                  annotation_text="SGP: −3%", annotation_position="top right")
    fig.add_hline(y=60, line_dash="dash", line_color="red", line_width=1,
                  annotation_text="SGP: 60%", annotation_position="bottom right")
    fig.update_traces(textposition="top center", textfont_size=10)
    fig.update_layout(plot_bgcolor="white", yaxis=dict(gridcolor="#eee"),
                      xaxis=dict(gridcolor="#eee"))
    st.plotly_chart(fig, use_container_width=True)

    # Bar chart: projected debt change
    fig2 = px.bar(
        ranking_df.sort_values("Δ debt", ascending=False),
        x="Country", y="Δ debt", color="Risk",
        color_discrete_map={
            "Stable": "#16a34a",
            "At risk": "#d97706",
            "Unsustainable": "#dc2626",
            "Explosive": "#7c2d12",
        },
        labels={"Δ debt": "Projected debt change 2023–2035 (pp)", "Country": ""},
        title="Projected change in debt-to-GDP by 2035",
    )
    fig2.add_hline(y=0, line_color="black", line_width=1)
    fig2.update_layout(plot_bgcolor="white", yaxis=dict(gridcolor="#eee"), showlegend=False)
    st.plotly_chart(fig2, use_container_width=True)

    # Full ranking table
    st.subheader("Full ranking")
    display_cols = ["Country", "Risk", "Debt (% GDP)", "Deficit (% GDP)",
                    "pb* (stabilising)", "Gap (pp)", "Debt 2035 (projected)", "Δ debt"]
    st.dataframe(
        ranking_df[display_cols].reset_index(drop=True),
        use_container_width=True, hide_index=True,
        column_config={
            "Gap (pp)": st.column_config.NumberColumn(help="Primary balance minus stabilising pb*. Positive = sustainable."),
            "Δ debt": st.column_config.NumberColumn(help="Projected debt change by 2035 (pp of GDP)"),
        }
    )

    # Narrative
    st.divider()
    worst = ranking_df[ranking_df["risk_order"] == ranking_df["risk_order"].max()].head(3)["Country"].tolist()
    best  = ranking_df[ranking_df["risk_order"] == 1].head(3)["Country"].tolist()
    st.info(
        f"**Under current assumptions (r={r_all}%, g={g_all}%):** "
        f"{n_stable} EU countries are on a stable debt path, while {n_unsust + n_explosive} face unsustainable dynamics. "
        f"Most at risk: **{', '.join(worst)}**. "
        f"Most stable: **{', '.join(best) if best else 'none'}**. "
        f"Adjust the r and g sliders above to model different macroeconomic environments."
    )

    with st.expander("📄 Full data"):
        st.download_button("⬇ Download CSV", ranking_df.to_csv(index=False).encode(),
                           "eu_sustainability_ranking.csv", "text/csv")

# ══════════════════════════════════════════════════════════════════════════════
elif page == "🔍 Deficit Decomposition":
# ══════════════════════════════════════════════════════════════════════════════
    st.subheader("Where does the deficit come from?")
    st.caption("Revenue vs. expenditure gap · % of GDP · General government")

    focus_options = [f"{k} – {EU_COUNTRIES[k]}" for k in selected_geos if k in EU_COUNTRIES]
    focus_display = st.selectbox("Focus country", focus_options)
    focus_geo = focus_display.split(" – ")[0]
    focus_name = EU_COUNTRIES.get(focus_geo, focus_geo)

    with st.spinner(f"Loading data for {focus_name}…"):
        re_df = load_rev_exp(focus_geo, year_from, year_to)
        health = load_fiscal_health(focus_geo)

    if re_df.empty:
        st.error("No data available for this country/period.")
        st.stop()

    latest = re_df[re_df["year"] == re_df["year"].max()].iloc[0]
    rev_val, exp_val, gap_val, latest_year = latest["revenue"], latest["expenditure"], latest["gap"], latest["year"]
    debt = health["debt"]

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Revenue", f"{rev_val:.1f}% GDP")
    m2.metric("Expenditure", f"{exp_val:.1f}% GDP")
    m3.metric("Fiscal balance", f"{gap_val:+.1f}% GDP")
    if gap_val < -3:
        m4.metric("Required adjustment", f"+{abs(gap_val+3):.1f}pp", delta="to reach SGP −3%", delta_color="off")
    elif debt is not None:
        m4.metric("Gross debt", f"{debt:.1f}% GDP",
                  delta="above 60% SGP" if debt > 60 else "below 60% SGP",
                  delta_color="inverse" if debt > 60 else "normal")

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=re_df["year"], y=re_df["expenditure"], name="Expenditure",
                             fill="tozeroy", line=dict(color="#ef4444", width=2), fillcolor="rgba(239,68,68,0.12)"))
    fig.add_trace(go.Scatter(x=re_df["year"], y=re_df["revenue"], name="Revenue",
                             fill="tozeroy", line=dict(color="#22c55e", width=2), fillcolor="rgba(34,197,94,0.18)"))
    fig.add_trace(go.Scatter(
        x=pd.concat([re_df["year"], re_df["year"][::-1]]),
        y=pd.concat([re_df["expenditure"], re_df["revenue"][::-1]]),
        fill="toself", fillcolor="rgba(239,68,68,0.22)",
        line=dict(color="rgba(0,0,0,0)"), name="Deficit gap"))
    fig.update_layout(title=f"{focus_name} · Revenue vs. Expenditure (% GDP)",
                      hovermode="x unified", plot_bgcolor="white",
                      yaxis=dict(gridcolor="#eee", title="% of GDP"), xaxis=dict(title="Year"),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
    st.plotly_chart(fig, use_container_width=True)

    fig3 = px.bar(re_df, x="year", y="gap", color="gap",
                  color_continuous_scale=["#dc2626", "#f97316", "#facc15", "#86efac", "#16a34a"],
                  color_continuous_midpoint=0,
                  labels={"gap": "Revenue − Expenditure (pp)", "year": "Year"},
                  title=f"{focus_name} · Fiscal balance over time")
    fig3.add_hline(y=0, line_color="#1e293b", line_width=1)
    fig3.add_hline(y=-3, line_dash="dash", line_color="red", line_width=1.5,
                   annotation_text="SGP limit: −3%", annotation_position="bottom right")
    fig3.update_layout(coloraxis_showscale=False, plot_bgcolor="white", yaxis=dict(gridcolor="#eee"))
    st.plotly_chart(fig3, use_container_width=True)

    narrative = generate_analytical_narrative(focus_name, gap_val, rev_val, exp_val, latest_year, re_df, debt)
    if gap_val < -3:
        st.error(narrative)
    elif gap_val < 0:
        st.warning(narrative)
    else:
        st.success(narrative)

    with st.expander("📄 Raw data"):
        st.dataframe(re_df.rename(columns={"year": "Year", "revenue": "Revenue (% GDP)",
                                            "expenditure": "Expenditure (% GDP)", "gap": "Gap (pp)"}),
                     use_container_width=True, hide_index=True)
        st.download_button("⬇ Download CSV", re_df.to_csv(index=False).encode(), f"{focus_geo}_rev_exp.csv", "text/csv")

# ══════════════════════════════════════════════════════════════════════════════
elif page == "📐 Debt Sustainability":
# ══════════════════════════════════════════════════════════════════════════════
    st.subheader("Is the debt trajectory sustainable?")
    st.caption("Debt dynamics model: Δd ≈ (r − g) · d + primary deficit · General government")

    focus_options = [f"{k} – {EU_COUNTRIES[k]}" for k in selected_geos if k in EU_COUNTRIES]
    focus_display = st.selectbox("Focus country", focus_options)
    focus_geo = focus_display.split(" – ")[0]
    focus_name = EU_COUNTRIES.get(focus_geo, focus_geo)

    with st.spinner(f"Loading fiscal data for {focus_name}…"):
        health = load_fiscal_health(focus_geo)

    debt0 = health["debt"]
    deficit0 = health["deficit"]

    if debt0 is None:
        st.error("No debt data available for this country.")
        st.stop()

    # Estimate primary balance: deficit - interest payments (approx 2% of debt as interest)
    approx_interest = 0.02 * debt0
    primary0 = (deficit0 if deficit0 is not None else -3.0) + approx_interest

    st.markdown(f"**Starting point (2023):** Gross debt **{debt0:.1f}% GDP** · "
                f"Budget balance **{deficit0:.1f}% GDP**" if deficit0 else f"**Starting point (2023):** Gross debt **{debt0:.1f}% GDP**")

    # Default values based on actual data
    r_default  = 3.5
    g_default  = 1.5
    pb_default = round(float(primary0), 1) if primary0 else -1.0
    pb_default = max(-6.0, min(4.0, pb_default))

    # Reset button
    st.markdown("#### Scenario parameters")
    reset_col, _ = st.columns([1, 4])
    with reset_col:
        if st.button("↺ Reset to current values"):
            for k, v in [
                ("r_base", r_default), ("g_base", g_default), ("pb_base", pb_default),
                ("r_stress", min(r_default+1.5, 8.0)), ("g_stress", max(g_default-1.0, -2.0)),
                ("pb_stress", max(-6.0, pb_default-1.0)),
                ("r_cons", r_default), ("g_cons", g_default), ("pb_cons", min(pb_default+2.0, 4.0)),
            ]:
                st.session_state[k] = v

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**Baseline**")
        r_base   = st.slider("Interest rate r (%)", 0.0, 8.0, r_default, 0.1, key="r_base")
        g_base   = st.slider("GDP growth g (%)", -2.0, 6.0, g_default, 0.1, key="g_base")
        pb_base  = st.slider("Primary balance (% GDP)", -6.0, 4.0, pb_default, 0.1, key="pb_base")
    with col_b:
        st.markdown("**Stress scenario**")
        r_stress  = st.slider("Interest rate r (%)", 0.0, 8.0, min(r_default+1.5, 8.0), 0.1, key="r_stress")
        g_stress  = st.slider("GDP growth g (%)", -2.0, 6.0, max(g_default-1.0, -2.0), 0.1, key="g_stress")
        pb_stress = st.slider("Primary balance (% GDP)", -6.0, 4.0, max(-6.0, pb_default-1.0), 0.1, key="pb_stress")

    st.markdown("**Consolidation scenario**")
    col_c1, col_c2, col_c3 = st.columns(3)
    with col_c1:
        r_cons  = st.slider("Interest rate r (%)", 0.0, 8.0, r_default, 0.1, key="r_cons")
    with col_c2:
        g_cons  = st.slider("GDP growth g (%)", -2.0, 6.0, g_default, 0.1, key="g_cons")
    with col_c3:
        pb_cons = st.slider("Primary balance (% GDP)", -6.0, 4.0, min(pb_default+2.0, 4.0), 0.1, key="pb_cons")

    # Simulate trajectories
    years = list(range(2023, 2036))
    traj_base   = debt_trajectory(debt0, pb_base,   r_base,   g_base)
    traj_stress = debt_trajectory(debt0, pb_stress, r_stress, g_stress)
    traj_cons   = debt_trajectory(debt0, pb_cons,   r_cons,   g_cons)

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=years, y=traj_base, name="Baseline",
                             line=dict(color="#3b82f6", width=2.5), mode="lines+markers"))
    fig.add_trace(go.Scatter(x=years, y=traj_stress, name="Stress",
                             line=dict(color="#ef4444", width=2, dash="dash"), mode="lines+markers"))
    fig.add_trace(go.Scatter(x=years, y=traj_cons, name="Consolidation",
                             line=dict(color="#22c55e", width=2, dash="dot"), mode="lines+markers"))
    fig.add_hline(y=60, line_dash="dash", line_color="red", line_width=1.5,
                  annotation_text="SGP limit: 60%", annotation_position="bottom right")
    fig.update_layout(
        title=f"{focus_name} · Debt-to-GDP trajectory 2023–2035",
        hovermode="x unified", plot_bgcolor="white",
        yaxis=dict(gridcolor="#eee", title="Gross debt (% GDP)"),
        xaxis=dict(title="Year", dtick=1),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
    st.plotly_chart(fig, use_container_width=True)

    # Verdict
    end_base   = traj_base[-1]
    end_stress = traj_stress[-1]
    end_cons   = traj_cons[-1]
    rg_base    = r_base - g_base

    # Required primary balance for stabilisation: pb* = (r-g)/(1+g) * debt
    def required_pb(r, g, debt):
        return ((r/100 - g/100) / (1 + g/100)) * debt

    pb_star_base   = required_pb(r_base,   g_base,   debt0)
    pb_star_stress = required_pb(r_stress, g_stress, debt0)
    pb_star_cons   = required_pb(r_cons,   g_cons,   debt0)
    gap_base       = pb_base   - pb_star_base
    gap_stress     = pb_stress - pb_star_stress
    gap_cons       = pb_cons   - pb_star_cons

    def verdict_label(end_val, rg, pb_gap):
        if pb_gap >= 0 and end_val < 60:
            return "✅ Stabilising", "#1a7f37", "#f0fdf4", "#86efac"
        elif pb_gap >= -1 or end_val < 70:
            return "⚠️ At risk", "#92400e", "#fffbeb", "#fcd34d"
        else:
            return "❌ Unsustainable", "#b91c1c", "#fef2f2", "#fca5a5"

    def verdict_card(label, end_val, start_val, rg, pb_current, pb_star, pb_gap):
        direction = "📈 Rising" if end_val > start_val + 1 else ("📉 Falling" if end_val < start_val - 1 else "→ Stable")
        vl, vc, bg, bc = verdict_label(end_val, rg, pb_gap)
        above60 = end_val > 60
        cons_note = f"Debt {'remains above' if above60 else 'falls below'} 60% SGP threshold by 2035."
        st.markdown(f"""
        <div style="background:{bg};border:1.5px solid {bc};border-radius:10px;padding:14px 18px;text-align:center;">
            <div style="font-size:0.8em;color:#64748b;text-transform:uppercase;letter-spacing:.05em;">{label}</div>
            <div style="font-size:1.8em;font-weight:800;color:{vc};">{end_val:.1f}%</div>
            <div style="font-size:0.82em;color:#475569;">by 2035 · {direction}</div>
            <div style="font-size:0.9em;font-weight:700;color:{vc};margin:6px 0 4px 0;">{vl}</div>
            <div style="font-size:0.75em;color:#64748b;">r−g = {rg:+.1f}pp</div>
            <div style="font-size:0.75em;color:#64748b;">Stabilising pb*: {pb_star:+.1f}% GDP</div>
            <div style="font-size:0.75em;color:#64748b;">Current pb: {pb_current:+.1f}% → gap: {pb_gap:+.1f}pp</div>
            <div style="font-size:0.72em;color:#94a3b8;margin-top:4px;">{cons_note}</div>
        </div>""", unsafe_allow_html=True)

    st.markdown("#### Sustainability verdict")
    v1, v2, v3 = st.columns(3)
    with v1:
        verdict_card("Baseline", end_base, debt0, r_base-g_base, pb_base, pb_star_base, gap_base)
    with v2:
        verdict_card("Stress", end_stress, debt0, r_stress-g_stress, pb_stress, pb_star_stress, gap_stress)
    with v3:
        verdict_card("Consolidation", end_cons, debt0, r_cons-g_cons, pb_cons, pb_star_cons, gap_cons)

    # Key takeaway
    st.markdown("---")
    vl_base, _, _, _ = verdict_label(end_base, r_base - g_base, gap_base)
    why = f"This is driven by a {'persistent primary deficit' if pb_base < 0 else 'primary surplus insufficient to offset r−g dynamics'} and r > g." if r_base > g_base else "The favourable r−g differential helps contain debt dynamics."

    if gap_base < -1 and end_base > 60:
        st.error(
            f"**Key takeaway:** {focus_name}'s debt is on an **unfavourable upward trajectory** under current policies, "
            f"rising from **{debt0:.1f}%** to **{end_base:.1f}% GDP** by 2035. {why} "
            f"Stabilising debt would require a primary balance of **{pb_star_base:+.1f}% GDP** — "
            f"an adjustment of **{abs(gap_base):.1f}pp** from the current **{pb_base:+.1f}%**."
        )
    elif end_base > debt0 + 5:
        st.warning(
            f"**Key takeaway:** {focus_name}'s debt is **rising but not on an explosive path**, "
            f"projected at **{end_base:.1f}% GDP** by 2035. {why} "
            f"Stabilisation requires a primary balance of **{pb_star_base:+.1f}% GDP** "
            f"(current gap: **{abs(gap_base):.1f}pp**)."
        )
    else:
        st.success(
            f"**Key takeaway:** {focus_name}'s debt trajectory is **broadly sustainable** under baseline assumptions, "
            f"projected at **{end_base:.1f}% GDP** by 2035. {why} "
            f"The stabilising primary balance is **{pb_star_base:+.1f}% GDP** — "
            f"{'currently met' if gap_base >= 0 else f'a gap of {abs(gap_base):.1f}pp remains'}."
        )
