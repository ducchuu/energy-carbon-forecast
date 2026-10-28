{{ config(
    materialized='incremental',
    unique_key=['timestamp_utc', 'asset_id'],
    incremental_strategy='merge',
    partition_by={
      "field": "timestamp_utc",
      "data_type": "timestamp",
      "granularity": "day"
    },
    cluster_by=["bidding_zone", "asset_id"]
) }}

WITH RECURSIVE grid_metrics AS (
    SELECT
        timestamp_utc,
        local_datetime,
        local_date,
        bidding_zone,
        is_forecasted,
        price_eur_kwh,
        carbon_intensity_gco2_kwh,
        renewable_share_pct,
        imbalance_shortage_eur_mwh,
        imbalance_surplus_eur_mwh,
        is_congestion_active,
        congestion_severity,
        export_limit_factor,
        norm_price,
        norm_ci
    FROM {{ ref('fct_hourly_grid_metrics') }}
    {% if is_incremental() %}
    WHERE timestamp_utc >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 48 HOUR)
    {% endif %}
),

substation_congestion AS (
    SELECT
        timestamp_utc,
        bidding_zone,
        substation_area,
        is_congestion_active,
        congestion_severity,
        min_export_limit_factor,
        message_details
    FROM {{ ref('stg_tennet_congestion') }}
),

asset_grid_joined AS (
    SELECT
        m.timestamp_utc,
        m.local_datetime,
        m.local_date,
        m.bidding_zone,
        a.asset_id,
        a.facility_name,
        a.substation_area,
        m.is_forecasted,
        m.price_eur_kwh,
        m.carbon_intensity_gco2_kwh,
        m.renewable_share_pct,
        m.norm_price,
        m.norm_ci,
        a.alpha_weight,
        ROUND(
            a.alpha_weight * m.norm_price + (1.0 - a.alpha_weight) * m.norm_ci,
            4
        ) AS composite_score,
        COALESCE(sc.is_congestion_active, m.is_congestion_active, FALSE) AS is_congestion_active,
        COALESCE(sc.congestion_severity, m.congestion_severity, 'NONE') AS congestion_severity,
        COALESCE(sc.min_export_limit_factor, m.export_limit_factor, 1.0) AS effective_export_factor,
        COALESCE(
            sc.message_details,
            'Nominal substation operating limits'
        ) AS congestion_message,
        a.solar_kwp,
        a.grid_export_limit_kw,
        a.bess_capacity_kwh,
        a.bess_max_charge_kw,
        a.bess_max_discharge_kw,
        a.bess_roundtrip_efficiency,
        a.bess_min_soc_pct,
        a.bess_max_soc_pct,
        a.baseline_load_kw,
        a.max_flexible_load_kw,
        a.thermal_shift_buffer_hours,
        CASE
            WHEN EXTRACT(HOUR FROM m.local_datetime) BETWEEN 7 AND 19
                THEN ROUND(
                    a.solar_kwp
                    * LEAST(1.0, GREATEST(0.05, m.renewable_share_pct / 100.0))
                    * SIN(
                        (EXTRACT(HOUR FROM m.local_datetime) - 6) * ACOS(-1.0) / 14.0
                    ),
                    2
                )
            ELSE 0.0
        END AS estimated_solar_kw
    FROM grid_metrics AS m
    INNER JOIN {{ ref('dim_asset_constraints') }} AS a
        ON m.bidding_zone = a.bidding_zone
    LEFT JOIN substation_congestion AS sc
        ON m.timestamp_utc = sc.timestamp_utc
        AND a.bidding_zone = sc.bidding_zone
        AND a.substation_area = sc.substation_area
),

