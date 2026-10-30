import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv
from plotly.subplots import make_subplots

from asset_config import render_asset_sidebar
from data_fetcher import (
    load_asset_constraints,
    load_dispatch_schedule,
    load_forecast_accuracy,
    load_gold_metrics,
    load_tennet_congestion,
)
from optimizer import (
    DEFAULT_MARGINAL_CYCLE_COST_EUR_KWH,
    compute_pareto_frontier,
    simulate_commercial_dispatch,
)

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


def _parse_custom_load_upload(uploaded_file, default_base_kw: float) -> dict:
    try:
        name = uploaded_file.name.lower()
        if name.endswith(".json"):
            payload = json.load(uploaded_file)
            if isinstance(payload, dict):
                return {int(k) % 24: float(v) for k, v in payload.items()}
            if isinstance(payload, list):
                return {
                    int(item.get("hour", idx)) % 24: float(
                        item.get("load_kw", item.get("baseline_load_kw", default_base_kw))
                    )
                    for idx, item in enumerate(payload)
                }
        else:
            df_up = pd.read_csv(uploaded_file)
            hour_col = next(
                (c for c in df_up.columns if "hour" in c.lower()),
                df_up.columns[0],
            )
            load_col = next(
                (c for c in df_up.columns if "kw" in c.lower() or "load" in c.lower()),
                df_up.columns[-1],
            )
            return {
                int(row[hour_col]) % 24: float(row[load_col])
                for _, row in df_up.iterrows()
            }
    except Exception as exc:
        st.sidebar.warning(f"Could not parse custom load curve: {exc}")
    return {}


def _build_modbus_json_payload(df_sched: pd.DataFrame, asset_id: str, zone_code: str) -> str:
    setpoints = []
    for _, row in df_sched.iterrows():
        bess_kw = float(row["bess_power_kw"])
        ts_val = row["timestamp_utc"]
        ts_iso = ts_val.isoformat() if hasattr(ts_val, "isoformat") else str(ts_val)
        setpoints.append(
            {
                "timestamp_utc": ts_iso,
                "dispatch_action": str(row["dispatch_action"]),
                "CHARGE_KW": round(max(0.0, bess_kw), 2),
                "DISCHARGE_KW": round(max(0.0, -bess_kw), 2),
                "EXPORT_LIMIT_KW": round(float(row["effective_export_limit_kw"]), 2),
                "FLEX_LOAD_SETPOINT_KW": round(float(row["flex_load_kw"]), 2),
                "CURTAIL_SOLAR_KW": round(float(row["curtailed_solar_kw"]), 2),
            }
        )
    payload = {
        "schema_version": "optigrid-bms-v2.0",
        "asset_id": asset_id,
        "bidding_zone": zone_code,
        "generated_at_utc": datetime.now(ZoneInfo("UTC")).isoformat(),
        "setpoints": setpoints,
    }
    return json.dumps(payload, indent=2)


