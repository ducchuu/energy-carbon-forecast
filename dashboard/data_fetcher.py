import os
from typing import Any, Dict

import pandas as pd
import streamlit as st
from google.cloud import bigquery

from asset_config import get_default_assets_dataframe


@st.cache_resource
def get_bq_client() -> bigquery.Client:
    return bigquery.Client(project=os.environ.get("GCP_PROJECT_ID"))


@st.cache_data(ttl=3600, max_entries=10, show_spinner=False)
def load_gold_metrics(bidding_zone: str, anchor_date_iso: str) -> pd.DataFrame:
    try:
        client = get_bq_client()
        project_id = client.project
        dataset_id = os.environ.get("BQ_DATASET_GOLD", "energy_gold_dev")
        sql = f"""
            SELECT
                timestamp_utc,
                local_datetime,
                local_date,
                bidding_zone,
                is_forecasted,
                price_eur_kwh,
                carbon_intensity_gco2_kwh,
                renewable_share_pct,
                imbalance_shortage_eur_mwh,
                imbalance_surplus_eur_mwh,
                is_congestion_active,
                congestion_severity,
                export_limit_factor,
                norm_price,
                norm_ci
            FROM `{project_id}.{dataset_id}.fct_hourly_grid_metrics`
            WHERE DATE(timestamp_utc) >= DATE_SUB(@anchor_date, INTERVAL 1 DAY)
              AND bidding_zone = @bidding_zone
            ORDER BY timestamp_utc ASC
        """
        job_config = bigquery.QueryJobConfig(
            use_query_cache=True,
            maximum_bytes_billed=50 * 1024 * 1024,
            query_parameters=[
                bigquery.ScalarQueryParameter("bidding_zone", "STRING", bidding_zone),
                bigquery.ScalarQueryParameter("anchor_date", "DATE", anchor_date_iso),
            ],
        )
        return client.query(sql, job_config=job_config).to_dataframe()
    except Exception as exc:
        print(f"Error querying fct_hourly_grid_metrics: {exc}")
        return pd.DataFrame()


@st.cache_data(ttl=300, max_entries=10, show_spinner=False)
def load_tennet_congestion(bidding_zone: str) -> pd.DataFrame:
    try:
        client = get_bq_client()
        project_id = client.project
        dataset_id = os.environ.get("BQ_DATASET_SILVER", "energy_silver_dev")
        sql = f"""
            SELECT
                timestamp_utc,
                bidding_zone,
                substation_area,
                is_congestion_active,
                congestion_severity,
                min_export_limit_factor,
                total_redispatch_mw,
                message_details
            FROM `{project_id}.{dataset_id}.stg_tennet_congestion`
            WHERE bidding_zone = @bidding_zone
              AND timestamp_utc >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
            ORDER BY timestamp_utc DESC
        """
        job_config = bigquery.QueryJobConfig(
            use_query_cache=True,
            maximum_bytes_billed=25 * 1024 * 1024,
            query_parameters=[
                bigquery.ScalarQueryParameter("bidding_zone", "STRING", bidding_zone),
            ],
        )
        df = client.query(sql, job_config=job_config).to_dataframe()
        if not df.empty:
            return df
    except Exception as exc:
        print(f"Error querying stg_tennet_congestion: {exc}")

    return pd.DataFrame(
        [
            {
                "timestamp_utc": pd.Timestamp.utcnow(),
                "bidding_zone": bidding_zone,
                "substation_area": "NL-RANDSTAD-NORTH" if "NL" in bidding_zone else "REGIONAL-GRID",
                "is_congestion_active": False,
                "congestion_severity": "NONE",
                "min_export_limit_factor": 1.0,
                "total_redispatch_mw": 0.0,
                "message_details": "Nominal grid operating status (TenneT telemetry nominal)",
            }
        ]
    )