ordered_inputs AS (
    SELECT
        *,
        ROUND(grid_export_limit_kw * effective_export_factor, 2) AS effective_export_limit_kw,
        bess_capacity_kwh * (bess_min_soc_pct / 100.0) AS bess_min_kwh,
        bess_capacity_kwh * (bess_max_soc_pct / 100.0) AS bess_max_kwh,
        GREATEST(
            0.0,
            estimated_solar_kw - (baseline_load_kw + max_flexible_load_kw * 0.40)
        ) AS surplus_kw,
        ROW_NUMBER() OVER (
            PARTITION BY asset_id, local_date
            ORDER BY timestamp_utc ASC
        ) AS step_idx
    FROM asset_grid_joined
),

stateful_sim AS (
    SELECT
        inp.*,
        step_calc.dispatch_action,
        step_calc.bess_action_kw,
        step_calc.flex_load_kw,
        step_calc.curtailed_solar_kw,
        LEAST(
            inp.bess_max_kwh,
            GREATEST(
                inp.bess_min_kwh,
                init_state.start_kwh
                + CASE
                    WHEN step_calc.bess_action_kw > 0.0
                        THEN step_calc.bess_action_kw * SQRT(inp.bess_roundtrip_efficiency)
                    WHEN step_calc.bess_action_kw < 0.0
                        THEN step_calc.bess_action_kw / SQRT(inp.bess_roundtrip_efficiency)
                    ELSE 0.0
                END
            )
        ) AS end_bess_kwh
    FROM ordered_inputs AS inp
    CROSS JOIN UNNEST([
        STRUCT(
            inp.bess_min_kwh + (inp.bess_max_kwh - inp.bess_min_kwh) * 0.40 AS start_kwh,
            LEAST(
                inp.bess_max_charge_kw,
                GREATEST(0.0, inp.bess_max_kwh - (inp.bess_min_kwh + (inp.bess_max_kwh - inp.bess_min_kwh) * 0.40))
            ) AS charge_headroom_kw,
            LEAST(
                inp.bess_max_discharge_kw,
                GREATEST(
                    0.0,
                    ((inp.bess_min_kwh + (inp.bess_max_kwh - inp.bess_min_kwh) * 0.40) - inp.bess_min_kwh)
                    * inp.bess_roundtrip_efficiency
                )
            ) AS discharge_headroom_kw
        )
    ]) AS init_state
    CROSS JOIN UNNEST([
        STRUCT(
            CASE
                WHEN (
                    inp.surplus_kw > inp.effective_export_limit_kw
                    OR (inp.is_congestion_active AND inp.surplus_kw > 0.0)
                    OR (inp.price_eur_kwh < 0.0 AND inp.surplus_kw > 0.0)
                ) THEN
                    CASE
                        WHEN GREATEST(0.0, inp.surplus_kw - LEAST(inp.surplus_kw, init_state.charge_headroom_kw))
                            > CASE WHEN inp.price_eur_kwh < 0.0 THEN 0.0 ELSE inp.effective_export_limit_kw END
                            THEN 'CURTAIL_SOLAR'
                        WHEN LEAST(inp.surplus_kw, init_state.charge_headroom_kw) > 25.0
                            THEN 'CHARGE_BATTERY'
                        ELSE 'HOLD_BASELINE'
                    END
                WHEN (inp.composite_score <= 0.35 OR inp.price_eur_kwh <= 0.04) THEN
                    CASE
                        WHEN init_state.charge_headroom_kw > 25.0 THEN 'CHARGE_BATTERY'
                        WHEN NOT inp.is_congestion_active THEN 'RAMP_LOAD'
                        ELSE 'HOLD_BASELINE'
                    END
                WHEN (inp.composite_score <= 0.45 AND NOT inp.is_congestion_active) THEN 'RAMP_LOAD'
                WHEN (inp.composite_score >= 0.70 OR inp.price_eur_kwh >= 0.18) THEN
                    CASE
                        WHEN init_state.discharge_headroom_kw > 25.0 THEN 'DISCHARGE_BATTERY'
                        ELSE 'HOLD_BASELINE'
                    END
                ELSE 'HOLD_BASELINE'
            END AS dispatch_action,
            CASE
                WHEN (
                    inp.surplus_kw > inp.effective_export_limit_kw
                    OR (inp.is_congestion_active AND inp.surplus_kw > 0.0)
                    OR (inp.price_eur_kwh < 0.0 AND inp.surplus_kw > 0.0)
                ) THEN LEAST(inp.surplus_kw, init_state.charge_headroom_kw)
                WHEN (inp.composite_score <= 0.35 OR inp.price_eur_kwh <= 0.04)
                    AND init_state.charge_headroom_kw > 25.0
                    THEN init_state.charge_headroom_kw
                WHEN (inp.composite_score >= 0.70 OR inp.price_eur_kwh >= 0.18)
                    AND init_state.discharge_headroom_kw > 25.0
                    THEN -init_state.discharge_headroom_kw
                ELSE 0.0
            END AS bess_action_kw,
            CASE
                WHEN (
                    inp.surplus_kw > inp.effective_export_limit_kw
                    OR (inp.is_congestion_active AND inp.surplus_kw > 0.0)
                    OR (inp.price_eur_kwh < 0.0 AND inp.surplus_kw > 0.0)
                ) THEN inp.max_flexible_load_kw * 0.35
                WHEN (inp.composite_score <= 0.35 OR inp.price_eur_kwh <= 0.04)
                    AND init_state.charge_headroom_kw <= 25.0
                    AND NOT inp.is_congestion_active
                    THEN inp.max_flexible_load_kw
                WHEN (inp.composite_score <= 0.45 AND NOT inp.is_congestion_active)
                    AND NOT (
                        (inp.composite_score <= 0.35 OR inp.price_eur_kwh <= 0.04)
                        AND init_state.charge_headroom_kw > 25.0
                    )
                    THEN inp.max_flexible_load_kw
                WHEN (inp.composite_score >= 0.70 OR inp.price_eur_kwh >= 0.18)
                    AND init_state.discharge_headroom_kw > 25.0
                    THEN 0.0
                ELSE inp.max_flexible_load_kw * 0.35
            END AS flex_load_kw,
            CASE
                WHEN (
                    inp.surplus_kw > inp.effective_export_limit_kw
                    OR (inp.is_congestion_active AND inp.surplus_kw > 0.0)
                    OR (inp.price_eur_kwh < 0.0 AND inp.surplus_kw > 0.0)
                ) THEN GREATEST(
                    0.0,
                    GREATEST(0.0, inp.surplus_kw - LEAST(inp.surplus_kw, init_state.charge_headroom_kw))
                    - CASE WHEN inp.price_eur_kwh < 0.0 THEN 0.0 ELSE inp.effective_export_limit_kw END
                )
                ELSE 0.0
            END AS curtailed_solar_kw
        )
    ]) AS step_calc
    WHERE inp.step_idx = 1

    UNION ALL

    SELECT
        nxt.*,
        step_calc.dispatch_action,
        step_calc.bess_action_kw,
        step_calc.flex_load_kw,
        step_calc.curtailed_solar_kw,
        LEAST(
            nxt.bess_max_kwh,
            GREATEST(
                nxt.bess_min_kwh,
                prev.end_bess_kwh
                + CASE
                    WHEN step_calc.bess_action_kw > 0.0
                        THEN step_calc.bess_action_kw * SQRT(nxt.bess_roundtrip_efficiency)
                    WHEN step_calc.bess_action_kw < 0.0
                        THEN step_calc.bess_action_kw / SQRT(nxt.bess_roundtrip_efficiency)
                    ELSE 0.0
                END
            )
        ) AS end_bess_kwh
    FROM stateful_sim AS prev
    INNER JOIN ordered_inputs AS nxt
        ON prev.asset_id = nxt.asset_id
        AND prev.local_date = nxt.local_date
        AND nxt.step_idx = prev.step_idx + 1
    CROSS JOIN UNNEST([
        STRUCT(
            LEAST(
                nxt.bess_max_charge_kw,
                GREATEST(0.0, nxt.bess_max_kwh - prev.end_bess_kwh)
            ) AS charge_headroom_kw,
            LEAST(
                nxt.bess_max_discharge_kw,
                GREATEST(
                    0.0,
                    (prev.end_bess_kwh - nxt.bess_min_kwh) * nxt.bess_roundtrip_efficiency
                )
            ) AS discharge_headroom_kw
        )
    ]) AS dyn_state
    CROSS JOIN UNNEST([
        STRUCT(
            CASE
                WHEN (
                    nxt.surplus_kw > nxt.effective_export_limit_kw
                    OR (nxt.is_congestion_active AND nxt.surplus_kw > 0.0)
                    OR (nxt.price_eur_kwh < 0.0 AND nxt.surplus_kw > 0.0)
                ) THEN
                    CASE
                        WHEN GREATEST(0.0, nxt.surplus_kw - LEAST(nxt.surplus_kw, dyn_state.charge_headroom_kw))
                            > CASE WHEN nxt.price_eur_kwh < 0.0 THEN 0.0 ELSE nxt.effective_export_limit_kw END
                            THEN 'CURTAIL_SOLAR'
                        WHEN LEAST(nxt.surplus_kw, dyn_state.charge_headroom_kw) > 25.0
                            THEN 'CHARGE_BATTERY'
                        ELSE 'HOLD_BASELINE'
                    END
                WHEN (nxt.composite_score <= 0.35 OR nxt.price_eur_kwh <= 0.04) THEN
                    CASE
                        WHEN dyn_state.charge_headroom_kw > 25.0 THEN 'CHARGE_BATTERY'
                        WHEN NOT nxt.is_congestion_active THEN 'RAMP_LOAD'
                        ELSE 'HOLD_BASELINE'
                    END
                WHEN (nxt.composite_score <= 0.45 AND NOT nxt.is_congestion_active) THEN 'RAMP_LOAD'
                WHEN (nxt.composite_score >= 0.70 OR nxt.price_eur_kwh >= 0.18) THEN
                    CASE
                        WHEN dyn_state.discharge_headroom_kw > 25.0 THEN 'DISCHARGE_BATTERY'
                        ELSE 'HOLD_BASELINE'
                    END
                ELSE 'HOLD_BASELINE'
            END AS dispatch_action,
            CASE
                WHEN (
                    nxt.surplus_kw > nxt.effective_export_limit_kw
                    OR (nxt.is_congestion_active AND nxt.surplus_kw > 0.0)
                    OR (nxt.price_eur_kwh < 0.0 AND nxt.surplus_kw > 0.0)
                ) THEN LEAST(nxt.surplus_kw, dyn_state.charge_headroom_kw)
                WHEN (nxt.composite_score <= 0.35 OR nxt.price_eur_kwh <= 0.04)
                    AND dyn_state.charge_headroom_kw > 25.0
                    THEN dyn_state.charge_headroom_kw
                WHEN (nxt.composite_score >= 0.70 OR nxt.price_eur_kwh >= 0.18)
                    AND dyn_state.discharge_headroom_kw > 25.0
                    THEN -dyn_state.discharge_headroom_kw
                ELSE 0.0
            END AS bess_action_kw,
            CASE
                WHEN (
                    nxt.surplus_kw > nxt.effective_export_limit_kw
                    OR (nxt.is_congestion_active AND nxt.surplus_kw > 0.0)
                    OR (nxt.price_eur_kwh < 0.0 AND nxt.surplus_kw > 0.0)
                ) THEN nxt.max_flexible_load_kw * 0.35
                WHEN (nxt.composite_score <= 0.35 OR nxt.price_eur_kwh <= 0.04)
                    AND dyn_state.charge_headroom_kw <= 25.0
                    AND NOT nxt.is_congestion_active
                    THEN nxt.max_flexible_load_kw
                WHEN (nxt.composite_score <= 0.45 AND NOT nxt.is_congestion_active)
                    AND NOT (
                        (nxt.composite_score <= 0.35 OR nxt.price_eur_kwh <= 0.04)
                        AND dyn_state.charge_headroom_kw > 25.0
                    )
                    THEN nxt.max_flexible_load_kw
                WHEN (nxt.composite_score >= 0.70 OR nxt.price_eur_kwh >= 0.18)
                    AND dyn_state.discharge_headroom_kw > 25.0
                    THEN 0.0
                ELSE nxt.max_flexible_load_kw * 0.35
            END AS flex_load_kw,
            CASE
                WHEN (
                    nxt.surplus_kw > nxt.effective_export_limit_kw
                    OR (nxt.is_congestion_active AND nxt.surplus_kw > 0.0)
                    OR (nxt.price_eur_kwh < 0.0 AND nxt.surplus_kw > 0.0)
                ) THEN GREATEST(
                    0.0,
                    GREATEST(0.0, nxt.surplus_kw - LEAST(nxt.surplus_kw, dyn_state.charge_headroom_kw))
                    - CASE WHEN nxt.price_eur_kwh < 0.0 THEN 0.0 ELSE nxt.effective_export_limit_kw END
                )
                ELSE 0.0
            END AS curtailed_solar_kw
        )
    ]) AS step_calc
)

