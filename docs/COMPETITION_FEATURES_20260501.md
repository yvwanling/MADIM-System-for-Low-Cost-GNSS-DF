# 复赛增强功能说明（2026-05-01）

本版本在前一版 GNSS 多智能体导航分析系统的基础上，新增四类面向复赛评分维度的功能，重点提升“完整性与价值、创新性、技术实现性”。

## 1. 多策略对比实验台

新增接口：`POST /api/navigation/compare-strategies`

前端入口：左侧“运行多策略对比实验台”。

能力说明：

- 对同一数据集比较四类策略：精度优先、平衡稳健、连续性优先、遮挡恢复。
- 输出固定率、平均置信度、高风险点数、重试轮数、主导策略、综合分和推荐结论。
- 为复赛现场稳定性，采用“一次基础分析 + 确定性策略仿真评估”的方式，避免单请求内重复解析大文件造成等待。

## 2. 异常窗口深挖诊断 Agent

新增 Agent：`HotspotDiagnosticAgent`

新增接口：`POST /api/navigation/diagnose-hotspot`

前端入口：风险热点详情中的“深挖诊断该热点”。

能力说明：

- 以用户选中的风险热点为局部窗口。
- 自动提取平均置信度、质量分数、卫星数、候选分离度、跳变次数、基线误差与动态阈值等证据。
- 输出诊断原因、处理建议和建议策略参数。
- 保持核心证据来自本地工具链，LLM 仅作为可选解释增强。

## 3. 一键报告导出

新增接口：`POST /api/navigation/export-report`

前端入口：左侧“导出分析报告 HTML”。

能力说明：

- 生成可下载的 HTML 分析报告。
- 报告包含数据集信息、核心指标、关键发现、风险热点、下一次采集建议、执行流程、协议日志和 Agent 执行链。
- 用于形成完整交付闭环：数据输入 → Agent 分析 → 风险定位 → 策略建议 → 报告导出。

## 4. 演示模式与样例评测面板

新增接口：`POST /api/navigation/evaluate-samples`

前端入口：

- “一键演示完整流程”：自动加载内置样例，完成分析并生成场景策略规划。
- “一键样例评测”：对内置样例进行轻量确定性评测，展示多数据集稳定性。

能力说明：

- 演示模式用于复赛现场快速展示完整流程。
- 样例评测面板输出每个数据集的历元数、估计固定率、平均置信度、风险热点数和推荐策略。
- 轻量评测不替代完整分析链路，而是作为现场稳定演示与工程可信度补充。

## 修改文件概览

后端：

- `backend/app/api/routes/navigation.py`
- `backend/app/agents/orchestrator.py`
- `backend/app/agents/diagnostic_agent.py`
- `backend/app/models/schemas.py`
- `backend/app/tools/navigation_tools.py`

前端：

- `frontend/index.html`
- `frontend/app.js`
- `frontend/style.css`

## 验证建议

启动后端：

```bash
cd backend
python run.py
```

启动前端：

```bash
cd frontend
python server.py
```

浏览器访问：

```text
http://localhost:5173
```

推荐演示顺序：

1. 点击“一键演示完整流程”。
2. 展开风险热点列表，选择一个热点，点击“深挖诊断该热点”。
3. 点击“运行多策略对比实验台”。
4. 点击“一键样例评测”。
5. 点击“导出分析报告 HTML”。