def render_dashboard():
    st.sidebar.title("OptiGrid Dispatch Console")
    zone_label = st.sidebar.selectbox("Bidding Zone", list(BIDDING_ZONES.keys()))
    zone_code = BIDDING_ZONES[zone_label]

    df_assets = load_asset_constraints(bidding_zone=zone_code)
    asset_config = render_asset_sidebar(df_assets, bidding_zone=zone_code)
    asset_id = asset_config.get("asset_id", "NL-AMS-DC01")
    default_alpha = float(asset_config.get("alpha_weight", 0.50))

    st.sidebar.subheader("Optimization & Wear Cost")
    pricing_mode = st.sidebar.radio(
        "Carbon Valuation Mode",
        ["Pareto Weight (α)", "Internal Carbon Tax (€/tCO₂)"],
        horizontal=False,
    )

    if pricing_mode == "Pareto Weight (α)":
        alpha = st.sidebar.slider(
            "Optimization Preference (Alpha)",
            min_value=0.0,
            max_value=1.0,
            value=default_alpha,
            step=0.05,
            help="0.0 = 100% Green (Minimize Carbon), 1.0 = 100% Cheapest (Maximize Arbitrage)",
        )
        implied_shadow_eur = round((1.0 - alpha) / max(alpha, 0.05) * 65.0, 1)
        st.sidebar.caption(
            f"Implied Shadow Carbon Price: **€{implied_shadow_eur:.1f} / tCO₂** (EU ETS ref: €65/t)"
        )
        asset_config.pop("shadow_carbon_eur_tco2", None)
    else:
        shadow_tax = st.sidebar.slider(
            "Internal Carbon Tax (€/tCO₂)",
            min_value=0.0,
            max_value=250.0,
            value=65.0,
            step=5.0,
            help="EU ETS benchmark ~65 €/tCO₂. Directly monetizes hourly Scope 2 emissions in the LP objective.",
        )
        alpha = round(float(1.0 / (1.0 + (shadow_tax / 65.0))), 2)
        asset_config["shadow_carbon_eur_tco2"] = float(shadow_tax)
        st.sidebar.caption(f"Equivalent Pareto Weight: **α = {alpha:.2f}**")

    marginal_cycle_cost = st.sidebar.slider(
        "BESS Cell Degradation Cost (€/kWh Cycled)",
        min_value=0.00,
        max_value=0.08,
        value=float(
            asset_config.get(
                "marginal_cycle_cost_eur_kwh", DEFAULT_MARGINAL_CYCLE_COST_EUR_KWH
            )
        ),
        step=0.005,
        help="Amortized LiFePO4 battery wear cost (typically 0.02–0.04 €/kWh cycled). Prevents unprofitable micro-cycling.",
    )
    asset_config["marginal_cycle_cost_eur_kwh"] = marginal_cycle_cost

    with st.sidebar.expander("Custom 24h Load Profile (CSV / JSON)"):
        uploaded_curve = st.file_uploader(
            "Upload 24h Load Curve (.csv / .json)",
            type=["csv", "json"],
            help="Columns: hour (0-23), load_kw",
        )
        base_kw_default = float(asset_config.get("baseline_load_kw", 300.0))
        if uploaded_curve is not None:
            parsed_map = _parse_custom_load_upload(uploaded_curve, base_kw_default)
            if parsed_map:
                asset_config["custom_load_profile_kw"] = parsed_map
                st.success(f"Applied custom 24h load profile ({len(parsed_map)} hours)")

        enable_interactive_curve = st.checkbox("Edit 24h Baseline Curve Interactively")
        if enable_interactive_curve:
            default_curve_df = pd.DataFrame(
                {
                    "hour": list(range(24)),
                    "load_kw": [
                        float(
                            asset_config.get("custom_load_profile_kw", {}).get(
                                h, base_kw_default
                            )
                        )
                        for h in range(24)
                    ],
                }
            )
            edited_curve_df = st.data_editor(
                default_curve_df,
                hide_index=True,
                height=220,
                key="custom_24h_curve_editor",
            )
            asset_config["custom_load_profile_kw"] = {
                int(r["hour"]) % 24: float(r["load_kw"])
                for _, r in edited_curve_df.iterrows()
            }

    today_iso = datetime.now(ZoneInfo("Europe/Amsterdam")).date().isoformat()
    df_metrics = load_gold_metrics(bidding_zone=zone_code, anchor_date_iso=today_iso)
    df_congestion = load_tennet_congestion(bidding_zone=zone_code)
    df_bq_schedule = load_dispatch_schedule(
        bidding_zone=zone_code,
        asset_id=asset_id,
        anchor_date_iso=today_iso,
    )
    df_accuracy = load_forecast_accuracy(bidding_zone=zone_code)

    source_df = df_metrics if not df_metrics.empty else df_bq_schedule
    dispatch_results = simulate_commercial_dispatch(
        df_metrics=source_df,
        asset_config=asset_config,
        alpha=alpha,
        df_congestion=df_congestion,
        use_lp=True,
    )

    st.title("Commercial Facility Dispatch & Dynamic Energy Arbitrage")
    facility_name = asset_config.get("facility_name", "Commercial Facility")
    substation = asset_config.get("substation_area", "NL-RANDSTAD-NORTH")

    sol_kwp = asset_config.get("solar_kwp", 0)
    bess_kwh = asset_config.get("bess_capacity_kwh", 0)

    mae_badge = ""
    if df_accuracy is not None and not df_accuracy.empty and "rolling_7d_mae_gco2_kwh" in df_accuracy.columns:
        latest_mae = float(df_accuracy.iloc[0]["rolling_7d_mae_gco2_kwh"])
        mae_badge = f" | **7d Carbon Forecast MAE:** `{latest_mae:.1f} gCO₂/kWh`"

    st.caption(
        f"**Facility:** {facility_name} (`{asset_id}`) | **Bidding Zone:** {zone_label} | "
        f"**Substation:** `{substation}` | **Solar:** {sol_kwp:.0f} kWp | "
        f"**BESS:** {bess_kwh:.0f} kWh (Wear: €{marginal_cycle_cost:.3f}/kWh){mae_badge}"
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

    st.markdown("### Executive KPI Comparison (OptiGrid MPC vs. Unmanaged Baseline)")
    kpi1, kpi2, kpi3, kpi4 = st.columns(4)

    opt_spend = dispatch_results["total_optimized_cost_eur"]
    saved_eur = dispatch_results["net_financial_yield_eur"]
    saved_pct = dispatch_results["cost_saving_pct"]
    kpi1.metric(
        "Net Energy Spend",
        f"€{opt_spend:.2f}",
        f"↓ €{saved_eur:.2f} saved ({-saved_pct:.1f}%)",
        delta_color="normal",
    )

    opt_co2 = dispatch_results.get("optimized_emissions_kg", 0.0)
    abated_co2 = dispatch_results["total_carbon_avoided_kg"]
    carbon_pct = dispatch_results.get("carbon_saving_pct", 0.0)
    kpi2.metric(
        "Net Carbon Footprint",
        f"{opt_co2:.1f} kgCO₂",
        f"↓ {abated_co2:.1f} kgCO₂ abated ({-carbon_pct:.1f}%)",
        delta_color="normal",
    )

    rescued_kwh = dispatch_results.get(
        "solar_curtailment_avoided_kwh", dispatch_results["curtailed_solar_kwh"]
    )
    kpi3.metric(
        "Solar Curtailment Avoided",
        f"{rescued_kwh:.1f} kWh",
        f"{dispatch_results['bess_cycles']:.2f} eq. BESS cycles",
        delta_color="normal",
    )

    abatement_cost = dispatch_results.get("implied_abatement_cost_eur_tco2", 0.0)
    kpi4.metric(
        "Implied Carbon Abatement Cost",
        f"€{abatement_cost:.2f} / tCO₂",
        "Net negative cost (profit + green)" if abatement_cost <= 0 else "vs €65/t EU ETS",
        delta_color="normal" if abatement_cost <= 65.0 else "inverse",
    )

    col_main, col_pareto = st.columns([2.2, 1.0])

    with col_main:
        st.markdown("### Synchronized Grid Metrics & Commercial MPC Dispatch Schedule")
        fig = make_subplots(
            rows=2,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.10,
            subplot_titles=(
                "Day-Ahead Wholesale Price (€/kWh) & Flow-Traced Carbon Intensity (gCO₂/kWh)",
                "HiGHS LP Battery State-of-Charge (SoC %) & Net Dispatch Import/Export (kW)",
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
                name="Consumption Carbon (gCO₂/kWh)",
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
            height=640,
            hovermode="x unified",
            template="plotly_white",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        st.plotly_chart(fig, width="stretch")

    with col_pareto:
        st.markdown("### Cost vs. Carbon Pareto Frontier")
        df_pareto = compute_pareto_frontier(
            df_metrics=source_df,
            asset_config=asset_config,
            df_congestion=df_congestion,
            steps=11,
        )
        if not df_pareto.empty:
            fig_p = go.Figure()
            fig_p.add_trace(
                go.Scatter(
                    x=df_pareto["total_cost_eur"],
                    y=df_pareto["total_emissions_kg"],
                    mode="lines+markers",
                    name="Pareto Frontier (α ∈ [0, 1])",
                    text=[f"α = {a:.1f}" for a in df_pareto["alpha"]],
                    line=dict(color="#64748B", width=2.5),
                    marker=dict(size=8, color="#3B82F6"),
                )
            )
            fig_p.add_trace(
                go.Scatter(
                    x=[dispatch_results["total_optimized_cost_eur"]],
                    y=[dispatch_results["optimized_emissions_kg"]],
                    mode="markers",
                    name=f"Active Operating Point (α={alpha:.2f})",
                    marker=dict(
                        size=16,
                        color="#10B981",
                        line=dict(width=3, color="#065F46"),
                        symbol="diamond",
                    ),
                )
            )
            fig_p.update_layout(
                height=420,
                template="plotly_white",
                xaxis_title="Total Net Energy Spend (€)",
                yaxis_title="Total Scope 2 Footprint (kgCO₂)",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
                margin=dict(l=20, r=20, t=40, b=20),
            )
            st.plotly_chart(fig_p, width="stretch")

        st.info(
            f"**MPC Solver Telemetry:** Global LP horizon solved across **{len(df_sched)} hours**. "
            f"Degradation gate: **€{marginal_cycle_cost:.3f}/kWh** "
            f"(Total cell wear cost: **€{dispatch_results.get('total_degradation_cost_eur', 0.0):.2f}**)."
        )

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

    st.markdown("### Export Machine-Actionable Dispatch Schedule (BMS / Modbus / ESG Audit)")
    exp_col1, exp_col2 = st.columns(2)

    modbus_json_str = _build_modbus_json_payload(df_sched, asset_id, zone_code)
    exp_col1.download_button(
        label="⬇️ Download JSON / Modbus Register Payload (PLC / Edge BMS)",
        data=modbus_json_str,
        file_name=f"optigrid_modbus_schedule_{asset_id}_{today_iso}.json",
        mime="application/json",
        use_container_width=True,
    )

    csv_ledger_str = ledger_df.to_csv(index=False)
    exp_col2.download_button(
        label="⬇️ Download CSV Financial & ESG Scope 2 Audit Ledger",
        data=csv_ledger_str,
        file_name=f"optigrid_esg_audit_ledger_{asset_id}_{today_iso}.csv",
        mime="text/csv",
        use_container_width=True,
    )


if __name__ == "__main__":
    render_dashboard()
