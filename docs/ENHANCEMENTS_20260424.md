# 2026-04-24 增强说明

本次在原 GNSS Navigation Agent System v2 基础上新增：

1. **风险感知轨迹回放与热点解释**
   - 轨迹 payload 新增 `hotspots`、`collection_advice`
   - 前端地图新增风险热点列表、热点点击解释、采集建议面板
   - 风险热点基于中高风险、低置信度与跳变窗口自动聚合

2. **场景策略规划功能**
   - 新增 `ScenarioPlanningAgent`
   - 新增 `/api/navigation/plan-scenario` 接口
   - 用户可输入目标，系统输出建议策略模式、候选解数量、搜索半径、hold 强度、重试阈值、是否启用恢复模式、解释与采集建议

3. **参考 Agent 规范增强（对应 hello-agents 章节）**
   - s03 Todo/Workflow：新增执行流程看板 `workflow`
   - s05 Skill Loading：新增 `backend/skills/*/SKILL.md` GNSS 技能包与 `NavigationSkillLoader`
   - s10 Protocols：新增重试决策的 request-response 风格 `protocol_log`

说明：本次增强保持 GNSS 核心解算链路的确定性，新增 Agent/Skill/Protocol 主要用于策略组织、结果解释与交互增强。
