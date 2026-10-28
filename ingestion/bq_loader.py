import pandas as pd
from google.cloud import bigquery

SCHEMAS = {
    "raw_generation_actuals": [
        bigquery.SchemaField("timestamp_utc", "TIMESTAMP", mode="REQUIRED"),
        bigquery.SchemaField("bidding_zone", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("psr_type", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("generation_mw", "FLOAT64", mode="NULLABLE"),
        bigquery.SchemaField("ingested_at", "TIMESTAMP", mode="REQUIRED"),
    ],
    "raw_day_ahead_prices": [
        bigquery.SchemaField("timestamp_utc", "TIMESTAMP", mode="REQUIRED"),
        bigquery.SchemaField("bidding_zone", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("price_eur_mwh", "FLOAT64", mode="NULLABLE"),
        bigquery.SchemaField("ingested_at", "TIMESTAMP", mode="REQUIRED"),
    ],
    "raw_grid_forecasts": [
        bigquery.SchemaField("timestamp_utc", "TIMESTAMP", mode="REQUIRED"),
        bigquery.SchemaField("bidding_zone", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("metric_type", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("forecast_mw", "FLOAT64", mode="NULLABLE"),
        bigquery.SchemaField("ingested_at", "TIMESTAMP", mode="REQUIRED"),
    ],
    "raw_tennet_imbalance": [
        bigquery.SchemaField("timestamp_utc", "TIMESTAMP", mode="REQUIRED"),
        bigquery.SchemaField("bidding_zone", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("isp_duration_minutes", "INT64", mode="NULLABLE"),
        bigquery.SchemaField("imbalance_shortage_eur_mwh", "FLOAT64", mode="NULLABLE"),
        bigquery.SchemaField("imbalance_surplus_eur_mwh", "FLOAT64", mode="NULLABLE"),
        bigquery.SchemaField("dispatch_up_mw", "FLOAT64", mode="NULLABLE"),
        bigquery.SchemaField("dispatch_down_mw", "FLOAT64", mode="NULLABLE"),
        bigquery.SchemaField("regulation_state", "INT64", mode="NULLABLE"),
        bigquery.SchemaField("ingested_at", "TIMESTAMP", mode="REQUIRED"),
    ],
    "raw_tennet_congestion": [
        bigquery.SchemaField("timestamp_utc", "TIMESTAMP", mode="REQUIRED"),
        bigquery.SchemaField("bidding_zone", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("substation_area", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("congestion_severity", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("export_limit_factor", "FLOAT64", mode="NULLABLE"),
        bigquery.SchemaField("redispatch_volume_mw", "FLOAT64", mode="NULLABLE"),
        bigquery.SchemaField("message_details", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("ingested_at", "TIMESTAMP", mode="REQUIRED"),
    ],
}


def ensure_bronze_tables_exist(project_id: str, dataset_id: str) -> None:
    client = bigquery.Client(project=project_id)
    for table_name, schema in SCHEMAS.items():
        table_id = f"{project_id}.{dataset_id}.{table_name}"
        table = bigquery.Table(table_id, schema=schema)
        table.time_partitioning = bigquery.TimePartitioning(
            type_=bigquery.TimePartitioningType.DAY,
            field="timestamp_utc",
        )
        table.clustering_fields = ["bidding_zone"]
        client.create_table(table, exists_ok=True)


def batch_load_dataframe_to_bronze(
    df: pd.DataFrame,
    project_id: str,
    dataset_id: str,
    table_name: str,
) -> int:
    client = bigquery.Client(project=project_id)
    table_id = f"{project_id}.{dataset_id}.{table_name}"

    if df.empty:
        schema = SCHEMAS.get(table_name)
        if schema:
            table = bigquery.Table(table_id, schema=schema)
            table.time_partitioning = bigquery.TimePartitioning(
                type_=bigquery.TimePartitioningType.DAY,
                field="timestamp_utc",
            )
            table.clustering_fields = ["bidding_zone"]
            client.create_table(table, exists_ok=True)
        return 0

    clean_df = df.copy()

    clean_df["timestamp_utc"] = pd.to_datetime(clean_df["timestamp_utc"], utc=True)

    if "ingested_at" in clean_df.columns:
        clean_df["ingested_at"] = pd.to_datetime(clean_df["ingested_at"], utc=True)
    else:
        clean_df["ingested_at"] = pd.Timestamp.now(tz="UTC")

    job_config = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        time_partitioning=bigquery.TimePartitioning(
            type_=bigquery.TimePartitioningType.DAY,
            field="timestamp_utc",
        ),
        clustering_fields=["bidding_zone"],
        schema=SCHEMAS.get(table_name),
    )

    load_job = client.load_table_from_dataframe(
        dataframe=clean_df,
        destination=table_id,
        job_config=job_config,
    )
    load_job.result()
    return load_job.output_rows
