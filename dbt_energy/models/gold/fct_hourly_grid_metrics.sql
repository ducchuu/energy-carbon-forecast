{{ config(
    materialized='incremental',
    unique_key=['timestamp_utc', 'bidding_zone'],
    incremental_strategy='merge',
    partition_by={
      "field": "timestamp_utc",
      "data_type": "timestamp",
      "granularity": "day"
    },
    cluster_by=["bidding_zone"]
) }}

WITH actual_hourly_carbon AS (
    SELECT
        g.timestamp_utc,
        g.bidding_zone,
        SUM(g.generation_mw) AS total_generation_mw,
        SAFE_DIVIDE(
            SUM(g.generation_mw * ef.emission_factor_gco2_kwh),
            SUM(g.generation_mw)
        ) AS actual_ci_gco2_kwh,
        SAFE_DIVIDE(
            SUM(CASE WHEN ef.is_renewable THEN g.generation_mw ELSE 0 END),
            SUM(g.generation_mw)
        ) * 100.0 AS actual_renewable_share_pct
    FROM {{ ref('stg_generation_actuals') }} AS g
    INNER JOIN {{ ref('emission_factors') }} AS ef
        ON g.psr_type = ef.psr_type
    {% if is_incremental() %}
    WHERE g.timestamp_utc >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 72 HOUR)
    {% endif %}
    GROUP BY
        g.timestamp_utc,
        g.bidding_zone
),

zone_congestion_hourly AS (
    SELECT
        timestamp_utc,
        bidding_zone,
        LOGICAL_OR(is_congestion_active) AS is_congestion_active,
        MAX(congestion_severity) AS congestion_severity,
        MIN(min_export_limit_factor) AS export_limit_factor,
        SUM(total_redispatch_mw) AS total_redispatch_mw
    FROM {{ ref('stg_tennet_congestion') }}
    GROUP BY
        timestamp_utc,
        bidding_zone
),

spliced_series AS (
    SELECT
        p.timestamp_utc,
        DATETIME(p.timestamp_utc, "Europe/Amsterdam") AS local_datetime,
        DATE(DATETIME(p.timestamp_utc, "Europe/Amsterdam")) AS local_date,
        p.bidding_zone,
        p.price_eur_mwh / 1000.0 AS price_eur_kwh,
        COALESCE(
            a.actual_ci_gco2_kwh,
            fc.forecast_ci_gco2_kwh,
            LAST_VALUE(fc.forecast_ci_gco2_kwh IGNORE NULLS) OVER (
                PARTITION BY p.bidding_zone
                ORDER BY p.timestamp_utc
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            ),
            LAST_VALUE(a.actual_ci_gco2_kwh IGNORE NULLS) OVER (
                PARTITION BY p.bidding_zone
                ORDER BY p.timestamp_utc
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            ),
            400.0
        ) AS carbon_intensity_gco2_kwh,
        COALESCE(
            a.actual_renewable_share_pct,
            fc.forecast_renewable_share_pct,
            LAST_VALUE(fc.forecast_renewable_share_pct IGNORE NULLS) OVER (
                PARTITION BY p.bidding_zone
                ORDER BY p.timestamp_utc
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            ),
            LAST_VALUE(a.actual_renewable_share_pct IGNORE NULLS) OVER (
                PARTITION BY p.bidding_zone
                ORDER BY p.timestamp_utc
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            ),
            0.0
        ) AS renewable_share_pct,
        a.actual_ci_gco2_kwh IS NULL AS is_forecasted,
        COALESCE(imb.avg_imbalance_shortage_eur_mwh, p.price_eur_mwh) AS imbalance_shortage_eur_mwh,
        COALESCE(imb.avg_imbalance_surplus_eur_mwh, p.price_eur_mwh) AS imbalance_surplus_eur_mwh,
        COALESCE(cong.is_congestion_active, FALSE) AS is_congestion_active,
        COALESCE(cong.congestion_severity, 'NONE') AS congestion_severity,
        COALESCE(cong.export_limit_factor, 1.0) AS export_limit_factor
    FROM {{ ref('stg_day_ahead_prices') }} AS p
    LEFT JOIN actual_hourly_carbon AS a
        ON p.timestamp_utc = a.timestamp_utc
        AND p.bidding_zone = a.bidding_zone
    LEFT JOIN {{ ref('int_forecast_carbon_hourly') }} AS fc
        ON p.timestamp_utc = fc.timestamp_utc
        AND p.bidding_zone = fc.bidding_zone
    LEFT JOIN {{ ref('stg_tennet_imbalance') }} AS imb
        ON p.timestamp_utc = imb.timestamp_utc
        AND p.bidding_zone = imb.bidding_zone
    LEFT JOIN zone_congestion_hourly AS cong
        ON p.timestamp_utc = cong.timestamp_utc
        AND p.bidding_zone = cong.bidding_zone
    {% if is_incremental() %}
    WHERE p.timestamp_utc >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 72 HOUR)
    {% endif %}
),

rolling_bounds AS (
    SELECT
        *,
        MIN(price_eur_kwh) OVER (
            PARTITION BY bidding_zone
            ORDER BY UNIX_SECONDS(timestamp_utc)
            RANGE BETWEEN 43200 PRECEDING AND 43200 FOLLOWING
        ) AS rolling_min_price,
        MAX(price_eur_kwh) OVER (
            PARTITION BY bidding_zone
            ORDER BY UNIX_SECONDS(timestamp_utc)
            RANGE BETWEEN 43200 PRECEDING AND 43200 FOLLOWING
        ) AS rolling_max_price,
        MIN(carbon_intensity_gco2_kwh) OVER (
            PARTITION BY bidding_zone
            ORDER BY UNIX_SECONDS(timestamp_utc)
            RANGE BETWEEN 43200 PRECEDING AND 43200 FOLLOWING
        ) AS rolling_min_ci,
        MAX(carbon_intensity_gco2_kwh) OVER (
            PARTITION BY bidding_zone
            ORDER BY UNIX_SECONDS(timestamp_utc)
            RANGE BETWEEN 43200 PRECEDING AND 43200 FOLLOWING
        ) AS rolling_max_ci
    FROM spliced_series
)

SELECT
    timestamp_utc,
    local_datetime,
    local_date,
    bidding_zone,
    is_forecasted,
    ROUND(price_eur_kwh, 4) AS price_eur_kwh,
    ROUND(carbon_intensity_gco2_kwh, 2) AS carbon_intensity_gco2_kwh,
    ROUND(renewable_share_pct, 1) AS renewable_share_pct,
    ROUND(imbalance_shortage_eur_mwh, 2) AS imbalance_shortage_eur_mwh,
    ROUND(imbalance_surplus_eur_mwh, 2) AS imbalance_surplus_eur_mwh,
    is_congestion_active,
    congestion_severity,
    ROUND(export_limit_factor, 2) AS export_limit_factor,
    ROUND(
        COALESCE(
            SAFE_DIVIDE(
                price_eur_kwh - rolling_min_price,
                NULLIF(rolling_max_price - rolling_min_price, 0.0)
            ),
            0.0
        ),
        4
    ) AS norm_price,
    ROUND(
        COALESCE(
            SAFE_DIVIDE(
                carbon_intensity_gco2_kwh - rolling_min_ci,
                NULLIF(rolling_max_ci - rolling_min_ci, 0.0)
            ),
            0.0
        ),
        4
    ) AS norm_ci
FROM rolling_bounds
