"""
高速服务区报表输出模块
生成异常清单、复跑说明和服务区小时级明细
"""
import numpy as np
import pandas as pd
from datetime import datetime
import os
import logging
import json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ReportGenerator:
    def __init__(self, output_dir="data/output/reports"):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def generate_anomaly_list(self, anomalies_df, hourly_df, cleaned_data):
        logger.info("生成异常清单...")
        report_rows = []
        if anomalies_df is not None and not anomalies_df.empty:
            for _, a in anomalies_df.iterrows():
                report_rows.append({
                    "异常日期": a.get("date"),
                    "异常时段": a.get("time"),
                    "异常类型": a.get("type"),
                    "异常位置": a.get("location"),
                    "观测值": a.get("value"),
                    "预警阈值": a.get("threshold"),
                    "严重程度": a.get("severity"),
                    "处理建议": a.get("suggestion"),
                })

        extra_anomalies = []
        if hourly_df is not None and not hourly_df.empty:
            for metric, cn, thresh, direction in [
                ("utilization_small", "小型车停车率", 0.9, "over"),
                ("charging_wait_p95_min", "充电P95等待(分)", 30, "over"),
                ("restaurant_queue_p95_min", "餐饮P95排队(分)", 25, "over"),
            ]:
                if metric in hourly_df.columns:
                    if direction == "over":
                        mask = hourly_df[metric] >= thresh
                    else:
                        mask = hourly_df[metric] <= thresh
                    if mask.any():
                        for _, row in hourly_df[mask].iterrows():
                            extra_anomalies.append({
                                "异常日期": pd.to_datetime(row["hour"]).strftime("%Y-%m-%d"),
                                "异常时段": pd.to_datetime(row["hour"]).strftime("%H:%M"),
                                "异常类型": f"{cn}异常",
                                "异常位置": "服务区全域",
                                "观测值": f"{row[metric]:.2f}",
                                "预警阈值": str(thresh),
                                "严重程度": "高" if direction == "over" and row[metric] >= thresh * 1.1 else "中",
                                "处理建议": f"检查{cn}相关运营措施，关注该时段客流",
                            })

        equip = cleaned_data.get("equipment") if cleaned_data else None
        if equip is not None and not equip.empty:
            faults = equip[equip["status"].isin(["离线", "故障"])]
            for _, r in faults.iterrows():
                extra_anomalies.append({
                    "异常日期": pd.to_datetime(r["timestamp"]).strftime("%Y-%m-%d"),
                    "异常时段": pd.to_datetime(r["timestamp"]).strftime("%H:%M"),
                    "异常类型": "设备故障",
                    "异常位置": f"{r.get('device_type','')}-{r['device_id']}",
                    "观测值": r.get("description", ""),
                    "预警阈值": f"停机 {r.get('downtime_min', 0)} 分钟",
                    "严重程度": "高" if r.get("downtime_min", 0) > 60 else "中",
                    "处理建议": "通知运维团队排查，记录维修工单，必要时启动备用设备",
                })

        for a in extra_anomalies:
            if not any(r.get("异常日期") == a["异常日期"]
                      and r.get("异常时段") == a["异常时段"]
                      and r.get("异常类型") == a["异常类型"]
                      for r in report_rows):
                report_rows.append(a)

        anomaly_df = pd.DataFrame(report_rows)
        if not anomaly_df.empty:
            anomaly_df = anomaly_df.sort_values(["异常日期", "异常时段", "严重程度"], ascending=[True, True, False])
            severity_map = {"严重": 1, "高": 2, "中": 3, "低": 4}
            anomaly_df["_sort"] = anomaly_df["严重程度"].map(severity_map).fillna(99)
            anomaly_df = anomaly_df.sort_values(["_sort", "异常日期", "异常时段"]).drop(columns=["_sort"])
            anomaly_df.to_csv(os.path.join(self.output_dir, "异常清单.csv"),
                             index=False, encoding="utf-8-sig")
            anomaly_df.to_excel(os.path.join(self.output_dir, "异常清单.xlsx"),
                               index=False, sheet_name="异常清单")
            logger.info(f"异常清单: {len(anomaly_df)} 条异常记录")
        return anomaly_df

    def generate_rerun_specification(self, cleaning_report, start_time, end_time):
        logger.info("生成复跑说明...")
        total_time = (end_time - start_time).total_seconds()

        rerun_doc = f"""# 高速服务区分析系统 · 复跑说明文档

**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**分析周期**: {start_time.strftime('%Y-%m-%d')} ~ {end_time.strftime('%Y-%m-%d')}
**总处理耗时**: {total_time:.2f} 秒

---

## 一、数据输入要求

### 1.1 原始数据文件列表
所有原始数据需为 CSV 格式，统一放置在 `data/raw/` 目录下：

| 文件名 | 核心字段 | 用途 |
|--------|----------|------|
| traffic_flow.csv | timestamp, vehicle_id, vehicle_type, axle_count, speed_kmh | 车流统计与客流估算 |
| parking_records.csv | parking_id, vehicle_id, entry_time, exit_time, vehicle_type, zone | 停车拥堵与周转分析 |
| restroom_usage.csv | timestamp, device_id, gender, stall_id, duration_sec | 卫生间排队与使用分析 |
| restaurant_orders.csv | order_id, timestamp, category, item_name, quantity, total_amount | 餐饮消费与备货分析 |
| convenience_store.csv | transaction_id, timestamp, category, sku_name, quantity, subtotal | 便利店销售贡献分析 |
| charging_station.csv | session_id, charger_id, start_time, end_time, energy_kwh, wait_time_min | 充电服务与等待分析 |
| gas_station.csv | transaction_id, timestamp, pump_id, fuel_type, liters, total_amount | 加油服务统计 |
| weather_hourly.csv | timestamp, temperature_c, humidity_pct, weather, visibility_km | 天气影响归因分析 |
| holiday_calendar.csv | date, is_holiday, is_weekend, holiday_name, traffic_factor | 节假日权重校正 |
| complaints.csv | complaint_id, timestamp, category, issue_detail, severity, resolution_status | 投诉风险评估 |
| equipment_logs.csv | device_id, device_type, timestamp, status, downtime_min | 设备故障与临时封闭识别 |

### 1.2 字段命名规范
- 所有时间字段统一使用 ISO 8601 格式（YYYY-MM-DD HH:MM:SS）
- 金额单位为人民币元（保留2位小数）
- 车辆类型枚举值：small（小型）/ large（大型）
- 设备状态枚举值：正常/离线/故障/重启中

---

## 二、数据校正流程

> 共执行 {len(cleaning_report) if cleaning_report is not None else 0} 项校正操作

### 2.1 传感器缺口修复
- **车流数据**: 按小时分组，使用同车辆类型+时段中位数补全 `vehicle_type` 和 `speed_kmh`
- **天气数据**: 线性插值填充温度、湿度、风速等数值字段，前向填充天气类型
- **处理策略**: 保留原始标记列 `_corrected_flag`，支持后续审计追溯

### 2.2 重复交易去重
- **餐饮订单**: 同一 `order_id` + 1分钟时间窗 + 金额差异<0.01元判定为重复，保留首条
- **便利店明细**: 同交易+同SKU+同数量+同单价的重复明细行去除
- **去重数量**: 各数据集去重记录请参考 `data/input/cleaning_report.csv`

### 2.3 跨日停留处理
- 入场日期≠离场日期标记为 `is_cross_day=True`
- 单次停留超过12小时按最大12小时截断
- 跨日记录分别拆计入所属日期的占用时段

### 2.4 大车小车分类校正
- 主分类规则：`vehicle_type` 字段优先
- 辅助分类：`axle_count>=4` 判定为大型，`axle_count<=2` 判定为小型
- 二次校准：`speed_kmh<60` 的小型车降级为中型

### 2.5 设备故障识别
- 从 equipment_logs.csv 提取 status ∈ {{离线, 故障, 重启中}} 的记录
- 生成故障时间窗口：`[timestamp, timestamp + downtime_min]`
- 故障期间的相关传感器数据标记为低可信度

### 2.6 临时封闭标记
- 设备故障影响的设施/区域自动标记为临时封闭
- 封闭时段在看板中用虚线标注，数据统计时降低权重

---

## 三、核心计算逻辑

### 3.1 客流估算公式
```
小时客流 = 小型车数 × 1.5 + 大型车数 × 3.0
（含司机和乘客的综合换算系数）
```

### 3.2 停车利用率
```
利用率 = 小时累计占用泊位数 / 总泊位数
小型车总泊位 = 200，大型车总泊位 = 80
```
拥堵分级：正常(<60%) / 偏高(60-75%) / 拥堵(75-90%) / 严重拥堵(≥90%)

### 3.3 消费转化率
```
餐饮转化率 = 餐饮订单数 / 小时客流
便利店转化率 = 便利店交易数 / 小时客流
整体转化率 = 付费用户总数 / 小时客流
人均消费 = 总收入 / 小时客流
```

### 3.4 排队压力指数
| 项目 | 低(+0) | 中(+1) | 高(+2) | 极高(+3) |
|------|--------|--------|--------|----------|
| 餐饮P95排队(分) | <5 | 5-10 | 10-20 | >20 |
| 卫生间平均等(分) | <5 | 5-10 | >10 | — |
| 充电P95等待(分) | <5 | 5-15 | 15-30 | >30 |
| 加油排队(估计) | <5 | 5-10 | >10 | — |
分级：低(0-1) / 中(2-4) / 高(5-7) / 极高(≥8)

### 3.5 充电等待时长
- 基于会话 `wait_time_min` 字段统计均值、P95、最大值
- 利用率 = 活跃充电桩数 / 20 总台数
- 缺口估计 = 会话数 - 活跃桩数 × 2（考虑单桩2次周转）

### 3.6 餐饮备货建议
```
建议备货量 = 小时销量P95分位数 × 1.1
安全备货量 = 小时销量P95分位数 × 1.2
```
分品类统计：中式快餐 / 西式快餐 / 地方特色 / 饮品甜点

### 3.7 投诉风险评分
```
风险分 = 投诉数×2 + 严重程度加权和 + 未解决数×3
严重程度权重：一般=1, 较严重=3, 严重=5
未解决权重：已处理=0, 处理中=1, 未处理=2
```
分级：正常(<3) / 低风险(3-7) / 中风险(8-14) / 高风险(≥15)

---

## 四、复跑命令

### 方式一：全流程复跑（推荐）
```bash
python run_pipeline.py
```
顺序执行：数据生成 → 数据校正 → 指标计算 → 可视化 → 报表 → 启动看板

### 方式二：仅重新计算指标（跳过数据生成）
```bash
python -m src.metrics_calculator
```

### 方式三：仅重绘图表
```bash
python -c "
from src.visualizations import ServiceAreaVisualizer
from src.data_cleaner import DataCleaner
from src.metrics_calculator import MetricsCalculator
c = DataCleaner(); d, _ = c.clean_all();
m = MetricsCalculator(); r = m.calculate_all(d);
v = ServiceAreaVisualizer(); v.generate_all(r, d)
"
```

### 方式四：自定义日期范围
```bash
python run_pipeline.py --start 2026-05-01 --end 2026-06-15
```

---

## 五、输出文件清单

```
data/output/
├── service_area_hourly_detail.csv    # 小时级主表（含50+指标列）
├── daily_summary.csv                 # 日汇总表（SUM/MEAN/MAX/MIN）
├── stocking_advice.csv               # 餐饮备货建议明细
├── stocking_advice.xlsx              # 备货计划Excel版
├── anomalies.csv                     # 异常清单
├── reports/
│   ├── 异常清单.csv
│   ├── 异常清单.xlsx
│   ├── 复跑说明.md
│   └── 小时级明细_数据字典.xlsx
└── visualizations/
    ├── kpi_linked_dashboard.html     # 联动看板（核心）
    ├── heatmap_est_people_flow.html  # 客流热力图
    ├── heatmap_total_revenue.html    # 营收热力图
    ├── heatmap_utilization_small.html
    ├── heatmap_queue_pressure_score.html
    ├── heatmap_complaint_risk_score.html
    ├── category_contribution.html    # 品类贡献
    ├── complaint_risk_analysis.html  # 投诉风险
    ├── energy_service_analysis.html  # 能源服务
    ├── stocking_advice_heatmap.html  # 备货建议
    └── weather_impact_analysis.html  # 天气影响
```

---

## 六、版本与追溯

- **分析引擎版本**: v1.0.0
- **配置文件**: `config/config.yaml`
- **校正审计报告**: `data/input/cleaning_report.csv`
- **随机种子**: 固定 seed=42（确保结果可复现）

---

*本说明文档由系统自动生成，复跑时请确保 `data/raw/` 目录包含完整原始数据*
"""
        path = os.path.join(self.output_dir, "复跑说明.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(rerun_doc)
        logger.info(f"复跑说明已保存至: {path}")
        return rerun_doc

    def generate_hourly_detail_export(self, hourly_df):
        logger.info("导出小时级明细...")
        if hourly_df is None or hourly_df.empty:
            return pd.DataFrame()

        export_cols = [c for c in hourly_df.columns if not c.startswith("zones_")]
        export_df = hourly_df[export_cols].copy()
        export_df["hour"] = pd.to_datetime(export_df["hour"]).dt.strftime("%Y-%m-%d %H:%M")

        col_rename = {
            "hour": "时段",
            "total_vehicles": "总车流量",
            "small_vehicles": "小型车数",
            "large_vehicles": "大型车数",
            "est_people_flow": "预估客流",
            "occupied_small": "占用小车泊位",
            "occupied_large": "占用大车泊位",
            "utilization_small": "小车泊位利用率",
            "utilization_large": "大车泊位利用率",
            "congestion_level": "拥堵等级",
            "restaurant_revenue": "餐饮收入(元)",
            "restaurant_orders": "餐饮订单数",
            "restaurant_conversion": "餐饮转化率",
            "convenience_revenue": "便利店收入(元)",
            "convenience_transactions": "便利店交易数",
            "convenience_conversion": "便利店转化率",
            "gas_revenue": "加油收入(元)",
            "gas_transactions": "加油交易数",
            "gas_liters": "加油升数",
            "charging_revenue": "充电收入(元)",
            "charging_sessions": "充电会话数",
            "charging_kwh": "充电电量(kWh)",
            "total_revenue": "总收入(元)",
            "overall_conversion": "整体转化率",
            "avg_spend_per_person": "人均消费(元)",
            "sessions": "充电活跃会话数",
            "utilization_rate": "充电桩利用率",
            "avg_wait_min": "充电平均等待(分)",
            "active_chargers": "活跃充电桩数",
            "queue_pressure_score": "排队压力总分",
            "queue_pressure_level": "排队压力等级",
            "restaurant_queue_p95_min": "餐饮P95排队(分)",
            "charging_wait_p95_min": "充电P95等待(分)",
            "complaint_count": "投诉数",
            "complaint_risk_score": "投诉风险分",
            "risk_level": "风险等级",
            "temperature_c": "气温(°C)",
            "humidity_pct": "湿度(%)",
            "weather": "天气类型",
            "is_holiday": "是否节假日",
            "is_weekend": "是否周末",
            "holiday_name": "节假日名称",
        }
        export_df = export_df.rename(columns={k: v for k, v in col_rename.items() if k in export_df.columns})

        detail_path = os.path.join(self.output_dir, "服务区小时级明细.csv")
        export_df.to_csv(detail_path, index=False, encoding="utf-8-sig")

        dict_df = pd.DataFrame([
            {"字段名": cn, "原字段名": orig, "数据类型": str(export_df[cn].dtype),
             "说明": self._col_description(orig)}
            for orig, cn in col_rename.items() if orig in hourly_df.columns
        ])
        xlsx_path = os.path.join(self.output_dir, "小时级明细_数据字典.xlsx")
        with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
            export_df.to_excel(writer, index=False, sheet_name="小时级明细")
            dict_df.to_excel(writer, index=False, sheet_name="数据字典")

        logger.info(f"小时级明细: {len(export_df)} 行 × {len(export_df.columns)} 列")
        return export_df

    def _col_description(self, orig):
        desc = {
            "hour": "数据所属小时时段（向下取整到小时）",
            "total_vehicles": "通过服务区入口的车辆总数",
            "small_vehicles": "7座及以下小客车数量",
            "large_vehicles": "货车、大客车等大型车辆数量",
            "est_people_flow": "基于车辆数估算的客流人次（小车×1.5+大车×3）",
            "occupied_small": "小车泊位累计占用次数",
            "utilization_small": "小车泊位利用率=占用/总泊位200",
            "congestion_level": "拥堵程度分级：正常/偏高/拥堵/严重拥堵",
            "total_revenue": "餐饮+便利店+加油+充电的总收入",
            "overall_conversion": "所有付费交易数与客流的比率",
            "sessions": "开始充电的会话数量",
            "utilization_rate": "充电桩利用率=活跃桩数/20总台",
            "queue_pressure_score": "餐饮+卫生间+充电+加油排队综合加权分",
            "complaint_risk_score": "投诉数量×2+严重程度+未解决×3的加权分",
            "is_holiday": "是否法定节假日或调休工作日",
        }
        return desc.get(orig, "运营指标字段，请参考计算模块")

    def generate_summary_json(self, results, cleaned_data):
        hourly = results.get("hourly_master")
        anomalies = results.get("anomalies")
        summary = {}
        if hourly is not None and not hourly.empty:
            summary["period"] = {
                "start": hourly["hour"].min().strftime("%Y-%m-%d %H:%M"),
                "end": hourly["hour"].max().strftime("%Y-%m-%d %H:%M"),
                "hours": len(hourly),
                "days": hourly["hour"].dt.date.nunique(),
            }
            cols = ["est_people_flow", "total_vehicles", "total_revenue",
                   "restaurant_orders", "convenience_transactions", "charging_sessions",
                   "gas_transactions", "complaint_count"]
            for c in cols:
                if c in hourly.columns:
                    summary[c] = {
                        "total": float(hourly[c].sum()),
                        "avg": float(hourly[c].mean()),
                        "max": float(hourly[c].max()),
                        "max_at": hourly.loc[hourly[c].idxmax(), "hour"].strftime("%Y-%m-%d %H:%M") if not hourly.empty else "",
                    }
        if anomalies is not None:
            summary["anomalies"] = {
                "total_count": len(anomalies),
                "severity_breakdown": anomalies["severity"].value_counts().to_dict() if not anomalies.empty else {}
            }
        path = os.path.join(self.output_dir, "summary.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        logger.info(f"汇总JSON已生成")
        return summary

    def generate_all_reports(self, results, cleaned_data, cleaning_report, start_time, end_time):
        self.generate_anomaly_list(results.get("anomalies"), results.get("hourly_master"), cleaned_data)
        self.generate_rerun_specification(cleaning_report, start_time, end_time)
        self.generate_hourly_detail_export(results.get("hourly_master"))
        self.generate_summary_json(results, cleaned_data)
        logger.info("所有报表生成完毕")
