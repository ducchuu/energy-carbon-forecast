{{ config(materialized='view') }}
WITH dedup_imbalance AS (
    SELECT
        timestamp_utc,
        bidding_zone,
        imbalance_shortage_eur_mwh,
        imbalance_surplus_eur_mwh,
        dispatch_up_mw,
        dispatch_down_mw,
        regulation_state
    FROM {{ source('bronze', 'raw_tennet_imbalance') }}
    WHERE timestamp_utc >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY timestamp_utc, bidding_zone
        ORDER BY ingested_at DESC
    ) = 1
)
SELECT
    TIMESTAMP_TRUNC(timestamp_utc, HOUR) AS timestamp_utc,
    bidding_zone,
    AVG(imbalance_shortage_eur_mwh) AS avg_imbalance_shortage_eur_mwh,
    AVG(imbalance_surplus_eur_mwh) AS avg_imbalance_surplus_eur_mwh,
    SUM(dispatch_up_mw) AS total_dispatch_up_mw,
    SUM(dispatch_down_mw) AS total_dispatch_down_mw,
    MAX(regulation_state) AS max_regulation_state
FROM dedup_imbalance
GROUP BY
    TIMESTAMP_TRUNC(timestamp_utc, HOUR),
    bidding_zone

