# GNSS 导航 Agent 系统 v2

这是一个面向低成本 GNSS 测向与完好性监测的多智能体原型系统。

与第一版相比，这一版不再是“函数顺序流水线”，而是改造成了真正的 **Supervisor + 多专业 Agent + 工具注册表 + 共享黑板** 架构：

- Supervisor Agent：决定流程路由、是否重试、重试后交给谁。
- Ingestion Agent：识别文件、解析 NMEA、生成历元输入。
- Quality Control Agent：做质量评估与异常历元检测。
- Strategy Agent：根据质量状态和重试轮数选择导航模式、候选解预算、时序保持强度。
- Ambiguity Resolution Agent：调用候选解生成与三步搜索工具。
- Integrity Agent：调用动态阈值与基线约束工具，估计置信度并决定是否重试。
- Continuity Agent：做时序保持、平滑与航向跳变检测。
- Explanation Agent：生成总报告与追问回答，可选调用高德逆地理编码增强语义位置描述。

## 一、目录结构

```text
backend/
  app/
    agents/            # 多智能体实现
    api/               # FastAPI 接口
    core/              # 配置
    models/            # Pydantic schema
    services/          # LLM 与 NMEA 解析服务
    tools/             # 工具注册表与本地/外部工具
frontend/
  index.html           # 纯前端页面
  app.js               # 前端逻辑
  style.css            # 样式
  server.py            # 本地静态服务
scripts/
  run_functional_test.py
backend/tests/
  test_pipeline.py
```

## 二、运行环境

推荐环境：

- Python 3.11
- PyCharm
- Windows 10/11

本项目前端采用纯 HTML/CSS/JS，不需要 Node.js。

## 三、创建虚拟环境

### 方式 A：命令行创建（推荐）

在项目根目录执行：

```bash
py -3.11 -m venv .venv
```

激活环境：

```bash
.venv\Scripts\activate
```

### 方式 B：PyCharm 创建解释器

1. `File -> Settings -> Project -> Python Interpreter`
2. 点击 `Add Interpreter`
3. 选择 `Virtualenv`
4. Base interpreter 选你的 Python 3.11
5. 位置建议为项目根目录下的 `.venv`

> 不要用一个已经激活的 `venv` 去创建同名 `venv`，否则会出现 `Permission denied ...\venv\Scripts\python.exe`。

## 四、安装依赖

进入后端目录：

```bash
cd backend
pip install -r requirements.txt
```

## 五、配置 `.env`

复制模板：

```bash
copy .env.example .env
```

至少先配置阿里云百炼：

```env
LLM_MODEL_ID=qwen3-max
LLM_API_KEY=你的阿里云 API Key
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

如果你还想让 Explanation Agent 使用高德逆地理编码来解释数据集中心位置，再补：

```env
AMAP_WEB_KEY=你的高德 Web 服务 Key
```

> 未配置 `AMAP_WEB_KEY` 时，不影响核心导航 Agent 流程。

## 六、启动后端

在 `backend` 目录执行：

```bash
python run.py
```

看到类似输出后表示成功：

```text
Uvicorn running on http://0.0.0.0:8000
```

## 七、启动前端

新开一个终端，进入 `frontend` 目录：

```bash
cd frontend
python server.py
```

浏览器打开：

```text
http://localhost:5173
```

## 八、系统使用方式

### 1. 分析内置样例

- 选择左侧数据集
- 设置基线长度和初始候选解数量
- 勾选 `启用阿里云大模型 Agent 规划与解释`
- 点击 `分析内置样例`

### 2. 上传自己的 NMEA 数据

- 主文件上传 `.nmea / .txt / .log` 文本格式 NMEA 文件
- 第二个文件可上传参考 GGA 文件
- 点击 `上传并分析`

### 3. 追问解释 Agent

先完成一次分析，再在左侧输入追问，例如：

- 为什么这次系统触发了重试？
- 为什么质量等级是 poor？
- 为什么采用 retry recovery mode？

然后点击 `让解释 Agent 回答`

## 九、工具来自哪里

本项目中的工具分为两类。

### A. 本地 Python 工具（核心）

这些工具全部位于 `backend/app/tools/navigation_tools.py`，不依赖外部 API：

- `detect_file_format`
- `parse_nmea_dataset`
- `summarize_dataset`
- `compute_quality_metrics`
- `detect_outlier_epochs`
- `classify_quality_state`
- `choose_navigation_mode`
- `configure_candidate_budget`
- `configure_retry_policy`
- `generate_lambda_candidates`
- `score_candidate_separation`
- `expand_three_step_candidates`
- `apply_dynamic_baseline_constraint`
- `estimate_confidence`
- `assess_retry_need`
- `apply_temporal_hold`
- `smooth_heading_series`
- `detect_heading_jumps`
- `compile_report_payload`

这些是整个导航 Agent 项目的核心工具来源。

### B. 外部 API 工具（可选）

#### 1）阿里云百炼

用途：

- 让 Agent 真的“规划工具调用”而不是只走规则回退
- 让 Explanation Agent 生成更自然的专业解释
- 让 Follow-up 问答更加像真正的智能体交互

项目接入方式：OpenAI 兼容接口。

#### 2）高德逆地理编码（可选）

用途：

- 让 Explanation Agent 把轨迹中心位置解释成人能读懂的位置描述
- 不参与 GNSS 核心数值解算，只做语义增强

## 十、Agent 真正如何调用工具

项目中的每个 Agent 都继承自 `BaseAgent`。

Agent 执行过程为：

1. 读取共享黑板中的当前状态
2. 获取自己可用的工具列表
3. 若启用了阿里云大模型，则用 LLM 生成 JSON 计划
4. 若未启用或失败，则走 `fallback_plan`
5. 调用工具注册表执行工具
6. 将结果写回共享黑板
7. 记录 `agent_trace`
8. 把任务交给下一个 Agent

所以当前版本的核心不是“主函数直接顺序调函数”，而是：

- Agent 决定调用哪些工具
- 工具通过注册表执行
- 结果写入共享黑板
- Supervisor 决定是否继续、是否回退、是否重试

## 十一、功能测试

### 1. 运行自动化功能测试

在项目根目录执行：

```bash
python scripts/run_functional_test.py
```

测试报告会输出到：

```text
docs/functional_test_report.json
```

### 2. 运行后端单元测试

在项目根目录执行：

```bash
python -m pytest backend/tests/test_pipeline.py
```

## 十二、停止项目

- 停止后端：在后端终端按 `Ctrl + C`
- 停止前端：在前端终端按 `Ctrl + C`

## 十三、常见问题

### 1. `Permission denied ...\venv\Scripts\python.exe`

这是因为你正在使用旧 `venv` 的 Python 去创建同名 `venv` 环境。

解决方式：

- 不要再重复创建同名环境
- 直接使用已有环境安装依赖
- 或者重新创建一个不同名字的环境，例如 `.venv`

### 2. `npm 不是内部或外部命令`

本项目前端不需要 Node.js。直接在 `frontend` 目录运行：

```bash
python server.py
```

### 3. 上传文件后分析失败

请先确认文件是纯文本 NMEA 文件，打开后能看到大量以 `$` 开头的语句，例如：

```text
$GPGGA,...
$GPRMC,...
$GPVTG,...
```

## 十四、建议的使用顺序

1. 先跑内置样例，确认前后端都能通
2. 再配置阿里云百炼，开启真正的 LLM Agent 规划
3. 然后上传你自己的 NMEA 数据
4. 最后再配置高德 `AMAP_WEB_KEY` 体验语义位置增强
