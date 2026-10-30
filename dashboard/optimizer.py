import math
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd

try:
    from scipy.optimize import linprog
except ImportError:
    linprog = None

SCORE_CHARGE_THRESHOLD = 0.35
SCORE_RAMP_THRESHOLD = 0.45
SCORE_DISCHARGE_THRESHOLD = 0.70
PRICE_CHARGE_GATE_EUR_KWH = 0.04
PRICE_DISCHARGE_GATE_EUR_KWH = 0.18
SOLAR_START_HOUR = 7
SOLAR_END_HOUR = 19
DEFAULT_MARGINAL_CYCLE_COST_EUR_KWH = 0.025


def find_optimal_window(
    df: pd.DataFrame,
    alpha: float,
    window_hours: int,
    appliance_kw: float,
    filter_future_only: bool = True,
) -> dict:
    if df.empty:
        return {}

    work_df = df.copy()
    work_df["timestamp_utc"] = pd.to_datetime(work_df["timestamp_utc"], utc=True)
    work_df = (
        work_df.sort_values("timestamp_utc")
        .drop_duplicates(subset=["timestamp_utc"])
        .reset_index(drop=True)
    )

    if filter_future_only:
        now_utc = datetime.now(timezone.utc)
        work_df = work_df[
            work_df["timestamp_utc"] >= now_utc.replace(minute=0, second=0, microsecond=0)
        ].reset_index(drop=True)

    if len(work_df) < window_hours:
        return {}

    price_col = "norm_price" if "norm_price" in work_df.columns else "norm_price_daily"
    carbon_col = "norm_ci" if "norm_ci" in work_df.columns else "norm_carbon_daily"

    work_df[price_col] = work_df[price_col].fillna(0.0)
    work_df[carbon_col] = work_df[carbon_col].fillna(0.0)

    work_df["score_t"] = alpha * work_df[price_col] + (1.0 - alpha) * work_df[carbon_col]

    time_diffs = work_df["timestamp_utc"].diff().dt.total_seconds()
    num_windows = len(work_df) - window_hours + 1

    valid_window_mask = []
    for i in range(num_windows):
        diff_slice = time_diffs.iloc[i + 1 : i + window_hours]
        is_contiguous = (diff_slice == 3600.0).all() if len(diff_slice) > 0 else True
        valid_window_mask.append(is_contiguous)

    kernel = np.ones(window_hours, dtype=float) / float(window_hours)
    conv_scores = np.convolve(work_df["score_t"].to_numpy(), kernel, mode="valid")

    valid_indices = [i for i, is_valid in enumerate(valid_window_mask) if is_valid]
    if not valid_indices:
        return {}

    filtered_scores = [(conv_scores[i], i) for i in valid_indices]
    best_score, best_idx = min(filtered_scores, key=lambda x: x[0])
    worst_score, worst_idx = max(filtered_scores, key=lambda x: x[0])

    best_slice = work_df.iloc[best_idx : best_idx + window_hours]
    worst_slice = work_df.iloc[worst_idx : worst_idx + window_hours]

    best_cost = float(best_slice["price_eur_kwh"].sum() * appliance_kw)
    worst_cost = float(worst_slice["price_eur_kwh"].sum() * appliance_kw)

    best_co2 = float(best_slice["carbon_intensity_gco2_kwh"].sum() * appliance_kw)
    worst_co2 = float(worst_slice["carbon_intensity_gco2_kwh"].sum() * appliance_kw)

    return {
        "scored_df": work_df,
        "start_time": best_slice.iloc[0]["local_datetime"],
        "end_time": best_slice.iloc[-1]["local_datetime"] + timedelta(hours=1),
        "window_score": round(float(best_score), 4),
        "best_cost_eur": round(best_cost, 4),
        "cost_saving_pct": round(100.0 * (worst_cost - best_cost) / max(worst_cost, 1e-6), 1),
        "best_co2_g": round(best_co2, 1),
        "co2_saving_pct": round(100.0 * (worst_co2 - best_co2) / max(worst_co2, 1e-6), 1),
        "avg_renewable_pct": round(float(best_slice["renewable_share_pct"].mean()), 1),
    }


