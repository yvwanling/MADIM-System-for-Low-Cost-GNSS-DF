# GNSS 导航 Agent 系统 v2 设计说明

## 1. 为什么第二版要重构

第一版虽然把流程拆成了多个“Agent”文件，但本质上仍然是固定顺序的函数流水线：

- 主程序固定地先调质量模块
- 再调策略模块
- 再调候选解模块
- 再调完整性模块

这更像“算法模块化调用”，而不是“多智能体协同决策”。

第二版因此进行了重构：

- 引入 Supervisor Agent 负责动态路由
- 引入共享黑板（blackboard）保存中间状态
- 每个 Agent 自带工具列表，而不是主流程直接调用函数
- Agent 可以根据当前状态选择工具，失败后可以回退或重试
- 前端增加 Agent 执行轨迹和追问机制，用户可直接看到真正的 Agent 协同过程

## 2. 多智能体架构

### 2.1 Supervisor Agent

职责：

- 决定当前阶段交给哪个 Agent
- 在完整性不足时触发重试
- 控制工作流的推进与回退

### 2.2 Ingestion Agent

职责：

- 判断文件是否为 NMEA 文本
- 调用 NMEA 解析工具生成历元序列
- 输出数据集摘要

### 2.3 Quality Control Agent

职责：

- 计算历元质量分数
- 标记异常历元
- 给出全局质量等级和主导问题

### 2.4 Strategy Agent

职责：

- 根据质量等级和重试轮数选择策略
- 设置候选解数量
- 设置搜索半径
- 设置时序保持强度
- 设置重试门限

### 2.5 Ambiguity Resolution Agent

职责：

- 生成候选解集合
- 在低质量或重试场景下触发三步搜索扩展
- 输出候选分离度信息

### 2.6 Integrity Agent

职责：

- 应用动态阈值与基线约束
- 估计置信度
- 判断是否需要重新规划策略并重试

### 2.7 Continuity Agent

职责：

- 执行时序保持
- 平滑航向
- 检测航向跳变

### 2.8 Explanation Agent

职责：

- 汇总多 Agent 的结论
- 用大模型生成解释文本
- 回答用户对当前分析的追问
- 可选调用高德逆地理编码给出位置语义说明

## 3. 工具调用机制

所有工具统一注册在 `backend/app/tools/navigation_tools.py` 中。

### 核心工具来自哪里

#### 本地 Python 工具

它们来自论文思路的工程化封装：

- 数据接入与摘要
- 质量控制
- 策略选择
- 候选解生成
- 动态阈值与基线约束
- 连续性平滑
- 报告整理

#### 外部 API 工具

- 阿里云百炼：用于 Agent 规划与解释
- 高德 Web 服务：仅用于可选的语义位置增强

## 4. 共享黑板设计

共享黑板中保存以下关键信息：

- `request`
- `dataset`
- `raw_epochs`
- `quality_report`
- `strategy_report`
- `ambiguity_report`
- `integrity_report`
- `continuity_report`
- `optional_context`
- `warnings`
- `agent_trace`
- `retry_round`

每个 Agent 只关心自己需要读写的字段。

## 5. 核心工作流

1. Supervisor 路由到 Ingestion Agent
2. Ingestion Agent 调用数据接入工具
3. Quality Control Agent 调用质量控制工具
4. Strategy Agent 生成求解策略
5. Supervisor 决定进入模糊度搜索阶段
6. Ambiguity Resolution Agent 调用候选解工具
7. Integrity Agent 评估可信度并给出是否重试
8. 如果需要重试，Supervisor 回退到 Strategy Agent
9. 否则进入 Continuity Agent
10. 最后由 Explanation Agent 输出报告

## 6. 与 hello-agents 旅行规划项目的对应关系

旅游项目中：

- Supervisor / Planner 负责路由
- 景点、天气、酒店 Agent 负责获取事实
- Planner Agent 负责整合输出

导航项目中：

- Supervisor Agent 负责路由和重试
- Ingestion / Quality / Strategy / Ambiguity / Integrity / Continuity Agent 负责专业事实与决策
- Explanation Agent 负责对外解释和交互

因此第二版已经不再是简单函数拆分，而是真正采用了“多个角色各自使用工具并交接结果”的多智能体模式。
