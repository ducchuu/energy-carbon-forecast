import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

DARK_LAYOUT = dict(
    template="plotly_dark",
    paper_bgcolor="rgba(15, 23, 42, 0.72)",
    plot_bgcolor="rgba(11, 17, 32, 0.85)",
    font=dict(family="Inter, -apple-system, sans-serif", color="#CBD5E1", size=12),
    hovermode="x unified",
    hoverlabel=dict(
        bgcolor="#0F172A",
        bordercolor="rgba(56, 189, 248, 0.45)",
        font=dict(color="#F8FAFC", size=12),
    ),
)

ACTION_STYLES = {
    "CHARGE_BATTERY": {
        "fill": "rgba(16, 185, 129, 0.14)",
        "label": "Charge",
        "color": "#10B981",
    },
    "DISCHARGE_BATTERY": {
        "fill": "rgba(167, 139, 250, 0.14)",
        "label": "Discharge",
        "color": "#A78BFA",
    },
    "CURTAIL_SOLAR": {
        "fill": "rgba(244, 63, 94, 0.18)",
        "label": "Curtail",
        "color": "#F43F5E",
    },
}


def merge_action_spans(df_sched: pd.DataFrame) -> list[dict]:
    if df_sched.empty or "dispatch_action" not in df_sched.columns:
        return []

    spans: list[dict] = []
    ordered = df_sched.sort_values("local_datetime").reset_index(drop=True)

    current_action = None
    span_start = None
    span_end = None

    for _, row in ordered.iterrows():
        act = row["dispatch_action"]
        t_start = row["local_datetime"]
        t_end = t_start + pd.Timedelta(hours=1)

        if act not in ACTION_STYLES:
            if current_action is not None:
                spans.append(
                    {"action": current_action, "x0": span_start, "x1": span_end}
                )
                current_action = None
            continue

        if act == current_action and span_end == t_start:
            span_end = t_end
        else:
            if current_action is not None:
                spans.append(
                    {"action": current_action, "x0": span_start, "x1": span_end}
                )
            current_action = act
            span_start = t_start
            span_end = t_end

    if current_action is not None:
        spans.append({"action": current_action, "x0": span_start, "x1": span_end})

    return spans


