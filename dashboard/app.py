import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from asset_config import render_asset_sidebar
from charts import (
    build_cost_comparison_chart,
    build_dispatch_cockpit_chart,
    build_forecast_accuracy_chart,
    build_pareto_chart,
)
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
from ui_theme import inject_custom_css, render_header_bar, render_kpi_strip

load_dotenv(override=True)

st.set_page_config(
    page_title="OptiGrid: Commercial Asset Energy & Carbon Dispatch",
    page_icon="⚡",
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


def _render_cockpit_sidebar_panel(
    df_sched: pd.DataFrame,
    dispatch_results: dict,
    marginal_cycle_cost: float,
) -> None:
    total_hrs = max(len(df_sched), 1)
    counts = df_sched["dispatch_action"].value_counts().to_dict()
    chg_n = int(counts.get("CHARGE_BATTERY", 0))
    dis_n = int(counts.get("DISCHARGE_BATTERY", 0))
    rmp_n = int(counts.get("RAMP_LOAD", 0))
    cur_n = int(counts.get("CURTAIL_SOLAR", 0))
    hld_n = int(counts.get("HOLD_BASELINE", 0))

    pct = lambda n: 100.0 * n / total_hrs

    st.markdown(
        f"""
        <div class="og-panel">
            <div class="og-panel-title">
                <span>Dispatch Mix ({total_hrs}h Horizon)</span>
                <span class="og-mono" style="color:#38BDF8;">HiGHS LP</span>
            </div>
            <div class="og-action-bar">
                <div style="width:{pct(chg_n):.1f}%; background:#10B981;"></div>
                <div style="width:{pct(dis_n):.1f}%; background:#A78BFA;"></div>
                <div style="width:{pct(rmp_n):.1f}%; background:#38BDF8;"></div>
                <div style="width:{pct(cur_n):.1f}%; background:#F43F5E;"></div>
                <div style="width:{pct(hld_n):.1f}%; background:#475569;"></div>
            </div>
            <div class="og-action-legend">
                <div class="og-legend-item"><span><span class="og-swatch" style="background:#10B981;"></span>Charge</span><span class="og-mono">{chg_n}h</span></div>
                <div class="og-legend-item"><span><span class="og-swatch" style="background:#A78BFA;"></span>Discharge</span><span class="og-mono">{dis_n}h</span></div>
                <div class="og-legend-item"><span><span class="og-swatch" style="background:#38BDF8;"></span>Ramp Load</span><span class="og-mono">{rmp_n}h</span></div>
                <div class="og-legend-item"><span><span class="og-swatch" style="background:#F43F5E;"></span>Curtail</span><span class="og-mono">{cur_n}h</span></div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    cheapest_row = df_sched.loc[df_sched["price_eur_kwh"].idxmin()]
    cleanest_row = df_sched.loc[df_sched["carbon_intensity_gco2_kwh"].idxmin()]
    peak_price_row = df_sched.loc[df_sched["price_eur_kwh"].idxmax()]
    max_solar_row = df_sched.loc[df_sched["estimated_solar_kw"].idxmax()]

    st.markdown(
        f"""
        <div class="og-panel">
            <div class="og-panel-title"><span>Market Extremes & Opportunity</span></div>
            <div class="og-stat-row">
                <span class="og-stat-k">Cheapest Price Hour</span>
                <span class="og-stat-v" style="color:#38BDF8;">{cheapest_row['local_datetime'].strftime('%d %b %H:%M')} · €{cheapest_row['price_eur_kwh']:.3f}</span>
            </div>
            <div class="og-stat-row">
                <span class="og-stat-k">Cleanest Grid Hour</span>
                <span class="og-stat-v" style="color:#34D399;">{cleanest_row['local_datetime'].strftime('%d %b %H:%M')} · {cleanest_row['carbon_intensity_gco2_kwh']:.0f} g</span>
            </div>
            <div class="og-stat-row">
                <span class="og-stat-k">Peak Tariff Risk</span>
                <span class="og-stat-v" style="color:#FB7185;">{peak_price_row['local_datetime'].strftime('%d %b %H:%M')} · €{peak_price_row['price_eur_kwh']:.3f}</span>
            </div>
            <div class="og-stat-row">
                <span class="og-stat-k">Peak Solar PV Output</span>
                <span class="og-stat-v" style="color:#FBBF24;">{max_solar_row['local_datetime'].strftime('%d %b %H:%M')} · {max_solar_row['estimated_solar_kw']:.0f} kW</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    baseline_eur = float(dispatch_results.get("total_baseline_cost_eur", 0.0))
    opt_eur = float(dispatch_results.get("total_optimized_cost_eur", 0.0))
    wear_eur = float(dispatch_results.get("total_degradation_cost_eur", 0.0))
    base_co2 = float(dispatch_results.get("baseline_emissions_kg", 0.0))
    opt_co2 = float(dispatch_results.get("optimized_emissions_kg", 0.0))

    st.markdown(
        f"""
        <div class="og-panel">
            <div class="og-panel-title"><span>MPC Solver & Wear Telemetry</span></div>
            <div class="og-stat-row">
                <span class="og-stat-k">Unmanaged Baseline Spend</span>
                <span class="og-stat-v">€{baseline_eur:,.2f}</span>
            </div>
            <div class="og-stat-row">
                <span class="og-stat-k">Optimized MPC Spend</span>
                <span class="og-stat-v" style="color:#34D399;">€{opt_eur:,.2f}</span>
            </div>
            <div class="og-stat-row">
                <span class="og-stat-k">Cell Wear Gate / Total Wear</span>
                <span class="og-stat-v">€{marginal_cycle_cost:.3f}/kWh · €{wear_eur:.2f}</span>
            </div>
            <div class="og-stat-row">
                <span class="og-stat-k">Scope 2 (Base → MPC)</span>
                <span class="og-stat-v">{base_co2:,.0f} → {opt_co2:,.0f} kg</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_dashboard():
    inject_custom_css()

    zone_label = st.sidebar.selectbox("Bidding Zone", list(BIDDING_ZONES.keys()))
    zone_code = BIDDING_ZONES[zone_label]

    df_assets = load_asset_constraints(bidding_zone=zone_code)
    asset_config = render_asset_sidebar(df_assets, bidding_zone=zone_code)
    asset_id = asset_config.get("asset_id", "NL-AMS-DC01")
    default_alpha = float(asset_config.get("alpha_weight", 0.50))

    st.sidebar.markdown("##### Objective & Degradation")
    pricing_mode = st.sidebar.segmented_control(
        "Carbon Valuation Mode",
        options=["Pareto Weight (α)", "Carbon Tax (€/t)"],
        default="Pareto Weight (α)",
        label_visibility="collapsed",
    )
    if pricing_mode is None:
        pricing_mode = "Pareto Weight (α)"

    if pricing_mode == "Pareto Weight (α)":
        alpha = st.sidebar.slider(
            "Preference α  (0 = Green · 1 = Profit)",
            min_value=0.0,
            max_value=1.0,
            value=default_alpha,
            step=0.05,
            help="0.0 = 100% Green (Minimize Carbon), 1.0 = 100% Cheapest (Maximize Arbitrage)",
        )
        implied_shadow_eur = round((1.0 - alpha) / max(alpha, 0.05) * 65.0, 1)
        st.sidebar.caption(
            f"Implied Carbon Shadow Price: **€{implied_shadow_eur:.1f} / tCO₂** (EU ETS €65/t)"
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
        "BESS Wear Cost (€/kWh Cycled)",
        min_value=0.00,
        max_value=0.08,
        value=float(
            asset_config.get(
                "marginal_cycle_cost_eur_kwh", DEFAULT_MARGINAL_CYCLE_COST_EUR_KWH
            )
        ),
        step=0.005,
        help="Amortized LiFePO4 battery wear cost (typically 0.02–0.04 €/kWh cycled).",
    )
    asset_config["marginal_cycle_cost_eur_kwh"] = marginal_cycle_cost

    with st.sidebar.expander("📈 Custom 24h Load Profile", expanded=False):
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
                st.success(f"Applied custom 24h profile ({len(parsed_map)}h)")

        enable_interactive_curve = st.checkbox("Edit 24h Baseline Interactively")
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
                height=190,
                key="custom_24h_curve_editor",
            )
            asset_config["custom_load_profile_kw"] = {
                int(r["hour"]) % 24: float(r["load_kw"])
                for _, r in edited_curve_df.iterrows()
            }

    st.sidebar.markdown(
        """
        <div class="og-side-footer">
            <b>Engine:</b> SciPy HiGHS LP MPC<br/>
            <b>Viewport Lock:</b> 1920 × 1080 px<br/>
            <b>Data Cache:</b> BigQuery + RAM TTL
        </div>
        """,
        unsafe_allow_html=True,
    )

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

    facility_name = asset_config.get("facility_name", "Commercial Facility")
    substation = asset_config.get("substation_area", "NL-RANDSTAD-NORTH")
    sol_kwp = float(asset_config.get("solar_kwp", 0.0))
    bess_kwh = float(asset_config.get("bess_capacity_kwh", 0.0))
    is_cong = bool(dispatch_results.get("is_congestion_active", False))
    exp_factor = float(dispatch_results.get("export_factor", 1.0))
    tso_name = "TenneT" if "NL" in zone_code else ("PSE" if "PL" in zone_code else "Regional Grid")

    mae_value = None
    if (
        df_accuracy is not None
        and not df_accuracy.empty
        and "rolling_7d_mae_gco2_kwh" in df_accuracy.columns
    ):
        mae_value = float(df_accuracy.iloc[0]["rolling_7d_mae_gco2_kwh"])

    render_header_bar(
        facility_name=facility_name,
        asset_id=asset_id,
        zone_label=zone_label,
        substation=substation,
        sol_kwp=sol_kwp,
        bess_kwh=bess_kwh,
        marginal_cycle_cost=marginal_cycle_cost,
        is_congestion=is_cong,
        export_factor=exp_factor,
        tso_name=tso_name,
        mae_value=mae_value,
    )

    has_data = (
        dispatch_results
        and "df_schedule" in dispatch_results
        and not dispatch_results["df_schedule"].empty
    )
    if not has_data:
        st.warning("Awaiting day-ahead market settlement telemetry. Re-evaluating schedule...")
        return

    df_sched = dispatch_results["df_schedule"].copy()
    if "is_forecasted" in source_df.columns:
        fc_src = source_df[["timestamp_utc", "is_forecasted"]].copy()
        fc_src["timestamp_utc"] = pd.to_datetime(fc_src["timestamp_utc"], utc=True)
        df_sched["timestamp_utc"] = pd.to_datetime(df_sched["timestamp_utc"], utc=True)
        df_sched = df_sched.merge(
            fc_src.drop_duplicates(subset=["timestamp_utc"]),
            on="timestamp_utc",
            how="left",
        )
        df_sched["is_forecasted"] = df_sched["is_forecasted"].fillna(False).astype(bool)

    render_kpi_strip(dispatch_results)

    tab_cockpit, tab_pareto, tab_forecast, tab_ledger = st.tabs(
        [
            "Cockpit",
            "Pareto & Strategy",
            "Forecast & Imbalance",
            "Export",
        ]
    )

    with tab_cockpit:
        col_main, col_side = st.columns([2.35, 1.0], gap="medium")

        with col_main:
            ctrl1, ctrl2, ctrl3 = st.columns([1.6, 1.0, 1.0])
            with ctrl1:
                horizon_filter = st.segmented_control(
                    "Horizon",
                    options=["All Hours", "Actuals (Past)", "Forecast (Ahead)"],
                    default="All Hours",
                    label_visibility="collapsed",
                )
            with ctrl2:
                show_action_bands = st.toggle("Action Shading", value=True)
            with ctrl3:
                show_solar_overlay = st.toggle("Solar PV Overlay", value=True)

            df_plot = df_sched.copy()
            if horizon_filter == "Actuals (Past)" and "is_forecasted" in df_plot.columns:
                filtered = df_plot[df_plot["is_forecasted"] == False]
                if not filtered.empty:
                    df_plot = filtered
            elif horizon_filter == "Forecast (Ahead)" and "is_forecasted" in df_plot.columns:
                filtered = df_plot[df_plot["is_forecasted"] == True]
                if not filtered.empty:
                    df_plot = filtered

            fig_cockpit = build_dispatch_cockpit_chart(
                df_sched=df_plot,
                show_action_bands=show_action_bands,
                show_solar_overlay=show_solar_overlay,
                bess_min_soc_pct=float(asset_config.get("bess_min_soc_pct", 10.0)),
                bess_max_soc_pct=float(asset_config.get("bess_max_soc_pct", 95.0)),
                height=625,
            )
            st.plotly_chart(fig_cockpit, width="stretch", config={"displayModeBar": False})

        with col_side:
            _render_cockpit_sidebar_panel(
                df_sched=df_sched,
                dispatch_results=dispatch_results,
                marginal_cycle_cost=marginal_cycle_cost,
            )

    with tab_pareto:
        df_pareto = compute_pareto_frontier(
            df_metrics=source_df,
            asset_config=asset_config,
            df_congestion=df_congestion,
            steps=11,
        )
        p_col1, p_col2 = st.columns([1.25, 1.0], gap="medium")
        with p_col1:
            fig_pareto = build_pareto_chart(
                df_pareto=df_pareto,
                active_cost=dispatch_results["total_optimized_cost_eur"],
                active_emissions=dispatch_results["optimized_emissions_kg"],
                active_alpha=alpha,
                height=640,
            )
            st.plotly_chart(fig_pareto, width="stretch", config={"displayModeBar": False})

        with p_col2:
            fig_cost = build_cost_comparison_chart(df_sched, height=345)
            st.plotly_chart(fig_cost, width="stretch", config={"displayModeBar": False})

            if not df_pareto.empty:
                st.markdown("##### Strategy Tradeoff Matrix")
                key_alphas = [0.0, 0.5, 1.0]
                summary_rows = []
                for a_target in key_alphas:
                    row_match = df_pareto.iloc[(df_pareto["alpha"] - a_target).abs().argsort()[:1]].iloc[0]
                    label = (
                        "Max Green (α=0.0)"
                        if a_target == 0.0
                        else ("Balanced (α=0.5)" if a_target == 0.5 else "Max Profit (α=1.0)")
                    )
                    summary_rows.append(
                        {
                            "Strategy": label,
                            "Net Spend (€)": round(float(row_match["total_cost_eur"]), 2),
                            "Savings (€)": round(float(row_match["net_savings_eur"]), 2),
                            "Scope 2 (kg)": round(float(row_match["total_emissions_kg"]), 1),
                            "Abated (kg)": round(float(row_match["carbon_avoided_kg"]), 1),
                        }
                    )
                summary_rows.append(
                    {
                        "Strategy": f"Active (α={alpha:.2f})",
                        "Net Spend (€)": round(float(dispatch_results["total_optimized_cost_eur"]), 2),
                        "Savings (€)": round(float(dispatch_results["net_financial_yield_eur"]), 2),
                        "Scope 2 (kg)": round(float(dispatch_results["optimized_emissions_kg"]), 1),
                        "Abated (kg)": round(float(dispatch_results["total_carbon_avoided_kg"]), 1),
                    }
                )
                st.dataframe(
                    pd.DataFrame(summary_rows),
                    hide_index=True,
                    width="stretch",
                    height=180,
                )

    with tab_forecast:
        f_col1, f_col2 = st.columns([2.1, 1.0], gap="medium")
        with f_col1:
            fig_fc = build_forecast_accuracy_chart(
                df_accuracy=df_accuracy,
                df_metrics=source_df,
                height=640,
            )
            st.plotly_chart(fig_fc, width="stretch", config={"displayModeBar": False})

        with f_col2:
            latest_mae = (
                float(df_accuracy.iloc[0]["rolling_7d_mae_gco2_kwh"])
                if not df_accuracy.empty and "rolling_7d_mae_gco2_kwh" in df_accuracy.columns
                else 0.0
            )
            latest_rmse = (
                float(df_accuracy.iloc[0]["rolling_7d_rmse_gco2_kwh"])
                if not df_accuracy.empty and "rolling_7d_rmse_gco2_kwh" in df_accuracy.columns
                else 0.0
            )
            cong_sev = (
                str(df_congestion.iloc[0].get("congestion_severity", "NONE"))
                if df_congestion is not None and not df_congestion.empty
                else "NONE"
            )
            cong_msg = (
                str(df_congestion.iloc[0].get("message_details", "Nominal grid operating status"))
                if df_congestion is not None and not df_congestion.empty
                else "Nominal grid operating status"
            )

            st.markdown(
                f"""
                <div class="og-panel">
                    <div class="og-panel-title"><span>Carbon Model Telemetry (7d Rolling)</span></div>
                    <div class="og-stat-row">
                        <span class="og-stat-k">7d Rolling MAE</span>
                        <span class="og-stat-v" style="color:#38BDF8;">{latest_mae:.2f} gCO₂/kWh</span>
                    </div>
                    <div class="og-stat-row">
                        <span class="og-stat-k">7d Rolling RMSE</span>
                        <span class="og-stat-v" style="color:#A78BFA;">{latest_rmse:.2f} gCO₂/kWh</span>
                    </div>
                    <div class="og-stat-row">
                        <span class="og-stat-k">Substation Severity</span>
                        <span class="og-stat-v">{cong_sev}</span>
                    </div>
                    <div style="margin-top:8px; font-size:0.78rem; color:#94A3B8; line-height:1.45;">
                        {cong_msg}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            if not df_accuracy.empty and "error_gco2_kwh" in df_accuracy.columns:
                st.markdown("##### Recent Backtest Residuals")
                acc_disp = df_accuracy[
                    ["local_datetime", "forecast_ci_gco2_kwh", "actual_ci_gco2_kwh", "error_gco2_kwh"]
                ].head(12).copy()
                acc_disp["local_datetime"] = pd.to_datetime(acc_disp["local_datetime"]).dt.strftime("%m-%d %H:%M")
                acc_disp.columns = ["Time", "Forecast", "Actual", "Error"]
                st.dataframe(acc_disp, hide_index=True, width="stretch", height=365)

    with tab_ledger:
        action_options = ["ALL"] + sorted(df_sched["dispatch_action"].unique().tolist())
        selected_actions = st.pills(
            "Filter by Dispatch Action",
            options=action_options,
            default="ALL",
            selection_mode="single",
        )

        filtered_sched = df_sched if selected_actions in (None, "ALL") else df_sched[df_sched["dispatch_action"] == selected_actions]

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
        ledger_df = filtered_sched[display_cols].copy()
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

        st.dataframe(
            ledger_df,
            hide_index=True,
            width="stretch",
            height=485,
            column_config={
                "Price (€/kWh)": st.column_config.NumberColumn(format="€%.4f"),
                "Carbon (g/kWh)": st.column_config.NumberColumn(format="%.1f g"),
                "Solar Gen (kW)": st.column_config.NumberColumn(format="%.1f kW"),
                "BESS Power (kW)": st.column_config.NumberColumn(format="%+.1f kW"),
                "BESS SoC (%)": st.column_config.ProgressColumn(
                    min_value=0,
                    max_value=100,
                    format="%.1f%%",
                ),
                "Curtailed (kW)": st.column_config.NumberColumn(format="%.1f kW"),
                "Cost Delta (€)": st.column_config.NumberColumn(format="€%+.2f"),
            },
        )

        exp_col1, exp_col2, exp_col3 = st.columns([1.2, 1.2, 0.8])
        modbus_json_str = _build_modbus_json_payload(df_sched, asset_id, zone_code)
        exp_col1.download_button(
            label="⬇️ Download JSON / Modbus Register Payload",
            data=modbus_json_str,
            file_name=f"optigrid_modbus_schedule_{asset_id}_{today_iso}.json",
            mime="application/json",
            use_container_width=True,
        )

        csv_ledger_str = ledger_df.to_csv(index=False)
        exp_col2.download_button(
            label="⬇️ Download CSV Financial & ESG Audit Ledger",
            data=csv_ledger_str,
            file_name=f"optigrid_esg_audit_ledger_{asset_id}_{today_iso}.csv",
            mime="text/csv",
            use_container_width=True,
        )

        with exp_col3:
            with st.popover("👁️ Preview Modbus JSON", use_container_width=True):
                st.code(modbus_json_str[:1800], language="json")


if __name__ == "__main__":
    render_dashboard()
