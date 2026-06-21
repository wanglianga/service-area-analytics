# 高速服务区客流与消费智能分析系统

基于 **Python + Pandas + Plotly + Dash** 的高速服务区一体化运营分析平台。实现从传感器数据校正、核心指标计算、联动可视化看板到异常清单与报表输出的全流程自动化。

---

## 原始需求

> 请用 Python、Pandas 和 Plotly 完成高速服务区客流与消费分析，输入车流、停车场、卫生间、餐饮、便利店、充电桩、加油、天气、节假日和投诉数据。分析要先校正传感器缺口、重复交易、跨日停留、大车小车分类、设备故障和临时封闭记录，计算服务区客流峰值、消费转化、排队压力、充电等待、餐饮备货、停车拥堵和投诉风险。输出联动看板、时段热力图、品类贡献、异常清单、复跑说明和服务区小时级明细，运营人员要能定位到具体位置与时段。
> 请修复高速服务区客流与消费分析系统的启动失败问题。当前 run_pipeline.py 在生成时段热力图时失败，原因是 src/visualizations.py 中多处 Plotly Heatmap colorbar=dict(..., titleside="right") 使用了 Plotly 6.8 不支持的 titleside 属性，导致全流程中断，Dash 看板不可访问。请移除或改写这些不兼容配置，确保 python run_pipeline.py --start 2026-05-01 --end 2026-06-15 和 Docker 启动均可完成数据生成、清洗、指标计算、可视化导出、报告生成并启动看板。修复后需要验证联动看板、时段热力图、品类贡献、异常清单、复跑说明和服务区小时级明细均可正常输出，运营人员能按具体位置与时段定位问题。

---

## 项目简介

本系统针对**京沪高速苏州服务区**场景，内置完整的模拟数据生成器（可直接替换为真实数据），支持以下核心能力：

### 🎯 六大分析维度
| 模块 | 说明 |
|------|------|
| **数据校正** | 传感器缺口修复、重复交易去重、跨日停留处理、大小车分类校准、设备故障识别、临时封闭标记 |
| **客流峰值** | 基于车辆数×换算系数估算小时级客流，自动识别早/午/晚高峰 |
| **消费转化** | 餐饮/便利店/加油/充电四大业态的转化率、客单价、品类贡献 |
| **排队压力** | 餐饮P95排队、卫生间等待、充电等待、加油排队综合评分（0-10级） |
| **停车拥堵** | 大小车泊位分区利用率、拥堵分级、周转率计算 |
| **投诉风险** | 投诉量×2 + 严重程度加权 + 未解决×3 的综合风险评分 |

### 📊 可视化与输出
- 🎨 **联动看板**：客流+营收双轴趋势、星期×时段热力图、停车利用率、收入构成、充电等待、排队压力（6大核心图表）
- 🔥 **5张时段热力图**：客流、营收、停车利用率、排队压力、投诉风险
- 🏪 **品类贡献分析**：餐饮品类营收+TOP销量、便利店品类占比+TOP SKU
- ⚡ **能源服务分析**：充电量+营收、充电桩分时利用率、油品分布、加油交易趋势
- 🍽️ **餐饮备货建议**：分品类×时段备货热力图（P95 × 110% 建议量）
- 🌤️ **天气影响分析**：不同天气下客流/营收对比、气温-转化率散点+趋势线
- ⚠️ **异常清单**：含日期、时段、位置、类型、阈值、严重程度、处理建议
- 📋 **小时级明细**：50+指标列，支持运营按位置与时段精确定位

---

## 启动方式

### 前置要求

- **Python** ≥ 3.10（推荐 3.12.x，系统已验证 3.12.10）
- **Docker** ≥ 24.0（推荐，一键启动首选）
- **Docker Compose** ≥ 2.20
- 内存 ≥ 4GB，磁盘可用空间 ≥ 2GB

### 启动步骤

> 优先推荐 **Docker 一键启动**（下方章节），本方式适合本地开发与调试。

#### 1. 安装依赖

```bash
cd d:\code\solocoder-0608-wl\wl-405
pip install -r requirements.txt
```

预计安装包：pandas、numpy、plotly、flask、dash、dash-bootstrap-components、flask-cors、openpyxl。

#### 2. 启动服务（全流程）

```bash
python run_pipeline.py
```

将依次执行：**生成模拟数据 → 数据校正 → 指标计算 → 可视化 → 报表生成 → 启动 Dash 看板**。

如需自定义分析日期范围：

```bash
python run_pipeline.py --start 2026-05-01 --end 2026-06-15
```

其他参数：
| 参数 | 说明 |
|------|------|
| `--skip-data` | 跳过原始数据生成（直接使用已有的 `data/raw/`） |
| `--no-dashboard` | 只运行分析，不启动 Web 看板 |
| `--port 8050` | 指定看板端口（默认 8050） |

访问地址：**http://localhost:8050**

---

## Docker 一键启动（推荐）

### 前置要求
- 已安装 Docker 与 Docker Compose
- 宿主机 8050 端口未被占用

### 启动步骤

#### 1. 构建并启动

```bash
cd d:\code\solocoder-0608-wl\wl-405
docker compose up --build
```

