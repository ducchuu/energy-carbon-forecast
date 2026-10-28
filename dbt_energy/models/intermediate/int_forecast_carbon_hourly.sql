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

WITH vre_ef AS (
    SELECT
        MAX(CASE WHEN psr_type = 'B16' THEN emission_factor_gco2_kwh END) AS solar_ef,
        MAX(CASE WHEN psr_type = 'B19' THEN emission_factor_gco2_kwh END) AS wind_onshore_ef,
        MAX(CASE WHEN psr_type = 'B18' THEN emission_factor_gco2_kwh END) AS wind_offshore_ef
    FROM {{ ref('emission_factors') }}
),

pivoted_forecasts AS (
    SELECT
        timestamp_utc,
        bidding_zone,
        SUM(CASE WHEN metric_type = 'SOLAR' THEN forecast_mw ELSE 0.0 END) AS solar_mw,
        SUM(CASE WHEN metric_type = 'WIND_ONSHORE' THEN forecast_mw ELSE 0.0 END) AS wind_onshore_mw,
        SUM(CASE WHEN metric_type = 'WIND_OFFSHORE' THEN forecast_mw ELSE 0.0 END) AS wind_offshore_mw,
        SUM(CASE WHEN metric_type = 'TOTAL_LOAD' THEN forecast_mw ELSE 0.0 END) AS total_load_mw
    FROM {{ ref('stg_grid_forecasts') }}
    {% if is_incremental() %}
    WHERE timestamp_utc >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 48 HOUR)
    {% endif %}
    GROUP BY
        timestamp_utc,
        bidding_zone
)

SELECT
    f.timestamp_utc,
    f.bidding_zone,
    f.solar_mw + f.wind_onshore_mw + f.wind_offshore_mw AS vre_mw,
    GREATEST(
        0.0,
        f.total_load_mw - (f.solar_mw + f.wind_onshore_mw + f.wind_offshore_mw) - COALESCE(b.avg_baseload_mw, 0.0)
    ) AS residual_thermal_mw,
    SAFE_DIVIDE(
        (f.solar_mw * COALESCE(v.solar_ef, 45.0))
        + (f.wind_onshore_mw * COALESCE(v.wind_onshore_ef, 11.0))
        + (f.wind_offshore_mw * COALESCE(v.wind_offshore_ef, 12.0))
        + (COALESCE(b.avg_baseload_mw, 0.0) * COALESCE(b.avg_baseload_ef, 12.0))
        + (
            GREATEST(
                0.0,
                f.total_load_mw - (f.solar_mw + f.wind_onshore_mw + f.wind_offshore_mw) - COALESCE(b.avg_baseload_mw, 0.0)
            ) * COALESCE(b.empirical_thermal_ef, 490.0)
        ),
        GREATEST(
            f.total_load_mw,
            f.solar_mw + f.wind_onshore_mw + f.wind_offshore_mw + COALESCE(b.avg_baseload_mw, 0.0)
        )
    ) AS forecast_ci_gco2_kwh,
    SAFE_DIVIDE(
        f.solar_mw + f.wind_onshore_mw + f.wind_offshore_mw,
        GREATEST(
            f.total_load_mw,
            f.solar_mw + f.wind_onshore_mw + f.wind_offshore_mw + COALESCE(b.avg_baseload_mw, 0.0)
        )
    ) * 100.0 AS forecast_renewable_share_pct
FROM pivoted_forecasts AS f
CROSS JOIN vre_ef AS v
LEFT JOIN {{ ref('int_grid_trailing_baselines') }} AS b
    ON f.bidding_zone = b.bidding_zone
