from typing import Any

import pandas as pd

FACILITY_ARCHETYPE_PRESETS: dict[str, dict[str, Any]] = {
    "Cold Storage Logistics": {
        "label": "Cold Storage Logistics Warehouse",
        "description": "High thermal inertia, 500 kW solar, 1 MWh BESS",
        "solar_kwp": 500.0,
        "grid_export_limit_kw": 350.0,
        "bess_capacity_kwh": 1000.0,
        "bess_max_charge_kw": 350.0,
        "bess_max_discharge_kw": 350.0,
        "bess_roundtrip_efficiency": 0.91,
        "baseline_load_kw": 280.0,
        "max_flexible_load_kw": 320.0,
        "marginal_cycle_cost_eur_kwh": 0.025,
        "alpha_weight": 0.45,
    },
    "EV Fleet Depot": {
        "label": "EV Fleet Charging Depot",
        "description": "Strict 4-hour overnight charging window, high peak demand",
        "solar_kwp": 800.0,
        "grid_export_limit_kw": 500.0,
        "bess_capacity_kwh": 2200.0,
        "bess_max_charge_kw": 750.0,
        "bess_max_discharge_kw": 750.0,
        "bess_roundtrip_efficiency": 0.90,
        "baseline_load_kw": 180.0,
        "max_flexible_load_kw": 900.0,
        "marginal_cycle_cost_eur_kwh": 0.030,
        "alpha_weight": 0.65,
    },
    "Batch Chemical Plant": {
        "label": "Batch Chemical / Industrial Plant",
        "description": "Discrete K-hour high-load shiftable batch process",
        "solar_kwp": 2500.0,
        "grid_export_limit_kw": 1000.0,
        "bess_capacity_kwh": 4000.0,
        "bess_max_charge_kw": 1000.0,
        "bess_max_discharge_kw": 1000.0,
        "bess_roundtrip_efficiency": 0.88,
        "baseline_load_kw": 800.0,
        "max_flexible_load_kw": 1200.0,
        "marginal_cycle_cost_eur_kwh": 0.020,
        "alpha_weight": 0.60,
    },
}

DEFAULT_ASSET_CONSTRAINTS: dict[str, dict[str, Any]] = {
    "NL-AMS-DC01": {
        "asset_id": "NL-AMS-DC01",
        "facility_name": "Amsterdam Cold Storage & Logistics Hub",
        "bidding_zone": "10YNL----------L",
        "substation_area": "NL-RANDSTAD-NORTH",
        "solar_kwp": 1200.0,
        "grid_export_limit_kw": 600.0,
        "bess_capacity_kwh": 2000.0,
        "bess_max_charge_kw": 500.0,
        "bess_max_discharge_kw": 500.0,
        "bess_roundtrip_efficiency": 0.90,
        "bess_min_soc_pct": 10.0,
        "bess_max_soc_pct": 95.0,
        "baseline_load_kw": 350.0,
        "max_flexible_load_kw": 450.0,
        "thermal_shift_buffer_hours": 4,
        "alpha_weight": 0.50,
    },
    "NL-RTM-IND02": {
        "asset_id": "NL-RTM-IND02",
        "facility_name": "Rotterdam Port Electrolyzer & Chemical Facility",
        "bidding_zone": "10YNL----------L",
        "substation_area": "NL-RANDSTAD-SOUTH",
        "solar_kwp": 2500.0,
        "grid_export_limit_kw": 1000.0,
        "bess_capacity_kwh": 4000.0,
        "bess_max_charge_kw": 1000.0,
        "bess_max_discharge_kw": 1000.0,
        "bess_roundtrip_efficiency": 0.88,
        "bess_min_soc_pct": 15.0,
        "bess_max_soc_pct": 95.0,
        "baseline_load_kw": 800.0,
        "max_flexible_load_kw": 1200.0,
        "thermal_shift_buffer_hours": 6,
        "alpha_weight": 0.65,
    },
    "DE-LU-MFG01": {
        "asset_id": "DE-LU-MFG01",
        "facility_name": "Rhine-Ruhr Precision Manufacturing Campus",
        "bidding_zone": "10Y1001A1001A82H",
        "substation_area": "DE-WEST-GRID",
        "solar_kwp": 1800.0,
        "grid_export_limit_kw": 800.0,
        "bess_capacity_kwh": 2500.0,
        "bess_max_charge_kw": 625.0,
        "bess_max_discharge_kw": 625.0,
        "bess_roundtrip_efficiency": 0.91,
        "bess_min_soc_pct": 10.0,
        "bess_max_soc_pct": 90.0,
        "baseline_load_kw": 500.0,
        "max_flexible_load_kw": 600.0,
        "thermal_shift_buffer_hours": 3,
        "alpha_weight": 0.40,
    },
    "PL-WAW-LOG01": {
        "asset_id": "PL-WAW-LOG01",
        "facility_name": "Warsaw Automated Distribution Park",
        "bidding_zone": "10YPL-AREA-----S",
        "substation_area": "PL-CENTRAL",
        "solar_kwp": 900.0,
        "grid_export_limit_kw": 450.0,
        "bess_capacity_kwh": 1200.0,
        "bess_max_charge_kw": 300.0,
        "bess_max_discharge_kw": 300.0,
        "bess_roundtrip_efficiency": 0.89,
        "bess_min_soc_pct": 10.0,
        "bess_max_soc_pct": 95.0,
        "baseline_load_kw": 250.0,
        "max_flexible_load_kw": 350.0,
        "thermal_shift_buffer_hours": 3,
        "alpha_weight": 0.55,
    },
}


