"""
高速服务区模拟数据生成器
生成车流、停车场、卫生间、餐饮、便利店、充电桩、加油、天气、节假日和投诉数据
"""
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import os
import random

np.random.seed(42)
random.seed(42)


class ServiceAreaDataGenerator:
    def __init__(self, start_date=None, end_date=None, output_dir="data/raw"):
        if start_date is None:
            start_date = datetime(2026, 5, 1)
        if end_date is None:
            end_date = datetime(2026, 6, 15)
        self.start_date = start_date
        self.end_date = end_date
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        self.date_range = pd.date_range(start=start_date, end=end_date, freq='D')
        self.holiday_dates = self._generate_holidays()

    def _generate_holidays(self):
        holidays = [
            datetime(2026, 5, 1), datetime(2026, 5, 2), datetime(2026, 5, 3),
            datetime(2026, 5, 4), datetime(2026, 5, 5),
            datetime(2026, 6, 12), datetime(2026, 6, 13), datetime(2026, 6, 14),
        ]
        return set(holidays)

    def _is_holiday(self, dt):
        return dt.date() in {h.date() for h in self.holiday_dates} or dt.weekday() >= 5

    def _hourly_factor(self, hour, is_holiday):
        base = np.array([0.05, 0.03, 0.02, 0.02, 0.03, 0.08,
                         0.15, 0.35, 0.65, 0.85, 0.95, 1.00,
                         0.95, 0.75, 0.60, 0.55, 0.65, 0.80,
                         0.90, 0.85, 0.60, 0.35, 0.20, 0.10])
        if is_holiday:
            base = base * 1.4 + 0.1
        return base[hour]

    def generate_traffic_flow(self):
        records = []
        for date in self.date_range:
            is_holiday = self._is_holiday(date)
            for hour in range(24):
                hf = self._hourly_factor(hour, is_holiday)
                base_cars = int(200 * hf + np.random.normal(0, 15))
                base_trucks = int(80 * hf * 0.7 + np.random.normal(0, 8))
                for _ in range(max(1, base_cars + base_trucks)):
                    ts = date + timedelta(hours=hour, minutes=random.randint(0, 59),
                                          seconds=random.randint(0, 59))
                    is_truck = random.random() < (base_trucks / max(1, base_cars + base_trucks))
                    records.append({
                        "timestamp": ts,
                        "vehicle_id": f"V{random.randint(100000, 999999)}",
                        "vehicle_type": "large" if is_truck else "small",
                        "axle_count": random.choice([2, 3, 4, 5]) if is_truck else 2,
                        "lane": random.randint(1, 4),
                        "speed_kmh": round(random.uniform(40, 80) if is_truck else random.uniform(60, 100), 1),
                        "direction": random.choice(["north", "south"]),
                        "plate_province": random.choice(["苏", "沪", "浙", "皖", "鲁", "京", "粤", "川"])
                    })
        df = pd.DataFrame(records).sort_values("timestamp").reset_index(drop=True)
        for i in random.sample(range(len(df)), k=int(len(df) * 0.03)):
            if random.random() < 0.5:
                df.loc[i, "speed_kmh"] = np.nan
            else:
                df.loc[i, "vehicle_type"] = np.nan
        df.to_csv(os.path.join(self.output_dir, "traffic_flow.csv"), index=False)
        return df

    def generate_parking(self):
        records = []
        for date in self.date_range:
            is_holiday = self._is_holiday(date)
            for hour in range(24):
                hf = self._hourly_factor(hour, is_holiday)
                small_occ = min(200, int(160 * hf + np.random.normal(0, 15)))
                large_occ = min(80, int(60 * hf * 0.6 + np.random.normal(0, 8)))
                for vtype, occ, cap in [("small", small_occ, 200), ("large", large_occ, 80)]:
                    ts = date + timedelta(hours=hour)
                    for i in range(max(0, int(occ * random.uniform(0.8, 1.2)))):
                        enter_ts = ts + timedelta(minutes=random.randint(-15, 45))
                        duration = random.expovariate(1 / 30) if vtype == "small" else random.expovariate(1 / 90)
                        duration = min(720, max(5, duration))
                        exit_ts = enter_ts + timedelta(minutes=duration)
                        records.append({
                            "parking_id": f"P{vtype[0].upper()}{(i % cap) + 1:03d}",
                            "vehicle_id": f"V{random.randint(100000, 999999)}",
                            "vehicle_type": vtype,
                            "entry_time": enter_ts,
                            "exit_time": exit_ts if random.random() > 0.05 else pd.NaT,
                            "zone": random.choice(["A区", "B区", "C区", "D区"]),
                            "floor": 1 if vtype == "small" else 0
                        })
        df = pd.DataFrame(records).sort_values("entry_time").reset_index(drop=True)
        df.to_csv(os.path.join(self.output_dir, "parking_records.csv"), index=False)
        return df

    def generate_restroom(self):
        records = []
        for date in self.date_range:
            is_holiday = self._is_holiday(date)
            for hour in range(24):
                hf = self._hourly_factor(hour, is_holiday)
                count = int(250 * hf + np.random.normal(0, 30))
                for i in range(max(1, count)):
                    ts = date + timedelta(hours=hour, minutes=random.randint(0, 59),
                                          seconds=random.randint(0, 59))
                    records.append({
                        "timestamp": ts,
                        "device_id": f"RS{random.randint(1, 12):02d}",
                        "gender": random.choice(["M", "F"]),
                        "stall_id": f"S{random.randint(1, 40):02d}",
                        "duration_sec": int(random.expovariate(1 / 180)),
                        "paper_dispensed": round(random.uniform(0.5, 2.0), 2),
                        "soap_used": random.choice([0, 1])
                    })
        df = pd.DataFrame(records).sort_values("timestamp").reset_index(drop=True)
        df.to_csv(os.path.join(self.output_dir, "restroom_usage.csv"), index=False)
        return df

    def generate_restaurant(self):
        categories = {
            "中式快餐": ["红烧肉饭", "鸡腿饭", "牛肉面", "炒饭套餐", "水饺"],
            "西式快餐": ["汉堡套餐", "炸鸡套餐", "披萨", "三明治", "热狗"],
            "地方特色": ["小笼包", "鸭血粉丝汤", "生煎包", "奥灶面", "苏式汤面"],
            "饮品甜点": ["咖啡", "奶茶", "冰淇淋", "蛋糕", "果汁"]
        }
        records = []
        for date in self.date_range:
            is_holiday = self._is_holiday(date)
            for hour in range(24):
                hf = self._hourly_factor(hour, is_holiday)
                if hour < 6 or hour > 22:
                    hf *= 0.1
                count = int(80 * hf + np.random.normal(0, 10))
                for i in range(max(1, count)):
                    ts = date + timedelta(hours=hour, minutes=random.randint(0, 59),
                                          seconds=random.randint(0, 59))
                    cat = random.choice(list(categories.keys()))
                    item = random.choice(categories[cat])
                    qty = random.choice([1, 1, 1, 2, 2, 3])
                    base_price = random.uniform(15, 60) if cat != "饮品甜点" else random.uniform(8, 35)
                    records.append({
                        "order_id": f"R{random.randint(1000000, 9999999)}",
                        "timestamp": ts,
                        "category": cat,
                        "item_name": item,
                        "quantity": qty,
                        "unit_price": round(base_price, 2),
                        "total_amount": round(base_price * qty, 2),
                        "payment_method": random.choice(["微信", "支付宝", "现金", "云闪付"]),
                        "dine_in": random.choice([True, True, True, False]),
                        "seat_id": f"SEAT{random.randint(1, 150):03d}" if random.random() > 0.25 else None,
                        "queue_wait_min": max(0, int(np.random.exponential(hf * 8)))
                    })
        df = pd.DataFrame(records).sort_values("timestamp").reset_index(drop=True)
        dup_idx = random.sample(range(len(df)), k=int(len(df) * 0.02))
        for idx in dup_idx:
            dup = df.iloc[idx].copy()
            dup["order_id"] = f"R{random.randint(1000000, 9999999)}"
            df = pd.concat([df, pd.DataFrame([dup])], ignore_index=True)
        df = df.sort_values("timestamp").reset_index(drop=True)
        df.to_csv(os.path.join(self.output_dir, "restaurant_orders.csv"), index=False)
        return df

    def generate_convenience_store(self):
        categories = {
            "饮料": ["矿泉水", "可乐", "雪碧", "红茶", "绿茶", "功能饮料", "牛奶"],
            "零食": ["薯片", "巧克力", "饼干", "坚果", "糖果", "辣条"],
            "日用": ["纸巾", "湿巾", "创可贴", "牙刷", "牙膏", "雨伞"],
            "食品": ["泡面", "面包", "火腿肠", "速食饭", "罐头", "水果"]
        }
        records = []
        for date in self.date_range:
            is_holiday = self._is_holiday(date)
            for hour in range(24):
                hf = self._hourly_factor(hour, is_holiday)
                if hour < 5 or hour > 23:
                    hf *= 0.05
                count = int(120 * hf + np.random.normal(0, 15))
                for i in range(max(1, count)):
                    ts = date + timedelta(hours=hour, minutes=random.randint(0, 59),
                                          seconds=random.randint(0, 59))
                    tx_id = f"TX{random.randint(1000000, 9999999)}"
                    num_items = random.choice([1, 2, 2, 3, 3, 4, 5])
                    for _ in range(num_items):
                        cat = random.choice(list(categories.keys()))
                        item = random.choice(categories[cat])
                        qty = random.choice([1, 1, 1, 2, 2, 3])
                        price = random.uniform(2, 20)
                        records.append({
                            "transaction_id": tx_id,
                            "timestamp": ts,
                            "category": cat,
                            "sku_name": item,
                            "quantity": qty,
                            "unit_price": round(price, 2),
                            "subtotal": round(price * qty, 2),
                            "shelf_id": f"SH{random.randint(1, 20):02d}",
                            "checkout_id": f"CHK{random.randint(1, 4)}"
                        })
        df = pd.DataFrame(records).sort_values("timestamp").reset_index(drop=True)
        df.to_csv(os.path.join(self.output_dir, "convenience_store.csv"), index=False)
        return df

    def generate_charging_station(self):
        records = []
        charger_ids = [f"EV{i:02d}" for i in range(1, 21)]
        for date in self.date_range:
            is_holiday = self._is_holiday(date)
            for hour in range(24):
                hf = self._hourly_factor(hour, is_holiday)
                active_count = min(20, int(15 * hf + np.random.normal(0, 3)))
                for cid in charger_ids[:active_count]:
                    ts = date + timedelta(hours=hour, minutes=random.randint(0, 59))
                    duration = random.uniform(20, 90)
                    energy = random.uniform(15, 80)
                    records.append({
                        "session_id": f"CH{random.randint(100000, 999999)}",
                        "charger_id": cid,
                        "start_time": ts,
                        "end_time": ts + timedelta(minutes=duration),
                        "duration_min": round(duration, 1),
                        "energy_kwh": round(energy, 2),
                        "peak_power_kw": round(random.uniform(40, 120), 1),
                        "battery_start_pct": random.randint(5, 40),
                        "battery_end_pct": random.randint(60, 95),
                        "amount_cny": round(energy * random.uniform(1.2, 2.0), 2),
                        "wait_time_min": max(0, int(np.random.exponential(hf * 12)))
                    })
        df = pd.DataFrame(records).sort_values("start_time").reset_index(drop=True)
        broken_idx = random.sample(range(len(df)), k=int(len(df) * 0.01))
        for idx in broken_idx:
            df.loc[idx, "end_time"] = pd.NaT
            df.loc[idx, "energy_kwh"] = np.nan
        df.to_csv(os.path.join(self.output_dir, "charging_station.csv"), index=False)
        return df

    def generate_gas_station(self):
        records = []
        fuel_types = {"92#汽油": 7.65, "95#汽油": 8.15, "98#汽油": 8.95, "0#柴油": 7.25}
        for date in self.date_range:
            is_holiday = self._is_holiday(date)
            for hour in range(24):
                hf = self._hourly_factor(hour, is_holiday)
                count = int(60 * hf + np.random.normal(0, 8))
                for i in range(max(1, count)):
                    ts = date + timedelta(hours=hour, minutes=random.randint(0, 59),
                                          seconds=random.randint(0, 59))
                    ft = random.choice(list(fuel_types.keys()))
                    liters = random.uniform(20, 70)
                    records.append({
                        "transaction_id": f"G{random.randint(1000000, 9999999)}",
                        "timestamp": ts,
                        "pump_id": f"PUMP{random.randint(1, 8):02d}",
                        "fuel_type": ft,
                        "liters": round(liters, 2),
                        "unit_price": fuel_types[ft],
                        "total_amount": round(liters * fuel_types[ft], 2),
                        "vehicle_type": random.choice(["small", "small", "large"]),
                        "payment_method": random.choice(["微信", "支付宝", "加油卡", "现金"])
                    })
        df = pd.DataFrame(records).sort_values("timestamp").reset_index(drop=True)
        df.to_csv(os.path.join(self.output_dir, "gas_station.csv"), index=False)
        return df

    def generate_weather(self):
        records = []
        for date in self.date_range:
            for hour in range(24):
                ts = date + timedelta(hours=hour)
                month = date.month
                base_temp = 20 if month in [3, 4] else 28 if month in [6, 7, 8] else 10 if month in [11, 12, 1] else 18
                temp = base_temp + np.sin(hour * np.pi / 12 - np.pi / 2) * 8 + np.random.normal(0, 1.5)
                humidity = random.uniform(50, 90)
                weather_type = random.choices(
                    ["晴", "多云", "阴", "小雨", "中雨", "大雨", "雾"],
                    weights=[35, 25, 15, 10, 5, 3, 7], k=1
                )[0]
                records.append({
                    "timestamp": ts,
                    "temperature_c": round(temp, 1),
                    "humidity_pct": round(humidity, 1),
                    "weather": weather_type,
                    "wind_speed_ms": round(random.uniform(0, 12), 1),
                    "wind_direction": random.choice(["东", "南", "西", "北", "东北", "东南", "西北", "西南"]),
                    "visibility_km": round(random.uniform(0.5, 15), 1) if weather_type in ["雾", "大雨"] else round(random.uniform(5, 20), 1),
                    "station": "SSA-001"
                })
        df = pd.DataFrame(records).sort_values("timestamp").reset_index(drop=True)
        missing_hours = random.sample(range(len(df)), k=int(len(df) * 0.02))
        for idx in missing_hours:
            df.loc[idx, "temperature_c"] = np.nan
        df.to_csv(os.path.join(self.output_dir, "weather_hourly.csv"), index=False)
        return df

    def generate_holiday_calendar(self):
        records = []
        for date in self.date_range:
            dt = date.to_pydatetime()
            is_holiday = self._is_holiday(dt)
            records.append({
                "date": date.date(),
                "is_holiday": is_holiday,
                "is_weekend": dt.weekday() >= 5,
                "holiday_name": "" if not is_holiday else random.choice(["五一劳动节", "端午节", "周末"]),
                "special_event": random.choice([None, None, None, "车展", "地方美食节", "促销活动"]),
                "traffic_factor": round(1.0 if not is_holiday else random.uniform(1.3, 1.8), 2),
                "staff_on_duty": random.randint(35, 55) if is_holiday else random.randint(20, 35)
            })
        df = pd.DataFrame(records)
        df.to_csv(os.path.join(self.output_dir, "holiday_calendar.csv"), index=False)
        return df

    def generate_complaints(self):
        complaint_types = {
            "停车场": ["车位不足", "排队等待久", "指示不清", "乱收费", "车辆刮擦"],
            "卫生间": ["清洁不及时", "排队久", "设备故障", "无纸巾", "异味"],
            "餐饮": ["价格过高", "口味差", "卫生问题", "上菜慢", "分量不足"],
            "便利店": ["价格高", "缺货", "过期商品", "排队久"],
            "充电桩": ["排队久", "设备故障", "充电慢", "价格高"],
            "加油站": ["排队久", "设备故障", "油品质量"],
            "服务态度": ["工作人员态度差", "投诉无人处理", "失物招领问题"],
            "环境": ["噪声大", "蚊虫多", "垃圾未及时清理"]
        }
        records = []
        for date in self.date_range:
            is_holiday = self._is_holiday(date)
            base = 3 if is_holiday else 1
            count = max(0, int(base + np.random.normal(0, 1)))
            for i in range(count):
                hour = random.choices(
                    range(24),
                    weights=[0.02, 0.01, 0, 0, 0.01, 0.05, 0.08, 0.1, 0.12, 0.08,
                             0.07, 0.06, 0.08, 0.07, 0.05, 0.04, 0.05, 0.05,
                             0.04, 0.03, 0.03, 0.02, 0.02, 0.02], k=1
                )[0]
                ts = date + timedelta(hours=hour, minutes=random.randint(0, 59))
                cat = random.choice(list(complaint_types.keys()))
                issue = random.choice(complaint_types[cat])
                records.append({
                    "complaint_id": f"CP{random.randint(100000, 999999)}",
                    "timestamp": ts,
                    "category": cat,
                    "issue_detail": issue,
                    "severity": random.choices(["一般", "较严重", "严重"], weights=[0.6, 0.3, 0.1], k=1)[0],
                    "resolution_status": random.choice(["已处理", "已处理", "处理中", "未处理"]),
                    "resolution_time_min": random.randint(10, 180) if random.random() > 0.2 else None,
                    "feedback_score": random.choice([1, 2, 2, 3, 3, 4]),
                    "location": cat if cat != "服务态度" else random.choice(["服务台", "投诉中心", "热线"])
                })
        df = pd.DataFrame(records).sort_values("timestamp").reset_index(drop=True)
        df.to_csv(os.path.join(self.output_dir, "complaints.csv"), index=False)
        return df

    def generate_equipment_logs(self):
        devices = [f"CAM{i:03d}" for i in range(1, 51)] + \
                  [f"SENSOR{i:02d}" for i in range(1, 31)] + \
                  [f"POS{i:02d}" for i in range(1, 11)]
        records = []
        for date in self.date_range:
            for dev in random.sample(devices, k=random.randint(2, 10)):
                ts = date + timedelta(hours=random.randint(0, 23), minutes=random.randint(0, 59))
                status = random.choices(["正常", "离线", "故障", "重启中"], weights=[0.85, 0.06, 0.06, 0.03])[0]
                records.append({
                    "device_id": dev,
                    "device_type": "摄像头" if dev.startswith("CAM") else "传感器" if dev.startswith("SENSOR") else "POS机",
                    "timestamp": ts,
                    "status": status,
                    "error_code": None if status == "正常" else random.choice(["E101", "E202", "E303", "E404", "E505"]),
                    "description": "" if status == "正常" else random.choice([
                        "网络中断", "设备过热", "电源异常", "传感器校准失败", "数据读取错误"
                    ]),
                    "downtime_min": 0 if status == "正常" else random.randint(5, 240)
                })
        df = pd.DataFrame(records).sort_values("timestamp").reset_index(drop=True)
        df.to_csv(os.path.join(self.output_dir, "equipment_logs.csv"), index=False)
        return df

    def generate_all(self):
        print("开始生成模拟数据...")
        print("  [1/11] 车流数据...")
        self.generate_traffic_flow()
        print("  [2/11] 停车场数据...")
        self.generate_parking()
        print("  [3/11] 卫生间数据...")
        self.generate_restroom()
        print("  [4/11] 餐饮数据...")
        self.generate_restaurant()
        print("  [5/11] 便利店数据...")
        self.generate_convenience_store()
        print("  [6/11] 充电桩数据...")
        self.generate_charging_station()
        print("  [7/11] 加油站数据...")
        self.generate_gas_station()
        print("  [8/11] 天气数据...")
        self.generate_weather()
        print("  [9/11] 节假日日历...")
        self.generate_holiday_calendar()
        print("  [10/11] 投诉数据...")
        self.generate_complaints()
        print("  [11/11] 设备日志...")
        self.generate_equipment_logs()
        print(f"所有数据已生成完毕，保存在 {self.output_dir}/ 目录下")
        return True


if __name__ == "__main__":
    gen = ServiceAreaDataGenerator()
    gen.generate_all()
