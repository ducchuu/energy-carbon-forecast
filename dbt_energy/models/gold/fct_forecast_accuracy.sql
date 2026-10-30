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
    WHERE g.timestamp_utc >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 168 HOUR)
    {% endif %}
    GROUP BY
        g.timestamp_utc,
        g.bidding_zone
),

paired_backtest AS (
    SELECT
        a.timestamp_utc,
        DATETIME(a.timestamp_utc, "Europe/Amsterdam") AS local_datetime,
        DATE(DATETIME(a.timestamp_utc, "Europe/Amsterdam")) AS local_date,
        a.bidding_zone,
        fc.forecast_ci_gco2_kwh,
        a.actual_ci_gco2_kwh,
        fc.forecast_renewable_share_pct,
        a.actual_renewable_share_pct,
        fc.forecast_ci_gco2_kwh - a.actual_ci_gco2_kwh AS error_gco2_kwh,
        ABS(fc.forecast_ci_gco2_kwh - a.actual_ci_gco2_kwh) AS abs_error_gco2_kwh,
        POW(fc.forecast_ci_gco2_kwh - a.actual_ci_gco2_kwh, 2) AS sq_error_gco2_kwh
    FROM actual_hourly_carbon AS a
    INNER JOIN {{ ref('int_forecast_carbon_hourly') }} AS fc
        ON a.timestamp_utc = fc.timestamp_utc
        AND a.bidding_zone = fc.bidding_zone
)

SELECT
    timestamp_utc,
    local_datetime,
    local_date,
    bidding_zone,
    ROUND(forecast_ci_gco2_kwh, 2) AS forecast_ci_gco2_kwh,
    ROUND(actual_ci_gco2_kwh, 2) AS actual_ci_gco2_kwh,
    ROUND(forecast_renewable_share_pct, 1) AS forecast_renewable_share_pct,
    ROUND(actual_renewable_share_pct, 1) AS actual_renewable_share_pct,
    ROUND(error_gco2_kwh, 2) AS error_gco2_kwh,
    ROUND(abs_error_gco2_kwh, 2) AS abs_error_gco2_kwh,
    ROUND(
        AVG(abs_error_gco2_kwh) OVER (
            PARTITION BY bidding_zone
            ORDER BY UNIX_SECONDS(timestamp_utc)
            RANGE BETWEEN 604800 PRECEDING AND CURRENT ROW
        ),
        2
    ) AS rolling_7d_mae_gco2_kwh,
    ROUND(
        SQRT(
            AVG(sq_error_gco2_kwh) OVER (
                PARTITION BY bidding_zone
                ORDER BY UNIX_SECONDS(timestamp_utc)
                RANGE BETWEEN 604800 PRECEDING AND CURRENT ROW
            )
        ),
        2
    ) AS rolling_7d_rmse_gco2_kwh
FROM paired_backtest

