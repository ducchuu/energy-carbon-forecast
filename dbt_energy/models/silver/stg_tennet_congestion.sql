{{ config(materialized='view') }}
WITH dedup_congestion AS (
    SELECT
        timestamp_utc,
        bidding_zone,
        substation_area,
        congestion_severity,
        export_limit_factor,
        redispatch_volume_mw,
        message_details
    FROM {{ source('bronze', 'raw_tennet_congestion') }}
    WHERE timestamp_utc >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY timestamp_utc, bidding_zone, substation_area
        ORDER BY ingested_at DESC
    ) = 1
)
SELECT
    TIMESTAMP_TRUNC(timestamp_utc, HOUR) AS timestamp_utc,
    bidding_zone,
    substation_area,
    LOGICAL_OR(
        congestion_severity IN ('ACTIVE_RESTRICTION', 'CRITICAL_REDISPATCH')
    ) AS is_congestion_active,
    MAX(congestion_severity) AS congestion_severity,
    MIN(COALESCE(export_limit_factor, 1.0)) AS min_export_limit_factor,
    SUM(COALESCE(redispatch_volume_mw, 0.0)) AS total_redispatch_mw,
    ANY_VALUE(message_details) AS message_details
FROM dedup_congestion
GROUP BY
    TIMESTAMP_TRUNC(timestamp_utc, HOUR),
    bidding_zone,
    substation_area

