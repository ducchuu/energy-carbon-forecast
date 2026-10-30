from pathlib import Path

try:
    import pytest
except ImportError:
    pytest = None

import pandas as pd

from dashboard.optimizer import (
    PRICE_CHARGE_GATE_EUR_KWH,
    PRICE_DISCHARGE_GATE_EUR_KWH,
    SCORE_CHARGE_THRESHOLD,
    SCORE_DISCHARGE_THRESHOLD,
    SCORE_RAMP_THRESHOLD,
    SOLAR_END_HOUR,
    SOLAR_START_HOUR,
    compute_pareto_frontier,
    find_optimal_window,
    simulate_commercial_dispatch,
)


def test_find_optimal_window():
    df = pd.DataFrame(
        {
            "timestamp_utc": pd.date_range(
                start="2028-10-01 12:00", periods=5, freq="1h", tz="UTC"
            ),
            "local_datetime": pd.date_range(
                start="2028-10-01 14:00", periods=5, freq="1h"
            ),
            "price_eur_kwh": [0.10, 0.05, 0.02, 0.15, 0.20],
            "carbon_intensity_gco2_kwh": [200, 150, 100, 250, 300],
            "norm_price": [0.44, 0.17, 0.0, 0.72, 1.0],
            "norm_ci": [0.5, 0.25, 0.0, 0.75, 1.0],
            "renewable_share_pct": [30.0, 50.0, 80.0, 20.0, 10.0],
        }
    )

    result = find_optimal_window(df, alpha=0.5, window_hours=2, appliance_kw=1.0)

    assert result["window_score"] < 0.5
    assert result["best_cost_eur"] == 0.07
    assert result["best_co2_g"] == 250.0
    assert result["avg_renewable_pct"] == 65.0


def test_empty_dataframe_returns_empty_dict():
    df = pd.DataFrame()
    result = find_optimal_window(df, alpha=0.5, window_hours=2, appliance_kw=1.0)
    assert result == {}


def test_insufficient_rows_returns_empty_dict():
    df = pd.DataFrame(
        {
            "timestamp_utc": pd.date_range(
                start="2028-10-01 12:00", periods=1, freq="1h", tz="UTC"
            ),
            "local_datetime": pd.date_range(
                start="2028-10-01 14:00", periods=1, freq="1h"
            ),
            "price_eur_kwh": [0.10],
            "carbon_intensity_gco2_kwh": [200],
            "norm_price": [0.5],
            "norm_ci": [0.5],
            "renewable_share_pct": [50.0],
        }
    )
    result = find_optimal_window(df, alpha=0.5, window_hours=3, appliance_kw=1.0)
    assert result == {}


def test_legacy_column_names():
    df = pd.DataFrame(
        {
            "timestamp_utc": pd.date_range(
                start="2028-10-01 12:00", periods=4, freq="1h", tz="UTC"
            ),
            "local_datetime": pd.date_range(
                start="2028-10-01 14:00", periods=4, freq="1h"
            ),
            "price_eur_kwh": [0.10, 0.05, 0.15, 0.20],
            "carbon_intensity_gco2_kwh": [200, 100, 250, 300],
            "norm_price_daily": [0.33, 0.0, 0.67, 1.0],
            "norm_carbon_daily": [0.5, 0.0, 0.75, 1.0],
            "renewable_share_pct": [30.0, 80.0, 20.0, 10.0],
        }
    )
    result = find_optimal_window(df, alpha=0.5, window_hours=2, appliance_kw=1.0)
    assert result != {}
    assert result["window_score"] < 0.5


def test_non_contiguous_gap_detection():
    timestamps = pd.to_datetime(
        [
            "2028-10-01 12:00",
            "2028-10-01 13:00",
            "2028-10-01 15:00",
            "2028-10-01 16:00",
            "2028-10-01 17:00",
        ],
        utc=True,
    )
    df = pd.DataFrame(
        {
            "timestamp_utc": timestamps,
            "local_datetime": timestamps,
            "price_eur_kwh": [0.10, 0.05, 0.02, 0.15, 0.20],
            "carbon_intensity_gco2_kwh": [200, 150, 100, 250, 300],
            "norm_price": [0.44, 0.17, 0.0, 0.72, 1.0],
            "norm_ci": [0.5, 0.25, 0.0, 0.75, 1.0],
            "renewable_share_pct": [30.0, 50.0, 80.0, 20.0, 10.0],
        }
    )
    result = find_optimal_window(df, alpha=0.5, window_hours=2, appliance_kw=1.0)
    assert result != {}
    assert result["best_cost_eur"] == 0.15