def build_dispatch_cockpit_chart(
    df_sched: pd.DataFrame,
    show_action_bands: bool = True,
    show_solar_overlay: bool = True,
    bess_min_soc_pct: float = 10.0,
    bess_max_soc_pct: float = 95.0,
    height: int = 620,
) -> go.Figure:
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.14,
        row_heights=[0.52, 0.48],
        subplot_titles=(
            "Day-Ahead Price (€/kWh) vs. Carbon Intensity (gCO₂/kWh)",
            "Battery State-of-Charge (%) & Power Dispatch (kW)",
        ),
        specs=[[{"secondary_y": True}], [{"secondary_y": True}]],
    )

    ordered = df_sched.sort_values("local_datetime").reset_index(drop=True)
    has_fc_flag = "is_forecasted" in ordered.columns and ordered["is_forecasted"].nunique() > 1

    if has_fc_flag:
        actual_df = ordered[ordered["is_forecasted"] == False]
        fc_df = ordered[ordered["is_forecasted"] == True]
        if not actual_df.empty and not fc_df.empty:
            fc_bridge = pd.concat([actual_df.iloc[[-1]], fc_df], ignore_index=True)
        else:
            fc_bridge = fc_df

        if not actual_df.empty:
            fig.add_trace(
                go.Scatter(
                    x=actual_df["local_datetime"],
                    y=actual_df["price_eur_kwh"],
                    name="Price Actual (€/kWh)",
                    line=dict(color="#38BDF8", width=2.8),
                    hovertemplate="€%{y:.4f}/kWh<extra>Price (Actual)</extra>",
                ),
                row=1,
                col=1,
                secondary_y=False,
            )
            fig.add_trace(
                go.Scatter(
                    x=actual_df["local_datetime"],
                    y=actual_df["carbon_intensity_gco2_kwh"],
                    name="Carbon Actual (g/kWh)",
                    line=dict(color="#FB7185", width=2.4),
                    hovertemplate="%{y:.1f} gCO₂/kWh<extra>Carbon (Actual)</extra>",
                ),
                row=1,
                col=1,
                secondary_y=True,
            )

        if not fc_bridge.empty:
            fig.add_trace(
                go.Scatter(
                    x=fc_bridge["local_datetime"],
                    y=fc_bridge["price_eur_kwh"],
                    name="Price Forecast (€/kWh)",
                    line=dict(color="#38BDF8", width=2.4, dash="dash"),
                    hovertemplate="€%{y:.4f}/kWh<extra>Price (Day-Ahead)</extra>",
                ),
                row=1,
                col=1,
                secondary_y=False,
            )
            fig.add_trace(
                go.Scatter(
                    x=fc_bridge["local_datetime"],
                    y=fc_bridge["carbon_intensity_gco2_kwh"],
                    name="Carbon Forecast (g/kWh)",
                    line=dict(color="#FB7185", width=2.2, dash="dot"),
                    hovertemplate="%{y:.1f} gCO₂/kWh<extra>Carbon (Forecast)</extra>",
                ),
                row=1,
                col=1,
                secondary_y=True,
            )

        if not fc_df.empty:
            now_x = fc_df.iloc[0]["local_datetime"]
            fig.add_vline(
                x=now_x,
                line_width=1.5,
                line_dash="dash",
                line_color="rgba(248, 250, 252, 0.45)",
            )
            fig.add_annotation(
                x=now_x,
                y=0.97,
                yref="y domain",
                text="NOW",
                showarrow=False,
                xanchor="left",
                yanchor="top",
                xshift=6,
                font=dict(size=10, color="#E2E8F0", family="JetBrains Mono, monospace"),
                bgcolor="rgba(15, 23, 42, 0.88)",
                bordercolor="rgba(148, 163, 184, 0.35)",
                borderpad=3,
            )
    else:
        fig.add_trace(
            go.Scatter(
                x=ordered["local_datetime"],
                y=ordered["price_eur_kwh"],
                name="Price (€/kWh)",
                line=dict(color="#38BDF8", width=2.8),
                hovertemplate="€%{y:.4f}/kWh<extra>Price</extra>",
            ),
            row=1,
            col=1,
            secondary_y=False,
        )
        fig.add_trace(
            go.Scatter(
                x=ordered["local_datetime"],
                y=ordered["carbon_intensity_gco2_kwh"],
                name="Carbon (g/kWh)",
                line=dict(color="#FB7185", width=2.4, dash="dot"),
                hovertemplate="%{y:.1f} gCO₂/kWh<extra>Carbon</extra>",
            ),
            row=1,
            col=1,
            secondary_y=True,
        )

    fig.add_trace(
        go.Scatter(
            x=ordered["local_datetime"],
            y=ordered["bess_soc_pct"],
            name="BESS SoC (%)",
            line=dict(color="#A78BFA", width=2.8),
            fill="tozeroy",
            fillcolor="rgba(167, 139, 250, 0.16)",
            hovertemplate="%{y:.1f}%<extra>BESS SoC</extra>",
        ),
        row=2,
        col=1,
        secondary_y=False,
    )

    bess_colors = [
        "#10B981" if v > 0 else ("#A78BFA" if v < 0 else "rgba(100,116,139,0.25)")
        for v in ordered["bess_power_kw"]
    ]
    fig.add_trace(
        go.Bar(
            x=ordered["local_datetime"],
            y=ordered["bess_power_kw"],
            name="BESS Dispatch (+Chg / -Dis kW)",
            marker_color=bess_colors,
            opacity=0.82,
            hovertemplate="%{y:+.1f} kW<extra>BESS Power</extra>",
        ),
        row=2,
        col=1,
        secondary_y=True,
    )

    if show_solar_overlay and "estimated_solar_kw" in ordered.columns:
        fig.add_trace(
            go.Scatter(
                x=ordered["local_datetime"],
                y=ordered["estimated_solar_kw"],
                name="Solar PV Gen (kW)",
                line=dict(color="#FBBF24", width=2.0),
                hovertemplate="%{y:.1f} kW<extra>Solar PV</extra>",
            ),
            row=2,
            col=1,
            secondary_y=True,
        )

    fig.add_hline(
        y=bess_max_soc_pct,
        line_dash="dot",
        line_width=1,
        line_color="rgba(167, 139, 250, 0.35)",
        row=2,
        col=1,
    )
    fig.add_hline(
        y=bess_min_soc_pct,
        line_dash="dot",
        line_width=1,
        line_color="rgba(167, 139, 250, 0.35)",
        row=2,
        col=1,
    )

    if show_action_bands:
        for span in merge_action_spans(ordered):
            style = ACTION_STYLES[span["action"]]
            fig.add_vrect(
                x0=span["x0"],
                x1=span["x1"],
                fillcolor=style["fill"],
                layer="below",
                line_width=0,
                row=1,
                col=1,
            )

    fig.update_layout(
        **DARK_LAYOUT,
        height=height,
        margin=dict(l=54, r=54, t=112, b=40),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.10,
            xanchor="left",
            x=0.0,
            font=dict(size=11),
            bgcolor="rgba(0,0,0,0)",
            itemclick="toggle",
        ),
        barmode="relative",
    )

    grid_cfg = dict(gridcolor="rgba(148, 163, 184, 0.09)", zerolinecolor="rgba(148, 163, 184, 0.18)")
    fig.update_xaxes(**grid_cfg, tickformat="%d %b %H:%M")
    fig.update_yaxes(**grid_cfg, title_text="€/kWh", row=1, col=1, secondary_y=False)
    fig.update_yaxes(showgrid=False, title_text="gCO₂/kWh", row=1, col=1, secondary_y=True)
    fig.update_yaxes(**grid_cfg, title_text="SoC (%)", range=[0, 105], row=2, col=1, secondary_y=False)
    fig.update_yaxes(showgrid=False, title_text="Power (kW)", row=2, col=1, secondary_y=True)

    for ann in fig.layout.annotations:
        if ann.text in (
            "Day-Ahead Price (€/kWh) vs. Carbon Intensity (gCO₂/kWh)",
            "Battery State-of-Charge (%) & Power Dispatch (kW)",
        ):
            ann.font = dict(size=12, color="#E2E8F0", family="Inter, sans-serif")
            ann.yshift = 6

    return fig


