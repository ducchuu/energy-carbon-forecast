import json
import os
import sys
from dotenv import load_dotenv

load_dotenv(override=True)
sys.path.append(os.path.join(os.path.dirname(__file__), "ingestion"))

from ingestion.bq_loader import ensure_bronze_tables_exist
from ingestion.main import ingest_entsoe_data


class MockRequest:
    def __init__(self, json_data):
        self._json = json_data

    def get_json(self, silent=True):
        return self._json


def run_local_ingestion():
    project_id = os.environ.get("GCP_PROJECT_ID", "energy-carbon")
    dataset_id = os.environ.get(
        "BQ_DATASET", os.environ.get("BQ_DATASET_BRONZE", "energy_bronze_dev")
    )

    print(f"Ensuring all Bronze tables exist in BigQuery ({project_id}.{dataset_id})...")
    ensure_bronze_tables_exist(project_id, dataset_id)

    print("\n[Step 1/4] Ingesting 'actual_generation' (raw_generation_actuals)...")
    req1 = MockRequest({"job_type": "actual_generation", "lookback_hours": 24})
    response1, status1 = ingest_entsoe_data(req1)
    print(f"Result: {status1} - {response1}\n")

    print("[Step 2/4] Ingesting 'crossborder_flows' (raw_crossborder_flows)...")
    req_flows = MockRequest({"job_type": "crossborder_flows", "lookback_hours": 24})
    response_flows, status_flows = ingest_entsoe_data(req_flows)
    print(f"Result: {status_flows} - {response_flows}\n")

    print("[Step 3/4] Ingesting 'day_ahead_prices_and_forecasts' (prices & VRE/load forecasts)...")
    req2 = MockRequest({"job_type": "day_ahead_prices_and_forecasts", "horizon_hours": 36})
    response2, status2 = ingest_entsoe_data(req2)
    print(f"Result: {status2} - {response2}\n")

    print("[Step 4/4] Ingesting 'tennet_realtime' (settlement imbalance & congestion restrictions)...")
    req3 = MockRequest(
        {"job_type": "tennet_realtime", "lookback_minutes": 1440, "lookback_hours": 24}
    )
    response3, status3 = ingest_entsoe_data(req3)
    print(f"Result: {status3} - {response3}\n")


if __name__ == "__main__":
    if not os.environ.get("ENTSOE_API_KEY"):
        print("!!!!!!!!!Warning!!!!!!!!!: ENTSOE_API_KEY is not set in your environment variables.")
        print("Please copy .env.example to .env and add your API key.")
    else:
        run_local_ingestion()
