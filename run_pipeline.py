"""
高速服务区客流与消费分析 · 主入口流水线
一键执行：数据生成 → 数据校正 → 指标计算 → 可视化 → 报表 → 看板启动
"""
import os
import sys
import argparse
import time
from datetime import datetime, timedelta
import logging
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)


def main():
    parser = argparse.ArgumentParser(description="高速服务区客流与消费分析系统")
    parser.add_argument("--start", default="2026-05-01", help="分析开始日期 YYYY-MM-DD")
    parser.add_argument("--end", default="2026-06-15", help="分析结束日期 YYYY-MM-DD")
    parser.add_argument("--skip-data", action="store_true", help="跳过原始数据生成（使用已有 data/raw/）")
    parser.add_argument("--no-dashboard", action="store_true", help="不启动交互式看板")
    parser.add_argument("--port", type=int, default=8050, help="看板端口号")
    args = parser.parse_args()

    start_date = datetime.strptime(args.start, "%Y-%m-%d")
    end_date = datetime.strptime(args.end, "%Y-%m-%d")

    pipeline_start = datetime.now()
    logger.info("=" * 70)
    logger.info("    京沪高速苏州服务区 · 客流与消费智能分析系统")
    logger.info(f"    分析周期：{args.start} ~ {args.end}")
    logger.info("=" * 70)

    # ── Step 1: 数据生成 ──────────────────────────────────────────
    step_start = time.time()
    if not args.skip_data:
        logger.info("\n[1/6] 生成模拟原始数据...")
        from src.data_generator import ServiceAreaDataGenerator
        gen = ServiceAreaDataGenerator(start_date=start_date, end_date=end_date)
        gen.generate_all()
        logger.info(f"    ✅ 数据生成完成 ({time.time()-step_start:.1f}s)")
    else:
        logger.info("\n[1/6] 跳过数据生成，使用已有原始数据")
        raw_dir = os.path.join(BASE_DIR, "data", "raw")
        files = os.listdir(raw_dir) if os.path.isdir(raw_dir) else []
        if not files:
            logger.warning(f"    ⚠️ data/raw/ 目录为空，建议移除 --skip-data 参数")

    # ── Step 2: 数据校正 ──────────────────────────────────────────
    step_start = time.time()
    logger.info("\n[2/6] 执行数据校正（传感器缺口/重复/跨日/分类/故障/封闭）...")
    from src.data_cleaner import DataCleaner
    cleaner = DataCleaner(input_dir=os.path.join(BASE_DIR, "data", "raw"),
                         output_dir=os.path.join(BASE_DIR, "data", "input"))
    cleaned_data, cleaning_report = cleaner.clean_all()
    logger.info(f"    ✅ 数据校正完成，执行 {len(cleaning_report)} 项校正操作 ({time.time()-step_start:.1f}s)")

    # ── Step 3: 指标计算 ──────────────────────────────────────────
    step_start = time.time()
    logger.info("\n[3/6] 计算核心运营指标...")
    from src.metrics_calculator import MetricsCalculator
    calc = MetricsCalculator(output_dir=os.path.join(BASE_DIR, "data", "output"))
    results = calc.calculate_all(cleaned_data)
    logger.info(f"    ✅ 指标计算完成 ({time.time()-step_start:.1f}s)")
    if not results.get("hourly_master", pd.DataFrame()).empty:
        hm = results["hourly_master"]
        logger.info(f"    📊 小时主表：{len(hm)} 行 × {len(hm.columns)} 列")
        if "total_revenue" in hm.columns:
            logger.info(f"    💰 累计营收：¥{hm['total_revenue'].sum():,.2f}")
        if "est_people_flow" in hm.columns:
            logger.info(f"    👥 累计客流：{int(hm['est_people_flow'].sum()):,} 人次")
    anomalies = results.get("anomalies")
    if anomalies is not None and not anomalies.empty:
        logger.info(f"    ⚠️ 检测到 {len(anomalies)} 条异常记录")

    # ── Step 4: 可视化图表 ────────────────────────────────────────
    step_start = time.time()
    logger.info("\n[4/6] 生成 Plotly 可视化图表...")
    from src.visualizations import ServiceAreaVisualizer
    viz = ServiceAreaVisualizer(output_dir=os.path.join(BASE_DIR, "data", "output", "visualizations"))
    figs = viz.generate_all(results, cleaned_data)
    logger.info(f"    ✅ 可视化生成完成，{len(figs)} 张图表 ({time.time()-step_start:.1f}s)")
    for name in list(figs.keys())[:5]:
        logger.info(f"    🖼️  {name}")
    if len(figs) > 5:
        logger.info(f"    ... 以及其余 {len(figs)-5} 张")

    # ── Step 5: 报表输出 ──────────────────────────────────────────
    step_start = time.time()
    logger.info("\n[5/6] 生成运营报表（异常清单/复跑说明/小时明细）...")
    from src.report_generator import ReportGenerator
    rep = ReportGenerator(output_dir=os.path.join(BASE_DIR, "data", "output", "reports"))
    rep.generate_all_reports(results, cleaned_data, cleaning_report, start_date, end_date)
    logger.info(f"    ✅ 报表输出完成 ({time.time()-step_start:.1f}s)")

    total_duration = datetime.now() - pipeline_start
    logger.info("\n" + "=" * 70)
    logger.info("    🎉 全流程分析完成！")
    logger.info(f"    总耗时：{total_duration.total_seconds():.2f} 秒")
    logger.info("=" * 70)

    outputs = [
        ("data/output/service_area_hourly_detail.csv", "小时级明细主表（含50+指标）"),
        ("data/output/anomalies.csv", "异常清单（运营预警）"),
        ("data/output/visualizations/kpi_linked_dashboard.html", "联动看板HTML（核心）"),
        ("data/output/reports/复跑说明.md", "复跑说明文档"),
        ("data/output/reports/服务区小时级明细.csv", "面向运营的中文明细"),
        ("data/output/reports/异常清单.xlsx", "异常清单Excel版"),
    ]
    logger.info("\n📁 关键输出文件：")
    for fpath, desc in outputs:
        full = os.path.join(BASE_DIR, fpath)
        exists = "✅" if os.path.exists(full) else "⚠️"
        logger.info(f"  {exists} {desc}")
        logger.info(f"     → {fpath}")

    # ── Step 6: 启动看板 ──────────────────────────────────────────
    if not args.no_dashboard:
        logger.info(f"\n[6/6] 启动 Dash 交互式看板服务 (端口 {args.port})...")
        logger.info(f"    🌐 访问地址：http://localhost:{args.port}")
        logger.info("    按 Ctrl+C 停止服务")
        try:
            from src.dashboard_app import ServiceAreaDashboard
            dash_app = ServiceAreaDashboard(data_dir=os.path.join(BASE_DIR, "data", "output"))
            dash_app.run(port=args.port, debug=False)
        except KeyboardInterrupt:
            logger.info("\n    用户手动停止看板服务")
    else:
        logger.info("\n[6/6] 跳过看板启动（--no-dashboard）")
        logger.info(f"    可随时启动：python run_pipeline.py --skip-data")


if __name__ == "__main__":
    main()