def build_pareto_chart(
    df_pareto: pd.DataFrame,
    active_cost: float,
    active_emissions: float,
    active_alpha: float,
    height: int = 560,
) -> go.Figure:
    fig = go.Figure()
    if df_pareto.empty:
        fig.update_layout(**DARK_LAYOUT, height=height)
        return fig

    fig.add_trace(
        go.Scatter(
            x=df_pareto["total_cost_eur"],
            y=df_pareto["total_emissions_kg"],
            mode="lines+markers",
            name="Pareto Frontier (α ∈ [0, 1])",
            customdata=df_pareto[["alpha", "net_savings_eur", "carbon_avoided_kg"]].to_numpy(),
            hovertemplate=(
                "<b>α = %{customdata[0]:.2f}</b><br>"
                "Net Spend: €%{x:,.2f}<br>"
                "Scope 2: %{y:,.1f} kgCO₂<br>"
                "Savings: €%{customdata[1]:,.2f} · Abated: %{customdata[2]:,.1f} kg<extra></extra>"
            ),
            line=dict(color="rgba(148, 163, 184, 0.55)", width=2.5),
            marker=dict(
                size=10,
                color=df_pareto["alpha"],
                colorscale=[[0.0, "#10B981"], [0.5, "#38BDF8"], [1.0, "#F59E0B"]],
                line=dict(width=1.5, color="#0F172A"),
                showscale=True,
                colorbar=dict(title="α", thickness=12, len=0.65),
            ),
        )
    )

    fig.add_trace(
        go.Scatter(
            x=[active_cost],
            y=[active_emissions],
            mode="markers+text",
            name=f"Active (α={active_alpha:.2f})",
            text=[f"Active α={active_alpha:.2f}"],
            textposition="top center",
            textfont=dict(color="#34D399", size=11),
            marker=dict(
                size=16,
                color="#10B981",
                symbol="diamond",
                line=dict(width=2.5, color="#ECFDF5"),
            ),
            hovertemplate="<b>Active Operating Point</b><br>Spend: €%{x:,.2f}<br>Emissions: %{y:,.1f} kgCO₂<extra></extra>",
        )
    )

    fig.update_layout(
        **DARK_LAYOUT,
        height=height,
        title=dict(
            text="Cost vs. Scope 2 Carbon Pareto Frontier",
            font=dict(size=14, color="#F8FAFC"),
            y=0.96,
            yanchor="top",
        ),
        xaxis_title="Total Net Energy Spend (€)",
        yaxis_title="Total Scope 2 Footprint (kgCO₂)",
        margin=dict(l=58, r=30, t=92, b=52),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, font=dict(size=11)),
    )
    grid_cfg = dict(gridcolor="rgba(148, 163, 184, 0.09)")
    fig.update_xaxes(**grid_cfg)
    fig.update_yaxes(**grid_cfg)
    return fig