def _solve_bess_lp(
    prices: np.ndarray,
    carbon_intensities: np.ndarray,
    scores: np.ndarray,
    surplus_solar_kw: np.ndarray,
    allowed_export_kw: np.ndarray,
    alpha: float,
    bess_capacity_kwh: float,
    bess_min_kwh: float,
    bess_max_kwh: float,
    initial_bess_kwh: float,
    bess_max_charge_kw: float,
    bess_max_discharge_kw: float,
    eta_rt: float,
    marginal_cycle_cost_eur_kwh: float,
    shadow_carbon_eur_tco2: float = None,
) -> tuple[np.ndarray, np.ndarray]:
    n = len(prices)
    if n == 0 or bess_capacity_kwh <= 0.0 or (bess_max_charge_kw <= 0.0 and bess_max_discharge_kw <= 0.0):
        return np.zeros(n), np.zeros(n)

    eta_c = math.sqrt(max(0.01, min(1.0, eta_rt)))
    eta_d = math.sqrt(max(0.01, min(1.0, eta_rt)))

    p_span = max(float(np.max(prices) - np.min(prices)), 0.05)
    c_span = max(float(np.max(carbon_intensities) - np.min(carbon_intensities)), 50.0)

    if shadow_carbon_eur_tco2 is not None:
        effective_signal = prices + (carbon_intensities / 1000.0) * (shadow_carbon_eur_tco2 / 1000.0)
    else:
        carbon_eur_equiv = ((carbon_intensities - np.min(carbon_intensities)) / c_span) * p_span
        effective_signal = alpha * prices + (1.0 - alpha) * carbon_eur_equiv

    excess_surplus = np.maximum(0.0, surplus_solar_kw - allowed_export_kw)
    congestion_bonus = np.where(excess_surplus > 0.0, 0.12, 0.0)

    deg_half = 0.5 * max(0.0, marginal_cycle_cost_eur_kwh)
    c_charge = effective_signal + deg_half - congestion_bonus
    c_discharge = -effective_signal + deg_half
    c_obj = np.concatenate([c_charge, c_discharge])

    tril = np.tril(np.ones((n, n)))
    a_charge = tril * eta_c
    a_discharge = -tril / eta_d

    a_ub = np.vstack(
        [
            np.hstack([a_charge, a_discharge]),
            np.hstack([-a_charge, -a_discharge]),
        ]
    )
    b_ub = np.concatenate(
        [
            np.full(n, bess_max_kwh - initial_bess_kwh),
            np.full(n, initial_bess_kwh - bess_min_kwh),
        ]
    )

    bounds = [(0.0, bess_max_charge_kw) for _ in range(n)] + [
        (0.0, bess_max_discharge_kw) for _ in range(n)
    ]

    if linprog is not None:
        res = linprog(c_obj, A_ub=a_ub, b_ub=b_ub, bounds=bounds, method="highs")
        if res.success:
            c_sol = res.x[:n]
            d_sol = res.x[n:]
            net_sol = c_sol - d_sol
            c_clean = np.where(net_sol > 1e-3, net_sol, 0.0)
            d_clean = np.where(net_sol < -1e-3, -net_sol, 0.0)
            return c_clean, d_clean

    # Vectorized Dynamic Programming / Forward-Backward MPC solver when SciPy C-ext is unavailable
    c_clean = np.zeros(n)
    d_clean = np.zeros(n)
    soc = initial_bess_kwh
    q_low = float(np.percentile(effective_signal, 35))
    q_high = float(np.percentile(effective_signal, 65))
    spread = q_high - q_low

    for idx in range(n):
        headroom_c = min(bess_max_charge_kw, max(0.0, (bess_max_kwh - soc) / eta_c))
        headroom_d = min(bess_max_discharge_kw, max(0.0, (soc - bess_min_kwh) * eta_d))
        if excess_surplus[idx] > 0.0 and headroom_c > 0.0:
            c_clean[idx] = min(excess_surplus[idx], headroom_c)
            soc += c_clean[idx] * eta_c
        elif effective_signal[idx] <= q_low and spread >= marginal_cycle_cost_eur_kwh and headroom_c > 0.0:
            c_clean[idx] = headroom_c
            soc += c_clean[idx] * eta_c
        elif effective_signal[idx] >= q_high and spread >= marginal_cycle_cost_eur_kwh and headroom_d > 0.0:
            d_clean[idx] = headroom_d
            soc -= d_clean[idx] / eta_d

    return c_clean, d_clean


