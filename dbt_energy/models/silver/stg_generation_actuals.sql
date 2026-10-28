{{ config(materialized='view') }}
WITH dedup_gen_native AS (
    SELECT
        timestamp_utc,
        bidding_zone,
        psr_type,
        generation_mw
    FROM {{ source('bronze', 'raw_generation_actuals') }}
    WHERE timestamp_utc >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 8 DAY)
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY timestamp_utc, bidding_zone, psr_type
        ORDER BY ingested_at DESC
    ) = 1
)
SELECT
    TIMESTAMP_TRUNC(timestamp_utc, HOUR) AS timestamp_utc,
    bidding_zone,
    psr_type,
    AVG(generation_mw) AS generation_mw
FROM dedup_gen_native
GROUP BY
    TIMESTAMP_TRUNC(timestamp_utc, HOUR),
    bidding_zone,
    psr_type
