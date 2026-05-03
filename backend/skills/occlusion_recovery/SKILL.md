---
name: occlusion_recovery
description: 遮挡严重或高风险阶段采用恢复策略。
tags: 遮挡, 恢复, recovery, 高风险
---
适用场景：高风险热点集中、连续高风险窗口多、重试触发概率高。
建议：启用 recovery-ready 模式，提高候选预算和 retry 阈值容忍度，允许三步扩展。
重点指标：高风险比例、重试轮数、弱分离历元占比。
目标：尽快恢复可用输出，降低连续失锁影响。
