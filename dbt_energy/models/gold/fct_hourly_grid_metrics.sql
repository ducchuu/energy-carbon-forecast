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

WITH production_hourly_carbon AS (
    SELECT
        g.timestamp_utc,
        g.bidding_zone,
        SUM(g.generation_mw) AS total_generation_mw,
        SUM(g.generation_mw * ef.emission_factor_gco2_kwh) AS total_production_emissions,
        SAFE_DIVIDE(
            SUM(g.generation_mw * ef.emission_factor_gco2_kwh),
            SUM(g.generation_mw)
        ) AS production_ci_gco2_kwh,
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

crossborder_imports_hourly AS (
    SELECT
        fl.timestamp_utc,
        fl.to_zone AS bidding_zone,
        SUM(fl.flow_mw) AS imported_mw,
        SUM(
            fl.flow_mw * COALESCE(
                nb.production_ci_gco2_kwh,
                CASE fl.from_zone
                    WHEN '10YNO-2--------T' THEN 24.0
                    WHEN '10YSE-1--------K' THEN 35.0
                    WHEN '10YFR-RTE------C' THEN 55.0
                    WHEN '10YCH-SWISSGRIDZ' THEN 45.0
                    WHEN '10YDK-1--------W' THEN 140.0
                    WHEN '10YBE----------2' THEN 170.0
                    WHEN '10YAT-APG------L' THEN 150.0
                    WHEN '10YGB----------A' THEN 220.0
                    WHEN '10YCZ-CEPS-----N' THEN 430.0
                    WHEN '10YSK-SEPS-----K' THEN 210.0
                    ELSE 300.0
                END
            )
        ) AS imported_emissions
    FROM {{ ref('stg_crossborder_flows') }} AS fl
    LEFT JOIN production_hourly_carbon AS nb
        ON fl.timestamp_utc = nb.timestamp_utc
        AND fl.from_zone = nb.bidding_zone
    {% if is_incremental() %}
    WHERE fl.timestamp_utc >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 72 HOUR)
    {% endif %}
    GROUP BY
        fl.timestamp_utc,
        fl.to_zone
),

actual_hourly_carbon AS (
    SELECT
        pr.timestamp_utc,
        pr.bidding_zone,
        pr.total_generation_mw,
        COALESCE(imp.imported_mw, 0.0) AS imported_mw,
        pr.production_ci_gco2_kwh,
        SAFE_DIVIDE(
            pr.total_production_emissions + COALESCE(imp.imported_emissions, 0.0),
            pr.total_generation_mw + COALESCE(imp.imported_mw, 0.0)
        ) AS actual_ci_gco2_kwh,
        pr.actual_renewable_share_pct
    FROM production_hourly_carbon AS pr
    LEFT JOIN crossborder_imports_hourly AS imp
        ON pr.timestamp_utc = imp.timestamp_utc
        AND pr.bidding_zone = imp.bidding_zone
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
