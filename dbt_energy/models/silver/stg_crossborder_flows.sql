{{ config(materialized='view') }}
WITH dedup_flows AS (
    SELECT
        timestamp_utc,
        bidding_zone,
        from_zone,
        to_zone,
        flow_mw
    FROM {{ source('bronze', 'raw_crossborder_flows') }}
    WHERE timestamp_utc >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 8 DAY)
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY timestamp_utc, from_zone, to_zone
        ORDER BY ingested_at DESC
    ) = 1
)
SELECT
    TIMESTAMP_TRUNC(timestamp_utc, HOUR) AS timestamp_utc,
    bidding_zone,
    from_zone,
    to_zone,
    AVG(GREATEST(0.0, COALESCE(flow_mw, 0.0))) AS flow_mw
FROM dedup_flows
GROUP BY
    TIMESTAMP_TRUNC(timestamp_utc, HOUR),
    bidding_zone,
    from_zone,
    to_zone

