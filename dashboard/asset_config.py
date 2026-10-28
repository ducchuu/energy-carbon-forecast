from typing import Any, Dict

import pandas as pd

DEFAULT_ASSET_CONSTRAINTS: Dict[str, Dict[str, Any]] = {
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


def render_asset_sidebar(df_assets: pd.DataFrame, bidding_zone: str) -> Dict[str, Any]:
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

        success = save_asset_constraints_to_bq(updated_config)
        if success:
            st.sidebar.success("Asset constraints saved and synced to BigQuery!")
        else:
            st.sidebar.info("Updated in session memory (BigQuery live credentials optional).")

    return updated_config
