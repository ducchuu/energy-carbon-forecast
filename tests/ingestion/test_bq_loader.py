try:
    import pytest
except ImportError:
    pytest = None

import sys
from unittest.mock import MagicMock, patch
import pandas as pd

bq_mock = MagicMock()
sys.modules["google.cloud"] = MagicMock()
sys.modules["google.cloud.bigquery"] = bq_mock

from ingestion.bq_loader import batch_load_dataframe_to_bronze  # noqa: E402


def test_batch_load_dataframe_to_bronze():
    mock_client = MagicMock()
    mock_load_job = MagicMock()
    mock_load_job.output_rows = 5
    mock_client.load_table_from_dataframe.return_value = mock_load_job

    df = pd.DataFrame(
        {
            "timestamp_utc": pd.date_range(start="2026-10-01", periods=5, freq="1h", tz="UTC"),
            "bidding_zone": ["10YNL----------L"] * 5,
            "psr_type": ["B16"] * 5,
            "generation_mw": [100.0, 150.0, 200.0, 180.0, 120.0],
            "ingested_at": pd.Timestamp.now(tz="UTC"),
        }
    )

    with patch("ingestion.bq_loader.bigquery") as mock_bq:
        mock_bq.Client.return_value = mock_client
        mock_bq.WriteDisposition.WRITE_APPEND = "WRITE_APPEND"
        mock_bq.TimePartitioningType.DAY = "DAY"
        mock_bq.TimePartitioning.return_value = MagicMock()
        mock_bq.LoadJobConfig.return_value = MagicMock()
        mock_bq.SchemaField = MagicMock()

        rows = batch_load_dataframe_to_bronze(
            df, "test-project", "energy_bronze", "raw_generation_actuals"
        )

    assert rows == 5
    mock_client.load_table_from_dataframe.assert_called_once()


def test_batch_load_empty_df_returns_zero():
    df = pd.DataFrame()
    rows = batch_load_dataframe_to_bronze(
        df, "test-project", "energy_bronze", "raw_generation_actuals"
    )
    assert rows == 0
