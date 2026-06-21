"""
高速服务区可视化模块
生成 Plotly 联动看板、时段热力图、品类贡献图等可视化
"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

COLORS = {
    "primary": "#1976D2",
    "danger": "#E53935",
    "warning": "#FB8C00",
    "success": "#43A047",
    "neutral": "#757575",
    "accent1": "#8E24AA",
    "accent2": "#00ACC1",
    "accent3": "#5D4037",
}


class ServiceAreaVisualizer:
    def __init__(self, output_dir="data/output/visualizations"):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        px.defaults.template = "plotly_white"

    def _save_fig(self, fig, name, height=600):
        path_html = os.path.join(self.output_dir, f"{name}.html")
        fig.write_html(path_html, include_plotlyjs="cdn")
        logger.info(f"  保存图表: {name}")
        return fig

    def plot_kpi_dashboard(self, hourly_df, daily_df=None):
        logger.info("生成联动看板...")
        if hourly_df is None or hourly_df.empty:
            return go.Figure()
        df = hourly_df.copy()
        df["date"] = pd.to_datetime(df["hour"]).dt.date
        df["hour_of_day"] = pd.to_datetime(df["hour"]).dt.hour

        total_people = int(df["est_people_flow"].sum()) if "est_people_flow" in df.columns else 0
        total_revenue = round(df["total_revenue"].sum(), 2) if "total_revenue" in df.columns else 0
        avg_conversion = round(df["overall_conversion"].mean() * 100, 2) if "overall_conversion" in df.columns else 0
        total_complaints = int(df["complaint_count"].sum()) if "complaint_count" in df.columns else 0
        peak_people = int(df["est_people_flow"].max()) if "est_people_flow" in df.columns else 0
        peak_hour_row = df.loc[df["est_people_flow"].idxmax()] if "est_people_flow" in df.columns and not df.empty else None
        peak_hour = peak_hour_row["hour"].strftime("%Y-%m-%d %H:%M") if peak_hour_row is not None else "-"

        fig = make_subplots(
            rows=3, cols=2,
            subplot_titles=(
                "客流趋势与营收对照",
                "分时段消费转化率",
                "停车利用率（小型车）",
                "排队压力指数分布",
                "收入构成占比",
                "充电桩利用率与等待时间"
            ),
            vertical_spacing=0.08,
            horizontal_spacing=0.06,
            specs=[
                [{"type": "xy", "secondary_y": True}, {"type": "heatmap"}],
                [{"type": "xy"}, {"type": "xy"}],
                [{"type": "pie"}, {"type": "xy", "secondary_y": True}]
            ]
        )
        fig.update_annotations(font_size=12, font_color=COLORS["primary"])

        if "est_people_flow" in df.columns:
            daily = df.groupby("date")["est_people_flow"].sum().reset_index()
            fig.add_trace(
                go.Scatter(x=daily["date"], y=daily["est_people_flow"], name="日客流",
                          line=dict(color=COLORS["primary"], width=2),
                          mode="lines+markers"),
                row=1, col=1, secondary_y=False
            )
        if "total_revenue" in df.columns:
            daily_rev = df.groupby("date")["total_revenue"].sum().reset_index()
            fig.add_trace(
                go.Bar(x=daily_rev["date"], y=daily_rev["total_revenue"], name="日营收(元)",
                      marker_color=COLORS["accent2"], opacity=0.6),
                row=1, col=1, secondary_y=True
            )

        if "restaurant_conversion" in df.columns and "convenience_conversion" in df.columns:
            pivot = df.pivot_table(
                index=df["hour"].dt.weekday.map({0:"一",1:"二",2:"三",3:"四",4:"五",5:"六",6:"日"}),
                columns="hour_of_day",
                values="overall_conversion",
                aggfunc="mean"
            ).fillna(0)
            fig.add_trace(
                go.Heatmap(z=pivot.values * 100, x=pivot.columns, y=pivot.index,
                          colorscale="YlGnBu", showscale=True,
                          hovertemplate="星期%{y}<br>%{x}时<br>转化率:%{z:.2f}%<extra></extra>"),
                row=1, col=2
            )

        if "utilization_small" in df.columns:
            daily_util = df.groupby("date")["utilization_small"].mean().reset_index()
            fig.add_trace(
                go.Scatter(x=daily_util["date"], y=daily_util["utilization_small"] * 100,
                          name="小型车利用率%",
                          fill="tozeroy", fillcolor="rgba(25,118,210,0.2)",
                          line=dict(color=COLORS["primary"])),
                row=2, col=1
            )
            if "utilization_large" in df.columns:
                daily_util_l = df.groupby("date")["utilization_large"].mean().reset_index()
                fig.add_trace(
                    go.Scatter(x=daily_util_l["date"], y=daily_util_l["utilization_large"] * 100,
                              name="大型车利用率%",
                              line=dict(color=COLORS["accent3"], dash="dash")),
                    row=2, col=1
                )
            fig.add_hline(y=85, line_dash="dot", line_color=COLORS["danger"],
                         annotation_text="拥堵警戒线85%", row=2, col=1)

        if "queue_pressure_score" in df.columns:
            qp = df.groupby("hour_of_day")["queue_pressure_score"].mean().reset_index()
            colors_qp = [COLORS["success"] if v < 2 else COLORS["warning"] if v < 5 else COLORS["danger"] for v in qp["queue_pressure_score"]]
            fig.add_trace(
                go.Bar(x=qp["hour_of_day"], y=qp["queue_pressure_score"],
                      marker_color=colors_qp, name="排队压力指数"),
                row=2, col=2
            )

        rev_items = {}
        for c in ["restaurant_revenue", "convenience_revenue", "gas_revenue", "charging_revenue"]:
            if c in df.columns:
                label = c.replace("_revenue", "").replace("restaurant", "餐饮").replace("convenience", "便利店").replace("gas", "加油").replace("charging", "充电")
                rev_items[label] = df[c].sum()
        if rev_items:
            fig.add_trace(
                go.Pie(labels=list(rev_items.keys()), values=list(rev_items.values()),
                      hole=0.4, marker_colors=[COLORS["primary"], COLORS["accent2"], COLORS["accent3"], COLORS["accent1"]]),
                row=3, col=1
            )

        if "utilization_rate" in df.columns and "avg_wait_min" in df.columns:
            ch = df.groupby("hour_of_day").agg(
                util=("utilization_rate", "mean"),
                wait=("avg_wait_min", "mean")
            ).reset_index()
            fig.add_trace(
                go.Bar(x=ch["hour_of_day"], y=ch["util"] * 100, name="利用率%",
                      marker_color=COLORS["primary"]),
                row=3, col=2
            )
            fig.add_trace(
                go.Scatter(x=ch["hour_of_day"], y=ch["wait"], name="平均等待(分)",
                          line=dict(color=COLORS["warning"], width=2), mode="lines+markers"),
                row=3, col=2, secondary_y=True
            )

        fig.update_layout(
            height=1100, width=1400,
            title={
                "text": f"<b>京沪高速苏州服务区 · 运营联动看板</b><br>"
                        f"<span style='font-size:12px;color:{COLORS['neutral']}'>"
                        f"总客流 {total_people:,} | 总营收 ¥{total_revenue:,.2f} | 平均转化率 {avg_conversion}% | "
                        f"投诉 {total_complaints} 起 | 峰值客流 {peak_people:,} @ {peak_hour}"
                        f"</span>",
                "font": {"size": 18, "color": COLORS["primary"]},
                "x": 0.5
            },
            legend=dict(orientation="h", yanchor="bottom", y=-0.02),
            hovermode="x unified"
        )
        return self._save_fig(fig, "kpi_linked_dashboard", height=1100)

    def plot_hourly_heatmap(self, hourly_df, metric="est_people_flow"):
        logger.info(f"生成时段热力图: {metric}")
        if hourly_df is None or hourly_df.empty or metric not in hourly_df.columns:
            return go.Figure()
        df = hourly_df.copy()
        df["date"] = pd.to_datetime(df["hour"]).dt.strftime("%m-%d")
        df["hour_of_day"] = pd.to_datetime(df["hour"]).dt.hour

        pivot = df.pivot_table(index="date", columns="hour_of_day", values=metric, aggfunc="mean")

        metric_cn = {
            "est_people_flow": "小时客流",
            "total_revenue": "小时营收(元)",
            "utilization_small": "小车停车利用率(%)",
            "queue_pressure_score": "排队压力指数",
            "complaint_risk_score": "投诉风险指数",
            "charging_sessions": "充电会话数",
            "restaurant_orders": "餐饮订单数",
            "overall_conversion": "整体转化率(%)",
        }.get(metric, metric)

        is_pct = "%" in metric_cn
        z_vals = (pivot.values * 100) if is_pct else pivot.values

        fig = go.Figure(data=go.Heatmap(
            z=z_vals,
            x=pivot.columns.tolist(),
            y=pivot.index.tolist(),
            colorscale="RdYlGn_r",
            showscale=True,
            colorbar=dict(title=metric_cn),
            hovertemplate=(
                "日期: %{y}<br>时段: %{x}时<br>" + metric_cn + ": %{z:.1f}<extra></extra>"
            ),
            zsmooth="best"
        ))

        for h in [7, 11, 17]:
            fig.add_vline(x=h, line_width=1, line_dash="dash", line_color=COLORS["primary"],
                         opacity=0.5)
            fig.add_annotation(x=h, y=-0.03, yref="paper", text=["早高峰","午高峰","晚高峰"][[7,11,17].index(h)],
                             showarrow=False, font_color=COLORS["primary"], font_size=10)

        fig.update_layout(
            height=550 + len(pivot) * 10,
            width=1300,
            title=f"<b>服务区时段热力图 — {metric_cn}</b>",
            title_font_size=16,
            xaxis=dict(title="时段 (0-23时)", tickmode="linear", dtick=2),
            yaxis=dict(title="日期", autorange="reversed"),
            font=dict(family="Microsoft YaHei, sans-serif")
        )
        return self._save_fig(fig, f"heatmap_{metric}", height=600)

    def plot_category_contribution(self, restaurant_df, convenience_df, hourly_df):
        logger.info("生成品类贡献图...")
        fig = make_subplots(
            rows=2, cols=2,
            subplot_titles=("餐饮品类营收贡献", "餐饮品类销量TOP10",
                           "便利店品类销售占比", "便利店SKU销售TOP10"),
            specs=[[{"type": "xy", "secondary_y": True}, {"type": "xy"}],
                   [{"type": "pie"}, {"type": "xy"}]],
            vertical_spacing=0.12
        )

        if restaurant_df is not None and not restaurant_df.empty:
            rdf = restaurant_df.copy()
            cat_rev = rdf.groupby("category").agg(
                revenue=("total_amount", "sum"),
                orders=("order_id", "nunique"),
                qty=("quantity", "sum")
            ).reset_index().sort_values("revenue", ascending=False)
            colors_cat = [COLORS["primary"], COLORS["accent1"], COLORS["accent2"], COLORS["accent3"]]
            fig.add_trace(
                go.Bar(x=cat_rev["category"], y=cat_rev["revenue"],
                      text=[f"¥{v:,.0f}" for v in cat_rev["revenue"]],
                      textposition="outside",
                      marker_color=colors_cat[:len(cat_rev)],
                      name="营收"),
                row=1, col=1
            )
            fig.add_trace(
                go.Scatter(x=cat_rev["category"],
                          y=(cat_rev["revenue"] / cat_rev["revenue"].sum() * 100).round(1),
                          mode="lines+markers+text",
                          text=[f"{v}%" for v in (cat_rev["revenue"]/cat_rev["revenue"].sum()*100).round(1)],
                          textposition="top center",
                          line=dict(color=COLORS["warning"], width=2),
                          name="占比%"),
                row=1, col=1, secondary_y=True
            )

            item_top = rdf.groupby("item_name").agg(
                qty=("quantity", "sum"),
                revenue=("total_amount", "sum")
            ).reset_index().sort_values("qty", ascending=False).head(10)
            fig.add_trace(
                go.Bar(y=item_top["item_name"][::-1], x=item_top["qty"][::-1],
                      orientation="h",
                      marker_color=COLORS["primary"],
                      name="销量", text=item_top["qty"][::-1], textposition="outside"),
                row=1, col=2
            )

        if convenience_df is not None and not convenience_df.empty:
            cdf = convenience_df.copy()
            cat_sales = cdf.groupby("category").agg(
                amount=("subtotal", "sum"),
                qty=("quantity", "sum")
            ).reset_index()
            colors_c = [COLORS["accent1"], COLORS["warning"], COLORS["success"], COLORS["accent2"]]
            fig.add_trace(
                go.Pie(labels=cat_sales["category"], values=cat_sales["amount"],
                      marker_colors=colors_c, hole=0.35,
                      textinfo="label+percent",
                      pull=[0.02]*len(cat_sales)),
                row=2, col=1
            )

            sku_top = cdf.groupby("sku_name").agg(
                qty=("quantity", "sum"),
                amount=("subtotal", "sum")
            ).reset_index().sort_values("qty", ascending=False).head(10)
            fig.add_trace(
                go.Bar(y=sku_top["sku_name"][::-1], x=sku_top["amount"][::-1],
                      orientation="h",
                      marker_color=COLORS["accent2"],
                      name="销售额(元)",
                      text=[f"¥{v:,.0f}" for v in sku_top["amount"][::-1]],
                      textposition="outside"),
                row=2, col=2
            )

        fig.update_layout(
            height=900, width=1300,
            title="<b>餐饮与便利店品类销售贡献分析</b>",
            title_font_size=16,
            showlegend=False,
            font=dict(family="Microsoft YaHei, sans-serif")
        )
        return self._save_fig(fig, "category_contribution", height=900)

    def plot_complaint_risk(self, complaints_df, hourly_df):
        logger.info("生成投诉风险分析图...")
        fig = make_subplots(
            rows=2, cols=2,
            subplot_titles=("投诉类型分布", "投诉严重程度占比",
                           "每日投诉趋势与风险评分", "TOP投诉问题类别"),
            specs=[[{"type": "pie"}, {"type": "pie"}],
                   [{"type": "xy", "secondary_y": True}, {"type": "xy"}]]
        )

        if complaints_df is not None and not complaints_df.empty:
            cdf = complaints_df.copy()
            cdf["date"] = pd.to_datetime(cdf["timestamp"]).dt.date

            cat_cnt = cdf.groupby("category").size().reset_index(name="count").sort_values("count", ascending=False)
            fig.add_trace(
                go.Pie(labels=cat_cnt["category"], values=cat_cnt["count"],
                      hole=0.3,
                      marker_colors=px.colors.qualitative.Set2,
                      textinfo="label+value"),
                row=1, col=1
            )

            sev_cnt = cdf.groupby("severity").size().reset_index(name="count")
            sev_order = ["一般", "较严重", "严重"]
            sev_cnt["severity"] = pd.Categorical(sev_cnt["severity"], categories=sev_order, ordered=True)
            sev_cnt = sev_cnt.sort_values("severity")
            fig.add_trace(
                go.Pie(labels=sev_cnt["severity"], values=sev_cnt["count"],
                      marker_colors=[COLORS["warning"], COLORS["accent1"], COLORS["danger"]],
                      textinfo="label+percent+value"),
                row=1, col=2
            )

            daily = cdf.groupby("date").size().reset_index(name="count")
            fig.add_trace(
                go.Bar(x=daily["date"], y=daily["count"], name="投诉数",
                      marker_color=COLORS["danger"]),
                row=2, col=1, secondary_y=False
            )
            if hourly_df is not None and not hourly_df.empty and "complaint_risk_score" in hourly_df.columns:
                h = hourly_df.copy()
                h["date"] = pd.to_datetime(h["hour"]).dt.date
                risk_daily = h.groupby("date")["complaint_risk_score"].mean().reset_index()
                fig.add_trace(
                    go.Scatter(x=risk_daily["date"], y=risk_daily["complaint_risk_score"],
                              name="风险评分均值", mode="lines+markers",
                              line=dict(color=COLORS["warning"], width=2)),
                    row=2, col=1, secondary_y=True
                )

            issue_cnt = cdf.groupby("issue_detail").size().reset_index(name="count").sort_values("count", ascending=False).head(8)
            fig.add_trace(
                go.Bar(x=issue_cnt["count"][::-1], y=issue_cnt["issue_detail"][::-1],
                      orientation="h",
                      marker_color=COLORS["accent1"],
                      text=issue_cnt["count"][::-1], textposition="outside"),
                row=2, col=2
            )

        fig.update_layout(
            height=850, width=1300,
            title="<b>投诉风险与问题归因分析</b>",
            title_font_size=16,
            font=dict(family="Microsoft YaHei, sans-serif")
        )
        return self._save_fig(fig, "complaint_risk_analysis", height=850)

    def plot_charging_gas_analysis(self, charging_df, gas_df, hourly_df):
        logger.info("生成能源服务分析图...")
        fig = make_subplots(
            rows=2, cols=2,
            subplot_titles=("每日充电量与营收", "充电桩分时利用率",
                           "油品销售分布", "加油分时交易数"),
            vertical_spacing=0.1,
            specs=[
                [{"type": "xy", "secondary_y": True}, {"type": "xy"}],
                [{"type": "pie"}, {"type": "xy"}]
            ]
        )

        if charging_df is not None and not charging_df.empty:
            cdf = charging_df.copy()
            cdf["date"] = pd.to_datetime(cdf["start_time"]).dt.date
            daily = cdf.groupby("date").agg(
                kwh=("energy_kwh", "sum"),
                rev=("amount_cny", "sum"),
                sessions=("session_id", "count")
            ).reset_index()
            fig.add_trace(
                go.Bar(x=daily["date"], y=daily["kwh"], name="充电量(kWh)",
                      marker_color=COLORS["accent2"]),
                row=1, col=1
            )
            fig.add_trace(
                go.Scatter(x=daily["date"], y=daily["rev"], name="营收(元)",
                          mode="lines+markers", line=dict(color=COLORS["warning"])),
                row=1, col=1, secondary_y=True
            )

            cdf["hour"] = pd.to_datetime(cdf["start_time"]).dt.hour
            hr = cdf.groupby("hour").agg(
                sessions=("session_id", "count"),
                avg_wait=("wait_time_min", "mean")
            ).reset_index()
            fig.add_trace(
                go.Bar(x=hr["hour"], y=hr["sessions"], name="充电会话数",
                      marker_color=COLORS["primary"]),
                row=1, col=2
            )
            fig.add_trace(
                go.Scatter(x=hr["hour"], y=hr["avg_wait"], name="平均等待(分)",
                          mode="lines+markers", line=dict(color=COLORS["danger"])),
                row=1, col=2
            )

        if gas_df is not None and not gas_df.empty:
            gdf = gas_df.copy()
            fuel = gdf.groupby("fuel_type").agg(
                liters=("liters", "sum"),
                amount=("total_amount", "sum")
            ).reset_index()
            fig.add_trace(
                go.Pie(labels=fuel["fuel_type"], values=fuel["liters"],
                      marker_colors=px.colors.qualitative.Pastel,
                      textinfo="label+percent", hole=0.3),
                row=2, col=1
            )

            gdf["hour"] = pd.to_datetime(gdf["timestamp"]).dt.hour
            hr_gas = gdf.groupby("hour").size().reset_index(name="count")
            fig.add_trace(
                go.Scatter(x=hr_gas["hour"], y=hr_gas["count"],
                          fill="tozeroy", fillcolor="rgba(93,64,55,0.2)",
                          line=dict(color=COLORS["accent3"], width=2),
                          name="加油交易数"),
                row=2, col=2
            )

        fig.update_layout(
            height=800, width=1300,
            title="<b>充电桩与加油站运营分析</b>",
            title_font_size=16,
            font=dict(family="Microsoft YaHei, sans-serif")
        )
        return self._save_fig(fig, "energy_service_analysis", height=800)

    def plot_stocking_advice(self, stocking_df):
        logger.info("生成餐饮备货热力图...")
        if stocking_df is None or stocking_df.empty:
            return go.Figure()
        df = stocking_df.copy()
        df["hour_of_day"] = df["hour"].dt.hour
        pivot = df.pivot_table(index="category", columns="hour_of_day",
                              values="suggest_stock_qty", aggfunc="mean").fillna(0)

        fig = go.Figure(data=go.Heatmap(
            z=pivot.values,
            x=[f"{h}时" for h in pivot.columns],
            y=pivot.index.tolist(),
            colorscale="OrRd",
            showscale=True,
            colorbar=dict(title="建议备货量"),
            text=[[f"{int(v)}份" for v in row] for row in pivot.values],
            texttemplate="%{text}",
            hovertemplate="品类:%{y}<br>时段:%{x}<br>建议备货:%{z}份<extra></extra>"
        ))
        for t, label in [(7, "早餐"), (12, "午餐"), (18, "晚餐")]:
            fig.add_vline(x=t, line_dash="dash", line_color=COLORS["primary"])
            fig.add_annotation(x=t, y=-0.08, yref="paper", text=label,
                             showarrow=False, font_color=COLORS["primary"], font_size=11)

        fig.update_layout(
            height=450, width=1200,
            title="<b>餐饮分品类备货建议（P95 × 110%）</b>",
            title_font_size=16,
            xaxis=dict(tickmode="linear", dtick=2),
            font=dict(family="Microsoft YaHei, sans-serif")
        )
        return self._save_fig(fig, "stocking_advice_heatmap", height=450)

    def plot_weather_impact(self, weather_df, hourly_df):
        logger.info("生成天气影响分析...")
        if hourly_df is None or hourly_df.empty:
            return go.Figure()
        df = hourly_df.copy()
        if "temperature_c" not in df.columns or "weather" not in df.columns:
            return go.Figure()

        agg = df.groupby("weather").agg(
            avg_people=("est_people_flow", "mean"),
            avg_revenue=("total_revenue", "mean"),
            avg_conversion=("overall_conversion", "mean"),
            count=("hour", "count")
        ).reset_index()

        fig = make_subplots(
            rows=1, cols=2,
            subplot_titles=("不同天气下客流与营收对比", "温度与转化率散点图"),
            specs=[[{"type": "xy", "secondary_y": True}, {"type": "xy"}]]
        )

        fig.add_trace(
            go.Bar(x=agg["weather"], y=agg["avg_people"], name="平均客流",
                  marker_color=COLORS["primary"]),
            row=1, col=1
        )
        fig.add_trace(
            go.Scatter(x=agg["weather"], y=agg["avg_revenue"], name="平均营收(元)",
                      mode="markers", marker_size=15, marker_color=COLORS["warning"]),
            row=1, col=1, secondary_y=True
        )

        scatter = df.sample(min(500, len(df)), random_state=42) if len(df) > 500 else df
        fig.add_trace(
            go.Scatter(
                x=scatter["temperature_c"],
                y=scatter["overall_conversion"] * 100,
                mode="markers",
                marker=dict(
                    color=scatter["est_people_flow"],
                    colorscale="Viridis",
                    size=8,
                    showscale=True,
                    colorbar=dict(title="客流规模")
                ),
                text=[f"{w}<br>{t}°C" for w, t in zip(scatter["weather"], scatter["temperature_c"])],
                hovertemplate="气温:%{x}°C<br>转化率:%{y}%<br>%{text}<extra></extra>",
                name=""
            ),
            row=1, col=2
        )
        z = np.polyfit(scatter["temperature_c"].dropna(),
                      (scatter["overall_conversion"] * 100).loc[scatter["temperature_c"].dropna().index], 1)
        p = np.poly1d(z)
        x_line = np.linspace(scatter["temperature_c"].min(), scatter["temperature_c"].max(), 100)
        fig.add_trace(
            go.Scatter(x=x_line, y=p(x_line), mode="lines",
                      line=dict(color=COLORS["danger"], dash="dash"), name="趋势线"),
            row=1, col=2
        )

        fig.update_layout(
            height=500, width=1300,
            title="<b>天气对客流与消费的影响分析</b>",
            title_font_size=16,
            font=dict(family="Microsoft YaHei, sans-serif")
        )
        return self._save_fig(fig, "weather_impact_analysis", height=500)

    def generate_all(self, results, cleaned_data):
        hourly = results.get("hourly_master")
        daily = results.get("daily_summary")
        anomalies = results.get("anomalies")
        stocking = results.get("stocking_advice")

        restaurant = cleaned_data.get("restaurant")
        convenience = cleaned_data.get("convenience")
        charging = cleaned_data.get("charging")
        gas = cleaned_data.get("gas")
        complaints = cleaned_data.get("complaints")
        weather = cleaned_data.get("weather")

        figs = {}
        figs["kpi_dashboard"] = self.plot_kpi_dashboard(hourly, daily)

        for m in ["est_people_flow", "total_revenue", "utilization_small",
                  "queue_pressure_score", "complaint_risk_score"]:
            if hourly is not None and not hourly.empty and m in hourly.columns:
                figs[f"heatmap_{m}"] = self.plot_hourly_heatmap(hourly, m)

        figs["category_contribution"] = self.plot_category_contribution(restaurant, convenience, hourly)
        figs["complaint_risk"] = self.plot_complaint_risk(complaints, hourly)
        figs["energy_analysis"] = self.plot_charging_gas_analysis(charging, gas, hourly)
        figs["stocking"] = self.plot_stocking_advice(stocking)
        figs["weather_impact"] = self.plot_weather_impact(weather, hourly)

        logger.info(f"共生成 {len(figs)} 个可视化图表")
        return figs
