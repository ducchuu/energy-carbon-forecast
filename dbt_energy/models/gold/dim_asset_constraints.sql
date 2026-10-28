{{ config(
    materialized='incremental',
    unique_key='asset_id',
    incremental_strategy='merge',
    full_refresh=false,
    cluster_by=['bidding_zone', 'asset_id']
) }}

WITH seed_defaults AS (
    SELECT
        CAST(asset_id AS STRING) AS asset_id,
        CAST(facility_name AS STRING) AS facility_name,
        CAST(bidding_zone AS STRING) AS bidding_zone,
        CAST(substation_area AS STRING) AS substation_area,
        CAST(solar_kwp AS FLOAT64) AS solar_kwp,
        CAST(grid_export_limit_kw AS FLOAT64) AS grid_export_limit_kw,
        CAST(bess_capacity_kwh AS FLOAT64) AS bess_capacity_kwh,
        CAST(bess_max_charge_kw AS FLOAT64) AS bess_max_charge_kw,
        CAST(bess_max_discharge_kw AS FLOAT64) AS bess_max_discharge_kw,
        CAST(bess_roundtrip_efficiency AS FLOAT64) AS bess_roundtrip_efficiency,
        CAST(bess_min_soc_pct AS FLOAT64) AS bess_min_soc_pct,
        CAST(bess_max_soc_pct AS FLOAT64) AS bess_max_soc_pct,
        CAST(baseline_load_kw AS FLOAT64) AS baseline_load_kw,
        CAST(max_flexible_load_kw AS FLOAT64) AS max_flexible_load_kw,
        CAST(thermal_shift_buffer_hours AS INT64) AS thermal_shift_buffer_hours,
        CAST(alpha_weight AS FLOAT64) AS alpha_weight,
        CAST(updated_at AS TIMESTAMP) AS updated_at
    FROM {{ ref('default_asset_constraints') }}
),

combined_constraints AS (
    SELECT * FROM seed_defaults
    {% if is_incremental() %}
    UNION ALL
    SELECT
        asset_id,
        facility_name,
        bidding_zone,
        substation_area,
        solar_kwp,
        grid_export_limit_kw,
        bess_capacity_kwh,
        bess_max_charge_kw,
        bess_max_discharge_kw,
        bess_roundtrip_efficiency,
        bess_min_soc_pct,
        bess_max_soc_pct,
        baseline_load_kw,
        max_flexible_load_kw,
        thermal_shift_buffer_hours,
        alpha_weight,
        updated_at
    FROM {{ this }}
    {% endif %}
)

SELECT
    asset_id,
    facility_name,
    bidding_zone,
    substation_area,
    solar_kwp,
    grid_export_limit_kw,
    bess_capacity_kwh,
    bess_max_charge_kw,
    bess_max_discharge_kw,
    bess_roundtrip_efficiency,
    bess_min_soc_pct,
    bess_max_soc_pct,
    baseline_load_kw,
    max_flexible_load_kw,
    thermal_shift_buffer_hours,
    alpha_weight,
    updated_at
FROM combined_constraints
QUALIFY ROW_NUMBER() OVER (
    PARTITION BY asset_id
    ORDER BY updated_at DESC
) = 1
