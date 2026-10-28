import os
from typing import Any, Dict, List, Optional

import pandas as pd
import requests

DEFAULT_TENNET_BASE_URL = "https://api.tennet.eu/publications/v1"


def get_tennet_headers() -> Dict[str, str]:
    api_key = os.environ.get("TENNET_API_KEY")
    if not api_key:
        raise ValueError("TENNET_API_KEY environment variable is not set.")
    return {
        "apikey": api_key,
        "Accept": "application/json",
    }


def _extract_records(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        if "Response" in payload and isinstance(payload["Response"], dict):
            time_series = payload["Response"].get("TimeSeries", [])
            if isinstance(time_series, dict):
                time_series = [time_series]
            records: List[Dict[str, Any]] = []
            for series in time_series:
                periods = series.get("Period", [])
                if isinstance(periods, dict):
                    periods = [periods]
                for period in periods:
                    points = period.get("Points", period.get("Point", []))
                    if isinstance(points, dict):
                        points = [points]
                    for pt in points:
                        records.append(pt)
            if records:
                return records
        for key in ("data", "records", "items", "points"):
            if key in payload and isinstance(payload[key], list):
                return payload[key]
    return []


def _first_present(rec: Dict[str, Any], keys: List[str]) -> Optional[Any]:
    for key in keys:
        if key in rec and rec[key] is not None:
            return rec[key]
    return None


def fetch_tennet_imbalance(
    bidding_zone: str = "10YNL----------L",
    lookback_minutes: int = 1440,
) -> pd.DataFrame:
    headers = get_tennet_headers()
    base_url = os.environ.get("TENNET_BASE_URL", DEFAULT_TENNET_BASE_URL).rstrip("/")
    end_time = pd.Timestamp.now(tz="UTC")
    start_time = end_time - pd.Timedelta(minutes=lookback_minutes)

    params = {
        "date_from": start_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "date_to": end_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    resp = requests.get(
        f"{base_url}/settlement-prices",
        headers=headers,
        params=params,
        timeout=30,
    )
    resp.raise_for_status()
    payload = resp.json()
    raw_records = _extract_records(payload)

    # If recent window had no published settlement prices due to TSO lag, fallback to 48-hour window
    if not raw_records and lookback_minutes < 2880:
        start_time_alt = end_time - pd.Timedelta(hours=48)
        params_alt = {
            "date_from": start_time_alt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "date_to": end_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        try:
            resp_alt = requests.get(
                f"{base_url}/settlement-prices",
                headers=headers,
                params=params_alt,
                timeout=30,
            )
            if resp_alt.status_code == 200:
                raw_records = _extract_records(resp_alt.json())
        except Exception:
            pass

    if not raw_records:
        return pd.DataFrame()

    rows = []
    ingested_at = pd.Timestamp.now(tz="UTC")
    for rec in raw_records:
        ts_raw = _first_present(
            rec,
            ["timestamp_utc", "timeInterval_start", "TimeIntervalStart", "timestamp"],
        )
        shortage_val = _first_present(rec, ["shortage", "imbalance_shortage_eur_mwh"])
        surplus_val = _first_present(rec, ["surplus", "imbalance_surplus_eur_mwh"])

        if not ts_raw or shortage_val is None or surplus_val is None:
            continue

        dispatch_up_val = _first_present(rec, ["dispatch_up", "dispatch_up_mw"])
        dispatch_down_val = _first_present(rec, ["dispatch_down", "dispatch_down_mw"])
        reg_state_val = _first_present(rec, ["regulation_state"])

        rows.append(
            {
                "timestamp_utc": pd.to_datetime(ts_raw, utc=True),
                "bidding_zone": bidding_zone,
                "isp_duration_minutes": int(rec.get("isp_duration_minutes", 15)),
                "imbalance_shortage_eur_mwh": float(shortage_val),
                "imbalance_surplus_eur_mwh": float(surplus_val),
                "dispatch_up_mw": float(dispatch_up_val) if dispatch_up_val is not None else 0.0,
                "dispatch_down_mw": float(dispatch_down_val) if dispatch_down_val is not None else 0.0,
                "regulation_state": int(reg_state_val) if reg_state_val is not None else 0,
                "ingested_at": ingested_at,
            }
        )
    return pd.DataFrame(rows)


def fetch_tennet_congestion(
    bidding_zone: str = "10YNL----------L",
    lookback_hours: int = 24,
) -> pd.DataFrame:
    headers = get_tennet_headers()
    base_url = os.environ.get("TENNET_BASE_URL", DEFAULT_TENNET_BASE_URL).rstrip("/")
    end_time = pd.Timestamp.now(tz="UTC")
    start_time = end_time - pd.Timedelta(hours=lookback_hours)

    params = {
        "date_from": start_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "date_to": end_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    resp = requests.get(
        f"{base_url}/congestion-management",
        headers=headers,
        params=params,
        timeout=30,
    )
    resp.raise_for_status()
    raw_records = _extract_records(resp.json())
    if not raw_records:
        return pd.DataFrame()

    rows = []
    ingested_at = pd.Timestamp.now(tz="UTC")
    for rec in raw_records:
        ts_raw = _first_present(
            rec,
            ["timestamp_utc", "timeInterval_start", "TimeIntervalStart", "timestamp"],
        )
        severity_raw = _first_present(rec, ["congestion_severity", "severity"])
        if not ts_raw or severity_raw is None:
            continue

        severity = str(severity_raw).upper()
        is_restricted = severity in ("ACTIVE_RESTRICTION", "CRITICAL_REDISPATCH")
        default_factor = 0.35 if is_restricted else 1.0
        export_factor_val = _first_present(rec, ["export_limit_factor"])
        redispatch_val = _first_present(rec, ["redispatch_volume_mw", "volume_mw"])

        rows.append(
            {
                "timestamp_utc": pd.to_datetime(ts_raw, utc=True),
                "bidding_zone": bidding_zone,
                "substation_area": str(rec.get("substation_area", "NL-RANDSTAD-NORTH")),
                "congestion_severity": severity,
                "export_limit_factor": float(
                    export_factor_val if export_factor_val is not None else default_factor
                ),
                "redispatch_volume_mw": float(
                    redispatch_val if redispatch_val is not None else 0.0
                ),
                "message_details": str(
                    rec.get("message_details", "Standard substation operating state")
                ),
                "ingested_at": ingested_at,
            }
        )
    return pd.DataFrame(rows)
