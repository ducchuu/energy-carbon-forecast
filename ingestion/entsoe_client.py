import os
import pandas as pd
import requests
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

CROSS_BORDER_NEIGHBORS = {
    "10YNL----------L": [
        "10Y1001A1001A82H",  # Germany-Luxembourg
        "10YBE----------2",  # Belgium
        "10YNO-2--------T",  # Norway NO2 (NorNed)
    ],
    "10Y1001A1001A82H": [
        "10YNL----------L",  # Netherlands
        "10YFR-RTE------Q",  # France
        "10YAT-APG------L",  # Austria
    ],
    "10YPL-AREA-----S": [
        "10Y1001A1001A82H",  # Germany-Luxembourg
        "10YCZ-CEPS-----N",  # Czechia
    ],
}


class TimeoutSession(requests.Session):
    def __init__(self, timeout=20):
        super().__init__()
        self.timeout = timeout

    def request(self, *args, **kwargs):
        if "timeout" not in kwargs or kwargs["timeout"] is None:
            kwargs["timeout"] = self.timeout
        return super().request(*args, **kwargs)


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
    session = TimeoutSession(timeout=20)
    return EntsoePandasClient(api_key=api_key, session=session, retry_count=2, retry_delay=2)


def fetch_actual_generation(bidding_zone: str, lookback_hours: int) -> pd.DataFrame:
    client = get_entsoe_client()
    end_time = pd.Timestamp.now(tz="UTC").floor("h")
    start_time = end_time - pd.Timedelta(hours=lookback_hours)

    print(f"  [ENTSO-E] Fetching actual generation for {bidding_zone} (last {lookback_hours}h)...")
    try:
        df = client.query_generation(bidding_zone, start=start_time, end=end_time)
    except Exception as exc:
        print(f"  [ENTSO-E] Notice: Actual generation query failed for {bidding_zone}: {exc}")
        return pd.DataFrame()

    if df is None or df.empty:
        print(f"  [ENTSO-E] No generation records returned for {bidding_zone}")
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
    cleaned = df.dropna(subset=["generation_mw"])
    print(f"  [ENTSO-E] Successfully parsed {len(cleaned)} generation records for {bidding_zone}")
    return cleaned


def fetch_day_ahead_prices(bidding_zone: str, horizon_hours: int) -> pd.DataFrame:
    client = get_entsoe_client()
    start_time = pd.Timestamp.now(tz="UTC").floor("D")
    end_time = start_time + pd.Timedelta(hours=horizon_hours)

    print(f"  [ENTSO-E] Fetching day-ahead prices for {bidding_zone} (horizon {horizon_hours}h)...")
    try:
        ts = client.query_day_ahead_prices(bidding_zone, start=start_time, end=end_time)
    except Exception as exc:
        print(f"  [ENTSO-E] Notice: Day-ahead price query failed for {bidding_zone}: {exc}")
        return pd.DataFrame()

    if ts is None or ts.empty:
        print(f"  [ENTSO-E] No day-ahead price records returned for {bidding_zone}")
        return pd.DataFrame()

    if isinstance(ts, pd.DataFrame):
        ts = ts.iloc[:, 0]

    ts = ts.resample("1h").ffill()

    df = ts.reset_index()
    df.columns = ["timestamp_utc", "price_eur_mwh"]
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    df["bidding_zone"] = bidding_zone
    df["ingested_at"] = pd.Timestamp.now(tz="UTC")
    cleaned = df.dropna(subset=["price_eur_mwh"])
    print(f"  [ENTSO-E] Successfully parsed {len(cleaned)} hourly price records for {bidding_zone}")
    return cleaned


def fetch_forecasts(bidding_zone: str, horizon_hours: int) -> pd.DataFrame:
    client = get_entsoe_client()
    start_time = pd.Timestamp.now(tz="UTC").floor("D")
    end_time = start_time + pd.Timedelta(hours=horizon_hours + 1)

    print(f"  [ENTSO-E] Fetching wind/solar and load forecasts for {bidding_zone}...")
    forecasts = []

    try:
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
    except Exception as exc:
        print(f"  [ENTSO-E] Notice: Wind/solar forecast unavailable for {bidding_zone}: {exc}")

    try:
        ts_load = client.query_load_forecast(bidding_zone, start=start_time, end=end_time)
        if ts_load is not None and not ts_load.empty:
            if isinstance(ts_load, pd.DataFrame):
                ts_load = ts_load.iloc[:, 0]
            ts_load = ts_load.resample("1h").mean()
            df_load = ts_load.reset_index()
            df_load.columns = ["timestamp_utc", "forecast_mw"]
            df_load["metric_type"] = "TOTAL_LOAD"
            forecasts.append(df_load)
    except Exception as exc:
        print(f"  [ENTSO-E] Notice: Load forecast unavailable for {bidding_zone}: {exc}")

    if not forecasts:
        print(f"  [ENTSO-E] No forecasts returned for {bidding_zone}")
        return pd.DataFrame()

    df = pd.concat(forecasts, ignore_index=True)
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    df["bidding_zone"] = bidding_zone
    df["ingested_at"] = pd.Timestamp.now(tz="UTC")
    cleaned = df.dropna(subset=["forecast_mw"])
    print(f"  [ENTSO-E] Successfully parsed {len(cleaned)} forecast records for {bidding_zone}")
    return cleaned


def fetch_crossborder_flows(bidding_zone: str, lookback_hours: int) -> pd.DataFrame:
    client = get_entsoe_client()
    end_time = pd.Timestamp.now(tz="UTC").floor("h")
    start_time = end_time - pd.Timedelta(hours=lookback_hours)

    neighbors = CROSS_BORDER_NEIGHBORS.get(bidding_zone, [])
    flow_frames = []

    print(f"  [ENTSO-E] Fetching cross-border flows into {bidding_zone} ({len(neighbors)} neighbors)...")
    for neighbor_zone in neighbors:
        try:
            print(f"    -> Querying border: {neighbor_zone} -> {bidding_zone}...")
            ts = client.query_crossborder_flows(
                country_code_from=neighbor_zone,
                country_code_to=bidding_zone,
                start=start_time,
                end=end_time,
            )
            if ts is None or ts.empty:
                continue
            if isinstance(ts, pd.DataFrame):
                ts = ts.iloc[:, 0]
            ts = ts.resample("1h").mean()
            df_flow = ts.reset_index()
            df_flow.columns = ["timestamp_utc", "flow_mw"]
            df_flow["timestamp_utc"] = pd.to_datetime(df_flow["timestamp_utc"], utc=True)
            df_flow["from_zone"] = neighbor_zone
            df_flow["to_zone"] = bidding_zone
            df_flow["bidding_zone"] = bidding_zone
            df_flow["ingested_at"] = pd.Timestamp.now(tz="UTC")
            cleaned = df_flow.dropna(subset=["flow_mw"])
            print(f"       Retrieved {len(cleaned)} flow readings.")
            flow_frames.append(cleaned)
        except Exception as exc:
            print(f"       Notice: Border flow {neighbor_zone} -> {bidding_zone} unavailable ({exc})")

    if not flow_frames:
        return pd.DataFrame()

    total_df = pd.concat(flow_frames, ignore_index=True)
    print(f"  [ENTSO-E] Total cross-border records loaded for {bidding_zone}: {len(total_df)}")
    return total_df
