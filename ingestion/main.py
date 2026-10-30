import json
import os
import pandas as pd

from bq_loader import batch_load_dataframe_to_bronze
from entsoe_client import (
    fetch_actual_generation,
    fetch_crossborder_flows,
    fetch_day_ahead_prices,
    fetch_forecasts,
)
from tennet_client import fetch_tennet_congestion, fetch_tennet_imbalance


DEFAULT_BIDDING_ZONES = [
    "10YNL----------L",      # Netherlands
    "10Y1001A1001A82H",     # Germany-Luxembourg
    "10YPL-AREA-----S",     # Poland
]


def ingest_entsoe_data(request):
    """
    HTTP Cloud Function entry point for ENTSO-E and TenneT data ingestion.
    Returns structured JSON with row counts for observability.
    """
    request_json = request.get_json(silent=True)
    if not request_json:
        return json.dumps({"error": "Invalid or missing JSON payload"}), 400

    job_type = request_json.get("job_type")
    project_id = os.environ.get("GCP_PROJECT_ID")
    dataset_id = os.environ.get("BQ_DATASET", os.environ.get("BQ_DATASET_BRONZE", "energy_bronze_dev"))

    if not project_id:
        return json.dumps({"error": "GCP_PROJECT_ID environment variable is not set"}), 500

    # Determine bidding zones to ingest
    if request_json.get("bidding_zones"):
        zones = request_json.get("bidding_zones")
    elif request_json.get("bidding_zone"):
        zones = [request_json.get("bidding_zone")]
    elif os.environ.get("BIDDING_ZONES"):
        zones = [z.strip() for z in os.environ["BIDDING_ZONES"].split(",") if z.strip()]
    elif os.environ.get("BIDDING_ZONE") and os.environ.get("BIDDING_ZONE") != "10YNL----------L":
        zones = [os.environ.get("BIDDING_ZONE")]
    else:
        zones = DEFAULT_BIDDING_ZONES

    summary = {"job_type": job_type, "bidding_zones": zones, "rows_loaded": {}}

    try:
        if job_type == "actual_generation":
            lookback_hours = int(request_json.get("lookback_hours", 24))
            gen_frames = []
            for z in zones:
                try:
                    df_z = fetch_actual_generation(z, lookback_hours)
                    if df_z is not None and not df_z.empty:
                        gen_frames.append(df_z)
                except Exception as exc:
                    print(f"Error fetching actual generation for {z}: {exc}")

            if not gen_frames:
                return (
                    json.dumps(
                        {"warning": "No actual generation records fetched", "job_type": job_type}
                    ),
                    200,
                )

            df_gen = pd.concat(gen_frames, ignore_index=True)
            rows = batch_load_dataframe_to_bronze(
                df_gen, project_id, dataset_id, "raw_generation_actuals"
            )
            summary["rows_loaded"]["raw_generation_actuals"] = rows

        elif job_type == "crossborder_flows":
            lookback_hours = int(request_json.get("lookback_hours", 24))
            flow_frames = []
            for z in zones:
                try:
                    df_fl = fetch_crossborder_flows(z, lookback_hours)
                    if df_fl is not None and not df_fl.empty:
                        flow_frames.append(df_fl)
                except Exception as exc:
                    print(f"Error fetching crossborder flows for {z}: {exc}")

            if flow_frames:
                df_flows = pd.concat(flow_frames, ignore_index=True)
                rows_fl = batch_load_dataframe_to_bronze(
                    df_flows, project_id, dataset_id, "raw_crossborder_flows"
                )
                summary["rows_loaded"]["raw_crossborder_flows"] = rows_fl
            else:
                summary["rows_loaded"]["raw_crossborder_flows"] = 0

        elif job_type == "day_ahead_prices_and_forecasts":
            horizon_hours = int(request_json.get("horizon_hours", 36))

            price_frames = []
            forecast_frames = []

            for z in zones:
                try:
                    df_p = fetch_day_ahead_prices(z, horizon_hours)
                    if df_p is not None and not df_p.empty:
                        price_frames.append(df_p)
                except Exception as exc:
                    print(f"Error fetching prices for {z}: {exc}")

                try:
                    df_f = fetch_forecasts(z, horizon_hours)
                    if df_f is not None and not df_f.empty:
                        forecast_frames.append(df_f)
                except Exception as exc:
                    print(f"Error fetching forecasts for {z}: {exc}")

            if price_frames:
                df_prices = pd.concat(price_frames, ignore_index=True)
                rows_p = batch_load_dataframe_to_bronze(
                    df_prices, project_id, dataset_id, "raw_day_ahead_prices"
                )
                summary["rows_loaded"]["raw_day_ahead_prices"] = rows_p
            else:
                summary["rows_loaded"]["raw_day_ahead_prices"] = 0

            if forecast_frames:
                df_forecasts = pd.concat(forecast_frames, ignore_index=True)
                rows_f = batch_load_dataframe_to_bronze(
                    df_forecasts, project_id, dataset_id, "raw_grid_forecasts"
                )
                summary["rows_loaded"]["raw_grid_forecasts"] = rows_f
            else:
                summary["rows_loaded"]["raw_grid_forecasts"] = 0

        elif job_type in ("tennet_realtime", "tennet_imbalance_and_congestion"):
            # TenneT telemetry specifically covers the Netherlands bidding zone
            tennet_zone = "10YNL----------L"
            lookback_minutes = int(request_json.get("lookback_minutes", 1440))
            lookback_hours = int(request_json.get("lookback_hours", 24))

            try:
                df_imb = fetch_tennet_imbalance(tennet_zone, lookback_minutes=lookback_minutes)
            except Exception as exc:
                print(f"TenneT imbalance error: {exc}")
                df_imb = pd.DataFrame()

            rows_i = batch_load_dataframe_to_bronze(
                df_imb, project_id, dataset_id, "raw_tennet_imbalance"
            )
            summary["rows_loaded"]["raw_tennet_imbalance"] = rows_i

            try:
                df_cong = fetch_tennet_congestion(tennet_zone, lookback_hours=lookback_hours)
            except Exception as exc:
                print(f"TenneT congestion error: {exc}")
                df_cong = pd.DataFrame()

            rows_c = batch_load_dataframe_to_bronze(
                df_cong, project_id, dataset_id, "raw_tennet_congestion"
            )
            summary["rows_loaded"]["raw_tennet_congestion"] = rows_c

        else:
            return json.dumps({"error": f"Unknown job_type: {job_type}"}), 400

    except Exception as exc:
        return json.dumps({"error": str(exc), "job_type": job_type}), 500

    return json.dumps(summary), 200
