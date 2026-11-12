"""Reproducible view of observed prices, never invented intrabar OHLC."""
import json
import math
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def cutoff_chart(snapshot, row, bars):
    fig = go.Figure()
    prior = pd.DataFrame(bars)
    if not prior.empty:
        prior = prior.loc[prior.session.eq("PREVIA")].sort_values("bar_index")
    have_bars = len(prior) >= 20
    cut_x = 9
    if have_bars:
        middle = prior.close.astype(float).rolling(20).mean()
        std = prior.close.astype(float).rolling(20).std(ddof=0)
        prior = prior.assign(upper=middle + 2 * std, lower=middle - 2 * std, middle=middle).tail(8)
        x = list(range(len(prior)))
        cut_x = len(prior) + 1
        for field, name, color in (("upper", "Superior previa", "#72a899"),
                                    ("lower", "Inferior previa", "#72a899"),
                                    ("middle", "Media previa", "#85948b")):
            fig.add_trace(go.Scatter(x=x, y=prior[field].tolist(), name=name, mode="lines",
                                    line={"color": color, "width": 1.5}))
        fig.add_trace(go.Candlestick(x=x, open=prior.open.tolist(), high=prior.high.tolist(),
                                    low=prior.low.tolist(), close=prior.close.tolist(),
                                    name="Velas previas · 15 min", increasing_line_color="#6ab69d",
                                    decreasing_line_color="#cb8778"))
        labels = [str(t)[11:16] if "T" in str(t) else str(t) for t in prior.time]
        fig.update_xaxes(tickvals=x + [cut_x - .6, cut_x],
                         ticktext=labels + ["Primera", f"{snapshot['seconds']} s"])
    else:
        fig.update_xaxes(tickvals=[0, 8.4, 9], ticktext=["BB previa", "Primera", f"{snapshot['seconds']} s"])
        fig.add_annotation(text="Sin OHLC previos guardados · se muestran observaciones y bandas conocidas",
                           x=.5, y=1.12, xref="paper", yref="paper", showarrow=False,
                           font={"color": "#a9b4ab", "size": 11})
    start_x = len(prior) - 1 if have_bars else 0
    for prior_name, cut_name, title, color in (
            ("prior_bb_upper", "cutoff_bb_upper", "BB superior al corte", "#8acbb8"),
            ("prior_bb_lower", "cutoff_bb_lower", "BB inferior al corte", "#aeacdb")):
        a, b = number(row.get(prior_name)), number(row.get(cut_name))
        if a is not None and b is not None:
            fig.add_trace(go.Scatter(x=[start_x, cut_x], y=[a, b], mode="lines+markers",
                                    name=title, line={"color": color, "dash": "dot", "width": 2},
                                    marker={"size": 7}))
    first, last = number(row.get("first_price")), number(row.get("price_at_cutoff"))
    if first is not None and last is not None:
        fig.add_trace(go.Scatter(x=[cut_x - .6, cut_x], y=[first, last], mode="markers",
                                name="Precios observados", marker={"color": "#dfbf79", "size": 11,
                                                                   "symbol": ["circle", "diamond"]},
                                text=["Primera cotización", f"Corte {snapshot['seconds']} s"],
                                hovertemplate="%{text}: %{y:.3f}<extra></extra>"))
    fig.add_vline(x=start_x + .5, line_dash="dash", line_color="#4b5a50")
    fig.update_layout(template="plotly_dark", paper_bgcolor="#141d19", plot_bgcolor="#141d19",
                      font={"family": "Arial, sans-serif", "color": "#c7d0c9"},
                      title={"text": f"{row['ticker']} · {snapshot['date']} · datos conocidos a {snapshot['seconds']} s",
                             "font": {"size": 15}},
                      margin={"l": 25, "r": 30, "t": 85, "b": 40}, height=530,
                      legend={"orientation": "h", "y": -.15, "font": {"size": 10}},
                      xaxis_rangeslider_visible=False, hovermode="closest")
    fig.update_xaxes(gridcolor="#26352d", zeroline=False)
    fig.update_yaxes(gridcolor="#26352d", zeroline=False, side="right", tickformat=".2f")
    return json.loads(pio.to_json(fig))
