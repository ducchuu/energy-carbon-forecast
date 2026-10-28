import os
import pandas as pd
from entsoe import EntsoePandasClient

REVERSE_PSRTYPE_MAPPINGS = {
    "Biomass": "B01",
    "Fossil Brown coal/Lignite": "B02",
    "Fossil Brown Coal / Lignite": "B02",
    "Fossil Coal-derived gas": "B03",
    "Fossil Coal-Derived Gas": "B03",
    "Fossil Gas": "B04",
    "Fossil Hard coal": "B05",
    "Fossil Hard Coal": "B05",
    "Fossil Oil": "B06",
    "Fossil Oil shale": "B07",
    "Fossil Oil Shale": "B07",
    "Fossil Peat": "B08",
    "Geothermal": "B09",
    "Hydro Pumped Storage": "B10",
    "Hydro Run-of-river and pondage": "B11",
    "Hydro Run-of-River and Poundage": "B11",
    "Hydro Water Reservoir": "B12",
    "Marine": "B13",
    "Nuclear": "B14",
    "Other renewable": "B15",
    "Other Renewable": "B15",
    "Solar": "B16",
    "Solar Photovoltaic": "B16",
    "Waste": "B17",
    "Wind Offshore": "B18",
    "Wind Onshore": "B19",
    "Other": "B20",
    "Energy storage": "B25",
}
NORMALIZED_PSR_MAPPINGS = {k.strip().lower(): v for k, v in REVERSE_PSRTYPE_MAPPINGS.items()}


def normalize_psr_code(raw_val: str) -> str:
    if not isinstance(raw_val, str):
        return str(raw_val)
    val_clean = raw_val.strip()
    if val_clean in REVERSE_PSRTYPE_MAPPINGS:
        return REVERSE_PSRTYPE_MAPPINGS[val_clean]
    lower_val = val_clean.lower()
    if lower_val in NORMALIZED_PSR_MAPPINGS:
        return NORMALIZED_PSR_MAPPINGS[lower_val]
    return val_clean


def get_entsoe_client() -> EntsoePandasClient:
    api_key = os.environ.get("ENTSOE_API_KEY")
    if not api_key:
        raise ValueError("ENTSOE_API_KEY environment variable is not set.")
    return EntsoePandasClient(api_key=api_key)


def fetch_actual_generation(bidding_zone: str, lookback_hours: int) -> pd.DataFrame:
    client = get_entsoe_client()
    end_time = pd.Timestamp.now(tz="UTC")
    start_time = end_time - pd.Timedelta(hours=lookback_hours)

    df = client.query_generation(bidding_zone, start=start_time, end=end_time)
    if df is None or df.empty:
        return pd.DataFrame()

    if isinstance(df.columns, pd.MultiIndex):
        level_1_vals = df.columns.get_level_values(1)
        if "Actual Aggregated" in level_1_vals:
            df = df.xs("Actual Aggregated", axis=1, level=1)
        else:
            df = df.droplevel(1, axis=1)
        df = df.T.groupby(level=0).sum().T

    df = df.reset_index().melt(
        id_vars=["index"], var_name="psr_type", value_name="generation_mw"
    )
    df.rename(columns={"index": "timestamp_utc"}, inplace=True)
    df["psr_type"] = df["psr_type"].apply(normalize_psr_code)
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    df["bidding_zone"] = bidding_zone
    df["ingested_at"] = pd.Timestamp.now(tz="UTC")
    return df.dropna(subset=["generation_mw"])


def fetch_day_ahead_prices(bidding_zone: str, horizon_hours: int) -> pd.DataFrame:
    client = get_entsoe_client()
    start_time = pd.Timestamp.now(tz="UTC").floor("D")
    end_time = start_time + pd.Timedelta(hours=horizon_hours)

    ts = client.query_day_ahead_prices(bidding_zone, start=start_time, end=end_time)
    if ts is None or ts.empty:
        return pd.DataFrame()

    if isinstance(ts, pd.DataFrame):
        ts = ts.iloc[:, 0]

    ts = ts.resample("1h").ffill()

    df = ts.reset_index()
    df.columns = ["timestamp_utc", "price_eur_mwh"]
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    df["bidding_zone"] = bidding_zone
    df["ingested_at"] = pd.Timestamp.now(tz="UTC")
    return df.dropna(subset=["price_eur_mwh"])


def fetch_forecasts(bidding_zone: str, horizon_hours: int) -> pd.DataFrame:
    client = get_entsoe_client()
    start_time = pd.Timestamp.now(tz="UTC").floor("D")
    end_time = start_time + pd.Timedelta(hours=horizon_hours + 1)

    forecasts = []

    df_ws = client.query_wind_and_solar_forecast(bidding_zone, start=start_time, end=end_time)
    if df_ws is not None and not df_ws.empty:
        df_ws = df_ws.resample("1h").mean().reset_index()
        df_ws = df_ws.melt(id_vars=["index"], var_name="metric_type", value_name="forecast_mw")
        df_ws.rename(columns={"index": "timestamp_utc"}, inplace=True)

        mapping = {
            "Solar": "SOLAR",
            "Wind Onshore": "WIND_ONSHORE",
            "Wind Offshore": "WIND_OFFSHORE",
        }
        df_ws["metric_type"] = df_ws["metric_type"].map(mapping)
        df_ws = df_ws.dropna(subset=["metric_type", "forecast_mw"])
        forecasts.append(df_ws)

    ts_load = client.query_load_forecast(bidding_zone, start=start_time, end=end_time)
    if ts_load is not None and not ts_load.empty:
        if isinstance(ts_load, pd.DataFrame):
            ts_load = ts_load.iloc[:, 0]
        ts_load = ts_load.resample("1h").mean()
        df_load = ts_load.reset_index()
        df_load.columns = ["timestamp_utc", "forecast_mw"]
        df_load["metric_type"] = "TOTAL_LOAD"
        forecasts.append(df_load)

    if not forecasts:
        return pd.DataFrame()

    df = pd.concat(forecasts, ignore_index=True)
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    df["bidding_zone"] = bidding_zone
    df["ingested_at"] = pd.Timestamp.now(tz="UTC")
    return df.dropna(subset=["forecast_mw"])
