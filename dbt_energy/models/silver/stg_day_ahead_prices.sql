{{ config(materialized='view') }}
WITH dedup_prices AS (
    SELECT
        timestamp_utc,
        bidding_zone,
        price_eur_mwh
    FROM {{ source('bronze', 'raw_day_ahead_prices') }}
    WHERE timestamp_utc >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY timestamp_utc, bidding_zone
        ORDER BY ingested_at DESC
    ) = 1
)
SELECT
    TIMESTAMP_TRUNC(timestamp_utc, HOUR) AS timestamp_utc,
    bidding_zone,
    AVG(price_eur_mwh) AS price_eur_mwh
FROM dedup_prices
GROUP BY
    TIMESTAMP_TRUNC(timestamp_utc, HOUR),
    bidding_zone
