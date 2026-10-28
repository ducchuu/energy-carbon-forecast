import os
import sys
from unittest.mock import MagicMock, patch

import pandas as pd

entsoe_mock = MagicMock()
sys.modules["entsoe"] = entsoe_mock

from ingestion.entsoe_client import (  # noqa: E402
    fetch_actual_generation,
    fetch_day_ahead_prices,
    fetch_forecasts,
    normalize_psr_code,
)


def test_normalize_psr_code():
    assert normalize_psr_code("Solar") == "B16"
    assert normalize_psr_code("Fossil Gas") == "B04"
    assert normalize_psr_code("Nuclear") == "B14"
    assert normalize_psr_code("Wind Onshore") == "B19"
    assert normalize_psr_code("B16") == "B16"
    assert normalize_psr_code("B04") == "B04"


@patch.dict(os.environ, {"ENTSOE_API_KEY": "fake_key"})
def test_fetch_actual_generation():
    mock_client = MagicMock()
    entsoe_mock.EntsoePandasClient.return_value = mock_client

    mock_ts = pd.Series(
        [100.0, 150.0],
        index=pd.date_range("2026-10-01", periods=2, freq="1h", tz="Europe/Amsterdam"),
    )
    mock_df = pd.DataFrame({"B16": mock_ts})
    mock_client.query_generation.return_value = mock_df

    df = fetch_actual_generation("10YNL----------L", lookback_hours=24)

    assert not df.empty
    assert "psr_type" in df.columns
    assert "generation_mw" in df.columns
    assert df.iloc[0]["psr_type"] == "B16"
    assert df.iloc[0]["generation_mw"] == 100.0


@patch.dict(os.environ, {"ENTSOE_API_KEY": "fake_key"})
def test_fetch_actual_generation_multiindex():
    mock_client = MagicMock()
    entsoe_mock.EntsoePandasClient.return_value = mock_client

    idx = pd.date_range("2026-10-01", periods=2, freq="1h", tz="UTC")
    cols = pd.MultiIndex.from_tuples(
        [("B10", "Actual Aggregated"), ("B10", "Actual Consumption"), ("B16", "Actual Aggregated")]
    )
    mock_df = pd.DataFrame([[50.0, 10.0, 200.0], [60.0, 15.0, 250.0]], index=idx, columns=cols)
    mock_client.query_generation.return_value = mock_df

    df = fetch_actual_generation("10YNL----------L", lookback_hours=24)

    b10_rows = df[df["psr_type"] == "B10"].sort_values("timestamp_utc")
    assert len(b10_rows) == 2
    assert b10_rows.iloc[0]["generation_mw"] == 50.0


@patch.dict(os.environ, {"ENTSOE_API_KEY": "fake_key"})
def test_fetch_day_ahead_prices_resamples_hourly():
    mock_client = MagicMock()
    entsoe_mock.EntsoePandasClient.return_value = mock_client

    idx = pd.to_datetime(["2026-10-01 00:00:00Z", "2026-10-01 02:00:00Z"])
    mock_ts = pd.Series([80.0, 100.0], index=idx)
    mock_client.query_day_ahead_prices.return_value = mock_ts

    df = fetch_day_ahead_prices("10YNL----------L", horizon_hours=4)

    assert len(df) == 3
    assert list(df["price_eur_mwh"]) == [80.0, 80.0, 100.0]


@patch.dict(os.environ, {"ENTSOE_API_KEY": "fake_key"})
def test_fetch_forecasts_combines_wind_solar_and_load():
    mock_client = MagicMock()
    entsoe_mock.EntsoePandasClient.return_value = mock_client

    idx = pd.date_range("2026-10-01 00:00:00Z", periods=2, freq="1h")
    df_ws = pd.DataFrame(
        {"Solar": [100.0, 200.0], "Wind Onshore": [300.0, 400.0]},
        index=idx,
    )
    ts_load = pd.Series([10000.0, 10500.0], index=idx)

    mock_client.query_wind_and_solar_forecast.return_value = df_ws
    mock_client.query_load_forecast.return_value = ts_load

    df = fetch_forecasts("10YNL----------L", horizon_hours=2)

    assert set(df["metric_type"]) == {"SOLAR", "WIND_ONSHORE", "TOTAL_LOAD"}
    assert len(df) == 6