def test_simulate_commercial_dispatch():
    timestamps = pd.date_range(start="2028-10-01 00:00", periods=24, freq="1h", tz="UTC")
    prices = [
        0.08, 0.07, 0.06, 0.05, 0.06, 0.09,
        0.14, 0.18, 0.12, 0.05, 0.02, -0.01,
        0.01, 0.03, 0.08, 0.14, 0.22, 0.26,
        0.20, 0.16, 0.12, 0.10, 0.09, 0.08,
    ]
    carbon_intensities = [
        240.0, 230.0, 220.0, 210.0, 220.0, 250.0,
        290.0, 320.0, 260.0, 180.0, 130.0, 90.0,
        100.0, 120.0, 190.0, 270.0, 360.0, 390.0,
        340.0, 300.0, 260.0, 250.0, 240.0, 230.0,
    ]
    df_metrics = pd.DataFrame(
        {
            "timestamp_utc": timestamps,
            "local_datetime": timestamps,
            "price_eur_kwh": prices,
            "carbon_intensity_gco2_kwh": carbon_intensities,
            "norm_price": [(p - min(prices)) / (max(prices) - min(prices)) for p in prices],
            "norm_ci": [
                (c - min(carbon_intensities)) / (max(carbon_intensities) - min(carbon_intensities))
                for c in carbon_intensities
            ],
            "renewable_share_pct": [65.0] * 24,
        }
    )

    asset_config = {
        "asset_id": "NL-AMS-DC01",
        "facility_name": "Amsterdam Cold Storage",
        "solar_kwp": 1200.0,
        "grid_export_limit_kw": 500.0,
        "bess_capacity_kwh": 2000.0,
        "bess_max_charge_kw": 500.0,
        "bess_max_discharge_kw": 500.0,
        "bess_roundtrip_efficiency": 0.90,
        "bess_min_soc_pct": 10.0,
        "bess_max_soc_pct": 95.0,
        "baseline_load_kw": 300.0,
        "max_flexible_load_kw": 400.0,
    }

    df_congestion = pd.DataFrame(
        [
            {
                "is_congestion_active": True,
                "min_export_limit_factor": 0.40,
                "congestion_severity": "ACTIVE_RESTRICTION",
            }
        ]
    )

    res = simulate_commercial_dispatch(
        df_metrics=df_metrics,
        asset_config=asset_config,
        alpha=0.60,
        df_congestion=df_congestion,
    )

    assert "df_schedule" in res
    df_sched = res["df_schedule"]
    assert not df_sched.empty
    assert res["is_congestion_active"] is True
    assert res["export_factor"] == 0.40
    assert res["net_financial_yield_eur"] > 0
    assert res["total_carbon_avoided_kg"] > 0
    assert res["bess_cycles"] > 0

    assert (df_sched["bess_soc_pct"] >= asset_config["bess_min_soc_pct"]).all()
    assert (df_sched["bess_soc_pct"] <= asset_config["bess_max_soc_pct"]).all()

    assert (df_sched["bess_power_kw"] > 0).any()
    assert (df_sched["bess_power_kw"] < 0).any()

    assert (df_sched["flag_charge_battery"] == (df_sched["dispatch_action"] == "CHARGE_BATTERY")).all()
    assert (df_sched["flag_curtail_solar"] == (df_sched["dispatch_action"] == "CURTAIL_SOLAR")).all()
    assert (df_sched["flag_ramp_load"] == (df_sched["dispatch_action"] == "RAMP_LOAD")).all()
    assert (
        df_sched["flag_discharge_battery"] == (df_sched["dispatch_action"] == "DISCHARGE_BATTERY")
    ).all()


def test_bess_soc_bounds_enforced_under_continuous_discharge():
    timestamps = pd.date_range(start="2028-10-01 00:00", periods=12, freq="1h", tz="UTC")
    df_metrics = pd.DataFrame(
        {
            "timestamp_utc": timestamps,
            "local_datetime": timestamps,
            "price_eur_kwh": [0.35] * 12,
            "carbon_intensity_gco2_kwh": [400.0] * 12,
            "norm_price": [0.95] * 12,
            "norm_ci": [0.95] * 12,
            "renewable_share_pct": [10.0] * 12,
        }
    )
    asset_config = {
        "solar_kwp": 0.0,
        "grid_export_limit_kw": 500.0,
        "bess_capacity_kwh": 1000.0,
        "bess_max_charge_kw": 500.0,
        "bess_max_discharge_kw": 500.0,
        "bess_roundtrip_efficiency": 0.90,
        "bess_min_soc_pct": 20.0,
        "bess_max_soc_pct": 90.0,
        "baseline_load_kw": 300.0,
        "max_flexible_load_kw": 200.0,
    }

    res = simulate_commercial_dispatch(df_metrics=df_metrics, asset_config=asset_config, alpha=0.5)
    df_sched = res["df_schedule"]

    assert (df_sched["bess_soc_pct"] >= 20.0).all()
    discharge_hours = (df_sched["dispatch_action"] == "DISCHARGE_BATTERY").sum()
    assert 1 <= discharge_hours <= 2
    assert df_sched.iloc[-1]["dispatch_action"] == "HOLD_BASELINE"
    assert df_sched.iloc[-1]["bess_power_kw"] == 0.0


