"""
高速服务区数据校正模块
处理传感器缺口、重复交易、跨日停留、车辆分类、设备故障和临时封闭记录
"""
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DataCleaner:
    def __init__(self, input_dir="data/raw", output_dir="data/input"):
        self.input_dir = input_dir
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        self.cleaning_report = []

    def _log_cleaning(self, step, dataset, before_count, after_count, details=""):
        change = after_count - before_count
        self.cleaning_report.append({
            "step": step,
            "dataset": dataset,
            "before_count": before_count,
            "after_count": after_count,
            "change": change,
            "details": details
        })
        logger.info(f"[{dataset}] {step}: {before_count} -> {after_count} ({change:+d}) {details}")

    def fix_sensor_gaps(self, df, time_col, value_cols, freq='h'):
        if df.empty:
            return df
        df = df.copy()
        df[time_col] = pd.to_datetime(df[time_col])
        df = df.sort_values(time_col).reset_index(drop=True)
        time_min = df[time_col].min().floor(freq)
        time_max = df[time_col].max().ceil(freq)
        full_range = pd.date_range(start=time_min, end=time_max, freq=freq)
        df["_time_bucket"] = df[time_col].dt.floor(freq)
        agg = df.groupby("_time_bucket")[value_cols].mean().reset_index()
        agg = agg.set_index("_time_bucket").reindex(full_range).reset_index()
        agg.columns = [time_col] + value_cols
        for col in value_cols:
            agg[col] = agg[col].interpolate(method='linear', limit_direction='both')
            if agg[col].isna().any():
                agg[col] = agg[col].fillna(agg[col].median())
        return agg

    def fix_traffic_flow(self, df):
        before = len(df)
        df = df.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"])

        missing_type = df["vehicle_type"].isna().sum()
        if missing_type > 0:
            axle_median_small = df[df["vehicle_type"] == "small"]["axle_count"].median()
            axle_median_large = df[df["vehicle_type"] == "large"]["axle_count"].median()
            mask = df["vehicle_type"].isna()
            df.loc[mask, "vehicle_type"] = np.where(
                df.loc[mask, "axle_count"].fillna(2) > 2, "large", "small"
            )

        missing_speed = df["speed_kmh"].isna().sum()
        if missing_speed > 0:
            df["speed_kmh"] = df.groupby(["vehicle_type", df["timestamp"].dt.hour])["speed_kmh"].transform(
                lambda x: x.fillna(x.median())
            )
            df["speed_kmh"] = df["speed_kmh"].fillna(df["speed_kmh"].median())

        df = df.drop_duplicates(subset=["timestamp", "vehicle_id"], keep="first")
        after = len(df)
        self._log_cleaning("传感器缺口+重复校正", "车流数据", before, after,
                          f"补全车辆类型{missing_type}条，补全速度{missing_speed}条")
        return df

    def fix_parking_records(self, df):
        before = len(df)
        df = df.copy()
        df["entry_time"] = pd.to_datetime(df["entry_time"])
        df["exit_time"] = pd.to_datetime(df["exit_time"], errors="coerce")

        missing_exit = df["exit_time"].isna().sum()
        if missing_exit > 0:
            median_duration = df.groupby("vehicle_type").apply(
                lambda x: (x["exit_time"] - x["entry_time"]).dt.total_seconds().median() / 60
            ).to_dict()
            mask = df["exit_time"].isna()
            for vtype in df["vehicle_type"].unique():
                vmask = mask & (df["vehicle_type"] == vtype)
                dur = median_duration.get(vtype, 30)
                df.loc[vmask, "exit_time"] = df.loc[vmask, "entry_time"] + timedelta(minutes=dur)

        df["duration_min"] = (df["exit_time"] - df["entry_time"]).dt.total_seconds() / 60

        cross_day = (df["entry_time"].dt.date != df["exit_time"].dt.date).sum()
        df["is_cross_day"] = df["entry_time"].dt.date != df["exit_time"].dt.date
        df.loc[df["duration_min"] > 720, "exit_time"] = df.loc[df["duration_min"] > 720, "entry_time"] + timedelta(hours=12)
        df["duration_min"] = (df["exit_time"] - df["entry_time"]).dt.total_seconds() / 60
        df = df[df["duration_min"] > 0]

        df = df.sort_values(["parking_id", "entry_time"]).copy()
        prev_exit = (
            df.groupby("parking_id")["exit_time"]
            .cummax()
            .groupby(df["parking_id"])
            .shift()
        )
        overlap_mask = prev_exit.notna() & (df["entry_time"] < prev_exit)
        overlap_count = int(overlap_mask.sum())
        df.loc[overlap_mask, "entry_time"] = prev_exit.loc[overlap_mask]
        df["duration_min"] = (df["exit_time"] - df["entry_time"]).dt.total_seconds() / 60
        df = df[df["duration_min"] > 0]

        after = len(df)
        self._log_cleaning("跨日停留+时间重叠校正", "停车场数据", before, after,
                          f"补全离场时间{missing_exit}条，跨日停留{cross_day}条，修正重叠{overlap_count}条")
        return df

    def fix_duplicate_transactions(self, df, id_cols, amount_col, time_col, time_window_min=2):
        before = len(df)
        df = df.copy()
        df[time_col] = pd.to_datetime(df[time_col])
        df = df.sort_values(time_col)
        removed = 0
        if len(id_cols) == 1:
            mask = pd.Series(True, index=df.index)
            for gid, sub in df.groupby(id_cols[0]):
                if len(sub) <= 1:
                    continue
                sub = sub.sort_values(time_col)
                diffs = sub[time_col].diff().dt.total_seconds() / 60
                amt_diff = sub[amount_col].diff().abs()
                dup_mask = (diffs <= time_window_min) & (amt_diff < 0.01)
                if dup_mask.any():
                    removed += dup_mask.sum()
                    mask.loc[sub.index[dup_mask]] = False
            df = df[mask].copy()
        after = len(df)
        return df, removed

    def fix_restaurant_orders(self, df):
        before = len(df)
        df = df.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df, removed = self.fix_duplicate_transactions(
            df, ["order_id"], "total_amount", "timestamp", time_window_min=1
        )
        df["total_amount"] = df["total_amount"].fillna(df["unit_price"] * df["quantity"])
        after = len(df)
        self._log_cleaning("重复订单校正", "餐饮数据", before, after,
                          f"移除重复交易{removed}条")
        return df

    def fix_convenience_store(self, df):
        before = len(df)
        df = df.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        tx_before = df["transaction_id"].nunique()
        df["subtotal"] = df["subtotal"].fillna(df["unit_price"] * df["quantity"])
        total_per_tx = df.groupby("transaction_id")["timestamp"].transform("min")
        df["_tx_time"] = total_per_tx
        df = df.sort_values(["transaction_id", "_tx_time"])
        duplicates = df.duplicated(subset=["transaction_id", "sku_name", "quantity", "unit_price"], keep="first")
        dup_count = duplicates.sum()
        df = df[~duplicates]
        tx_after = df["transaction_id"].nunique()
        after = len(df)
        self._log_cleaning("明细行去重", "便利店数据", before, after,
                          f"移除重复明细{dup_count}行，交易数{tx_before} -> {tx_after}")
        return df

    def fix_charging_station(self, df, equip_logs=None):
        before = len(df)
        df = df.copy()
        df["start_time"] = pd.to_datetime(df["start_time"])
        df["end_time"] = pd.to_datetime(df["end_time"], errors="coerce")

        missing_end = df["end_time"].isna().sum()
        if missing_end > 0:
            median_dur = df["duration_min"].median()
            mask = df["end_time"].isna()
            df.loc[mask, "end_time"] = df.loc[mask, "start_time"] + timedelta(minutes=median_dur)
            df.loc[mask, "duration_min"] = median_dur
            df.loc[mask, "energy_kwh"] = df.loc[mask, "energy_kwh"].fillna(
                df["energy_kwh"].median()
            )

        df["duration_min"] = (df["end_time"] - df["start_time"]).dt.total_seconds() / 60
        df["duration_min"] = df["duration_min"].clip(lower=5, upper=180)
        df["end_time"] = df["start_time"] + pd.to_timedelta(df["duration_min"], unit="m")

        fault_chargers = set()
        if equip_logs is not None and not equip_logs.empty:
            faults = equip_logs[equip_logs["status"].isin(["离线", "故障"])]
            for _, row in faults.iterrows():
                did = row["device_id"]
                if did.startswith("EV"):
                    fault_chargers.add(did)
        df["charger_fault_flag"] = df["charger_id"].isin(fault_chargers)

        after = len(df)
        self._log_cleaning("充电会话校正", "充电桩数据", before, after,
                          f"补全{missing_end}条异常结束会话，故障桩{len(fault_chargers)}个")
        return df

    def fix_weather(self, df):
        before = len(df)
        df = df.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.drop_duplicates(subset=["timestamp"], keep="last")
        value_cols = ["temperature_c", "humidity_pct", "wind_speed_ms", "visibility_km"]
        for col in value_cols:
            missing = df[col].isna().sum()
            if missing > 0:
                df[col] = df[col].interpolate(method='linear', limit_direction='both')
                df[col] = df[col].fillna(df[col].median())

        mode_weather = df["weather"].mode().iloc[0] if not df["weather"].mode().empty else "晴"
        df["weather"] = df["weather"].fillna(mode_weather)
        df["wind_direction"] = df["wind_direction"].ffill().bfill()

        time_min = df["timestamp"].min()
        time_max = df["timestamp"].max()
        full_idx = pd.date_range(start=time_min, end=time_max, freq="h")
        df = df.set_index("timestamp").reindex(full_idx)
        df.index.name = "timestamp"
        for col in value_cols:
            df[col] = df[col].interpolate(method='linear', limit_direction='both')
        df["weather"] = df["weather"].ffill().bfill()
        df["wind_direction"] = df["wind_direction"].ffill().bfill()
        df["station"] = df["station"].ffill().bfill()
        df = df.reset_index()
        after = len(df)
        self._log_cleaning("天气数据插值补全", "天气数据", before, after,
                          "按小时连续化并填充缺失")
        return df

    def fix_complaints(self, df):
        before = len(df)
        df = df.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df["resolution_time_min"] = df["resolution_time_min"].fillna(
            df.groupby("severity")["resolution_time_min"].transform("median")
        )
        df["feedback_score"] = df["feedback_score"].fillna(3)
        df["resolution_status"] = df["resolution_status"].fillna("未处理")
        after = len(df)
        self._log_cleaning("投诉字段补全", "投诉数据", before, after)
        return df

    def apply_closure_flags(self, data_dict, equip_logs):
        if equip_logs is None or equip_logs.empty:
            return data_dict
        faults = equip_logs[equip_logs["status"].isin(["离线", "故障", "重启中"])].copy()
        faults["timestamp"] = pd.to_datetime(faults["timestamp"])
        closure_windows = []
        for _, row in faults.iterrows():
            start = row["timestamp"]
            end = start + timedelta(minutes=max(row["downtime_min"], 30))
            closure_windows.append({
                "device_id": row["device_id"],
                "device_type": row["device_type"],
                "start": start,
                "end": end,
                "description": row["description"]
            })
        data_dict["closure_windows"] = pd.DataFrame(closure_windows)
        return data_dict

    def classify_vehicles(self, traffic_df):
        df = traffic_df.copy()
        conditions = [
            (df["vehicle_type"] == "large") | (df["axle_count"] >= 4),
            (df["vehicle_type"] == "small") | (df["axle_count"] <= 2),
        ]
        choices = ["large", "small"]
        df["vehicle_class"] = np.select(conditions, choices, default="medium")
        df["vehicle_class"] = np.where(
            df["speed_kmh"] < 60,
            np.where(df["vehicle_class"] == "small", "medium", df["vehicle_class"]),
            df["vehicle_class"]
        )
        return df

    def clean_all(self):
        logger.info("=" * 60)
        logger.info("开始数据校正流程")
        logger.info("=" * 60)

        data = {}
        files = {
            "traffic": "traffic_flow.csv",
            "parking": "parking_records.csv",
            "restroom": "restroom_usage.csv",
            "restaurant": "restaurant_orders.csv",
            "convenience": "convenience_store.csv",
            "charging": "charging_station.csv",
            "gas": "gas_station.csv",
            "weather": "weather_hourly.csv",
            "holiday": "holiday_calendar.csv",
            "complaints": "complaints.csv",
            "equipment": "equipment_logs.csv",
        }

        for key, fname in files.items():
            fpath = os.path.join(self.input_dir, fname)
            if os.path.exists(fpath):
                data[key] = pd.read_csv(fpath)
                logger.info(f"读取 {fname}: {len(data[key])} 条记录")
            else:
                logger.warning(f"未找到文件: {fname}")
                data[key] = pd.DataFrame()

        equip_logs = data.get("equipment", pd.DataFrame())
        if not equip_logs.empty:
            equip_logs["timestamp"] = pd.to_datetime(equip_logs["timestamp"])

        cleaned = {}

        if not data.get("traffic", pd.DataFrame()).empty:
            cleaned["traffic"] = self.fix_traffic_flow(data["traffic"])
            cleaned["traffic"] = self.classify_vehicles(cleaned["traffic"])

        if not data.get("parking", pd.DataFrame()).empty:
            cleaned["parking"] = self.fix_parking_records(data["parking"])

        if not data.get("restroom", pd.DataFrame()).empty:
            df = data["restroom"].copy()
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            df["duration_sec"] = df["duration_sec"].clip(lower=10, upper=600)
            df["paper_dispensed"] = df["paper_dispensed"].fillna(df["paper_dispensed"].median())
            df["soap_used"] = df["soap_used"].fillna(0)
            cleaned["restroom"] = df
            self._log_cleaning("使用时长裁剪+缺失补全", "卫生间数据", len(data["restroom"]), len(df))

        if not data.get("restaurant", pd.DataFrame()).empty:
            cleaned["restaurant"] = self.fix_restaurant_orders(data["restaurant"])

        if not data.get("convenience", pd.DataFrame()).empty:
            cleaned["convenience"] = self.fix_convenience_store(data["convenience"])

        if not data.get("charging", pd.DataFrame()).empty:
            cleaned["charging"] = self.fix_charging_station(data["charging"], equip_logs)

        if not data.get("gas", pd.DataFrame()).empty:
            df = data["gas"].copy()
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            df["liters"] = df["liters"].clip(lower=5, upper=150)
            df["total_amount"] = df["total_amount"].fillna(df["liters"] * df["unit_price"])
            cleaned["gas"] = df
            self._log_cleaning("加油量异常裁剪", "加油站数据", len(data["gas"]), len(df))

        if not data.get("weather", pd.DataFrame()).empty:
            cleaned["weather"] = self.fix_weather(data["weather"])

        if not data.get("holiday", pd.DataFrame()).empty:
            cleaned["holiday"] = data["holiday"]

        if not data.get("complaints", pd.DataFrame()).empty:
            cleaned["complaints"] = self.fix_complaints(data["complaints"])

        if not equip_logs.empty:
            cleaned["equipment"] = equip_logs

        cleaned = self.apply_closure_flags(cleaned, equip_logs)

        for key, df in cleaned.items():
            if isinstance(df, pd.DataFrame) and not df.empty:
                fname = f"{key}_cleaned.csv"
                df.to_csv(os.path.join(self.output_dir, fname), index=False)

        report_df = pd.DataFrame(self.cleaning_report)
        report_df.to_csv(os.path.join(self.output_dir, "cleaning_report.csv"), index=False)
        logger.info(f"校正报告已保存: {len(self.cleaning_report)} 项校正操作")
        logger.info("=" * 60)
        return cleaned, report_df


if __name__ == "__main__":
    cleaner = DataCleaner()
    cleaned_data, report = cleaner.clean_all()
    print("\n校正摘要:")
    print(report.to_string(index=False))
