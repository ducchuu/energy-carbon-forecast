{{ config(
    materialized='table'
) }}

WITH trailing_baseload AS (
    SELECT
        bidding_zone,
        AVG(hourly_baseload_mw) AS avg_baseload_mw,
        SAFE_DIVIDE(
            SUM(hourly_baseload_emissions),
            SUM(hourly_baseload_mw)
        ) AS avg_baseload_ef
    FROM (
        SELECT
            g.timestamp_utc,
            g.bidding_zone,
            SUM(g.generation_mw) AS hourly_baseload_mw,
            SUM(g.generation_mw * ef.emission_factor_gco2_kwh) AS hourly_baseload_emissions
        FROM {{ ref('stg_generation_actuals') }} AS g
        INNER JOIN {{ ref('emission_factors') }} AS ef
            ON g.psr_type = ef.psr_type
        WHERE g.timestamp_utc >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 72 HOUR)
          AND g.psr_type IN ('B09', 'B11', 'B14')
        GROUP BY
            g.timestamp_utc,
            g.bidding_zone
    )
    GROUP BY bidding_zone
),

trailing_thermal AS (
    SELECT
        g.bidding_zone,
        SAFE_DIVIDE(
            SUM(g.generation_mw * ef.emission_factor_gco2_kwh),
            SUM(g.generation_mw)
        ) AS empirical_thermal_ef
    FROM {{ ref('stg_generation_actuals') }} AS g
    INNER JOIN {{ ref('emission_factors') }} AS ef
        ON g.psr_type = ef.psr_type
    WHERE g.timestamp_utc >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 168 HOUR)
      AND g.psr_type IN ('B01', 'B02', 'B03', 'B04', 'B05', 'B06', 'B17', 'B20')
    GROUP BY g.bidding_zone
)

SELECT
    COALESCE(b.bidding_zone, t.bidding_zone) AS bidding_zone,
    COALESCE(b.avg_baseload_mw, 0.0) AS avg_baseload_mw,
    COALESCE(b.avg_baseload_ef, 12.0) AS avg_baseload_ef,
    COALESCE(t.empirical_thermal_ef, 490.0) AS empirical_thermal_ef
FROM trailing_baseload AS b
FULL OUTER JOIN trailing_thermal AS t
    ON b.bidding_zone = t.bidding_zone