def build_cost_comparison_chart(df_sched: pd.DataFrame, height: int = 330) -> go.Figure:
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    ordered = df_sched.sort_values("local_datetime").reset_index(drop=True)
    cum_savings = ordered["cost_saving_eur"].cumsum()

    fig.add_trace(
        go.Bar(
            x=ordered["local_datetime"],
            y=ordered["baseline_hourly_cost_eur"],
            name="Unmanaged Baseline (€)",
            marker_color="rgba(148, 163, 184, 0.35)",
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Bar(
            x=ordered["local_datetime"],
            y=ordered["optimized_hourly_cost_eur"],
            name="OptiGrid MPC (€)",
            marker_color="rgba(56, 189, 248, 0.78)",
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=ordered["local_datetime"],
            y=cum_savings,
            name="Cumulative Savings (€)",
            line=dict(color="#10B981", width=2.8),
        ),
        secondary_y=True,
    )

    fig.update_layout(
        **DARK_LAYOUT,
        height=height,
        barmode="group",
        title=dict(
            text="Hourly Spend: Baseline vs. OptiGrid MPC",
            font=dict(size=13, color="#F8FAFC"),
            y=0.95,
            yanchor="top",
        ),
        margin=dict(l=52, r=52, t=86, b=38),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, font=dict(size=10)),
    )
    fig.update_xaxes(gridcolor="rgba(148, 163, 184, 0.09)", tickformat="%H:%M")
    fig.update_yaxes(gridcolor="rgba(148, 163, 184, 0.09)", title_text="Hourly Cost (€)", secondary_y=False)
    fig.update_yaxes(showgrid=False, title_text="Cum. Savings (€)", secondary_y=True)
    return fig


def build_forecast_accuracy_chart(
    df_accuracy: pd.DataFrame,
    df_metrics: pd.DataFrame,
    height: int = 560,
) -> go.Figure:
    fig = make_subplots(
        rows=2,
        cols=1,
        vertical_spacing=0.18,
        subplot_titles=(
            "7-Day Carbon Forecast Backtest: Forecast vs. Actual (gCO₂/kWh)",
            "Grid Imbalance Prices: Shortage vs. Surplus Spread (€/MWh)",
        ),
    )

    if df_accuracy is not None and not df_accuracy.empty and "actual_ci_gco2_kwh" in df_accuracy.columns:
        acc = df_accuracy.sort_values("local_datetime")
        fig.add_trace(
            go.Scatter(
                x=acc["local_datetime"],
                y=acc["actual_ci_gco2_kwh"],
                name="Actual CI (g/kWh)",
                line=dict(color="#10B981", width=2.4),
            ),
            row=1,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=acc["local_datetime"],
                y=acc["forecast_ci_gco2_kwh"],
                name="Forecast CI (g/kWh)",
                line=dict(color="#38BDF8", width=2.2, dash="dash"),
            ),
            row=1,
            col=1,
        )

    if (
        df_metrics is not None
        and not df_metrics.empty
        and "imbalance_shortage_eur_mwh" in df_metrics.columns
    ):
        met = df_metrics.sort_values("local_datetime")
        fig.add_trace(
            go.Scatter(
                x=met["local_datetime"],
                y=met["imbalance_shortage_eur_mwh"],
                name="Imbalance Shortage (€/MWh)",
                line=dict(color="#FB7185", width=2.2),
            ),
            row=2,
            col=1,
        )
        if "imbalance_surplus_eur_mwh" in met.columns:
            fig.add_trace(
                go.Scatter(
                    x=met["local_datetime"],
                    y=met["imbalance_surplus_eur_mwh"],
                    name="Imbalance Surplus (€/MWh)",
                    line=dict(color="#F59E0B", width=2.2),
                    fill="tonexty",
                    fillcolor="rgba(245, 158, 11, 0.10)",
                ),
                row=2,
                col=1,
            )

    fig.update_layout(
        **DARK_LAYOUT,
        height=height,
        margin=dict(l=56, r=36, t=106, b=42),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.10,
            xanchor="left",
            x=0,
            font=dict(size=11),
            bgcolor="rgba(0,0,0,0)",
        ),
    )
    grid_cfg = dict(gridcolor="rgba(148, 163, 184, 0.09)")
    fig.update_xaxes(**grid_cfg)
    fig.update_yaxes(**grid_cfg, title_text="gCO₂/kWh", row=1, col=1)
    fig.update_yaxes(**grid_cfg, title_text="€/MWh", row=2, col=1)
    for ann in fig.layout.annotations:
        ann.font = dict(size=12, color="#E2E8F0", family="Inter, sans-serif")
        ann.yshift = 6
    return fig
