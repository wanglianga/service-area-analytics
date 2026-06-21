"""
高速服务区交互式 Dash 看板
支持日期筛选、指标联动、时段定位和异常定位
"""
import os
import sys
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from dash import Dash, dcc, html, Input, Output, State, dash_table, callback
import dash_bootstrap_components as dbc
from datetime import datetime, timedelta
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.visualizations import COLORS


class ServiceAreaDashboard:
    def __init__(self, data_dir="data/output"):
        self.data_dir = data_dir
        self.app = Dash(
            __name__,
            external_stylesheets=[dbc.themes.FLATLY],
            suppress_callback_exceptions=True,
            title="高速服务区运营分析看板"
        )
        self._load_data()
        self._build_layout()
        self._register_callbacks()

    def _load_data(self):
        self.hourly = pd.DataFrame()
        self.anomalies = pd.DataFrame()
        self.daily = pd.DataFrame()
        self.stocking = pd.DataFrame()
        for name, fname in [
            ("hourly", "service_area_hourly_detail.csv"),
            ("anomalies", "anomalies.csv"),
            ("daily", "daily_summary.csv"),
            ("stocking", "stocking_advice.csv"),
        ]:
            path = os.path.join(self.data_dir, fname)
            if os.path.exists(path):
                df = pd.read_csv(path)
                if "hour" in df.columns:
                    df["hour"] = pd.to_datetime(df["hour"], errors="coerce")
                if name == "hourly":
                    self.hourly = df
                elif name == "anomalies":
                    self.anomalies = df
                elif name == "daily":
                    self.daily = df
                elif name == "stocking":
                    self.stocking = df
        if not self.hourly.empty and "hour" in self.hourly.columns:
            self.hourly = self.hourly.dropna(subset=["hour"]).sort_values("hour").reset_index(drop=True)
            self.hourly["date"] = self.hourly["hour"].dt.date
            self.hourly["hour_of_day"] = self.hourly["hour"].dt.hour
            self.hourly["weekday"] = self.hourly["hour"].dt.weekday.map({0:"一",1:"二",2:"三",3:"四",4:"五",5:"六",6:"日"})
        logger.info(f"加载数据完成，小时主表: {len(self.hourly)} 行")

    def _build_layout(self):
        header = dbc.Navbar(
            color=COLORS["primary"],
            dark=True,
            children=[
                html.Div([
                    html.H2("🚗 京沪高速苏州服务区 · 客流与消费运营分析看板", className="text-white mb-0"),
                    html.P("数据驱动的精细化运营决策系统 · 支持时段定位与异常追溯",
                          className="text-white-50 mb-0 mt-1", style={"fontSize": "12px"})
                ], className="container-fluid")
            ],
            className="mb-3"
        )

        if self.hourly.empty:
            self.app.layout = html.Div([
                header,
                dbc.Alert("请先运行 `python run_pipeline.py` 生成分析数据后再启动看板",
                         color="danger", className="mx-4 mt-4")
            ])
            return

        date_start = self.hourly["hour"].min().date()
        date_end = self.hourly["hour"].max().date()
        unique_days = sorted(self.hourly["date"].unique().tolist())

        controls = dbc.Card([
            dbc.CardHeader([html.I(className="bi bi-filter-circle-fill me-1"), "筛选条件"]),
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        html.Label("日期范围", className="fw-bold mb-1"),
                        dcc.DatePickerRange(
                            id="date_range",
                            start_date=date_start,
                            end_date=date_end,
                            min_date_allowed=date_start,
                            max_date_allowed=date_end,
                            display_format="YYYY-MM-DD",
                            className="w-100"
                        )
                    ], md=4),
                    dbc.Col([
                        html.Label("时段筛选", className="fw-bold mb-1"),
                        dcc.RangeSlider(
                            id="hour_slider",
                            min=0, max=23, value=[0, 23], step=1,
                            marks={h: f"{h:02d}" for h in range(0, 24, 3)},
                            tooltip={"placement": "bottom", "always_visible": True}
                        )
                    ], md=4),
                    dbc.Col([
                        html.Label("只看异常时段", className="fw-bold mb-1"),
                        dcc.Dropdown(
                            id="anomaly_filter",
                            options=[
                                {"label": "全部时段", "value": "all"},
                                {"label": "仅异常时段", "value": "only"},
                                {"label": "排除异常时段", "value": "exclude"},
                            ],
                            value="all", clearable=False
                        ),
                        html.Div([
                            dbc.Button("🔄 重置筛选", id="reset_btn", color="secondary", size="sm", className="mt-2")
                        ])
                    ], md=4)
                ])
            ])
        ], className="mb-3")

        kpis = dbc.Row(id="kpi_cards", className="mb-3")

        main_charts = dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("📈 客流趋势与营收走势（日维度）"),
                    dbc.CardBody(dcc.Graph(id="trend_chart", config={"displaylogo": False}))
                ])
            ], md=7),
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("🔥 时段 × 星期 客流热力图"),
                    dbc.CardBody(dcc.Graph(id="heatmap_chart", config={"displaylogo": False}))
                ])
            ], md=5),
        ], className="mb-3")

        second_row = dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("🅿️ 停车利用率与拥堵等级"),
                    dbc.CardBody(dcc.Graph(id="parking_chart", config={"displaylogo": False}))
                ])
            ], md=6),
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("💰 收入构成与转化率"),
                    dbc.CardBody(dcc.Graph(id="revenue_chart", config={"displaylogo": False}))
                ])
            ], md=6),
        ], className="mb-3")

        third_row = dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("⚡ 充电桩利用率与等待时间"),
                    dbc.CardBody(dcc.Graph(id="charging_chart", config={"displaylogo": False}))
                ])
            ], md=6),
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("⚠️ 排队压力指数（按时段）"),
                    dbc.CardBody(dcc.Graph(id="queue_chart", config={"displaylogo": False}))
                ])
            ], md=6),
        ], className="mb-3")

        anomaly_section = dbc.Card([
            dbc.CardHeader([html.I(className="bi bi-exclamation-triangle-fill me-1 text-warning"),
                           f"🚨 运营异常清单（共 {len(self.anomalies)} 条）"]),
            dbc.CardBody(id="anomaly_table_div", className="table-responsive")
        ], className="mb-3")

        detail_section = dbc.Card([
            dbc.CardHeader([
                html.I(className="bi bi-table me-1"),
                "📋 小时级明细（点击上方图表点、时间段联动筛选到此处）",
                dbc.Button("📥 导出CSV", id="export_btn", color="primary", size="sm", className="ms-auto float-end")
            ]),
            dbc.CardBody([
                dash_table.DataTable(
                    id="hourly_table",
                    page_size=15,
                    style_table={"overflowX": "auto"},
                    style_cell={"fontSize": "12px", "padding": "6px 10px",
                               "whiteSpace": "normal", "height": "auto"},
                    style_header={"backgroundColor": COLORS["primary"], "color": "white",
                                 "fontWeight": "bold", "textAlign": "center"},
                    style_data_conditional=[
                        {"if": {"filter_query": "{拥堵等级} = '严重拥堵'"},
                         "backgroundColor": "#fdecea", "color": "#b71c1c"},
                        {"if": {"filter_query": "{排队压力等级} = '极高'"},
                         "backgroundColor": "#fff3e0", "color": "#e65100"},
                        {"if": {"filter_query": "{风险等级} = '高风险'"},
                         "backgroundColor": "#f3e5f5", "color": "#6a1b9a"},
                    ],
                    sort_action="native",
                    filter_action="native",
                ),
                dcc.Download(id="download_csv")
            ])
        ])

        self.app.layout = dbc.Container([
            header, controls, kpis, main_charts, second_row,
            third_row, anomaly_section, detail_section,
            html.Hr(),
            html.Footer([
                html.P("© 2026 高速服务区智能分析系统 v1.0 · Python + Pandas + Plotly + Dash",
                      className="text-center text-muted small")
            ], className="mb-4"),
            dcc.Store(id="filtered_data_store")
        ], fluid=True)

    def _register_callbacks(self):
        if self.hourly.empty:
            return

        @self.app.callback(
            [Output("filtered_data_store", "data"),
             Output("kpi_cards", "children"),
             Output("trend_chart", "figure"),
             Output("heatmap_chart", "figure"),
             Output("parking_chart", "figure"),
             Output("revenue_chart", "figure"),
             Output("charging_chart", "figure"),
             Output("queue_chart", "figure"),
             Output("anomaly_table_div", "children"),
             Output("hourly_table", "data"),
             Output("hourly_table", "columns")],
            [Input("date_range", "start_date"),
             Input("date_range", "end_date"),
             Input("hour_slider", "value"),
             Input("anomaly_filter", "value"),
             Input("reset_btn", "n_clicks")]
        )
        def update_all(start_d, end_d, hrs, anomaly_mode, reset):
            df = self.hourly.copy()
            if start_d and end_d:
                s = pd.to_datetime(start_d).date()
                e = pd.to_datetime(end_d).date()
                df = df[(df["date"] >= s) & (df["date"] <= e)]
            if hrs:
                df = df[(df["hour_of_day"] >= hrs[0]) & (df["hour_of_day"] <= hrs[1])]

            if anomaly_mode != "all" and not self.anomalies.empty:
                anom_dates = set(self.anomalies["date"].astype(str).tolist())
                anom_times = set()
                for _, r in self.anomalies.iterrows():
                    anom_times.add(f"{r['date']} {r['time']}")
                df["_key"] = df["hour"].dt.strftime("%Y-%m-%d %H:00")
                if anomaly_mode == "only":
                    mask = df["_key"].isin(anom_times) | df["date"].astype(str).isin(anom_dates)
                    df = df[mask]
                else:
                    mask = ~df["_key"].isin(anom_times)
                    df = df[mask]
                df = df.drop(columns=["_key"], errors="ignore")

            if df.empty:
                empty_fig = go.Figure().update_layout(title="所选时段无数据", xaxis_visible=False, yaxis_visible=False)
                return "", [], empty_fig, empty_fig, empty_fig, empty_fig, empty_fig, empty_fig, html.Div("无异常数据"), [], []

            kpis = self._make_kpi_cards(df)
            trend_fig = self._fig_trend(df)
            heatmap_fig = self._fig_heatmap(df)
            parking_fig = self._fig_parking(df)
            revenue_fig = self._fig_revenue(df)
            charging_fig = self._fig_charging(df)
            queue_fig = self._fig_queue(df)
            anomaly_tbl = self._make_anomaly_table()
            tbl_data, tbl_cols = self._make_hourly_table(df)

            store = df.to_dict("records")
            return store, kpis, trend_fig, heatmap_fig, parking_fig, revenue_fig, charging_fig, queue_fig, anomaly_tbl, tbl_data, tbl_cols

        @self.app.callback(
            Output("download_csv", "data"),
            Input("export_btn", "n_clicks"),
            State("filtered_data_store", "data"),
            prevent_initial_call=True
        )
        def export_csv(n, data):
            if not data:
                return None
            df = pd.DataFrame(data)
            export_cols = [c for c in df.columns if not c.startswith("zones_")]
            return dcc.send_data_frame(df[export_cols].to_csv, "服务区小时级明细_筛选结果.csv",
                                       index=False, encoding="utf-8-sig")

    def _make_kpi_cards(self, df):
        def _card(title, value, icon, color, delta=""):
            return dbc.Col(dbc.Card([
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([
                            html.P(title, className="text-muted small mb-1"),
                            html.H3(value, className="mb-0 text-" + color),
                            html.Small(delta, className="text-muted") if delta else None,
                        ]),
                        dbc.Col([html.Div(icon, className="text-end display-5 opacity-50")])
                    ])
                ])
            ], className="border-left-primary shadow-sm"), md=3)

        total_people = int(df["est_people_flow"].sum()) if "est_people_flow" in df.columns else 0
        total_rev = f"¥{df['total_revenue'].sum():,.0f}" if "total_revenue" in df.columns else "¥0"
        avg_conv = f"{df['overall_conversion'].mean()*100:.2f}%" if "overall_conversion" in df.columns else "0%"
        anom_cnt = len(self.anomalies)

        return [
            _card("周期总客流", f"{total_people:,}", "👥", "primary"),
            _card("总营收", total_rev, "💵", "success"),
            _card("平均转化率", avg_conv, "📊", "info"),
            _card("异常告警数", str(anom_cnt), "⚠️", "warning"),
        ]

    def _fig_trend(self, df):
        daily = df.groupby("date").agg(
            people=("est_people_flow", "sum"),
            rev=("total_revenue", "sum"),
            conv=("overall_conversion", "mean")
        ).reset_index()
        fig = go.Figure()
        fig.add_trace(go.Bar(x=daily["date"], y=daily["rev"], name="总营收(元)",
                            marker_color=COLORS["accent2"], opacity=0.7,
                            hovertemplate="日期: %{x}<br>营收: ¥%{y:,.0f}<extra></extra>"))
        fig.add_trace(go.Scatter(x=daily["date"], y=daily["people"], name="客流人次",
                                line=dict(color=COLORS["primary"], width=3), mode="lines+markers",
                                yaxis="y2",
                                hovertemplate="日期: %{x}<br>客流: %{y:,.0f}<extra></extra>"))
        fig.update_layout(
            title="", barmode="group",
            xaxis=dict(title="日期", tickformat="%m-%d"),
            yaxis=dict(title="营收（元）"),
            yaxis2=dict(title="客流（人次）", overlaying="y", side="right"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            height=380, margin=dict(l=40, r=40, t=30, b=40)
        )
        return fig

    def _fig_heatmap(self, df):
        pivot = df.pivot_table(index="weekday", columns="hour_of_day",
                              values="est_people_flow", aggfunc="mean").fillna(0)
        ordered = ["一","二","三","四","五","六","日"]
        pivot = pivot.reindex([w for w in ordered if w in pivot.index])
        fig = go.Figure(data=go.Heatmap(
            z=pivot.values, x=pivot.columns, y=pivot.index,
            colorscale="YlOrRd", showscale=True,
            hovertemplate="星期%{y}<br>%{x}时<br>平均客流: %{z:.0f}人<extra></extra>"
        ))
        for h in [7, 11, 17]:
            if h in pivot.columns:
                fig.add_vline(x=h, line_dash="dash", line_color=COLORS["primary"], opacity=0.6)
        fig.update_layout(xaxis=dict(title="时段（时）", dtick=2),
                         yaxis=dict(title="星期"),
                         height=380, margin=dict(l=40, r=40, t=30, b=40))
        return fig

    def _fig_parking(self, df):
        fig = go.Figure()
        if "utilization_small" in df.columns:
            daily_s = df.groupby("date")["utilization_small"].mean() * 100
            fig.add_trace(go.Scatter(x=daily_s.index, y=daily_s.values, name="小车利用率",
                                    line=dict(color=COLORS["primary"], width=2),
                                    fill="tozeroy", fillcolor="rgba(25,118,210,0.15)"))
        if "utilization_large" in df.columns:
            daily_l = df.groupby("date")["utilization_large"].mean() * 100
            fig.add_trace(go.Scatter(x=daily_l.index, y=daily_l.values, name="大车利用率",
                                    line=dict(color=COLORS["accent3"], width=2, dash="dash")))
        fig.add_hline(y=85, line_dash="dot", line_color=COLORS["danger"],
                     annotation_text="拥堵警戒线 85%", annotation_font_color=COLORS["danger"])
        fig.update_layout(xaxis=dict(title="日期", tickformat="%m-%d"),
                         yaxis=dict(title="利用率 (%)", range=[0, 110]),
                         legend=dict(orientation="h", yanchor="bottom", y=1.02),
                         height=400, margin=dict(l=40, r=40, t=30, b=40))
        return fig

    def _fig_revenue(self, df):
        from plotly.subplots import make_subplots
        fig = make_subplots(rows=1, cols=2, specs=[[{"type": "domain"}, {"type": "bar"}]],
                           subplot_titles=("收入构成占比", "分时段转化率"))
        rev_items = {}
        for c, label in [("restaurant_revenue", "餐饮"), ("convenience_revenue", "便利店"),
                          ("gas_revenue", "加油"), ("charging_revenue", "充电")]:
            if c in df.columns and df[c].sum() > 0:
                rev_items[label] = df[c].sum()
        if rev_items:
            fig.add_trace(go.Pie(labels=list(rev_items.keys()), values=list(rev_items.values()),
                                 hole=0.4, marker_colors=[COLORS["primary"], COLORS["accent2"],
                                                         COLORS["accent3"], COLORS["accent1"]]), row=1, col=1)
        if "overall_conversion" in df.columns:
            hr = df.groupby("hour_of_day")["overall_conversion"].mean() * 100
            bar_colors = [COLORS["success"] if v < 8 else COLORS["warning"] if v < 15 else COLORS["danger"] for v in hr.values]
            fig.add_trace(go.Bar(x=hr.index, y=hr.values, marker_color=bar_colors,
                                name="转化率%", text=[f"{v:.1f}%" for v in hr.values],
                                textposition="outside"), row=1, col=2)
            fig.update_yaxes(title_text="转化率 (%)", row=1, col=2)
        fig.update_layout(height=400, margin=dict(l=40, r=40, t=40, b=40), showlegend=False)
        return fig

    def _fig_charging(self, df):
        if "utilization_rate" not in df.columns:
            return go.Figure().update_layout(title="无充电数据")
        hr = df.groupby("hour_of_day").agg(
            util=("utilization_rate", "mean"),
            wait=("avg_wait_min", "mean"),
            sessions=("sessions", "sum")
        ).reset_index()
        fig = go.Figure()
        fig.add_trace(go.Bar(x=hr["hour_of_day"], y=hr["util"]*100, name="利用率%",
                            marker_color=COLORS["primary"]))
        fig.add_trace(go.Scatter(x=hr["hour_of_day"], y=hr["wait"], name="平均等待(分)",
                                line=dict(color=COLORS["warning"], width=3),
                                mode="lines+markers", yaxis="y2"))
        fig.update_layout(
            xaxis=dict(title="时段（时）", dtick=2),
            yaxis=dict(title="充电桩利用率 (%)", range=[0, 110]),
            yaxis2=dict(title="平均等待 (分钟)", overlaying="y", side="right"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            height=400, margin=dict(l=40, r=40, t=30, b=40)
        )
        return fig

    def _fig_queue(self, df):
        if "queue_pressure_score" not in df.columns:
            return go.Figure().update_layout(title="无排队数据")
        hr = df.groupby("hour_of_day").agg(
            score=("queue_pressure_score", "mean"),
            rest_p95=("restaurant_queue_p95_min", "mean"),
            charge_p95=("charging_wait_p95_min", "mean"),
        ).reset_index()
        colors = [COLORS["success"] if v < 2 else COLORS["warning"] if v < 5 else COLORS["danger"] for v in hr["score"]]
        fig = go.Figure()
        fig.add_trace(go.Bar(x=hr["hour_of_day"], y=hr["score"], marker_color=colors, name="综合压力指数"))
        fig.add_trace(go.Scatter(x=hr["hour_of_day"], y=hr["rest_p95"],
                                mode="lines+markers", name="餐饮排队P95(分)",
                                line=dict(color=COLORS["accent1"], width=2)))
        fig.add_trace(go.Scatter(x=hr["hour_of_day"], y=hr["charge_p95"],
                                mode="lines+markers", name="充电等待P95(分)",
                                line=dict(color=COLORS["accent3"], width=2, dash="dash")))
        fig.update_layout(
            xaxis=dict(title="时段（时）", dtick=2),
            yaxis=dict(title="压力指数 / 分钟"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            height=400, margin=dict(l=40, r=40, t=30, b=40)
        )
        return fig

    def _make_anomaly_table(self):
        if self.anomalies.empty:
            return html.Div("✅ 暂无异常记录，运营状态良好", className="text-success text-center py-3")
        df = self.anomalies.copy()
        cols_map = {"date": "日期", "time": "时段", "type": "异常类型",
                   "location": "位置", "value": "观测值", "threshold": "阈值",
                   "severity": "严重程度", "suggestion": "处理建议"}
        df = df.rename(columns=cols_map)
        style_cells = []
        for i, row in df.iterrows():
            sev = row.get("严重程度", "")
            bg = {"严重": "#ffebee", "高": "#fff3e0", "中": "#fffde7", "低": "#e8f5e9"}.get(sev, "white")
            style_cells.append({"if": {"row_index": i}, "backgroundColor": bg})

        return dash_table.DataTable(
            data=df.to_dict("records"),
            columns=[{"name": c, "id": c} for c in df.columns],
            style_table={"overflowX": "auto"},
            style_cell={"fontSize": "12px", "padding": "6px 10px", "textAlign": "left"},
            style_header={"backgroundColor": COLORS["primary"], "color": "white",
                         "fontWeight": "bold", "textAlign": "center"},
            style_data_conditional=style_cells,
            page_size=8,
            sort_action="native",
            filter_action="native",
        )

    def _make_hourly_table(self, df):
        keep_cols = {
            "hour": "时段", "weekday": "星期",
            "est_people_flow": "客流", "total_vehicles": "车流",
            "utilization_small": "小车利用率%", "utilization_large": "大车利用率%",
            "congestion_level": "拥堵等级",
            "total_revenue": "营收(元)", "overall_conversion": "转化率%",
            "avg_spend_per_person": "人均消费",
            "queue_pressure_score": "排队压力", "queue_pressure_level": "排队压力等级",
            "utilization_rate": "充电利用率%", "avg_wait_min": "充电等待(分)",
            "complaint_count": "投诉数", "complaint_risk_score": "投诉风险分", "risk_level": "风险等级",
            "temperature_c": "气温°C", "weather": "天气",
        }
        cols = [k for k in keep_cols if k in df.columns]
        out_df = df[cols].copy()
        for pct_col in ["utilization_small", "utilization_large", "overall_conversion", "utilization_rate"]:
            if pct_col in out_df.columns:
                out_df[pct_col] = (out_df[pct_col] * 100).round(1)
        for numc in ["est_people_flow", "total_vehicles", "total_revenue", "avg_spend_per_person"]:
            if numc in out_df.columns:
                out_df[numc] = out_df[numc].round(1)
        if "hour" in out_df.columns:
            out_df["hour"] = out_df["hour"].dt.strftime("%Y-%m-%d %H:%M")
        out_df = out_df.rename(columns={k: keep_cols[k] for k in cols})
        tbl_cols = [{"name": c, "id": c} for c in out_df.columns]
        return out_df.to_dict("records"), tbl_cols

    def run(self, port=8050, debug=False):
        logger.info(f"启动看板服务: http://localhost:{port}")
        self.app.run_server(host="0.0.0.0", port=port, debug=debug)


if __name__ == "__main__":
    dash_app = ServiceAreaDashboard()
    dash_app.run(port=8050, debug=True)
