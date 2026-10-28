{{ config(materialized='view') }}
WITH dedup_forecasts AS (
    SELECT
        timestamp_utc,
        bidding_zone,
        metric_type,
        forecast_mw
    FROM {{ source('bronze', 'raw_grid_forecasts') }}
    WHERE timestamp_utc >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 2 DAY)
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY timestamp_utc, bidding_zone, metric_type
        ORDER BY ingested_at DESC
    ) = 1
)
SELECT
    TIMESTAMP_TRUNC(timestamp_utc, HOUR) AS timestamp_utc,
    bidding_zone,
    metric_type,
    AVG(forecast_mw) AS forecast_mw
FROM dedup_forecasts
GROUP BY
    TIMESTAMP_TRUNC(timestamp_utc, HOUR),
    bidding_zone,
    metric_type