def get_default_assets_dataframe(bidding_zone: str = None) -> pd.DataFrame:
    records = list(DEFAULT_ASSET_CONSTRAINTS.values())
    df = pd.DataFrame(records)
    if bidding_zone:
        df_filtered = df[df["bidding_zone"] == bidding_zone]
        if not df_filtered.empty:
            return df_filtered.reset_index(drop=True)
    return df


def render_asset_sidebar(df_assets: pd.DataFrame, bidding_zone: str) -> dict[str, Any]:
    import streamlit as st

    st.sidebar.header("Commercial Facility Profile")

    zone_assets = df_assets[df_assets["bidding_zone"] == bidding_zone].reset_index(drop=True)
    if zone_assets.empty:
        zone_assets = df_assets.reset_index(drop=True)

    asset_options = {
        f"{row['facility_name']} ({row['asset_id']})": row["asset_id"]
        for _, row in zone_assets.iterrows()
    }

    selected_label = st.sidebar.selectbox("Select Asset", list(asset_options.keys()))
    selected_asset_id = asset_options[selected_label]
    asset_data = zone_assets[zone_assets["asset_id"] == selected_asset_id].iloc[0].to_dict()

    if hasattr(st.sidebar, "caption") and hasattr(st.sidebar, "columns"):
        st.sidebar.caption("One-Click Facility Archetype Presets")
        p_cols = st.sidebar.columns(3)
        if isinstance(p_cols, (list, tuple)) and len(p_cols) == 3:
            for col, (preset_key, preset_vals) in zip(
                p_cols, FACILITY_ARCHETYPE_PRESETS.items(), strict=False
            ):
                if col.button(preset_key, key=f"preset_{preset_key}", help=preset_vals["description"]):
                    if isinstance(getattr(st, "session_state", None), dict):
                        st.session_state["active_archetype_preset"] = preset_key

        if isinstance(getattr(st, "session_state", None), dict):
            active_preset = st.session_state.get("active_archetype_preset")
            if active_preset in FACILITY_ARCHETYPE_PRESETS:
                asset_data.update(FACILITY_ARCHETYPE_PRESETS[active_preset])

    st.sidebar.subheader("Asset Physical Constraints")
    with st.sidebar.form(key=f"asset_constraints_form_{selected_asset_id}"):
        solar_kwp = st.number_input(
            "Solar PV Peak (kWp)",
            min_value=0.0,
            max_value=20000.0,
            value=float(asset_data.get("solar_kwp", 1000.0)),
            step=50.0,
        )
        grid_export_limit_kw = st.number_input(
            "Grid Export Limit (kW)",
            min_value=0.0,
            max_value=10000.0,
            value=float(asset_data.get("grid_export_limit_kw", 500.0)),
            step=50.0,
        )
        bess_capacity_kwh = st.number_input(
            "BESS Capacity (kWh)",
            min_value=0.0,
            max_value=50000.0,
            value=float(asset_data.get("bess_capacity_kwh", 2000.0)),
            step=100.0,
        )
        bess_max_charge_kw = st.number_input(
            "BESS Max Charge Rate (kW)",
            min_value=0.0,
            max_value=10000.0,
            value=float(asset_data.get("bess_max_charge_kw", 500.0)),
            step=50.0,
        )
        bess_max_discharge_kw = st.number_input(
            "BESS Max Discharge Rate (kW)",
            min_value=0.0,
            max_value=10000.0,
            value=float(asset_data.get("bess_max_discharge_kw", 500.0)),
            step=50.0,
        )
        baseline_load_kw = st.number_input(
            "Baseline Unshiftable Load (kW)",
            min_value=0.0,
            max_value=10000.0,
            value=float(asset_data.get("baseline_load_kw", 300.0)),
            step=25.0,
        )
        max_flexible_load_kw = st.number_input(
            "Max Flexible / Shiftable Load (kW)",
            min_value=0.0,
            max_value=10000.0,
            value=float(asset_data.get("max_flexible_load_kw", 400.0)),
            step=25.0,
        )
        bess_roundtrip_efficiency = st.slider(
            "BESS Roundtrip Efficiency",
            min_value=0.70,
            max_value=0.98,
            value=float(asset_data.get("bess_roundtrip_efficiency", 0.90)),
            step=0.01,
        )

        submitted = st.form_submit_button("Save Constraints to BigQuery")

    updated_config = dict(asset_data)
    updated_config.update(
        {
            "solar_kwp": solar_kwp,
            "grid_export_limit_kw": grid_export_limit_kw,
            "bess_capacity_kwh": bess_capacity_kwh,
            "bess_max_charge_kw": bess_max_charge_kw,
            "bess_max_discharge_kw": bess_max_discharge_kw,
            "bess_roundtrip_efficiency": bess_roundtrip_efficiency,
            "baseline_load_kw": baseline_load_kw,
            "max_flexible_load_kw": max_flexible_load_kw,
        }
    )

    if submitted:
        from data_fetcher import save_asset_constraints_to_bq

        save_dict = {
            k: v
            for k, v in updated_config.items()
            if k in DEFAULT_ASSET_CONSTRAINTS["NL-AMS-DC01"]
        }
        success = save_asset_constraints_to_bq(save_dict)
        if success:
            st.sidebar.success("Asset constraints saved and synced to BigQuery!")
        else:
            st.sidebar.info("Updated in session memory (BigQuery live credentials optional).")

    return updated_config
