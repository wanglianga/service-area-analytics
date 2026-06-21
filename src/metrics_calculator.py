"""
高速服务区指标计算模块
计算客流峰值、消费转化、排队压力、充电等待、餐饮备货、停车拥堵、投诉风险等核心指标
"""
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CAPACITY = {
    "parking_small": 200,
    "parking_large": 80,
    "ev_chargers": 20,
    "gas_pumps": 8,
    "restaurant_seats": 150,
    "restroom_stalls": 40,
}

VEHICLE_COEF = {
    "small_to_people": 1.5,
    "large_to_people": 3.0,
}


class MetricsCalculator:
    def __init__(self, output_dir="data/output"):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        self.hourly_metrics = None
        self.daily_metrics = None
        self.anomalies = []

    def _get_hour_bucket(self, ts_series):
        return ts_series.dt.floor("h")

    def calc_people_flow(self, traffic_df, parking_df):
        logger.info("计算客流指标...")
        if traffic_df is None or traffic_df.empty:
            return pd.DataFrame()
        df = traffic_df.copy()
        df["hour"] = self._get_hour_bucket(df["timestamp"])
        small_vehicles = df[df["vehicle_class"].isin(["small", "medium"])]
        large_vehicles = df[df["vehicle_class"] == "large"]

        small_count = small_vehicles.groupby("hour").size().rename("small_vehicles")
        large_count = large_vehicles.groupby("hour").size().rename("large_vehicles")
        total_count = df.groupby("hour").size().rename("total_vehicles")

        est_people_small = small_count * VEHICLE_COEF["small_to_people"]
        est_people_large = large_count * VEHICLE_COEF["large_to_people"]
        est_people = (est_people_small + est_people_large).rename("est_people_flow")

        if parking_df is not None and not parking_df.empty:
            park = parking_df.copy()
            park["hour"] = self._get_hour_bucket(park["entry_time"])
            park["hour_exit"] = self._get_hour_bucket(park["exit_time"])
            parked_small = park[park["vehicle_type"] == "small"].groupby("hour").size().rename("parked_small")
            parked_large = park[park["vehicle_type"] == "large"].groupby("hour").size().rename("parked_large")
            avg_duration = park.groupby("hour")["duration_min"].mean().rename("avg_park_duration_min")
        else:
            parked_small = pd.Series(dtype="float64")
            parked_large = pd.Series(dtype="float64")
            avg_duration = pd.Series(dtype="float64")

        result = pd.concat([total_count, small_count, large_count,
                           est_people.rename("est_people_flow"),
                           parked_small, parked_large, avg_duration], axis=1).fillna(0)
        result.index.name = "hour"
        result = result.reset_index()
        return result

    def calc_parking_congestion(self, parking_df):
        logger.info("计算停车拥堵指标...")
        if parking_df is None or parking_df.empty:
            return pd.DataFrame()
        park = parking_df.copy()
        records = []
        for _, row in park.iterrows():
            start = row["entry_time"].floor("h")
            end = row["exit_time"].floor("h")
            for hour in pd.date_range(start=start, end=end, freq="h"):
                records.append({
                    "hour": hour,
                    "parking_id": row["parking_id"],
                    "vehicle_type": row["vehicle_type"],
                    "zone": row.get("zone", "未知")
                })
        occ_df = pd.DataFrame(records)
        if occ_df.empty:
            return pd.DataFrame()

        zone_small = occ_df[occ_df["vehicle_type"] == "small"].groupby(["hour", "zone"]).size().unstack(fill_value=0)
        zone_large = occ_df[occ_df["vehicle_type"] == "large"].groupby(["hour", "zone"]).size().unstack(fill_value=0)
        total_small = occ_df[occ_df["vehicle_type"] == "small"].groupby("hour").size().rename("occupied_small")
        total_large = occ_df[occ_df["vehicle_type"] == "large"].groupby("hour").size().rename("occupied_large")

        result = pd.concat([total_small, total_large], axis=1).fillna(0)
        result.index.name = "hour"
        result = result.reset_index()
        result["utilization_small"] = result["occupied_small"] / CAPACITY["parking_small"]
        result["utilization_large"] = result["occupied_large"] / CAPACITY["parking_large"]
        result["congestion_level"] = np.where(
            (result["utilization_small"] >= 0.9) | (result["utilization_large"] >= 0.9), "严重拥堵",
            np.where((result["utilization_small"] >= 0.75) | (result["utilization_large"] >= 0.75), "拥堵",
                     np.where((result["utilization_small"] >= 0.6) | (result["utilization_large"] >= 0.6), "偏高", "正常"))
        )
        result["turnover_count"] = 0
        result["zones_small"] = [zone_small.loc[h].to_dict() if h in zone_small.index else {} for h in result["hour"]]
        result["zones_large"] = [zone_large.loc[h].to_dict() if h in zone_large.index else {} for h in result["hour"]]
        return result

    def calc_consumption_conversion(self, traffic_stats, restaurant_df, conv_df, gas_df, charging_df):
        logger.info("计算消费转化指标...")
        people_col = "est_people_flow" if "est_people_flow" in traffic_stats.columns else "total_vehicles"
        traffic_stats = traffic_stats.set_index("hour") if "hour" in traffic_stats.columns else traffic_stats

        records = []
        for hour, row in traffic_stats.iterrows():
            people = max(1, row[people_col] if isinstance(row, pd.Series) else row[people_col])
            start = hour
            end = hour + timedelta(hours=1)

            rest_rev = 0
            rest_cnt = 0
            if restaurant_df is not None and not restaurant_df.empty:
                mask = (restaurant_df["timestamp"] >= start) & (restaurant_df["timestamp"] < end)
                rest_rev = restaurant_df.loc[mask, "total_amount"].sum()
                rest_cnt = restaurant_df.loc[mask, "order_id"].nunique()

            conv_rev = 0
            conv_cnt = 0
            if conv_df is not None and not conv_df.empty:
                mask = (conv_df["timestamp"] >= start) & (conv_df["timestamp"] < end)
                conv_rev = conv_df.loc[mask, "subtotal"].sum()
                conv_cnt = conv_df.loc[mask, "transaction_id"].nunique()

            gas_rev = 0
            gas_cnt = 0
            gas_liters = 0
            if gas_df is not None and not gas_df.empty:
                mask = (gas_df["timestamp"] >= start) & (gas_df["timestamp"] < end)
                gas_rev = gas_df.loc[mask, "total_amount"].sum()
                gas_cnt = gas_df.loc[mask, "transaction_id"].nunique()
                gas_liters = gas_df.loc[mask, "liters"].sum()

            charge_rev = 0
            charge_cnt = 0
            charge_kwh = 0
            if charging_df is not None and not charging_df.empty:
                mask = (charging_df["start_time"] >= start) & (charging_df["start_time"] < end)
                charge_rev = charging_df.loc[mask, "amount_cny"].sum() if "amount_cny" in charging_df.columns else 0
                charge_cnt = mask.sum()
                charge_kwh = charging_df.loc[mask, "energy_kwh"].sum() if "energy_kwh" in charging_df.columns else 0

            total_rev = rest_rev + conv_rev + gas_rev + charge_rev
            total_payers = rest_cnt + conv_cnt + gas_cnt + charge_cnt

            raw_conversion = total_payers / people if people > 0 else 0
            overall_conversion = round(min(raw_conversion, 1.0), 4)
            transaction_per_person = round(raw_conversion, 3) if people > 0 else 0

            records.append({
                "hour": hour,
                "restaurant_revenue": round(rest_rev, 2),
                "restaurant_orders": rest_cnt,
                "restaurant_conversion": round(rest_cnt / people, 4) if people > 0 else 0,
                "convenience_revenue": round(conv_rev, 2),
                "convenience_transactions": conv_cnt,
                "convenience_conversion": round(conv_cnt / people, 4) if people > 0 else 0,
                "gas_revenue": round(gas_rev, 2),
                "gas_transactions": gas_cnt,
                "gas_liters": round(gas_liters, 2),
                "gas_conversion": round(gas_cnt / max(1, row.get("total_vehicles", people)), 4),
                "charging_revenue": round(charge_rev, 2),
                "charging_sessions": charge_cnt,
                "charging_kwh": round(charge_kwh, 2),
                "charging_conversion": round(charge_cnt / max(1, row.get("total_vehicles", people)), 4),
                "total_revenue": round(total_rev, 2),
                "total_paying_customers": total_payers,
                "overall_conversion": overall_conversion,
                "transactions_per_person": transaction_per_person,
                "avg_spend_per_person": round(total_rev / people, 2) if people > 0 else 0,
            })
        return pd.DataFrame(records)

    def calc_queue_pressure(self, restaurant_df, restroom_df, charging_df, gas_df):
        logger.info("计算排队压力指标...")
        all_hours = set()
        for df, col in [(restaurant_df, "timestamp"), (restroom_df, "timestamp"),
                         (charging_df, "start_time"), (gas_df, "timestamp")]:
            if df is not None and not df.empty:
                all_hours.update(self._get_hour_bucket(df[col]).unique())
        all_hours = sorted(all_hours)

        records = []
        for hour in all_hours:
            start = hour
            end = hour + timedelta(hours=1)

            rest_queue_avg = 0
            rest_queue_max = 0
            rest_queue_p95 = 0
            if restaurant_df is not None and not restaurant_df.empty:
                mask = (restaurant_df["timestamp"] >= start) & (restaurant_df["timestamp"] < end)
                waits = restaurant_df.loc[mask, "queue_wait_min"]
                if len(waits) > 0:
                    rest_queue_avg = round(waits.mean(), 1)
                    rest_queue_max = int(waits.max())
                    rest_queue_p95 = int(waits.quantile(0.95))

            restroom_wait_avg = 0
            restroom_usage_cnt = 0
            if restroom_df is not None and not restroom_df.empty:
                mask = (restroom_df["timestamp"] >= start) & (restroom_df["timestamp"] < end)
                sub = restroom_df.loc[mask]
                restroom_usage_cnt = len(sub)
                if restroom_usage_cnt > 0:
                    avg_per_stall = restroom_usage_cnt / CAPACITY["restroom_stalls"]
                    avg_duration = sub["duration_sec"].mean() / 60
                    restroom_wait_avg = round(max(0, (avg_per_stall - 1) * avg_duration), 1)

            charge_wait_avg = 0
            charge_wait_max = 0
            charge_wait_p95 = 0
            if charging_df is not None and not charging_df.empty:
                mask = (charging_df["start_time"] >= start) & (charging_df["start_time"] < end)
                waits = charging_df.loc[mask, "wait_time_min"] if "wait_time_min" in charging_df.columns else pd.Series()
                if len(waits) > 0:
                    charge_wait_avg = round(waits.mean(), 1)
                    charge_wait_max = int(waits.max())
                    charge_wait_p95 = int(waits.quantile(0.95) if len(waits) > 5 else waits.max())

            gas_queue_cnt = 0
            if gas_df is not None and not gas_df.empty:
                mask = (gas_df["timestamp"] >= start) & (gas_df["timestamp"] < end)
                tx_count = mask.sum()
                if tx_count > 0:
                    tx_per_pump_per_hour = tx_count / CAPACITY["gas_pumps"]
                    gas_queue_cnt = max(0, int(tx_per_pump_per_hour - 8))

            pressure_score = 0
            if rest_queue_p95 > 20: pressure_score += 3
            elif rest_queue_p95 > 10: pressure_score += 2
            elif rest_queue_p95 > 5: pressure_score += 1
            if restroom_wait_avg > 10: pressure_score += 2
            elif restroom_wait_avg > 5: pressure_score += 1
            if charge_wait_p95 > 30: pressure_score += 3
            elif charge_wait_p95 > 15: pressure_score += 2
            elif charge_wait_p95 > 5: pressure_score += 1
            if gas_queue_cnt > 10: pressure_score += 2
            elif gas_queue_cnt > 5: pressure_score += 1

            records.append({
                "hour": hour,
                "restaurant_queue_avg_min": rest_queue_avg,
                "restaurant_queue_max_min": rest_queue_max,
                "restaurant_queue_p95_min": rest_queue_p95,
                "restroom_wait_avg_min": restroom_wait_avg,
                "restroom_usage_count": restroom_usage_cnt,
                "charging_wait_avg_min": charge_wait_avg,
                "charging_wait_max_min": charge_wait_max,
                "charging_wait_p95_min": charge_wait_p95,
                "gas_queue_estimate": gas_queue_cnt,
                "queue_pressure_score": pressure_score,
                "queue_pressure_level": "极高" if pressure_score >= 8 else ("高" if pressure_score >= 5 else ("中" if pressure_score >= 2 else "低")),
            })
        return pd.DataFrame(records)

    def calc_charging_metrics(self, charging_df):
        logger.info("计算充电等待与利用率...")
        if charging_df is None or charging_df.empty:
            return pd.DataFrame()
        df = charging_df.copy()
        df["hour"] = self._get_hour_bucket(df["start_time"])

        active_sessions = df.groupby("hour").size().rename("sessions")
        avg_duration = df.groupby("hour")["duration_min"].mean().rename("avg_duration_min")
        total_energy = df.groupby("hour")["energy_kwh"].sum().rename("total_kwh")
        avg_wait = df.groupby("hour")["wait_time_min"].mean().rename("avg_wait_min") if "wait_time_min" in df.columns else pd.Series(dtype="float64")
        fault_count = df.groupby("hour")["charger_fault_flag"].sum().rename("fault_count") if "charger_fault_flag" in df.columns else pd.Series(dtype="int64")
        unique_chargers = df.groupby("hour")["charger_id"].nunique().rename("active_chargers")

        result = pd.concat([active_sessions, avg_duration, total_energy, avg_wait, fault_count, unique_chargers], axis=1).fillna(0)
        result.index.name = "hour"
        result = result.reset_index()
        result["utilization_rate"] = (result["active_chargers"] / CAPACITY["ev_chargers"]).round(4)
        result["wait_level"] = np.where(result["avg_wait_min"] > 20, "等待>20分钟",
                                        np.where(result["avg_wait_min"] > 10, "等待10-20分钟",
                                                 np.where(result["avg_wait_min"] > 5, "等待5-10分钟", "基本无等待")))
        result["charger_shortage"] = (result["sessions"] - result["active_chargers"] * 2).clip(lower=0).astype(int)
        return result

    def calc_restaurant_stocking(self, restaurant_df):
        logger.info("计算餐饮备货建议...")
        if restaurant_df is None or restaurant_df.empty:
            return pd.DataFrame()
        df = restaurant_df.copy()
        df["hour"] = self._get_hour_bucket(df["timestamp"])
        df["date"] = df["timestamp"].dt.date

        category_hourly = df.groupby(["date", "hour", "category"]).agg(
            qty_sum=("quantity", "sum"),
            revenue=("total_amount", "sum"),
            order_count=("order_id", "nunique")
        ).reset_index()

        cat_hour_avg = category_hourly.groupby(["hour", "category"]).agg(
            avg_qty=("qty_sum", "mean"),
            median_qty=("qty_sum", "median"),
            p80_qty=("qty_sum", lambda x: x.quantile(0.80)),
            p95_qty=("qty_sum", lambda x: x.quantile(0.95)),
            avg_revenue=("revenue", "mean"),
            day_count=("date", "nunique")
        ).reset_index()

        cat_hour_avg["suggest_stock_qty"] = (cat_hour_avg["p95_qty"] * 1.1).round(0).astype(int)
        cat_hour_avg["safety_stock_qty"] = (cat_hour_avg["p95_qty"] * 1.2).round(0).astype(int)
        cat_hour_avg["hour_of_day"] = cat_hour_avg["hour"].dt.hour
        cat_hour_avg["meal_period"] = np.where(
            cat_hour_avg["hour_of_day"].between(6, 9), "早餐",
            np.where(cat_hour_avg["hour_of_day"].between(11, 14), "午餐",
                     np.where(cat_hour_avg["hour_of_day"].between(17, 20), "晚餐",
                              np.where(cat_hour_avg["hour_of_day"].between(14, 17), "下午茶", "其他时段")))
        )
        return cat_hour_avg

    def calc_complaint_risk(self, complaints_df, hourly_metrics_ref):
        logger.info("计算投诉风险指标...")
        risk_records = []
        if complaints_df is not None and not complaints_df.empty:
            df = complaints_df.copy()
            df["hour"] = self._get_hour_bucket(df["timestamp"])
            df["severity_score"] = df["severity"].map({"一般": 1, "较严重": 3, "严重": 5})
            df["unresolved_flag"] = df["resolution_status"].map({"已处理": 0, "处理中": 1, "未处理": 2}).fillna(1)

            hourly_complaints = df.groupby("hour").agg(
                complaint_count=("complaint_id", "count"),
                severity_sum=("severity_score", "sum"),
                unresolved_count=("unresolved_flag", "sum"),
                avg_feedback=("feedback_score", "mean")
            ).reset_index()
            hourly_complaints["risk_score"] = (
                hourly_complaints["complaint_count"] * 2 +
                hourly_complaints["severity_sum"] +
                hourly_complaints["unresolved_count"] * 3
            )
            for _, r in hourly_complaints.iterrows():
                risk_records.append({
                    "hour": r["hour"],
                    "complaint_count": int(r["complaint_count"]),
                    "complaint_risk_score": int(r["risk_score"]),
                    "unresolved_count": int(r["unresolved_count"]),
                    "avg_feedback_score": round(r["avg_feedback"], 2),
                })
            cat_hour = df.groupby(["hour", "category"])["complaint_id"].count().reset_index()
            for h in cat_hour["hour"].unique():
                sub = cat_hour[cat_hour["hour"] == h]
                top_cat = sub.sort_values("complaint_id", ascending=False).iloc[0]["category"] if len(sub) > 0 else None
                for rec in risk_records:
                    if rec["hour"] == h:
                        rec["top_complaint_category"] = top_cat

        if risk_records:
            risk_df = pd.DataFrame(risk_records)
        else:
            risk_df = pd.DataFrame(columns=["hour", "complaint_count", "complaint_risk_score",
                                             "unresolved_count", "avg_feedback_score", "top_complaint_category"])
        risk_df["risk_level"] = np.where(risk_df["complaint_risk_score"] >= 15, "高风险",
                                          np.where(risk_df["complaint_risk_score"] >= 8, "中风险",
                                                   np.where(risk_df["complaint_risk_score"] >= 3, "低风险", "正常")))
        return risk_df

    def detect_anomalies(self, hourly_df):
        logger.info("检测异常情况...")
        self.anomalies = []
        for _, row in hourly_df.iterrows():
            hour = row.get("hour")
            date_str = pd.to_datetime(hour).strftime("%Y-%m-%d")
            time_str = pd.to_datetime(hour).strftime("%H:%M")

            if "utilization_small" in row and row["utilization_small"] >= 0.95:
                self.anomalies.append({
                    "date": date_str, "time": time_str,
                    "type": "停车严重拥堵", "location": "小型车停车场",
                    "value": f"{row['utilization_small']*100:.1f}%",
                    "threshold": "95%", "severity": "严重",
                    "suggestion": "立即开放备用车位，引导至附近区域，安排人员疏导"
                })
            if "utilization_large" in row and row["utilization_large"] >= 0.95:
                self.anomalies.append({
                    "date": date_str, "time": time_str,
                    "type": "停车严重拥堵", "location": "大型车停车场",
                    "value": f"{row['utilization_large']*100:.1f}%",
                    "threshold": "95%", "severity": "严重",
                    "suggestion": "引导大型车辆临时停靠，协调路政分流"
                })
            if "utilization_rate" in row and row["utilization_rate"] >= 0.95:
                self.anomalies.append({
                    "date": date_str, "time": time_str,
                    "type": "充电桩饱和", "location": "充电站",
                    "value": f"{row['utilization_rate']*100:.1f}%",
                    "threshold": "95%", "severity": "高",
                    "suggestion": "开启移动充电车，通知车主前往邻近服务区"
                })
            if "restaurant_queue_p95_min" in row and row["restaurant_queue_p95_min"] >= 30:
                self.anomalies.append({
                    "date": date_str, "time": time_str,
                    "type": "餐饮排队超长", "location": "餐饮区",
                    "value": f"P95 {row['restaurant_queue_p95_min']}分钟",
                    "threshold": "30分钟", "severity": "高",
                    "suggestion": "增开临时窗口，推快速套餐，增加外带选项"
                })
            if "charging_wait_p95_min" in row and row["charging_wait_p95_min"] >= 45:
                self.anomalies.append({
                    "date": date_str, "time": time_str,
                    "type": "充电等待过长", "location": "充电站",
                    "value": f"P95 {row['charging_wait_p95_min']}分钟",
                    "threshold": "45分钟", "severity": "高",
                    "suggestion": "启动应急调度，设置预约排队系统"
                })
            if "complaint_risk_score" in row and row["complaint_risk_score"] >= 15:
                self.anomalies.append({
                    "date": date_str, "time": time_str,
                    "type": "投诉风险高", "location": row.get("top_complaint_category", "全域"),
                    "value": f"风险分 {row['complaint_risk_score']}",
                    "threshold": "15", "severity": "高",
                    "suggestion": "管理层介入处理，优先解决未解决投诉"
                })
            if "queue_pressure_score" in row and row["queue_pressure_score"] >= 8:
                self.anomalies.append({
                    "date": date_str, "time": time_str,
                    "type": "整体排队压力极高", "location": "服务区全域",
                    "value": f"压力分 {row['queue_pressure_score']}",
                    "threshold": "8", "severity": "严重",
                    "suggestion": "启动高峰应急预案，全员到岗，增开通道"
                })

        return pd.DataFrame(self.anomalies)

    def calc_daily_summary(self, hourly_df):
        if hourly_df is None or hourly_df.empty:
            return pd.DataFrame()
        df = hourly_df.copy()
        df["date"] = pd.to_datetime(df["hour"]).dt.date
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        agg_map = {}
        for c in numeric_cols:
            agg_map[c] = ["sum", "mean", "max", "min"]
        daily = df.groupby("date")[numeric_cols].agg(
            ["sum", "mean", "max", "min"]
        ).round(2)
        daily.columns = ["_".join(col).strip() for col in daily.columns.values]
        daily = daily.reset_index()
        peak_cols = [c for c in hourly_df.columns if c in ["est_people_flow", "total_revenue", "utilization_small",
                                                            "complaint_risk_score", "queue_pressure_score"]]
        for pc in peak_cols:
            if pc in hourly_df.columns:
                peak = df.loc[df.groupby("date")[pc].idxmax(), ["date", "hour", pc]].rename(columns={pc: f"{pc}_peak_value", "hour": f"{pc}_peak_hour"})
                daily = daily.merge(peak, on="date", how="left")
        return daily

    def build_hourly_master(self, cleaned_data):
        logger.info("构建小时级明细主表...")
        traffic = cleaned_data.get("traffic")
        parking = cleaned_data.get("parking")
        restaurant = cleaned_data.get("restaurant")
        convenience = cleaned_data.get("convenience")
        charging = cleaned_data.get("charging")
        gas = cleaned_data.get("gas")
        restroom = cleaned_data.get("restroom")
        complaints = cleaned_data.get("complaints")
        weather = cleaned_data.get("weather")
        holiday = cleaned_data.get("holiday")

        people_stats = self.calc_people_flow(traffic, parking)
        parking_stats = self.calc_parking_congestion(parking)
        consumption_stats = self.calc_consumption_conversion(people_stats, restaurant, convenience, gas, charging)
        queue_stats = self.calc_queue_pressure(restaurant, restroom, charging, gas)
        charging_stats = self.calc_charging_metrics(charging)
        stock_stats = self.calc_restaurant_stocking(restaurant)
        complaint_stats = self.calc_complaint_risk(complaints, people_stats)

        all_dfs = [people_stats, parking_stats, consumption_stats, queue_stats, charging_stats, complaint_stats]
        master = None
        for df in all_dfs:
            if df is None or df.empty:
                continue
            if master is None:
                master = df.copy()
            else:
                if "hour" in df.columns:
                    master = master.merge(df, on="hour", how="outer")
                else:
                    master = pd.concat([master, df], axis=1)

        if master is None:
            master = pd.DataFrame()
        else:
            master = master.sort_values("hour").reset_index(drop=True)
            master = master.fillna(0)

        if weather is not None and not weather.empty and not master.empty:
            weather = weather.copy()
            weather["hour"] = weather["timestamp"]
            master = master.merge(weather[["hour", "temperature_c", "humidity_pct", "weather", "wind_speed_ms", "visibility_km"]], on="hour", how="left")

        if holiday is not None and not holiday.empty and not master.empty:
            holiday = holiday.copy()
            holiday["date"] = pd.to_datetime(holiday["date"]).dt.date
            master["date"] = pd.to_datetime(master["hour"]).dt.date
            master = master.merge(holiday[["date", "is_holiday", "is_weekend", "holiday_name", "traffic_factor"]], on="date", how="left")
            master = master.drop(columns=["date"])

        self.hourly_metrics = master
        if not master.empty:
            self.daily_metrics = self.calc_daily_summary(master)

        anomalies_df = self.detect_anomalies(master) if not master.empty else pd.DataFrame()

        return {
            "hourly_master": master,
            "daily_summary": self.daily_metrics,
            "stocking_advice": stock_stats,
            "anomalies": anomalies_df,
        }

    def save_all(self, results):
        logger.info("保存计算结果...")
        for name, df in results.items():
            if isinstance(df, pd.DataFrame) and not df.empty:
                path = os.path.join(self.output_dir, f"{name}.csv")
                if name == "hourly_master":
                    path = os.path.join(self.output_dir, "service_area_hourly_detail.csv")
                df.to_csv(path, index=False, encoding="utf-8-sig")
                logger.info(f"  保存 {name}: {path} ({len(df)} 行)")

        if isinstance(results.get("stocking_advice"), pd.DataFrame):
            results["stocking_advice"].to_excel(
                os.path.join(self.output_dir, "restaurant_stocking_plan.xlsx"), index=False
            )

    def calculate_all(self, cleaned_data):
        logger.info("=" * 60)
        logger.info("开始核心指标计算")
        logger.info("=" * 60)
        results = self.build_hourly_master(cleaned_data)
        self.save_all(results)
        logger.info("=" * 60)
        return results


if __name__ == "__main__":
    from data_cleaner import DataCleaner
    cleaner = DataCleaner()
    cleaned, report = cleaner.clean_all()
    calc = MetricsCalculator()
    results = calc.calculate_all(cleaned)
    print("\n小时级主表前5行:")
    if results["hourly_master"] is not None:
        print(results["hourly_master"].head())
    print("\n异常清单:")
    if results["anomalies"] is not None:
        print(results["anomalies"].head(10))