SELECT
    timestamp_utc,
    local_datetime,
    local_date,
    bidding_zone,
    asset_id,
    facility_name,
    substation_area,
    is_forecasted,
    price_eur_kwh,
    carbon_intensity_gco2_kwh,
    renewable_share_pct,
    norm_price,
    norm_ci,
    composite_score,
    is_congestion_active,
    congestion_severity,
    congestion_message,
    estimated_solar_kw,
    effective_export_limit_kw,
    dispatch_action,
    (dispatch_action = 'CHARGE_BATTERY') AS flag_charge_battery,
    (dispatch_action = 'CURTAIL_SOLAR') AS flag_curtail_solar,
    (dispatch_action = 'RAMP_LOAD') AS flag_ramp_load,
    (dispatch_action = 'DISCHARGE_BATTERY') AS flag_discharge_battery,
    ROUND(bess_action_kw, 2) AS recommended_bess_kw,
    ROUND(flex_load_kw, 2) AS recommended_flex_load_kw,
    ROUND(curtailed_solar_kw, 2) AS curtailed_solar_kw,
    ROUND(
        GREATEST(0.0, baseline_load_kw + (max_flexible_load_kw * 0.5) - estimated_solar_kw)
        * price_eur_kwh,
        2
    ) AS baseline_hourly_cost_eur,
    ROUND(
        CASE
            WHEN (baseline_load_kw + flex_load_kw + bess_action_kw - GREATEST(0.0, estimated_solar_kw - curtailed_solar_kw)) >= 0.0
                THEN (baseline_load_kw + flex_load_kw + bess_action_kw - GREATEST(0.0, estimated_solar_kw - curtailed_solar_kw)) * price_eur_kwh
            ELSE (baseline_load_kw + flex_load_kw + bess_action_kw - GREATEST(0.0, estimated_solar_kw - curtailed_solar_kw)) * GREATEST(0.0, price_eur_kwh * 0.85)
        END,
        2
    ) AS optimized_hourly_cost_eur,
    ROUND(
        (
            GREATEST(0.0, baseline_load_kw + (max_flexible_load_kw * 0.5) - estimated_solar_kw)
            * price_eur_kwh
        ) - (
            CASE
                WHEN (baseline_load_kw + flex_load_kw + bess_action_kw - GREATEST(0.0, estimated_solar_kw - curtailed_solar_kw)) >= 0.0
                    THEN (baseline_load_kw + flex_load_kw + bess_action_kw - GREATEST(0.0, estimated_solar_kw - curtailed_solar_kw)) * price_eur_kwh
                ELSE (baseline_load_kw + flex_load_kw + bess_action_kw - GREATEST(0.0, estimated_solar_kw - curtailed_solar_kw)) * GREATEST(0.0, price_eur_kwh * 0.85)
            END
        ),
        2
    ) AS expected_cost_delta_eur
FROM stateful_sim
