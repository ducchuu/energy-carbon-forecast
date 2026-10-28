try:
    import pytest
except ImportError:
    pytest = None

import pandas as pd

if pytest:
    @pytest.fixture
    def sample_generation_df():
        return pd.DataFrame(
            {
                "timestamp_utc": pd.date_range(start="2026-10-01", periods=4, freq="15min"),
                "bidding_zone": ["10YNL----------L"] * 4,
                "psr_type": ["B16"] * 4,
                "generation_mw": [100.0, 150.0, 200.0, 180.0],
            }
        )

    @pytest.fixture
    def sample_price_df():
        return pd.DataFrame(
            {
                "timestamp_utc": pd.date_range(start="2026-10-01", periods=2, freq="1h"),
                "bidding_zone": ["10YNL----------L"] * 2,
                "price_eur_mwh": [45.0, 50.0],
            }
        )