def test_sql_python_dispatch_threshold_parity():
    repo_root = Path(__file__).resolve().parents[2]
    sql_path = repo_root / "dbt_energy" / "models" / "gold" / "fct_asset_dispatch_schedule.sql"
    sql_text = sql_path.read_text(encoding="utf-8")

    assert f"<= {SCORE_CHARGE_THRESHOLD:.2f}" in sql_text
    assert f"<= {SCORE_RAMP_THRESHOLD:.2f}" in sql_text
    assert f">= {SCORE_DISCHARGE_THRESHOLD:.2f}" in sql_text
    assert f"<= {PRICE_CHARGE_GATE_EUR_KWH:.2f}" in sql_text
    assert f">= {PRICE_DISCHARGE_GATE_EUR_KWH:.2f}" in sql_text
    assert f"BETWEEN {SOLAR_START_HOUR} AND {SOLAR_END_HOUR}" in sql_text


def test_degradation_cost_prevents_unprofitable_micro_cycling():
    timestamps = pd.date_range(start="2028-10-01 00:00", periods=12, freq="1h", tz="UTC")
    # Tiny price spread (0.004 EUR/kWh) well below battery wear cost (0.04 EUR/kWh)
    prices = [0.100, 0.101, 0.102, 0.104, 0.103, 0.100] * 2
    df_metrics = pd.DataFrame(
        {
            "timestamp_utc": timestamps,
            "local_datetime": timestamps,
            "price_eur_kwh": prices,
            "carbon_intensity_gco2_kwh": [200.0] * 12,
            "norm_price": [0.1, 0.3, 0.5, 0.9, 0.7, 0.1] * 2,
            "norm_ci": [0.5] * 12,
            "renewable_share_pct": [40.0] * 12,
        }
    )
    asset_config = {
        "solar_kwp": 0.0,
        "grid_export_limit_kw": 500.0,
        "bess_capacity_kwh": 1000.0,
        "bess_max_charge_kw": 500.0,
        "bess_max_discharge_kw": 500.0,
        "bess_roundtrip_efficiency": 0.90,
        "bess_min_soc_pct": 10.0,
        "bess_max_soc_pct": 95.0,
        "baseline_load_kw": 300.0,
        "max_flexible_load_kw": 200.0,
        "marginal_cycle_cost_eur_kwh": 0.04,
    }

    res = simulate_commercial_dispatch(df_metrics=df_metrics, asset_config=asset_config, alpha=1.0)
    assert res["bess_cycles"] == 0.0
    assert (res["df_schedule"]["bess_power_kw"] == 0.0).all()


def test_pareto_frontier_and_custom_load_profile():
    timestamps = pd.date_range(start="2028-10-01 00:00", periods=24, freq="1h", tz="UTC")
    prices = [0.03] * 6 + [0.18] * 6 + [0.02] * 6 + [0.24] * 6
    cis = [310.0] * 6 + [260.0] * 6 + [90.0] * 6 + [380.0] * 6
    df_metrics = pd.DataFrame(
        {
            "timestamp_utc": timestamps,
            "local_datetime": timestamps,
            "price_eur_kwh": prices,
            "carbon_intensity_gco2_kwh": cis,
            "renewable_share_pct": [60.0] * 24,
        }
    )
    custom_curve = {h: 200.0 + (h * 5.0) for h in range(24)}
    asset_config = {
        "solar_kwp": 800.0,
        "grid_export_limit_kw": 400.0,
        "bess_capacity_kwh": 1500.0,
        "bess_max_charge_kw": 500.0,
        "bess_max_discharge_kw": 500.0,
        "bess_roundtrip_efficiency": 0.90,
        "baseline_load_kw": 300.0,
        "max_flexible_load_kw": 300.0,
        "custom_load_profile_kw": custom_curve,
    }

    res = simulate_commercial_dispatch(df_metrics=df_metrics, asset_config=asset_config, alpha=0.5)
    assert res["df_schedule"].iloc[0]["baseline_load_kw"] == 200.0
    assert res["df_schedule"].iloc[10]["baseline_load_kw"] == 250.0

    df_pareto = compute_pareto_frontier(df_metrics=df_metrics, asset_config=asset_config, steps=5)
    assert len(df_pareto) == 5
    assert "total_cost_eur" in df_pareto.columns
    assert "total_emissions_kg" in df_pareto.columns