**后台运行：**
```bash
docker compose up --build -d
```

Docker Compose 会自动：
1. 构建 Python 3.12 镜像并安装依赖
2. 生成 2026-05-01 至 2026-06-15 的全量模拟数据
3. 执行数据校正 → 指标计算 → 可视化 → 报表全流程
4. 在 **http://localhost:8050** 启动交互式 Dash 看板
5. 挂载 `data/` 与 `config/` 目录到宿主机，数据持久化

#### 2. 查看服务状态与日志

```bash
docker compose logs -f service-area-analytics
```

#### 3. 停止与清理

```bash
docker compose down
```

如需清理数据卷：
```bash
docker compose down -v
```

#### 4. 验证 Docker 配置

```bash
docker compose config
```

---

## 访问与功能说明

看板启动后，访问 **http://localhost:8050**，提供以下运营功能：

### 🎛️ 顶部筛选栏
- **日期范围**：日期选择器，可自由缩小或扩大分析窗口
- **时段滑块**：0-23 小时范围筛选，重点关注早晚高峰
- **异常模式**：全部时段 / 仅异常时段 / 排除异常时段
- **重置按钮**：一键恢复默认筛选

### 📈 核心图表区（支持联动）
1. **客流趋势与营收走势**：双Y轴叠加，直观展现客流-营收相关性
2. **时段×星期热力图**：颜色深浅代表客流强度，早/午/晚高峰有标注线
3. **停车利用率曲线**：大小车分色叠加，85%警戒线自动标注
4. **收入构成+转化率**：饼图展示四业态占比，柱状图看各时段转化
5. **充电桩双轴**：利用率柱+等待时间折线，定位峰值矛盾
6. **排队压力指数**：综合压力+餐饮P95+充电P95三线叠加，颜色预警

### ⚠️ 异常清单表
- 按严重程度排序（严重→高→中→低），带条件格式着色
- 支持筛选与排序，含**具体位置**、**时段**、**观测值**、**阈值**、**处理建议**

### 📋 小时级明细表
- 50+ 指标列，支持原生**排序**、**筛选**、**搜索**
- 拥堵/排队/风险三列自动条件格式（高风险高亮红/橙/紫色）
- **CSV 导出按钮**：一键下载当前筛选结果

---

## 目录结构

```
wl-405/
├── run_pipeline.py                # 主入口：一键全流程
├── requirements.txt               # Python 依赖清单
├── config/
│   └── config.yaml               # 服务区容量、峰值时段等配置
├── src/
│   ├── data_generator.py          # [步骤1] 11类模拟数据生成器
│   ├── data_cleaner.py            # [步骤2] 6类数据校正逻辑
│   ├── metrics_calculator.py      # [步骤3] 7大核心指标计算+异常检测
│   ├── visualizations.py          # [步骤4] Plotly 12张图表生成
│   ├── report_generator.py        # [步骤5] 异常清单/复跑说明/明细导出
│   └── dashboard_app.py           # [步骤6] Dash 交互式看板应用
├── data/
│   ├── raw/                       # 11份原始CSV（模拟或真实）
│   ├── input/                     # 校正后数据 + cleaning_report.csv
│   └── output/
│       ├── service_area_hourly_detail.csv   # 小时级主表（50+指标）
│       ├── daily_summary.csv                 # 日汇总
│       ├── stocking_advice.csv/.xlsx         # 备货建议
│       ├── anomalies.csv                     # 异常清单
│       ├── reports/
│       │   ├── 异常清单.csv/.xlsx
│       │   ├── 复跑说明.md
│       │   ├── 服务区小时级明细.csv
│       │   └── 小时级明细_数据字典.xlsx
│       └── visualizations/                   # 12张 HTML/PNG 图表
│           ├── kpi_linked_dashboard.html     # ★核心联动看板
│           ├── heatmap_*.html (5张)
│           ├── category_contribution.html
│           ├── complaint_risk_analysis.html
│           ├── energy_service_analysis.html
│           ├── stocking_advice_heatmap.html
│           └── weather_impact_analysis.html
├── Dockerfile
├── docker-compose.yml
├── .dockerignore
├── .gitignore
└── README.md
```

---

## 真实数据接入说明

将 `data/raw/` 目录下的 11 个 CSV 文件替换为真实数据即可，字段命名需保持与 `复跑说明.md` 一致。

**最小接入步骤：**
1. 按字段规范准备 CSV（文件名与列名一致）
2. 放入 `data/raw/`
3. 执行：`python run_pipeline.py --skip-data`

如需修改容量参数，编辑 `config/config.yaml`（泊位/充电桩/座位数等）。

---

## 技术栈

| 层次 | 选型 | 版本 |
|------|------|------|
| 语言 | Python | 3.12 |
| 数据处理 | Pandas + NumPy | 2.x |
| 静态图表 | Plotly | 5.18+ |
| 交互看板 | Dash + Bootstrap | 2.16+ |
| 报表导出 | openpyxl | 3.1+ |
| 容器化 | Docker / Compose | 24+ |
| 配置文件 | YAML | — |

---

*© 2026 高速服务区智能分析系统 · All rights reserved.*
