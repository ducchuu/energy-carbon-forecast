from typing import Any

import streamlit as st


def inject_custom_css() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap');

        :root {
            --bg-canvas: #060911;
            --bg-surface: #0F172A;
            --bg-card: #111827;
            --bg-card-hover: #172033;
            --border-subtle: rgba(148, 163, 184, 0.14);
            --border-strong: rgba(56, 189, 248, 0.35);
            --text-primary: #F8FAFC;
            --text-secondary: #94A3B8;
            --text-muted: #64748B;
            --accent-cyan: #38BDF8;
            --accent-emerald: #10B981;
            --accent-violet: #A78BFA;
            --accent-rose: #FB7185;
            --accent-amber: #F59E0B;
        }

        html, body {
            background-color: var(--bg-canvas) !important;
            color: var(--text-primary);
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            overflow-x: hidden;
        }

        /* Responsive Control-Room Canvas (calibrated for 1920x1080, scales cleanly to 2K+) */
        [data-testid="stApp"] {
            width: 100% !important;
            min-height: 100vh !important;
            background: radial-gradient(circle at 18% 0%, #111C33 0%, #090D16 52%, #060911 100%) !important;
        }

        [data-testid="stHeader"] {
            height: 2.1rem !important;
            background: transparent !important;
        }

        [data-testid="stToolbar"] {
            right: 1rem !important;
            top: 0.25rem !important;
        }

        #MainMenu, footer {
            visibility: hidden;
        }

        /* Sidebar responsive width */
        [data-testid="stSidebar"] {
            width: clamp(275px, 16.5vw, 340px) !important;
            min-width: 275px !important;
            background: linear-gradient(180deg, #0B1120 0%, #080C17 100%) !important;
            border-right: 1px solid var(--border-subtle) !important;
        }

        [data-testid="stSidebar"] > div:first-child {
            padding-top: 1rem !important;
            padding-left: 1rem !important;
            padding-right: 1rem !important;
        }

        [data-testid="stSidebar"] h1,
        [data-testid="stSidebar"] h2,
        [data-testid="stSidebar"] h3 {
            color: var(--text-primary) !important;
            letter-spacing: -0.01em;
        }

        /* Main container fills available viewport width & height */
        [data-testid="stMain"] {
            min-height: 100vh !important;
            overflow-x: hidden !important;
        }

        [data-testid="stMainBlockContainer"],
        .block-container {
            max-width: 100% !important;
            padding: 1rem clamp(1.1rem, 1.8vw, 2.2rem) 1rem clamp(1.1rem, 1.8vw, 2.2rem) !important;
        }

        /* Custom Header Command Bar */
        .og-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            background: rgba(17, 24, 39, 0.85);
            border: 1px solid var(--border-subtle);
            border-radius: 12px;
            padding: 10px 18px;
            margin-bottom: 12px;
            backdrop-filter: blur(12px);
        }

        .og-header-left {
            display: flex;
            align-items: center;
            gap: 14px;
        }

        .og-logo-badge {
            width: 38px;
            height: 38px;
            border-radius: 10px;
            background: linear-gradient(135deg, rgba(56, 189, 248, 0.22), rgba(16, 185, 129, 0.22));
            border: 1px solid rgba(56, 189, 248, 0.45);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 18px;
            font-weight: 700;
            color: #38BDF8;
        }

        .og-title {
            font-size: 1.18rem;
            font-weight: 700;
            color: #F8FAFC;
            letter-spacing: -0.02em;
            line-height: 1.2;
        }

        .og-subtitle {
            font-size: 0.78rem;
            color: #94A3B8;
            margin-top: 2px;
            display: flex;
            align-items: center;
            gap: 8px;
            flex-wrap: wrap;
        }

        .og-mono {
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.75rem;
        }

        .og-header-right {
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .og-pill {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 5px 11px;
            border-radius: 999px;
            font-size: 0.75rem;
            font-weight: 600;
            border: 1px solid var(--border-subtle);
            background: rgba(15, 23, 42, 0.9);
            color: #E2E8F0;
            white-space: nowrap;
        }

        .og-pill-nominal {
            border-color: rgba(16, 185, 129, 0.40);
            background: rgba(16, 185, 129, 0.12);
            color: #34D399;
        }

        .og-pill-alert {
            border-color: rgba(244, 63, 94, 0.50);
            background: rgba(244, 63, 94, 0.14);
            color: #FDA4AF;
        }

        .og-pill-info {
            border-color: rgba(56, 189, 248, 0.35);
            background: rgba(56, 189, 248, 0.10);
            color: #7DD3FC;
        }

        .og-dot {
            width: 7px;
            height: 7px;
            border-radius: 50%;
            display: inline-block;
        }

        .og-dot-green { background: #10B981; box-shadow: 0 0 8px #10B981; }
        .og-dot-red { background: #F43F5E; box-shadow: 0 0 8px #F43F5E; }

        /* KPI Strip */
        .og-kpi-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 12px;
            margin-bottom: 12px;
        }

        .og-kpi-card {
            background: linear-gradient(180deg, rgba(17, 24, 39, 0.92) 0%, rgba(15, 23, 42, 0.88) 100%);
            border: 1px solid var(--border-subtle);
            border-radius: 12px;
            padding: 12px 16px;
            position: relative;
            overflow: hidden;
            transition: border-color 0.2s ease, transform 0.15s ease;
        }

        .og-kpi-card:hover {
            border-color: rgba(148, 163, 184, 0.30);
        }

        .og-kpi-accent {
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 2px;
        }

        .og-kpi-label {
            font-size: 0.72rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            color: #94A3B8;
            margin-bottom: 4px;
        }

        .og-kpi-value {
            font-family: 'JetBrains Mono', monospace;
            font-size: 1.55rem;
            font-weight: 700;
            color: #F8FAFC;
            line-height: 1.15;
        }

        .og-kpi-delta {
            font-size: 0.76rem;
            font-weight: 500;
            margin-top: 5px;
            display: flex;
            align-items: center;
            gap: 5px;
        }

        .og-delta-pos { color: #34D399; }
        .og-delta-warn { color: #FBBF24; }
        .og-delta-muted { color: #94A3B8; }

        /* Clean Tabs */
        [data-testid="stTabs"] [role="tablist"] {
            gap: 6px;
            border-bottom: 1px solid var(--border-subtle);
            padding-bottom: 6px;
            margin-bottom: 10px;
        }

        [data-testid="stTabs"] button[role="tab"] {
            background: rgba(15, 23, 42, 0.7);
            border: 1px solid var(--border-subtle);
            border-radius: 8px;
            padding: 6px 14px;
            color: #94A3B8;
            font-weight: 600;
            font-size: 0.82rem;
            height: auto;
        }

        [data-testid="stTabs"] button[role="tab"][aria-selected="true"] {
            background: rgba(56, 189, 248, 0.14);
            border-color: rgba(56, 189, 248, 0.45);
            color: #F8FAFC;
        }

        /* Side Telemetry Cards */
        .og-panel {
            background: rgba(15, 23, 42, 0.88);
            border: 1px solid var(--border-subtle);
            border-radius: 12px;
            padding: 14px 16px;
            margin-bottom: 10px;
        }

        .og-panel-title {
            font-size: 0.76rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            color: #94A3B8;
            margin-bottom: 10px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .og-stat-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 5px 0;
            border-bottom: 1px solid rgba(148, 163, 184, 0.08);
            font-size: 0.80rem;
        }

        .og-stat-row:last-child {
            border-bottom: none;
        }

        .og-stat-k { color: #94A3B8; }
        .og-stat-v {
            color: #F8FAFC;
            font-family: 'JetBrains Mono', monospace;
            font-weight: 600;
        }

        .og-action-bar {
            display: flex;
            height: 10px;
            border-radius: 999px;
            overflow: hidden;
            background: rgba(148, 163, 184, 0.12);
            margin: 8px 0 10px 0;
        }

        .og-action-legend {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 6px;
            font-size: 0.74rem;
            color: #CBD5E1;
        }

        .og-legend-item {
            display: flex;
            align-items: center;
            justify-content: space-between;
            background: rgba(17, 24, 39, 0.65);
            padding: 4px 8px;
            border-radius: 6px;
            border: 1px solid rgba(148, 163, 184, 0.08);
        }

        .og-swatch {
            width: 8px;
            height: 8px;
            border-radius: 2px;
            display: inline-block;
            margin-right: 6px;
        }

        /* Sidebar compact branding & status */
        .og-side-brand {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding-bottom: 8px;
            margin-bottom: 8px;
            border-bottom: 1px solid var(--border-subtle);
        }

        .og-side-title {
            font-size: 1.05rem;
            font-weight: 700;
            color: #F8FAFC;
            letter-spacing: -0.01em;
        }

        .og-res-badge {
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.65rem;
            padding: 2px 7px;
            border-radius: 999px;
            background: rgba(56, 189, 248, 0.12);
            border: 1px solid rgba(56, 189, 248, 0.30);
            color: #7DD3FC;
        }

        .og-side-footer {
            margin-top: 10px;
            padding: 8px 10px;
            border-radius: 8px;
            background: rgba(15, 23, 42, 0.75);
            border: 1px solid var(--border-subtle);
            font-size: 0.72rem;
            color: #94A3B8;
            line-height: 1.45;
        }

        /* Polish Streamlit expander & inputs in dark theme */
        [data-testid="stExpander"] {
            background: rgba(15, 23, 42, 0.65) !important;
            border: 1px solid var(--border-subtle) !important;
            border-radius: 10px !important;
        }

        div[data-testid="stMetric"] {
            background: rgba(17, 24, 39, 0.85);
            border: 1px solid var(--border-subtle);
            border-radius: 10px;
            padding: 10px 14px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_header_bar(
    facility_name: str,
    asset_id: str,
    zone_label: str,
    substation: str,
    sol_kwp: float,
    bess_kwh: float,
    marginal_cycle_cost: float,
    is_congestion: bool,
    export_factor: float,
    tso_name: str,
    mae_value: float | None,
) -> None:
    if is_congestion:
        status_cls = "og-pill-alert"
        dot_cls = "og-dot-red"
        status_text = f"{tso_name.upper()} Congestion · {export_factor * 100:.0f}% Cap"
    else:
        status_cls = "og-pill-nominal"
        dot_cls = "og-dot-green"
        status_text = f"{tso_name} Nominal · 100% Export"

    mae_pill = (
        f'<span class="og-pill og-pill-info">7d CI MAE: <span class="og-mono">{mae_value:.1f} g/kWh</span></span>'
        if mae_value is not None
        else ""
    )

    st.markdown(
        f"""
        <div class="og-header">
            <div class="og-header-left">
                <div class="og-logo-badge">⚡</div>
                <div>
                    <div class="og-title">{facility_name}</div>
                    <div class="og-subtitle">
                        <span class="og-mono">{asset_id}</span>
                        <span>•</span>
                        <span>{zone_label}</span>
                        <span>•</span>
                        <span>Substation <span class="og-mono">{substation}</span></span>
                        <span>•</span>
                        <span>{sol_kwp:,.0f} kWp Solar · {bess_kwh:,.0f} kWh BESS · Wear €{marginal_cycle_cost:.3f}/kWh</span>
                    </div>
                </div>
            </div>
            <div class="og-header-right">
                {mae_pill}
                <span class="og-pill {status_cls}">
                    <span class="og-dot {dot_cls}"></span>
                    {status_text}
                </span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_kpi_strip(dispatch_results: dict[str, Any]) -> None:
    opt_spend = float(dispatch_results.get("total_optimized_cost_eur", 0.0))
    saved_eur = float(dispatch_results.get("net_financial_yield_eur", 0.0))
    saved_pct = float(dispatch_results.get("cost_saving_pct", 0.0))

    opt_co2 = float(dispatch_results.get("optimized_emissions_kg", 0.0))
    abated_co2 = float(dispatch_results.get("total_carbon_avoided_kg", 0.0))
    carbon_pct = float(dispatch_results.get("carbon_saving_pct", 0.0))

    rescued_kwh = float(
        dispatch_results.get(
            "solar_curtailment_avoided_kwh",
            dispatch_results.get("curtailed_solar_kwh", 0.0),
        )
    )
    bess_cycles = float(dispatch_results.get("bess_cycles", 0.0))

    abatement_cost = float(dispatch_results.get("implied_abatement_cost_eur_tco2", 0.0))
    abatement_delta = (
        "Net negative cost (profit + green)"
        if abatement_cost <= 0
        else ("Below €65/t EU ETS" if abatement_cost <= 65.0 else "Above €65/t EU ETS")
    )
    abatement_cls = "og-delta-pos" if abatement_cost <= 65.0 else "og-delta-warn"

    st.markdown(
        f"""
        <div class="og-kpi-grid">
            <div class="og-kpi-card">
                <div class="og-kpi-accent" style="background: linear-gradient(90deg, #38BDF8, #10B981);"></div>
                <div class="og-kpi-label">Net Energy Spend</div>
                <div class="og-kpi-value">€{opt_spend:,.2f}</div>
                <div class="og-kpi-delta og-delta-pos">↓ €{saved_eur:,.2f} saved ({saved_pct:.1f}% vs baseline)</div>
            </div>
            <div class="og-kpi-card">
                <div class="og-kpi-accent" style="background: linear-gradient(90deg, #10B981, #34D399);"></div>
                <div class="og-kpi-label">Scope 2 Footprint</div>
                <div class="og-kpi-value">{opt_co2:,.1f} kgCO₂</div>
                <div class="og-kpi-delta og-delta-pos">↓ {abated_co2:,.1f} kg abated ({carbon_pct:.1f}% cleaner)</div>
            </div>
            <div class="og-kpi-card">
                <div class="og-kpi-accent" style="background: linear-gradient(90deg, #A78BFA, #38BDF8);"></div>
                <div class="og-kpi-label">Solar Rescued & Cycling</div>
                <div class="og-kpi-value">{rescued_kwh:,.1f} kWh</div>
                <div class="og-kpi-delta og-delta-muted">{bess_cycles:.2f} eq. BESS cycles executed</div>
            </div>
            <div class="og-kpi-card">
                <div class="og-kpi-accent" style="background: linear-gradient(90deg, #F59E0B, #FB7185);"></div>
                <div class="og-kpi-label">Implied Abatement Cost</div>
                <div class="og-kpi-value">€{abatement_cost:,.2f} / t</div>
                <div class="og-kpi-delta {abatement_cls}">{abatement_delta}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
