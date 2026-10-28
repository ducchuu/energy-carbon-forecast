try:
    import pytest
except ImportError:
    pytest = None

import sys
from unittest.mock import MagicMock, patch
import pandas as pd

st_mock = MagicMock()


def mock_decorator(*args, **kwargs):
    def decorator(func):
        return func

    if len(args) == 1 and callable(args[0]):
        return args[0]
    return decorator


st_mock.cache_data = mock_decorator
st_mock.cache_resource = mock_decorator
sys.modules["streamlit"] = st_mock

bq_mock = MagicMock()
sys.modules["google.cloud"] = MagicMock()
sys.modules["google.cloud.bigquery"] = bq_mock

from dashboard.data_fetcher import (  # noqa: E402
    load_asset_constraints,
    load_dispatch_schedule,
    load_gold_metrics,
    load_tennet_congestion,
    save_asset_constraints_to_bq,
)


@patch("dashboard.data_fetcher.get_bq_client")
def test_load_gold_metrics(mock_get_bq_client):
    mock_client = MagicMock()
    mock_client.project = "test-project"
    mock_get_bq_client.return_value = mock_client

    mock_query_job = MagicMock()
    mock_df = pd.DataFrame(
        {
            "timestamp_utc": ["2026-10-01T12:00:00"],
            "bidding_zone": ["10YNL----------L"],
            "price_eur_kwh": [0.10],
            "carbon_intensity_gco2_kwh": [200.0],
        }
    )
    mock_query_job.to_dataframe.return_value = mock_df
    mock_client.query.return_value = mock_query_job

    df = load_gold_metrics("10YNL----------L", "2026-10-01")

    assert not df.empty
    assert df.iloc[0]["price_eur_kwh"] == 0.10
    executed_sql = mock_client.query.call_args[0][0]
    assert "fct_hourly_grid_metrics" in executed_sql


@patch("dashboard.data_fetcher.get_bq_client")
def test_load_tennet_congestion_fallback(mock_get_bq_client):
    mock_client = MagicMock()
    mock_get_bq_client.return_value = mock_client
    mock_client.query.side_effect = Exception("BigQuery unavailable")

    df = load_tennet_congestion("10YNL----------L")

    assert not df.empty
    assert "is_congestion_active" in df.columns
    assert df.iloc[0]["bidding_zone"] == "10YNL----------L"
    assert bool(df.iloc[0]["is_congestion_active"]) is False


@patch("dashboard.data_fetcher.get_bq_client")
def test_load_asset_constraints_deduplicates_in_sql(mock_get_bq_client):
    mock_client = MagicMock()
    mock_client.project = "test-project"
    mock_get_bq_client.return_value = mock_client

    mock_query_job = MagicMock()
    mock_query_job.to_dataframe.return_value = pd.DataFrame(
        [
            {
                "asset_id": "NL-AMS-DC01",
                "bidding_zone": "10YNL----------L",
                "solar_kwp": 1400.0,
            }
        ]
    )
    mock_client.query.return_value = mock_query_job

    df = load_asset_constraints(bidding_zone="10YNL----------L")

    assert len(df) == 1
    assert df.iloc[0]["solar_kwp"] == 1400.0
    executed_sql = mock_client.query.call_args[0][0]
    assert "QUALIFY ROW_NUMBER() OVER (PARTITION BY asset_id ORDER BY updated_at DESC) = 1" in executed_sql


@patch("dashboard.data_fetcher.get_bq_client")
def test_load_asset_constraints_default_fallback(mock_get_bq_client):
    mock_client = MagicMock()
    mock_get_bq_client.return_value = mock_client
    mock_client.query.side_effect = Exception("Table not found")

    df = load_asset_constraints(bidding_zone="10YNL----------L")

    assert not df.empty
    assert "asset_id" in df.columns
    assert "bess_capacity_kwh" in df.columns
    assert "NL-AMS-DC01" in df["asset_id"].values


@patch("dashboard.data_fetcher.get_bq_client")
def test_load_dispatch_schedule(mock_get_bq_client):
    mock_client = MagicMock()
    mock_client.project = "test-project"
    mock_get_bq_client.return_value = mock_client

    mock_query_job = MagicMock()
    mock_query_job.to_dataframe.return_value = pd.DataFrame(
        [
            {
                "timestamp_utc": "2026-10-01T12:00:00Z",
                "asset_id": "NL-AMS-DC01",
                "dispatch_action": "CHARGE_BATTERY",
                "recommended_bess_kw": 500.0,
            }
        ]
    )
    mock_client.query.return_value = mock_query_job

    df = load_dispatch_schedule("10YNL----------L", "NL-AMS-DC01", "2026-10-01")

    assert not df.empty
    assert df.iloc[0]["dispatch_action"] == "CHARGE_BATTERY"
    executed_sql = mock_client.query.call_args[0][0]
    assert "fct_asset_dispatch_schedule" in executed_sql


@patch("dashboard.data_fetcher.get_bq_client")
def test_save_asset_constraints_to_bq(mock_get_bq_client):
    mock_client = MagicMock()
    mock_client.project = "test-project"
    mock_get_bq_client.return_value = mock_client
    mock_job = MagicMock()
    mock_client.load_table_from_dataframe.return_value = mock_job

    asset_dict = {
        "asset_id": "NL-AMS-DC01",
        "facility_name": "Amsterdam Cold Storage",
        "bidding_zone": "10YNL----------L",
        "solar_kwp": 1500.0,
        "grid_export_limit_kw": 800.0,
    }
    success = save_asset_constraints_to_bq(asset_dict)

    assert success is True
    loaded_df = mock_client.load_table_from_dataframe.call_args[0][0]
    assert loaded_df.iloc[0]["asset_id"] == "NL-AMS-DC01"
    assert "updated_at" in loaded_df.columns