@st.cache_data(ttl=600, max_entries=10, show_spinner=False)
def load_asset_constraints(bidding_zone: str = None) -> pd.DataFrame:
    try:
        client = get_bq_client()
        project_id = client.project
        dataset_id = os.environ.get("BQ_DATASET_GOLD", "energy_gold_dev")
        sql = f"""
            SELECT
                asset_id,
                facility_name,
                bidding_zone,
                substation_area,
                solar_kwp,
                grid_export_limit_kw,
                bess_capacity_kwh,
                bess_max_charge_kw,
                bess_max_discharge_kw,
                bess_roundtrip_efficiency,
                bess_min_soc_pct,
                bess_max_soc_pct,
                baseline_load_kw,
                max_flexible_load_kw,
                thermal_shift_buffer_hours,
                alpha_weight,
                updated_at
            FROM `{project_id}.{dataset_id}.dim_asset_constraints`
            QUALIFY ROW_NUMBER() OVER (PARTITION BY asset_id ORDER BY updated_at DESC) = 1
            ORDER BY asset_id ASC
        """
        job_config = bigquery.QueryJobConfig(
            use_query_cache=True,
            maximum_bytes_billed=10 * 1024 * 1024,
        )
        df = client.query(sql, job_config=job_config).to_dataframe()
        if not df.empty:
            if bidding_zone:
                df = df[df["bidding_zone"] == bidding_zone].reset_index(drop=True)
            return df
    except Exception as exc:
        print(f"Using default asset profiles: {exc}")

    return get_default_assets_dataframe(bidding_zone)


@st.cache_data(ttl=900, max_entries=10, show_spinner=False)
def load_dispatch_schedule(
    bidding_zone: str, asset_id: str, anchor_date_iso: str
) -> pd.DataFrame:
    try:
        client = get_bq_client()
        project_id = client.project
        dataset_id = os.environ.get("BQ_DATASET_GOLD", "energy_gold_dev")
        sql = f"""
            SELECT
                timestamp_utc,
                local_datetime,
                local_date,
                bidding_zone,
                asset_id,
                facility_name,
                substation_area,
                is_forecasted,
                price_eur_kwh,
                carbon_intensity_gco2_kwh,
                renewable_share_pct,
                norm_price,
                norm_ci,
                composite_score,
                is_congestion_active,
                congestion_severity,
                congestion_message,
                estimated_solar_kw,
                effective_export_limit_kw,
                dispatch_action,
                flag_charge_battery,
                flag_curtail_solar,
                flag_ramp_load,
                flag_discharge_battery,
                recommended_bess_kw,
                recommended_flex_load_kw,
                curtailed_solar_kw,
                baseline_hourly_cost_eur,
                optimized_hourly_cost_eur,
                expected_cost_delta_eur
            FROM `{project_id}.{dataset_id}.fct_asset_dispatch_schedule`
            WHERE DATE(timestamp_utc) >= DATE_SUB(@anchor_date, INTERVAL 1 DAY)
              AND bidding_zone = @bidding_zone
              AND asset_id = @asset_id
            ORDER BY timestamp_utc ASC
        """
        job_config = bigquery.QueryJobConfig(
            use_query_cache=True,
            maximum_bytes_billed=50 * 1024 * 1024,
            query_parameters=[
                bigquery.ScalarQueryParameter("bidding_zone", "STRING", bidding_zone),
                bigquery.ScalarQueryParameter("asset_id", "STRING", asset_id),
                bigquery.ScalarQueryParameter("anchor_date", "DATE", anchor_date_iso),
            ],
        )
        return client.query(sql, job_config=job_config).to_dataframe()
    except Exception as exc:
        print(f"Error loading fct_asset_dispatch_schedule from BQ: {exc}")
        return pd.DataFrame()


def save_asset_constraints_to_bq(asset_dict: Dict[str, Any]) -> bool:
    try:
        client = get_bq_client()
        project_id = client.project
        dataset_id = os.environ.get("BQ_DATASET_GOLD", "energy_gold_dev")
        table_id = f"{project_id}.{dataset_id}.dim_asset_constraints"

        row = dict(asset_dict)
        row["updated_at"] = pd.Timestamp.now(tz="UTC")
        df_row = pd.DataFrame([row])

        job_config = bigquery.LoadJobConfig(
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        )
        job = client.load_table_from_dataframe(df_row, table_id, job_config=job_config)
        job.result()
        if hasattr(load_asset_constraints, "clear"):
            load_asset_constraints.clear()
        return True
    except Exception as exc:
        print(f"Could not persist asset constraints to BigQuery: {exc}")
        return False
