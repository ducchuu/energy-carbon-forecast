from unittest.mock import MagicMock, patch

try:
    import pytest
except ImportError:
    pytest = None

from dashboard.asset_config import (
    DEFAULT_ASSET_CONSTRAINTS,
    FACILITY_ARCHETYPE_PRESETS,
    get_default_assets_dataframe,
    render_asset_sidebar,
)


def test_facility_archetype_presets_defined():
    assert "Cold Storage Logistics" in FACILITY_ARCHETYPE_PRESETS
    assert "EV Fleet Depot" in FACILITY_ARCHETYPE_PRESETS
    assert "Batch Chemical Plant" in FACILITY_ARCHETYPE_PRESETS
    assert FACILITY_ARCHETYPE_PRESETS["Cold Storage Logistics"]["solar_kwp"] == 500.0
    assert FACILITY_ARCHETYPE_PRESETS["Cold Storage Logistics"]["bess_capacity_kwh"] == 1000.0


def test_get_default_assets_dataframe():
    df = get_default_assets_dataframe()
    assert not df.empty
    assert "asset_id" in df.columns
    assert "solar_kwp" in df.columns
    assert "bess_capacity_kwh" in df.columns
    assert len(df) == len(DEFAULT_ASSET_CONSTRAINTS)


def test_get_default_assets_filtered_by_zone():
    df_nl = get_default_assets_dataframe("10YNL----------L")
    assert not df_nl.empty
    assert (df_nl["bidding_zone"] == "10YNL----------L").all()
    assert "NL-AMS-DC01" in df_nl["asset_id"].values


def test_get_default_assets_unknown_zone_returns_all():
    df_fallback = get_default_assets_dataframe("UNKNOWN-ZONE")
    assert len(df_fallback) == len(DEFAULT_ASSET_CONSTRAINTS)


def test_render_asset_sidebar_updates_values():
    st_mock = MagicMock()
    df_nl = get_default_assets_dataframe("10YNL----------L")
    first_row = df_nl.iloc[0]
    expected_label = f"{first_row['facility_name']} ({first_row['asset_id']})"

    st_mock.sidebar.selectbox.return_value = expected_label
    st_mock.number_input.side_effect = [1500.0, 700.0, 2500.0, 600.0, 600.0, 400.0, 500.0]
    st_mock.slider.return_value = 0.92
    st_mock.form_submit_button.return_value = False

    with patch.dict("sys.modules", {"streamlit": st_mock}):
        updated = render_asset_sidebar(df_nl, "10YNL----------L")

    assert updated["asset_id"] == first_row["asset_id"]
    assert updated["solar_kwp"] == 1500.0
    assert updated["bess_capacity_kwh"] == 2500.0
    assert updated["bess_roundtrip_efficiency"] == 0.92
