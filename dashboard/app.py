from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
from dotenv import load_dotenv

from asset_config import render_asset_sidebar
from data_fetcher import (
    load_asset_constraints,
    load_dispatch_schedule,
    load_gold_metrics,
    load_tennet_congestion,
)
from optimizer import simulate_commercial_dispatch

load_dotenv(override=True)

st.set_page_config(
    page_title="OptiGrid: Commercial Asset Energy & Carbon Dispatch",
    layout="wide",
    initial_sidebar_state="expanded",
)

BIDDING_ZONES = {
    "Netherlands (NL)": "10YNL----------L",
    "Germany-Luxembourg (DE-LU)": "10Y1001A1001A82H",
    "Poland (PL)": "10YPL-AREA-----S",
}


def render_dashboard():
    st.sidebar.title("OptiGrid Dispatch Console")
    zone_label = st.sidebar.selectbox("Bidding Zone", list(BIDDING_ZONES.keys()))
    zone_code = BIDDING_ZONES[zone_label]

    df_assets = load_asset_constraints(bidding_zone=zone_code)
    asset_config = render_asset_sidebar(df_assets, bidding_zone=zone_code)
    asset_id = asset_config.get("asset_id", "NL-AMS-DC01")
    default_alpha = float(asset_config.get("alpha_weight", 0.50))

    alpha = st.sidebar.slider(
        "Optimization Preference (Alpha)",
        min_value=0.0,
        max_value=1.0,
        value=default_alpha,
        step=0.05,
        help="0.0 = 100% Green (Minimize Carbon), 1.0 = 100% Cheapest (Maximize Arbitrage)",
    )

    today_iso = datetime.now(ZoneInfo("Europe/Amsterdam")).date().isoformat()
    df_metrics = load_gold_metrics(bidding_zone=zone_code, anchor_date_iso=today_iso)
    df_congestion = load_tennet_congestion(bidding_zone=zone_code)
    df_bq_schedule = load_dispatch_schedule(
        bidding_zone=zone_code,
        asset_id=asset_id,
        anchor_date_iso=today_iso,
    )

    source_df = df_metrics if not df_metrics.empty else df_bq_schedule
    dispatch_results = simulate_commercial_dispatch(
        df_metrics=source_df,
        asset_config=asset_config,
        alpha=alpha,
        df_congestion=df_congestion,
    )

    st.title("Commercial Facility Dispatch & Dynamic Energy Arbitrage")
    facility_name = asset_config.get("facility_name", "Commercial Facility")
    substation = asset_config.get("substation_area", "NL-RANDSTAD-NORTH")

    sol_kwp = asset_config.get("solar_kwp", 0)
    bess_kwh = asset_config.get("bess_capacity_kwh", 0)
    st.caption(
        f"**Facility:** {facility_name} (`{asset_id}`) | **Bidding Zone:** {zone_label} | "
        f"**Substation:** `{substation}` | **Solar:** {sol_kwp:.0f} kWp | "
        f"**BESS:** {bess_kwh:.0f} kWh"
    )

    is_cong = dispatch_results.get("is_congestion_active", False)
    exp_factor = dispatch_results.get("export_factor", 1.0)

    tso_name = "TenneT" if "NL" in zone_code else ("PSE" if "PL" in zone_code else "Regional Grid")
    if is_cong:
        st.error(
            f"⚠️ **{tso_name.upper()} CONGESTION ACTIVE ON SUBSTATION `{substation}`** | "
            f"Export capacity de-rated to **{exp_factor * 100:.0f}%** of nominal limit. "
            f"Automated BESS absorption & solar curtailment safeguards are active."
        )
    else:
        st.success(
            f"🟢 **{tso_name} Substation `{substation}`: Nominal Operating State** | "
            f"Grid feed-in unrestricted (Export factor: 100%). Curtailment triggers armed."
        )

    has_data = (
        dispatch_results
        and "df_schedule" in dispatch_results
        and not dispatch_results["df_schedule"].empty
    )
    if not has_data:
        st.warning("Awaiting day-ahead market settlement telemetry. Re-evaluating schedule...")
        return

    df_sched = dispatch_results["df_schedule"]

    st.markdown("### Facility Yield & Dispatch Performance (Next 24–36 Hours)")
    kpi1, kpi2, kpi3, kpi4 = st.columns(4)

    kpi1.metric(
        "Net Financial Yield",
        f"€{dispatch_results['net_financial_yield_eur']:.2f}",
        f"+{dispatch_results['cost_saving_pct']:.1f}% vs unmanaged",
        delta_color="normal",
    )
    carbon_pct = dispatch_results.get("carbon_saving_pct", dispatch_results["cost_saving_pct"])
    kpi2.metric(
        "Carbon Abated",
        f"{dispatch_results['total_carbon_avoided_kg']:.1f} kgCO₂",
        f"-{carbon_pct:.1f}% emissions",
        delta_color="normal",
    )
    kpi3.metric(
        "BESS Arbitrage Cycles",
        f"{dispatch_results['bess_cycles']:.2f} eq. cycles",
        f"Cap: {asset_config.get('bess_capacity_kwh', 0):.0f} kWh",
    )
    kpi4.metric(
        "Solar Curtailment Mitigated",
        f"{dispatch_results['curtailed_solar_kwh']:.1f} kWh",
        "TenneT & Negative Price Guard",
        delta_color="inverse" if dispatch_results["curtailed_solar_kwh"] > 0 else "off",
    )

    st.markdown("### Synchronized Grid Metrics & Commercial Dispatch Schedule")

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.10,
        subplot_titles=(
            "Day-Ahead Wholesale Price (€/kWh) & Grid Carbon Intensity (gCO₂/kWh)",
            "Battery Storage State-of-Charge (SoC %) & Net Dispatch Import/Export (kW)",
        ),
        specs=[[{"secondary_y": True}], [{"secondary_y": True}]],
    )

    fig.add_trace(
        go.Scatter(
            x=df_sched["local_datetime"],
            y=df_sched["price_eur_kwh"],
            name="Electricity Price (€/kWh)",
            line=dict(color="#2563EB", width=2.5),
        ),
        row=1,
        col=1,
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=df_sched["local_datetime"],
            y=df_sched["carbon_intensity_gco2_kwh"],
            name="Carbon Intensity (gCO₂/kWh)",
            line=dict(color="#DC2626", width=2.5, dash="dot"),
        ),
        row=1,
        col=1,
        secondary_y=True,
    )

    fig.add_trace(
        go.Scatter(
            x=df_sched["local_datetime"],
            y=df_sched["bess_soc_pct"],
            name="BESS SoC (%)",
            line=dict(color="#8B5CF6", width=3),
            fill="tozeroy",
        ),
        row=2,
        col=1,
        secondary_y=False,
    )
    fig.add_trace(
        go.Bar(
            x=df_sched["local_datetime"],
            y=df_sched["net_grid_import_kw"],
            name="Net Grid Import (+) / Export (-) (kW)",
            marker_color="rgba(16, 185, 129, 0.45)",
        ),
        row=2,
        col=1,
        secondary_y=True,
    )

    for _, row in df_sched.iterrows():
        act = row["dispatch_action"]
        t_start = row["local_datetime"]
        t_end = t_start + pd.Timedelta(hours=1)

        if act == "CHARGE_BATTERY":
            fig.add_vrect(
                x0=t_start,
                x1=t_end,
                fillcolor="rgba(16, 185, 129, 0.18)",
                layer="below",
                line_width=0,
                row=1,
                col=1,
            )
        elif act == "DISCHARGE_BATTERY":
            fig.add_vrect(
                x0=t_start,
                x1=t_end,
                fillcolor="rgba(139, 92, 246, 0.18)",
                layer="below",
                line_width=0,
                row=1,
                col=1,
            )
        elif act == "CURTAIL_SOLAR":
            fig.add_vrect(
                x0=t_start,
                x1=t_end,
                fillcolor="rgba(239, 68, 68, 0.22)",
                layer="below",
                line_width=0,
                row=1,
                col=1,
            )

    fig.update_layout(
        height=680,
        hovermode="x unified",
        template="plotly_white",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    st.plotly_chart(fig, width="stretch")

    st.markdown("### Actionable Hourly Dispatch Ledger")
    display_cols = [
        "local_datetime",
        "price_eur_kwh",
        "carbon_intensity_gco2_kwh",
        "estimated_solar_kw",
        "bess_power_kw",
        "bess_soc_pct",
        "curtailed_solar_kw",
        "dispatch_action",
        "cost_saving_eur",
    ]

    ledger_df = df_sched[display_cols].copy()
    ledger_df["local_datetime"] = ledger_df["local_datetime"].dt.strftime("%Y-%m-%d %H:%M")
    ledger_df.columns = [
        "Time (Local)",
        "Price (€/kWh)",
        "Carbon (g/kWh)",
        "Solar Gen (kW)",
        "BESS Power (kW)",
        "BESS SoC (%)",
        "Curtailed (kW)",
        "Action Flag",
        "Cost Delta (€)",
    ]

    st.dataframe(ledger_df, width="stretch", height=360)


if __name__ == "__main__":
    render_dashboard()