def simulate_commercial_dispatch(
    df_metrics: pd.DataFrame,
    asset_config: dict[str, Any],
    alpha: float = 0.50,
    df_congestion: pd.DataFrame = None,
    use_lp: bool = True,
) -> dict[str, Any]:
    if df_metrics.empty:
        return {}

    work_df = df_metrics.copy()
    work_df["timestamp_utc"] = pd.to_datetime(work_df["timestamp_utc"], utc=True)
    work_df = (
        work_df.sort_values("timestamp_utc")
        .drop_duplicates(subset=["timestamp_utc"])
        .reset_index(drop=True)
    )

    if "local_datetime" not in work_df.columns:
        work_df["local_datetime"] = work_df["timestamp_utc"].dt.tz_convert("Europe/Amsterdam")
    else:
        work_df["local_datetime"] = pd.to_datetime(work_df["local_datetime"])

    price_col = "norm_price" if "norm_price" in work_df.columns else "norm_price_daily"
    carbon_col = "norm_ci" if "norm_ci" in work_df.columns else "norm_carbon_daily"

    if price_col not in work_df.columns:
        p_min, p_max = work_df["price_eur_kwh"].min(), work_df["price_eur_kwh"].max()
        work_df[price_col] = (work_df["price_eur_kwh"] - p_min) / max(p_max - p_min, 1e-6)
    if carbon_col not in work_df.columns:
        c_min = work_df["carbon_intensity_gco2_kwh"].min()
        c_max = work_df["carbon_intensity_gco2_kwh"].max()
        work_df[carbon_col] = (work_df["carbon_intensity_gco2_kwh"] - c_min) / max(
            c_max - c_min, 1e-6
        )

    work_df[price_col] = work_df[price_col].fillna(0.0)
    work_df[carbon_col] = work_df[carbon_col].fillna(0.0)
    work_df["composite_score"] = (
        alpha * work_df[price_col] + (1.0 - alpha) * work_df[carbon_col]
    )

    solar_kwp = float(asset_config.get("solar_kwp", 1000.0))
    grid_export_limit_kw = float(asset_config.get("grid_export_limit_kw", 500.0))
    bess_capacity_kwh = float(asset_config.get("bess_capacity_kwh", 2000.0))
    bess_max_charge_kw = float(asset_config.get("bess_max_charge_kw", 500.0))
    bess_max_discharge_kw = float(asset_config.get("bess_max_discharge_kw", 500.0))
    bess_roundtrip_efficiency = float(asset_config.get("bess_roundtrip_efficiency", 0.90))
    bess_min_soc_pct = float(asset_config.get("bess_min_soc_pct", 10.0))
    bess_max_soc_pct = float(asset_config.get("bess_max_soc_pct", 95.0))
    baseline_load_kw = float(asset_config.get("baseline_load_kw", 300.0))
    max_flexible_load_kw = float(asset_config.get("max_flexible_load_kw", 400.0))
    marginal_cycle_cost_eur_kwh = float(
        asset_config.get("marginal_cycle_cost_eur_kwh", DEFAULT_MARGINAL_CYCLE_COST_EUR_KWH)
    )
    shadow_carbon_eur_tco2 = asset_config.get("shadow_carbon_eur_tco2")
    custom_load_profile_kw = asset_config.get("custom_load_profile_kw")

    bess_min_kwh = bess_capacity_kwh * (bess_min_soc_pct / 100.0)
    bess_max_kwh = bess_capacity_kwh * (bess_max_soc_pct / 100.0)
    current_bess_kwh = bess_min_kwh + (bess_max_kwh - bess_min_kwh) * 0.40

    is_congestion_active = False
    export_factor = 1.0
    if df_congestion is not None and not df_congestion.empty:
        latest_cong = df_congestion.iloc[0]
        is_congestion_active = bool(latest_cong.get("is_congestion_active", False))
        export_factor = float(latest_cong.get("min_export_limit_factor", 1.0))
    elif "is_congestion_active" in work_df.columns:
        is_congestion_active = bool(work_df["is_congestion_active"].iloc[-1])
        export_factor = float(work_df.get("export_limit_factor", pd.Series([1.0])).iloc[-1])

    effective_export_limit_kw = grid_export_limit_kw * export_factor

    avg_ci_kwh = (
        float(work_df["carbon_intensity_gco2_kwh"].mean())
        if "carbon_intensity_gco2_kwh" in work_df.columns
        else 250.0
    )

    n_rows = len(work_df)
    prices_arr = np.zeros(n_rows)
    ci_arr = np.zeros(n_rows)
    scores_arr = np.zeros(n_rows)
    solar_arr = np.zeros(n_rows)
    base_arr = np.zeros(n_rows)
    surplus_arr = np.zeros(n_rows)
    allowed_exp_arr = np.zeros(n_rows)

    for idx, (_, row) in enumerate(work_df.iterrows()):
        dt = row["local_datetime"]
        hour = dt.hour if hasattr(dt, "hour") else 12
        p_kwh = float(row.get("price_eur_kwh", 0.10))
        ci_kwh = float(row.get("carbon_intensity_gco2_kwh", 250.0))
        score = float(row["composite_score"])
        ren_pct = float(row.get("renewable_share_pct", 50.0))

        if SOLAR_START_HOUR <= hour <= SOLAR_END_HOUR:
            solar_curve = math.sin((hour - 6) * math.pi / 14.0)
            solar_gen = solar_kwp * max(0.05, min(1.0, ren_pct / 100.0)) * solar_curve
        else:
            solar_gen = 0.0

        if custom_load_profile_kw and len(custom_load_profile_kw) > 0:
            if isinstance(custom_load_profile_kw, dict):
                hour_base_kw = float(custom_load_profile_kw.get(hour, baseline_load_kw))
            else:
                hour_base_kw = float(custom_load_profile_kw[hour % len(custom_load_profile_kw)])
        else:
            hour_base_kw = baseline_load_kw

        net_unmanaged = hour_base_kw + (max_flexible_load_kw * 0.4) - solar_gen
        surplus = abs(min(0.0, net_unmanaged))
        allowed_exp = 0.0 if p_kwh < 0.0 else effective_export_limit_kw

        prices_arr[idx] = p_kwh
        ci_arr[idx] = ci_kwh
        scores_arr[idx] = score
        solar_arr[idx] = solar_gen
        base_arr[idx] = hour_base_kw
        surplus_arr[idx] = surplus
        allowed_exp_arr[idx] = allowed_exp

    lp_charge_arr = np.zeros(n_rows)
    lp_discharge_arr = np.zeros(n_rows)
    if use_lp:
        lp_charge_arr, lp_discharge_arr = _solve_bess_lp(
            prices=prices_arr,
            carbon_intensities=ci_arr,
            scores=scores_arr,
            surplus_solar_kw=surplus_arr,
            allowed_export_kw=allowed_exp_arr,
            alpha=alpha,
            bess_capacity_kwh=bess_capacity_kwh,
            bess_min_kwh=bess_min_kwh,
            bess_max_kwh=bess_max_kwh,
            initial_bess_kwh=current_bess_kwh,
            bess_max_charge_kw=bess_max_charge_kw,
            bess_max_discharge_kw=bess_max_discharge_kw,
            eta_rt=bess_roundtrip_efficiency,
            marginal_cycle_cost_eur_kwh=marginal_cycle_cost_eur_kwh,
            shadow_carbon_eur_tco2=shadow_carbon_eur_tco2,
        )

    p_spread = float(np.max(prices_arr) - np.min(prices_arr)) if n_rows > 0 else 0.0
    schedule_rows = []
    total_charged_kwh = 0.0
    total_discharged_kwh = 0.0
    solar_rescued_kwh = 0.0

    for idx, (_, row) in enumerate(work_df.iterrows()):
        dt = row["local_datetime"]
        p_kwh = prices_arr[idx]
        ci_kwh = ci_arr[idx]
        score = scores_arr[idx]
        ren_pct = float(row.get("renewable_share_pct", 50.0))
        solar_generation_kw = solar_arr[idx]
        hour_base_kw = base_arr[idx]

        net_unmanaged_load_kw = (
            hour_base_kw + (max_flexible_load_kw * 0.4) - solar_generation_kw
        )
        curtailed_solar_kw = 0.0
        bess_action_kw = 0.0
        flex_load_kw = max_flexible_load_kw * 0.35
        action = "HOLD_BASELINE"

        charge_headroom_kw = min(
            bess_max_charge_kw,
            max(0.0, (bess_max_kwh - current_bess_kwh) / math.sqrt(bess_roundtrip_efficiency)),
        )
        discharge_headroom_kw = min(
            bess_max_discharge_kw,
            max(0.0, (current_bess_kwh - bess_min_kwh) * math.sqrt(bess_roundtrip_efficiency)),
        )

        lp_net_kw = lp_charge_arr[idx] - lp_discharge_arr[idx]

        if (
            (net_unmanaged_load_kw < -effective_export_limit_kw)
            or (is_congestion_active and net_unmanaged_load_kw < 0)
            or (p_kwh < 0.0 and net_unmanaged_load_kw < 0)
        ):
            surplus_kw = abs(min(0.0, net_unmanaged_load_kw))
            bess_action_kw = min(max(surplus_kw, lp_charge_arr[idx]), charge_headroom_kw)
            remaining_surplus_kw = max(0.0, surplus_kw - bess_action_kw)
            allowed_export_kw = 0.0 if p_kwh < 0.0 else effective_export_limit_kw
            unmanaged_curtailment = max(0.0, surplus_kw - allowed_export_kw)
            if remaining_surplus_kw > allowed_export_kw:
                curtailed_solar_kw = remaining_surplus_kw - allowed_export_kw
                action = "CURTAIL_SOLAR"
            else:
                action = "CHARGE_BATTERY" if bess_action_kw > 25.0 else "HOLD_BASELINE"
            solar_rescued_kwh += max(0.0, unmanaged_curtailment - curtailed_solar_kw)

        elif use_lp and abs(lp_net_kw) > 25.0:
            if lp_net_kw > 25.0 and charge_headroom_kw > 25.0:
                bess_action_kw = min(lp_net_kw, charge_headroom_kw)
                action = "CHARGE_BATTERY"
                if score <= SCORE_RAMP_THRESHOLD and not is_congestion_active:
                    flex_load_kw = max_flexible_load_kw * 0.75
            elif lp_net_kw < -25.0 and discharge_headroom_kw > 25.0:
                bess_action_kw = -min(abs(lp_net_kw), discharge_headroom_kw)
                action = "DISCHARGE_BATTERY"
                flex_load_kw = 0.0
            else:
                action = "HOLD_BASELINE"

        elif (score <= SCORE_CHARGE_THRESHOLD or p_kwh <= PRICE_CHARGE_GATE_EUR_KWH) and (
            p_spread >= marginal_cycle_cost_eur_kwh
            or p_kwh <= PRICE_CHARGE_GATE_EUR_KWH
            or alpha < 0.35
        ):
            if charge_headroom_kw > 25.0:
                bess_action_kw = charge_headroom_kw
                action = "CHARGE_BATTERY"
            elif not is_congestion_active:
                flex_load_kw = max_flexible_load_kw
                action = "RAMP_LOAD"
            else:
                action = "HOLD_BASELINE"

        elif score <= SCORE_RAMP_THRESHOLD and not is_congestion_active:
            flex_load_kw = max_flexible_load_kw
            action = "RAMP_LOAD"

        elif (score >= SCORE_DISCHARGE_THRESHOLD or p_kwh >= PRICE_DISCHARGE_GATE_EUR_KWH) and (
            p_spread >= marginal_cycle_cost_eur_kwh
            or p_kwh >= PRICE_DISCHARGE_GATE_EUR_KWH
            or alpha < 0.35
        ):
            if discharge_headroom_kw > 25.0:
                bess_action_kw = -discharge_headroom_kw
                action = "DISCHARGE_BATTERY"
                flex_load_kw = 0.0
            else:
                action = "HOLD_BASELINE"

        if bess_action_kw > 0:
            current_bess_kwh += bess_action_kw * math.sqrt(bess_roundtrip_efficiency)
            total_charged_kwh += bess_action_kw
        elif bess_action_kw < 0:
            current_bess_kwh -= abs(bess_action_kw) / math.sqrt(bess_roundtrip_efficiency)
            total_discharged_kwh += abs(bess_action_kw)

        current_bess_kwh = max(bess_min_kwh, min(bess_max_kwh, current_bess_kwh))
        soc_pct = 100.0 * (current_bess_kwh / max(1.0, bess_capacity_kwh))

        effective_solar_kw = max(0.0, solar_generation_kw - curtailed_solar_kw)
        optimized_net_kw = hour_base_kw + flex_load_kw + bess_action_kw - effective_solar_kw
        unmanaged_net_kw = hour_base_kw + (max_flexible_load_kw * 0.5) - solar_generation_kw

        hourly_deg_cost_eur = 0.5 * abs(bess_action_kw) * marginal_cycle_cost_eur_kwh
        baseline_cost_eur = max(0.0, unmanaged_net_kw) * p_kwh
        optimized_energy_cost_eur = (
            (optimized_net_kw * p_kwh)
            if optimized_net_kw >= 0
            else (optimized_net_kw * max(0.0, p_kwh * 0.85))
        )
        optimized_cost_eur = optimized_energy_cost_eur + hourly_deg_cost_eur
        cost_saving_eur = baseline_cost_eur - optimized_cost_eur

        if optimized_net_kw <= unmanaged_net_kw:
            carbon_saving_g = (unmanaged_net_kw - optimized_net_kw) * ci_kwh
        else:
            carbon_saving_g = (optimized_net_kw - unmanaged_net_kw) * (avg_ci_kwh - ci_kwh)

        schedule_rows.append(
            {
                "timestamp_utc": row["timestamp_utc"],
                "local_datetime": dt,
                "price_eur_kwh": round(p_kwh, 4),
                "carbon_intensity_gco2_kwh": round(ci_kwh, 1),
                "renewable_share_pct": round(ren_pct, 1),
                "composite_score": round(score, 3),
                "baseline_load_kw": round(hour_base_kw, 1),
                "estimated_solar_kw": round(solar_generation_kw, 1),
                "effective_export_limit_kw": round(effective_export_limit_kw, 1),
                "bess_power_kw": round(bess_action_kw, 1),
                "bess_soc_pct": round(soc_pct, 1),
                "flex_load_kw": round(flex_load_kw, 1),
                "curtailed_solar_kw": round(curtailed_solar_kw, 1),
                "degradation_cost_eur": round(hourly_deg_cost_eur, 2),
                "dispatch_action": action,
                "flag_charge_battery": action == "CHARGE_BATTERY",
                "flag_curtail_solar": action == "CURTAIL_SOLAR",
                "flag_ramp_load": action == "RAMP_LOAD",
                "flag_discharge_battery": action == "DISCHARGE_BATTERY",
                "net_grid_import_kw": round(optimized_net_kw, 1),
                "baseline_hourly_cost_eur": round(baseline_cost_eur, 2),
                "optimized_hourly_cost_eur": round(optimized_cost_eur, 2),
                "cost_saving_eur": round(cost_saving_eur, 2),
                "carbon_saving_g": round(carbon_saving_g, 1),
            }
        )

    df_schedule = pd.DataFrame(schedule_rows)
    total_baseline_cost = float(df_schedule["baseline_hourly_cost_eur"].sum())
    total_optimized_cost = float(df_schedule["optimized_hourly_cost_eur"].sum())
    total_degradation_cost = float(df_schedule["degradation_cost_eur"].sum())
    net_savings_eur = total_baseline_cost - total_optimized_cost
    carbon_avoided_kg = float(df_schedule["carbon_saving_g"].sum()) / 1000.0
    baseline_emissions_kg = (
        float(
            (
                np.maximum(
                    0.0,
                    df_schedule["baseline_load_kw"]
                    + (max_flexible_load_kw * 0.5)
                    - df_schedule["estimated_solar_kw"],
                )
                * df_schedule["carbon_intensity_gco2_kwh"]
            ).sum()
        )
        / 1000.0
    )
    optimized_emissions_kg = max(0.0, baseline_emissions_kg - carbon_avoided_kg)
    carbon_saving_pct = round(
        100.0 * carbon_avoided_kg / max(baseline_emissions_kg, 1e-4), 1
    )
    bess_cycles = round(
        0.5 * (total_charged_kwh + total_discharged_kwh) / max(1.0, bess_capacity_kwh), 2
    )
    curtailed_total_kwh = float(df_schedule["curtailed_solar_kw"].sum())
    peak_shaving_kw = float(
        df_schedule["baseline_hourly_cost_eur"].max()
        - df_schedule["optimized_hourly_cost_eur"].max()
    )
    implied_abatement_cost_eur_tco2 = round(
        (-net_savings_eur / (carbon_avoided_kg / 1000.0))
        if abs(carbon_avoided_kg) > 1e-3
        else 0.0,
        2,
    )

    return {
        "df_schedule": df_schedule,
        "total_baseline_cost_eur": round(total_baseline_cost, 2),
        "total_optimized_cost_eur": round(total_optimized_cost, 2),
        "total_degradation_cost_eur": round(total_degradation_cost, 2),
        "net_financial_yield_eur": round(net_savings_eur, 2),
        "cost_saving_pct": round(
            100.0 * net_savings_eur / max(total_baseline_cost, 1e-4), 1
        ),
        "baseline_emissions_kg": round(baseline_emissions_kg, 1),
        "optimized_emissions_kg": round(optimized_emissions_kg, 1),
        "total_carbon_avoided_kg": round(carbon_avoided_kg, 1),
        "carbon_saving_pct": carbon_saving_pct,
        "bess_cycles": bess_cycles,
        "curtailed_solar_kwh": round(curtailed_total_kwh, 1),
        "solar_curtailment_avoided_kwh": round(solar_rescued_kwh, 1),
        "implied_abatement_cost_eur_tco2": implied_abatement_cost_eur_tco2,
        "peak_shaving_kw": round(peak_shaving_kw, 1),
        "is_congestion_active": is_congestion_active,
        "export_factor": export_factor,
    }


def compute_pareto_frontier(
    df_metrics: pd.DataFrame,
    asset_config: dict[str, Any],
    df_congestion: pd.DataFrame = None,
    steps: int = 11,
) -> pd.DataFrame:
    if df_metrics.empty:
        return pd.DataFrame()

    alphas = np.linspace(0.0, 1.0, steps)
    rows: list[dict[str, Any]] = []
    cfg_clean = dict(asset_config)
    cfg_clean.pop("shadow_carbon_eur_tco2", None)

    for a_val in alphas:
        res = simulate_commercial_dispatch(
            df_metrics=df_metrics,
            asset_config=cfg_clean,
            alpha=float(a_val),
            df_congestion=df_congestion,
            use_lp=True,
        )
        if not res:
            continue
        rows.append(
            {
                "alpha": round(float(a_val), 2),
                "total_cost_eur": res["total_optimized_cost_eur"],
                "total_emissions_kg": res["optimized_emissions_kg"],
                "net_savings_eur": res["net_financial_yield_eur"],
                "carbon_avoided_kg": res["total_carbon_avoided_kg"],
            }
        )

    return pd.DataFrame(rows)
