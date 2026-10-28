import os
from unittest.mock import MagicMock, patch

import pytest
import requests

from ingestion.tennet_client import (
    _extract_records,
    fetch_tennet_congestion,
    fetch_tennet_imbalance,
)


@patch.dict(os.environ, {"TENNET_API_KEY": "fake_tennet_key"})
@patch("ingestion.tennet_client.requests.get")
def test_fetch_tennet_imbalance(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "records": [
            {
                "timestamp_utc": "2026-10-01T12:00:00Z",
                "isp_duration_minutes": 15,
                "shortage": 85.5,
                "surplus": 72.0,
                "dispatch_up": 120.0,
                "dispatch_down": 0.0,
                "regulation_state": 1,
            }
        ]
    }
    mock_get.return_value = mock_resp

    df = fetch_tennet_imbalance("10YNL----------L", lookback_minutes=60)

    assert not df.empty
    assert "imbalance_shortage_eur_mwh" in df.columns
    assert df.iloc[0]["imbalance_shortage_eur_mwh"] == 85.5
    assert df.iloc[0]["bidding_zone"] == "10YNL----------L"

    called_params = mock_get.call_args.kwargs["params"]
    assert called_params["date_from"].endswith("Z")
    assert called_params["date_to"].endswith("Z")


@patch.dict(os.environ, {"TENNET_API_KEY": "fake_tennet_key"})
@patch("ingestion.tennet_client.requests.get")
def test_fetch_tennet_imbalance_skips_missing_core_numerics(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "Response": {
            "TimeSeries": [
                {
                    "Period": {
                        "Points": [
                            {"TimeIntervalStart": "2026-10-01T12:00:00Z"},
                            {
                                "TimeIntervalStart": "2026-10-01T12:15:00Z",
                                "shortage": 110.0,
                                "surplus": 95.0,
                            },
                        ]
                    }
                }
            ]
        }
    }
    mock_get.return_value = mock_resp

    df = fetch_tennet_imbalance("10YNL----------L", lookback_minutes=60)

    assert len(df) == 1
    assert df.iloc[0]["imbalance_shortage_eur_mwh"] == 110.0
    assert df.iloc[0]["imbalance_surplus_eur_mwh"] == 95.0


@patch.dict(os.environ, {"TENNET_API_KEY": "fake_tennet_key"})
@patch("ingestion.tennet_client.requests.get")
def test_fetch_tennet_imbalance_propagates_http_errors(mock_get):
    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = requests.HTTPError("401 Unauthorized")
    mock_get.return_value = mock_resp

    with pytest.raises(requests.HTTPError):
        fetch_tennet_imbalance("10YNL----------L", lookback_minutes=60)


@patch.dict(os.environ, {"TENNET_API_KEY": "fake_tennet_key"})
@patch("ingestion.tennet_client.requests.get")
def test_fetch_tennet_congestion(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "records": [
            {
                "timestamp_utc": "2026-10-01T12:00:00Z",
                "substation_area": "NL-RANDSTAD-NORTH",
                "congestion_severity": "ACTIVE_RESTRICTION",
                "export_limit_factor": 0.35,
                "redispatch_volume_mw": 150.0,
                "message_details": "Substation export bottleneck. Active curtailment required.",
            }
        ]
    }
    mock_get.return_value = mock_resp

    df = fetch_tennet_congestion("10YNL----------L", lookback_hours=24)

    assert not df.empty
    assert df.iloc[0]["congestion_severity"] == "ACTIVE_RESTRICTION"
    assert df.iloc[0]["export_limit_factor"] == 0.35
    assert df.iloc[0]["substation_area"] == "NL-RANDSTAD-NORTH"


def test_extract_records_nested_timeseries():
    payload = {
        "Response": {
            "TimeSeries": [
                {
                    "Period": [
                        {
                            "Points": [
                                {"timestamp_utc": "2026-10-01T10:00:00Z", "shortage": 50.0}
                            ]
                        }
                    ]
                }
            ]
        }
    }
    extracted = _extract_records(payload)
    assert len(extracted) == 1
    assert extracted[0]["shortage"] == 50.0
