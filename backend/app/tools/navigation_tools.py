from __future__ import annotations

import hashlib
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

import requests

from app.core.config import PROCESSED_DATA_DIR, SKILLS_DIR, settings
from app.skills.skill_loader import NavigationSkillLoader
from app.services.nmea_parser import EpochRecord, NMEAParser


ToolFn = Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]


@dataclass
class ToolSpec:
    name: str
    source: str
    description: str
    fn: ToolFn


class ToolRegistry:
    def __init__(self) -> None:
        self.parser = NMEAParser()
        self.skill_loader = NavigationSkillLoader(SKILLS_DIR)
        self._tools: Dict[str, ToolSpec] = {}
        for spec in self._build_specs():
            self._tools[spec.name] = spec

    def _build_specs(self) -> List[ToolSpec]:
        return [
            ToolSpec("detect_file_format", "local-python", "检测文件是否为 NMEA 文本并统计语句类型。", self.detect_file_format),
            ToolSpec("parse_nmea_dataset", "local-python", "解析 NMEA 日志为历元序列。", self.parse_nmea_dataset),
            ToolSpec("summarize_dataset", "local-python", "汇总数据集时间跨度、有效历元与观测统计。", self.summarize_dataset),
            ToolSpec("compute_quality_metrics", "local-python", "计算历元质量分数与全局质量指标。", self.compute_quality_metrics),
            ToolSpec("detect_outlier_epochs", "local-python", "检测低卫星数、高 HDOP、低 CN0 等异常历元。", self.detect_outlier_epochs),
            ToolSpec("classify_quality_state", "local-python", "给出质量等级和主导问题。", self.classify_quality_state),
            ToolSpec("choose_navigation_mode", "local-python", "根据质量、重试轮数和用户约束选择求解模式。", self.choose_navigation_mode),
            ToolSpec("configure_candidate_budget", "local-python", "根据策略设置候选解数量、搜索半径和时序保持强度。", self.configure_candidate_budget),
            ToolSpec("configure_retry_policy", "local-python", "配置重试策略与回退阈值。", self.configure_retry_policy),
            ToolSpec("generate_lambda_candidates", "local-python", "生成每个历元的候选模糊度解集合。", self.generate_lambda_candidates),
            ToolSpec("score_candidate_separation", "local-python", "评估候选解分离度和可疑历元比例。", self.score_candidate_separation),
            ToolSpec("expand_three_step_candidates", "local-python", "在低质量或重试场景下扩大候选搜索范围。", self.expand_three_step_candidates),
            ToolSpec("apply_dynamic_baseline_constraint", "local-python", "基于动态阈值和基线约束筛选候选解。", self.apply_dynamic_baseline_constraint),
            ToolSpec("estimate_confidence", "local-python", "根据质量、分离度和约束通过情况估计置信度。", self.estimate_confidence),
            ToolSpec("assess_retry_need", "local-python", "根据固定率和高风险比例判断是否重试。", self.assess_retry_need),
            ToolSpec("apply_temporal_hold", "local-python", "利用时序保持机制增强连续性。", self.apply_temporal_hold),
            ToolSpec("smooth_heading_series", "local-python", "平滑航向序列并检测突跳。", self.smooth_heading_series),
            ToolSpec("detect_heading_jumps", "local-python", "标注航向跳变。", self.detect_heading_jumps),
            ToolSpec("reverse_geocode_midpoint", "amap-webservice", "可选，调用高德逆地理编码获取数据集中心位置。", self.reverse_geocode_midpoint),
            ToolSpec("load_navigation_skills", "local-skill-loader", "按场景目标加载 GNSS 导航技能包。", self.load_navigation_skills),
            ToolSpec("plan_analysis_strategy", "local-python", "根据目标与历史风险轨迹规划分析/解算策略。", self.plan_analysis_strategy),
            ToolSpec("recommend_collection_actions", "local-python", "结合风险热点给出下一次采集建议。", self.recommend_collection_actions),
            ToolSpec("build_trajectory_payload", "local-python", "构造前端地图展示、风险叠加、热点解释与轨迹回放所需数据。", self.build_trajectory_payload),
            ToolSpec("diagnose_hotspot_window", "local-python", "围绕选中风险热点提取局部证据并生成诊断建议。", self.diagnose_hotspot_window),
            ToolSpec("compile_report_payload", "local-python", "整理总结、轨迹、告警和工具来源供报告 Agent 使用。", self.compile_report_payload),
        ]

    def names(self) -> List[str]:
        return sorted(self._tools)

    def describe_tools(self, names: Iterable[str]) -> List[Dict[str, str]]:
        return [
            {
                "name": self._tools[name].name,
                "source": self._tools[name].source,
                "description": self._tools[name].description,
            }
            for name in names
            if name in self._tools
        ]

    def source_map(self) -> Dict[str, str]:
        return {name: spec.source for name, spec in self._tools.items()}

    def call(self, tool_name: str, arguments: Dict[str, Any], board: Dict[str, Any]) -> Dict[str, Any]:
        if tool_name not in self._tools:
            raise KeyError(f"Unknown tool: {tool_name}")
        return self._tools[tool_name].fn(arguments, board)

    def detect_file_format(self, arguments: Dict[str, Any], board: Dict[str, Any]) -> Dict[str, Any]:
        file_path = Path(arguments["file_path"])
        return self.parser.detect_file_format(file_path)

    def parse_nmea_dataset(self, arguments: Dict[str, Any], board: Dict[str, Any]) -> Dict[str, Any]:
        file_path = Path(arguments["file_path"])
        reference_path = Path(arguments["reference_path"]) if arguments.get("reference_path") else None
        epochs = self.parser.parse_file(file_path, reference_path=reference_path)
        processed_csv = PROCESSED_DATA_DIR / f"{board['dataset']['name']}_processed.csv"
        self.parser.write_processed_csv(epochs, processed_csv)
        board["raw_epochs"] = epochs
        board["processed_csv"] = str(processed_csv)
        return {
            "epoch_count": len(epochs),
            "processed_csv": str(processed_csv),
        }

    def summarize_dataset(self, arguments: Dict[str, Any], board: Dict[str, Any]) -> Dict[str, Any]:
        epochs: List[EpochRecord] = board.get("raw_epochs", [])
        summary = self.parser.summarize_dataset(epochs)
        return summary

    def _quality_score(self, epoch: EpochRecord) -> float:
        sats = float(epoch.sats_used or epoch.total_sats_in_view or 0)
        hdop = float(epoch.hdop or 5.0)
        cn0 = float(epoch.avg_cn0 or 25.0)
        error_m = float(epoch.horizontal_error_m or 0.0)
        score = 0.0
        score += min(sats / 18.0, 1.0) * 0.35
        score += max(0.0, min((3.5 - min(hdop, 3.5)) / 3.5, 1.0)) * 0.25
        score += max(0.0, min((cn0 - 18.0) / 25.0, 1.0)) * 0.20
        score += max(0.0, 1.0 - min(error_m / 12.0, 1.0)) * 0.10
        score += 0.10 if epoch.course_deg is not None else 0.0
        return round(max(0.0, min(score, 1.0)), 4)

    def compute_quality_metrics(self, arguments: Dict[str, Any], board: Dict[str, Any]) -> Dict[str, Any]:
        epochs: List[EpochRecord] = board.get("raw_epochs", [])
        per_epoch: List[Dict[str, Any]] = []
        sats_hist: List[float] = []
        hdop_hist: List[float] = []
        quality_scores: List[float] = []
        for epoch in epochs:
            score = self._quality_score(epoch)
            per_epoch.append(
                {
                    "timestamp": epoch.timestamp,
                    "quality_score": score,
                    "sats_metric": float(epoch.sats_used or epoch.total_sats_in_view or 0),
                    "hdop": float(epoch.hdop or 5.0),
                    "avg_cn0": float(epoch.avg_cn0 or 25.0),
                    "horizontal_error_m": float(epoch.horizontal_error_m or 0.0),
                }
            )
            quality_scores.append(score)
            if epoch.sats_used or epoch.total_sats_in_view:
                sats_hist.append(float(epoch.sats_used or epoch.total_sats_in_view or 0))
            if epoch.hdop is not None:
                hdop_hist.append(float(epoch.hdop))
        board["quality_per_epoch"] = per_epoch
        return {
            "mean_quality_score": round(sum(quality_scores) / float(len(quality_scores) or 1), 4),
            "min_quality_score": round(min(quality_scores), 4) if quality_scores else 0.0,
            "max_quality_score": round(max(quality_scores), 4) if quality_scores else 0.0,
            "avg_satellite_count": round(sum(sats_hist) / float(len(sats_hist) or 1), 4) if sats_hist else 0.0,
            "avg_hdop": round(sum(hdop_hist) / float(len(hdop_hist) or 1), 4) if hdop_hist else None,
            "epoch_count": len(epochs),
        }

    def detect_outlier_epochs(self, arguments: Dict[str, Any], board: Dict[str, Any]) -> Dict[str, Any]:
        per_epoch = board.get("quality_per_epoch", [])
        outliers: List[Dict[str, Any]] = []
        for idx, item in enumerate(per_epoch):
            reasons: List[str] = []
            if item["sats_metric"] < 6:
                reasons.append("satellite_count_low")
            if item["hdop"] > 3.0:
                reasons.append("hdop_high")
            if item["avg_cn0"] < 24.0:
                reasons.append("cn0_low")
            if item["quality_score"] < 0.35:
                reasons.append("quality_score_low")
            if reasons:
                outliers.append({"index": idx, "timestamp": item["timestamp"], "reasons": reasons})
        board["outlier_epochs"] = outliers
        return {
            "outlier_count": len(outliers),
            "outlier_ratio": round(len(outliers) / float(len(per_epoch) or 1), 4),
            "sample_outliers": outliers[:5],
        }

    def classify_quality_state(self, arguments: Dict[str, Any], board: Dict[str, Any]) -> Dict[str, Any]:
        metrics = board.get("quality_metrics", {})
        outlier_ratio = board.get("quality_outliers", {}).get("outlier_ratio", 0.0)
        score = float(metrics.get("mean_quality_score", 0.0))
        issues: List[str] = []
        if float(metrics.get("avg_satellite_count", 0.0)) < 8:
            issues.append("卫星数量偏少")
        if metrics.get("avg_hdop") is not None and float(metrics["avg_hdop"]) > 2.5:
            issues.append("几何构型较差")
        if outlier_ratio > 0.25:
            issues.append("异常历元占比较高")
        if score >= 0.75:
            level = "excellent"
        elif score >= 0.55:
            level = "good"
        elif score >= 0.35:
            level = "fair"
        else:
            level = "poor"
        if not issues:
            issues.append("观测状态总体稳定")
        return {
            "quality_level": level,
            "dominant_issues": issues,
            "mean_quality_score": score,
        }

    def choose_navigation_mode(self, arguments: Dict[str, Any], board: Dict[str, Any]) -> Dict[str, Any]:
        request = board["request"]
        override = board.get("strategy_override") or request.get("strategy_override") or {}
        if override.get("model_choice"):
            return {
                "model_choice": str(override["model_choice"]),
                "reason": str(override.get("reason", "多策略对比实验台指定策略覆盖默认模式选择。")),
                "requested_candidate_count": int(request["candidate_count"]),
                "strategy_override_name": override.get("name"),
            }
        quality_report = board.get("quality_report", {})
        retry_round = board.get("retry_round", 0)
        score = float(quality_report.get("mean_quality_score", 0.0))
        if score >= 0.7:
            mode = "multi_gnss_precision"
            reason = "观测质量较高，优先使用多系统精细模式。"
        elif score >= 0.45:
            mode = "conservative_tracking"
            reason = "观测质量中等，采用保守跟踪模式并提高候选解预算。"
        else:
            mode = "degraded_monitoring"
            reason = "观测质量较差，进入退化监测模式，以稳健输出为主。"
        if retry_round > 0 and mode != "multi_gnss_precision":
            mode = "retry_recovery_mode"
            reason = "上一轮完整性不足，切换到恢复模式扩大搜索并放宽阈值。"
        return {
            "model_choice": mode,
            "reason": reason,
            "requested_candidate_count": int(request["candidate_count"]),
        }

    def configure_candidate_budget(self, arguments: Dict[str, Any], board: Dict[str, Any]) -> Dict[str, Any]:
        request = board["request"]
        override = board.get("strategy_override") or request.get("strategy_override") or {}
        mode = board.get("strategy_report", {}).get("model_choice", "conservative_tracking")
        retry_round = board.get("retry_round", 0)
        base = int(request["candidate_count"])
        if override.get("candidate_count"):
            candidate_count = int(override.get("candidate_count", base))
            search_radius_deg = float(override.get("search_radius_deg", 10.0))
            hold_strength = float(override.get("hold_strength", override.get("temporal_hold_strength", 0.60)))
            enable_three_step = bool(override.get("enable_three_step", True))
            profile = f"{mode}|n={candidate_count}|radius={search_radius_deg:.1f}"
            return {
                "candidate_count": candidate_count,
                "search_radius_deg": search_radius_deg,
                "hold_strength": hold_strength,
                "enable_three_step": enable_three_step,
                "strategy_profile": profile,
            }
        if mode == "multi_gnss_precision":
            candidate_count = max(base, 6 + retry_round * 2)
            search_radius_deg = 6.0
            hold_strength = 0.72
            enable_three_step = False
        elif mode == "conservative_tracking":
            candidate_count = max(base + 3, 10 + retry_round * 3)
            search_radius_deg = 10.0
            hold_strength = 0.60
            enable_three_step = True
        elif mode == "retry_recovery_mode":
            candidate_count = min(max(base + 8, 16 + retry_round * 4), 40)
            search_radius_deg = 16.0
            hold_strength = 0.55
            enable_three_step = True
        else:
            candidate_count = min(max(base + 5, 12), 30)
            search_radius_deg = 18.0
            hold_strength = 0.50
            enable_three_step = True
        profile = f"{mode}|n={candidate_count}|radius={search_radius_deg:.1f}"
        return {
            "candidate_count": int(candidate_count),
            "search_radius_deg": float(search_radius_deg),
            "hold_strength": float(hold_strength),
            "enable_three_step": bool(enable_three_step),
            "strategy_profile": profile,
        }

    def configure_retry_policy(self, arguments: Dict[str, Any], board: Dict[str, Any]) -> Dict[str, Any]:
        override = board.get("strategy_override") or board.get("request", {}).get("strategy_override") or {}
        if override.get("retry_policy"):
            policy = dict(override["retry_policy"])
            policy.setdefault("max_retry_rounds", settings.max_retry_rounds)
            return policy
        mode = board.get("strategy_report", {}).get("model_choice", "conservative_tracking")
        if mode == "multi_gnss_precision":
            min_fix_rate = 0.88
            max_high_risk_ratio = 0.25
        elif mode == "retry_recovery_mode":
            min_fix_rate = 0.82
            max_high_risk_ratio = 0.35
        else:
            min_fix_rate = 0.85
            max_high_risk_ratio = 0.30
        return {
            "min_fix_rate": min_fix_rate,
            "max_high_risk_ratio": max_high_risk_ratio,
            "max_retry_rounds": settings.max_retry_rounds,
        }

    def _stable_noise(self, token: str) -> float:
        digest = hashlib.md5(token.encode("utf-8")).hexdigest()
        return int(digest[:8], 16) / 0xFFFFFFFF

    def generate_lambda_candidates(self, arguments: Dict[str, Any], board: Dict[str, Any]) -> Dict[str, Any]:
        epochs: List[EpochRecord] = board.get("raw_epochs", [])
        per_epoch_quality: List[Dict[str, Any]] = board.get("quality_per_epoch", [])
        strategy = board.get("strategy_report", {})
        baseline_length = float(board["request"]["baseline_length_m"])
        candidate_count = int(strategy["candidate_count"])
        search_radius = float(strategy["search_radius_deg"])
        results: List[Dict[str, Any]] = []
        for idx, epoch in enumerate(epochs):
            quality_score = per_epoch_quality[idx]["quality_score"] if idx < len(per_epoch_quality) else 0.4
            hdop = float(epoch.hdop or 3.0)
            cn0 = float(epoch.avg_cn0 or 25.0)
            sats = max(float(epoch.sats_used or epoch.total_sats_in_view or 1), 1.0)
            posterior_sigma = max(0.003, (hdop / sats) * 0.8 + max(0.0, 35.0 - cn0) / 100.0)
            dynamic_threshold = max(0.008, posterior_sigma * 0.9)
            spread = search_radius * (1.15 - quality_score) + 1.5
            base_heading = epoch.heading_proxy_deg if epoch.heading_proxy_deg is not None else 0.0
            candidates: List[Dict[str, Any]] = []
            for cidx in range(candidate_count):
                u = self._stable_noise(f"{epoch.timestamp}-{board['retry_round']}-{cidx}")
                offset = (u - 0.5) * spread
                baseline_error = abs((0.5 - u) * dynamic_threshold * (2.1 - quality_score) + cidx * 0.0012 * (1.0 - quality_score))
                residual = abs(offset) * (1.0 + (1.0 - quality_score)) + cidx * 0.02 + (0.6 if quality_score < 0.3 else 0.0)
                candidates.append(
                    {
                        "index": cidx + 1,
                        "heading_deg": (base_heading + offset) % 360.0,
                        "baseline_error_m": round(baseline_error, 6),
                        "residual_score": round(residual, 6),
                        "baseline_estimate_m": round(baseline_length + (u - 0.5) * dynamic_threshold, 6),
                    }
                )
            candidates.sort(key=lambda item: item["residual_score"])
            separation = round(candidates[1]["residual_score"] - candidates[0]["residual_score"], 6) if len(candidates) > 1 else 0.0
            results.append(
                {
                    "timestamp": epoch.timestamp,
                    "posterior_sigma_m": round(posterior_sigma, 6),
                    "dynamic_threshold_m": round(dynamic_threshold, 6),
                    "candidates": candidates,
                    "separation_score": separation,
                }
            )
        board["candidate_results"] = results
        return {
            "epoch_count": len(results),
            "candidate_count": candidate_count,
            "mean_threshold_m": round(sum(item["dynamic_threshold_m"] for item in results) / float(len(results) or 1), 6),
        }

    def score_candidate_separation(self, arguments: Dict[str, Any], board: Dict[str, Any]) -> Dict[str, Any]:
        candidate_results = board.get("candidate_results", [])
        seps = [float(item["separation_score"]) for item in candidate_results]
        weak = [item for item in candidate_results if float(item["separation_score"]) < 0.12]
        return {
            "mean_separation": round(sum(seps) / float(len(seps) or 1), 6),
            "weak_epoch_ratio": round(len(weak) / float(len(candidate_results) or 1), 4),
            "weak_epoch_count": len(weak),
        }

    def expand_three_step_candidates(self, arguments: Dict[str, Any], board: Dict[str, Any]) -> Dict[str, Any]:
        if not board.get("strategy_report", {}).get("enable_three_step"):
            return {"expanded": False, "epoch_count": len(board.get("candidate_results", []))}
        updated: List[Dict[str, Any]] = []
        for item in board.get("candidate_results", []):
            candidates = list(item["candidates"])
            if float(item["separation_score"]) < 0.14 and candidates:
                best = candidates[0]
                for extra_idx, extra_delta in enumerate([-4.0, -2.0, 2.0, 4.0], start=1):
                    u = self._stable_noise(f"expand-{item['timestamp']}-{extra_idx}-{board['retry_round']}")
                    candidates.append(
                        {
                            "index": len(candidates) + 1,
                            "heading_deg": (float(best["heading_deg"]) + extra_delta + (u - 0.5) * 1.5) % 360.0,
                            "baseline_error_m": round(float(best["baseline_error_m"]) * (0.9 + extra_idx * 0.03), 6),
                            "residual_score": round(float(best["residual_score"]) + 0.12 + extra_idx * 0.03, 6),
                            "baseline_estimate_m": float(best["baseline_estimate_m"]),
                        }
                    )
                candidates.sort(key=lambda row: row["residual_score"])
                item = dict(item)
                item["candidates"] = candidates
                item["separation_score"] = round(candidates[1]["residual_score"] - candidates[0]["residual_score"], 6) if len(candidates) > 1 else item["separation_score"]
            updated.append(item)
        board["candidate_results"] = updated
        return {
            "expanded": True,
            "epoch_count": len(updated),
        }

    def apply_dynamic_baseline_constraint(self, arguments: Dict[str, Any], board: Dict[str, Any]) -> Dict[str, Any]:
        results: List[Dict[str, Any]] = []
        strategy = board.get("strategy_report", {})
        threshold_scale = 1.05 if strategy.get("model_choice") == "retry_recovery_mode" else 1.0
        for idx, item in enumerate(board.get("candidate_results", [])):
            selected = item["candidates"][0]
            threshold = float(item["dynamic_threshold_m"]) * threshold_scale
            for candidate in item["candidates"]:
                if float(candidate["baseline_error_m"]) <= threshold:
                    selected = candidate
                    break
            results.append(
                {
                    "timestamp": item["timestamp"],
                    "selected_candidate": selected,
                    "dynamic_threshold_m": round(threshold, 6),
                    "posterior_sigma_m": item["posterior_sigma_m"],
                    "separation_score": item["separation_score"],
                    "candidate_count": len(item["candidates"]),
                }
            )
        board["integrity_candidates"] = results
        passed = sum(1 for item in results if float(item["selected_candidate"]["baseline_error_m"]) <= float(item["dynamic_threshold_m"]))
        return {
            "passed_count": passed,
            "epoch_count": len(results),
            "pass_ratio": round(passed / float(len(results) or 1), 4),
        }

    def estimate_confidence(self, arguments: Dict[str, Any], board: Dict[str, Any]) -> Dict[str, Any]:
        per_epoch_quality = board.get("quality_per_epoch", [])
        selected_candidates = board.get("integrity_candidates", [])
        epoch_results: List[Dict[str, Any]] = []
        risk_counter: Counter[str] = Counter()
        fix_success_count = 0
        for idx, item in enumerate(selected_candidates):
            quality_score = per_epoch_quality[idx]["quality_score"] if idx < len(per_epoch_quality) else 0.3
            selected = item["selected_candidate"]
            threshold = float(item["dynamic_threshold_m"])
            separation = float(item["separation_score"])
            fix_success = quality_score >= 0.42 and float(selected["baseline_error_m"]) <= threshold
            confidence = max(
                0.05,
                min(
                    0.99,
                    quality_score * 0.52
                    + min(separation / 0.25, 1.0) * 0.18
                    + (0.22 if fix_success else 0.04)
                    + (0.07 if selected["index"] == 1 else 0.0),
                ),
            )
            if confidence >= 0.82:
                risk = "low"
            elif confidence >= 0.62:
                risk = "medium"
            else:
                risk = "high"
            if fix_success:
                fix_success_count += 1
            risk_counter[risk] += 1
            epoch_results.append(
                {
                    "timestamp": item["timestamp"],
                    "confidence": round(confidence, 4),
                    "fix_success": fix_success,
                    "risk": risk,
                    "selected_candidate": selected,
                    "dynamic_threshold_m": threshold,
                    "separation_score": separation,
                    "posterior_sigma_m": item["posterior_sigma_m"],
                    "candidate_count": item["candidate_count"],
                }
            )
        board["integrity_results"] = epoch_results
        return {
            "fix_rate": round(fix_success_count / float(len(epoch_results) or 1), 4),
            "risk_distribution": dict(risk_counter),
            "high_risk_ratio": round(risk_counter.get("high", 0) / float(len(epoch_results) or 1), 4),
        }

    def assess_retry_need(self, arguments: Dict[str, Any], board: Dict[str, Any]) -> Dict[str, Any]:
        integrity = board.get("integrity_report", {})
        retry_policy = board.get("strategy_retry_policy", {})
        retry_round = board.get("retry_round", 0)
        need_retry = (
            float(integrity.get("fix_rate", 0.0)) < float(retry_policy.get("min_fix_rate", 0.85))
            or float(integrity.get("high_risk_ratio", 0.0)) > float(retry_policy.get("max_high_risk_ratio", 0.30))
        )
        if retry_round >= int(retry_policy.get("max_retry_rounds", settings.max_retry_rounds)):
            need_retry = False
        return {
            "need_retry": need_retry,
            "reason": (
                "固定率或高风险比例未达标，建议扩大搜索并重新求解。"
                if need_retry
                else "当前完整性满足要求，无需重试。"
            ),
        }

    def apply_temporal_hold(self, arguments: Dict[str, Any], board: Dict[str, Any]) -> Dict[str, Any]:
        integrity_results = board.get("integrity_results", [])
        hold_strength = float(board.get("strategy_report", {}).get("hold_strength", 0.6))
        held: List[Dict[str, Any]] = []
        prev_heading: Optional[float] = None
        for item in integrity_results:
            selected_heading = float(item["selected_candidate"]["heading_deg"])
            if prev_heading is None:
                held_heading = selected_heading
            elif not item["fix_success"]:
                held_heading = prev_heading
            else:
                delta = ((selected_heading - prev_heading + 540.0) % 360.0) - 180.0
                held_heading = (prev_heading + hold_strength * delta) % 360.0
            prev_heading = held_heading
            held.append({**item, "held_heading_deg": round(held_heading, 4)})
        board["held_results"] = held
        return {"epoch_count": len(held), "hold_strength": hold_strength}

    def smooth_heading_series(self, arguments: Dict[str, Any], board: Dict[str, Any]) -> Dict[str, Any]:
        held_results = board.get("held_results", [])
        smoothed: List[Dict[str, Any]] = []
        prev: Optional[float] = None
        for item in held_results:
            current = float(item["held_heading_deg"])
            confidence = float(item["confidence"])
            if prev is None:
                value = current
            else:
                alpha = 0.25 if confidence < 0.60 else 0.45 if confidence < 0.80 else 0.68
                delta = ((current - prev + 540.0) % 360.0) - 180.0
                value = (prev + alpha * delta) % 360.0
            prev = value
            smoothed.append({**item, "smoothed_heading_deg": round(value, 4)})
        board["smoothed_results"] = smoothed
        return {"epoch_count": len(smoothed)}

    def detect_heading_jumps(self, arguments: Dict[str, Any], board: Dict[str, Any]) -> Dict[str, Any]:
        smoothed = board.get("smoothed_results", [])
        jump_count = 0
        previous: Optional[float] = None
        annotated: List[Dict[str, Any]] = []
        for item in smoothed:
            value = float(item["smoothed_heading_deg"])
            if previous is None:
                jump = False
            else:
                delta = abs(((value - previous + 540.0) % 360.0) - 180.0)
                jump = delta > 35.0
            if jump:
                jump_count += 1
            previous = value
            annotated.append({**item, "jump_detected": jump})
        board["final_epoch_results"] = annotated
        return {"jump_count": jump_count, "jump_ratio": round(jump_count / float(len(annotated) or 1), 4)}

    def reverse_geocode_midpoint(self, arguments: Dict[str, Any], board: Dict[str, Any]) -> Dict[str, Any]:
        if not settings.amap_web_key:
            return {"enabled": False, "reason": "AMAP_WEB_KEY 未配置。"}
        epochs: List[EpochRecord] = board.get("raw_epochs", [])
        coords = [(e.latitude, e.longitude) for e in epochs if e.latitude is not None and e.longitude is not None]
        if not coords:
            return {"enabled": False, "reason": "无有效经纬度。"}
        lat = sum(item[0] for item in coords) / len(coords)
        lon = sum(item[1] for item in coords) / len(coords)
        url = "https://restapi.amap.com/v3/geocode/regeo"
        response = requests.get(
            url,
            params={
                "key": settings.amap_web_key,
                "location": f"{lon:.6f},{lat:.6f}",
                "output": "JSON",
                "extensions": "base",
            },
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        if str(data.get("status")) != "1":
            return {"enabled": False, "reason": data.get("info", "逆地理编码失败")}
        return {
            "enabled": True,
            "formatted_address": data.get("regeocode", {}).get("formatted_address"),
            "midpoint": {"latitude": round(lat, 6), "longitude": round(lon, 6)},
        }


    def load_navigation_skills(self, arguments: Dict[str, Any], board: Dict[str, Any]) -> Dict[str, Any]:
        goal = str(arguments.get("goal") or board.get("scenario_goal") or "")
        selected = self.skill_loader.match(goal)
        payload = self.skill_loader.get_payload(selected)
        board["loaded_skills"] = payload
        return payload

    def _infer_scene_tags(self, goal: str, board: Dict[str, Any]) -> List[str]:
        goal_text = (goal or "").lower()
        tags: List[str] = []
        trajectory = board.get("optional_context", {}).get("trajectory", {})
        hotspots = trajectory.get("hotspots", [])
        high_hotspots = [h for h in hotspots if h.get("risk") == "high"]
        avg_speed = board.get("summary_payload", {}).get("avg_speed_knots") or 0.0
        if "城市峡谷" in goal or "urban" in goal_text or "遮挡" in goal or high_hotspots:
            tags.append("occlusion")
        if "连续性" in goal or "跳变" in goal or any(h.get("jump_count", 0) > 0 for h in hotspots):
            tags.append("continuity")
        if "开阔" in goal or "精度" in goal or "precision" in goal_text:
            tags.append("precision")
        if "动态" in goal or "稳健" in goal or avg_speed and float(avg_speed) > 8:
            tags.append("dynamic")
        if not tags:
            tags.append("balanced")
        return tags

    def plan_analysis_strategy(self, arguments: Dict[str, Any], board: Dict[str, Any]) -> Dict[str, Any]:
        goal = str(arguments.get("goal") or board.get("scenario_goal") or "")
        tags = self._infer_scene_tags(goal, board)
        trajectory = board.get("optional_context", {}).get("trajectory", {})
        hotspots = trajectory.get("hotspots", [])
        high_count = sum(1 for h in hotspots if h.get("risk") == "high")
        jump_count = sum(int(h.get("jump_count", 0)) for h in hotspots)
        low_sat_hotspots = sum(1 for h in hotspots if any("卫星数量偏低" in reason for reason in h.get("reasons", [])))
        if "precision" in tags and "continuity" not in tags and high_count == 0:
            mode = "precision_first"
            candidate_count = 6
            search_radius_deg = 6.0
            hold_strength = 0.42
            retry = {"min_fix_rate": 0.92, "max_high_risk_ratio": 0.22, "max_retry_rounds": settings.max_retry_rounds}
            recovery = False
            rationale_points = ["目标强调精度与开阔场景。", "历史风险热点较少，可收紧搜索半径。", "降低 hold 强度有助于保留精细变化。"]
        elif "occlusion" in tags or low_sat_hotspots > 0 or high_count >= 2 or jump_count > 2 or "continuity" in tags:
            mode = "continuity_first"
            candidate_count = 12 if high_count < 4 else 14
            search_radius_deg = 12.0 if jump_count < 4 else 14.0
            hold_strength = 0.84
            retry = {"min_fix_rate": 0.82, "max_high_risk_ratio": 0.18, "max_retry_rounds": settings.max_retry_rounds + 1}
            recovery = True
            rationale_points = ["历史轨迹存在明显风险热点或遮挡特征。", "优先连续性与抗跳变，因此提高候选解数量与 hold 强度。", "启用恢复模式便于在弱分离区段重新锁定。"]
        elif "dynamic" in tags:
            mode = "balanced_robust"
            candidate_count = 10
            search_radius_deg = 10.0
            hold_strength = 0.72
            retry = {"min_fix_rate": 0.86, "max_high_risk_ratio": 0.28, "max_retry_rounds": settings.max_retry_rounds}
            recovery = True
            rationale_points = ["目标强调动态载体稳健输出。", "适度增大候选预算有助于降低机动场景误判。", "提高 hold 强度可抑制高速转向中的跳变。"]
        else:
            mode = "balanced_navigation"
            candidate_count = 8
            search_radius_deg = 8.0
            hold_strength = 0.60
            retry = {"min_fix_rate": 0.88, "max_high_risk_ratio": 0.25, "max_retry_rounds": settings.max_retry_rounds}
            recovery = True
            rationale_points = ["当前目标未明显偏向精度或连续性，采用平衡模式。", "使用中等搜索半径和候选预算，以兼顾精度、稳定性和效率。"]
        plan = {
            "recommended_mode": mode,
            "candidate_count": int(candidate_count),
            "search_radius_deg": float(search_radius_deg),
            "temporal_hold_strength": float(hold_strength),
            "retry_thresholds": retry,
            "enable_recovery_mode": bool(recovery),
            "scene_tags": tags,
            "rationale_points": rationale_points,
            "hotspot_references": [
                f"{item.get('title')}（{item.get('start_timestamp')} - {item.get('end_timestamp')}）" for item in hotspots[:3]
            ],
        }
        board["scenario_strategy_plan"] = plan
        return plan

    def recommend_collection_actions(self, arguments: Dict[str, Any], board: Dict[str, Any]) -> Dict[str, Any]:
        trajectory = board.get("optional_context", {}).get("trajectory", {})
        hotspots = trajectory.get("hotspots", [])
        advice: List[str] = []
        for hotspot in hotspots[:4]:
            title = hotspot.get("title", "热点区段")
            if hotspot.get("jump_count", 0) > 0:
                advice.append(f"{title} 检测到跳变，建议下一次采集在该区段减速或补采，并优先 continuity-first。")
            elif any("卫星数量偏低" in reason for reason in hotspot.get("reasons", [])):
                advice.append(f"{title} 卫星可见性偏低，建议避开高楼遮挡侧或延长采样时长。")
            else:
                advice.append(f"{title} 存在持续风险，建议提前启用恢复模式并提高候选预算。")
        if not advice:
            advice = ["历史轨迹未发现显著热点，建议继续使用 balanced_navigation 并保留一次恢复重试。"]
        if any(h.get("risk") == "high" for h in hotspots):
            advice.append("高风险区段较集中，建议下次采集优先避开高楼密集或急转弯区域。")
        board.setdefault("scenario_strategy_plan", {})["collection_advice"] = advice[:5]
        return {"collection_advice": advice[:5]}

    def _build_hotspots_from_points(self, points: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        def is_hot(point: Dict[str, Any]) -> bool:
            return point.get("risk") in {"high", "medium"} or point.get("jump_detected") or float(point.get("confidence", 0.0)) < 0.62

        groups: List[List[Dict[str, Any]]] = []
        current: List[Dict[str, Any]] = []
        for point in points:
            if is_hot(point):
                if current and point["epoch_index"] == current[-1]["epoch_index"] + 1:
                    current.append(point)
                else:
                    if current:
                        groups.append(current)
                    current = [point]
            else:
                if current:
                    groups.append(current)
                    current = []
        if current:
            groups.append(current)

        hotspots: List[Dict[str, Any]] = []
        for idx, group in enumerate(groups, start=1):
            if len(group) == 1 and group[0].get("risk") == "medium" and not group[0].get("jump_detected"):
                continue
            risk_counter = Counter(point.get("risk", "unknown") for point in group)
            dominant_risk = "high" if risk_counter.get("high", 0) else "medium"
            avg_conf = round(sum(float(point.get("confidence", 0.0)) for point in group) / len(group), 4)
            avg_quality = round(sum(float(point.get("quality_score", 0.0)) for point in group) / len(group), 4)
            avg_sats = round(sum(float(point.get("satellite_count", 0)) for point in group) / len(group), 2)
            jump_count = sum(1 for point in group if point.get("jump_detected"))
            length_m = 0.0
            for prev, curr in zip(group[:-1], group[1:]):
                length_m += self.parser._haversine_m(prev["latitude"], prev["longitude"], curr["latitude"], curr["longitude"])
            max_err = max(float(point.get("baseline_error_m", 0.0)) for point in group)
            max_threshold = max(float(point.get("dynamic_threshold_m", 0.0)) for point in group)
            reasons: List[str] = []
            if avg_sats < 7.0:
                reasons.append("卫星数量偏低")
            if avg_quality < 0.55:
                reasons.append("观测质量偏低")
            if jump_count > 0:
                reasons.append("存在航向跳变")
            if risk_counter.get("high", 0) / len(group) >= 0.5:
                reasons.append("连续高风险历元占比较高")
            if max_err > max(max_threshold * 1.05, 0.02):
                reasons.append("基线误差接近或超过动态阈值")
            if not reasons:
                reasons.append("局部置信度下降")
            severity_score = round(min(1.0, 0.38 * (1 if dominant_risk == "high" else 0.6) + 0.32 * (1 - avg_conf) + 0.15 * min(jump_count / 3.0, 1.0) + 0.15 * max(0.0, (7.0 - avg_sats) / 7.0)), 4)
            recommendation = (
                "建议减速并采用 continuity-first，必要时补采该区段。" if jump_count > 0
                else "建议提高候选预算并关注遮挡区域，可考虑 recovery 模式。"
            )
            lat = round(sum(point["latitude"] for point in group) / len(group), 7)
            lon = round(sum(point["longitude"] for point in group) / len(group), 7)
            title = f"热点 {idx}｜{dominant_risk} 风险"
            hotspots.append({
                "id": f"hotspot_{idx}",
                "title": title,
                "risk": dominant_risk,
                "severity_score": severity_score,
                "start_timestamp": group[0]["timestamp"],
                "end_timestamp": group[-1]["timestamp"],
                "center": {"latitude": lat, "longitude": lon},
                "point_start_index": group[0]["seq"],
                "point_end_index": group[-1]["seq"],
                "avg_confidence": avg_conf,
                "avg_quality_score": avg_quality,
                "avg_satellite_count": avg_sats,
                "jump_count": jump_count,
                "length_m": round(length_m, 2),
                "dominant_strategy": Counter(point.get("strategy_profile", "unknown") for point in group).most_common(1)[0][0],
                "reasons": reasons,
                "explanation": f"{title} 从 {group[0]['timestamp']} 持续到 {group[-1]['timestamp']}，平均置信度 {avg_conf:.2f}，主要原因：{'、'.join(reasons)}。",
                "recommendation": recommendation,
            })
        return hotspots

    def _build_collection_advice(self, hotspots: List[Dict[str, Any]]) -> List[str]:
        advice: List[str] = []
        if not hotspots:
            return ["本次轨迹未出现显著风险热点，下一次采集可继续使用 balanced_navigation，并保留默认一次重试。"]
        if any(item.get("jump_count", 0) > 0 for item in hotspots):
            advice.append("存在跳变热点，建议在对应区段减速、增加采样时长，并优先 continuity-first。")
        if any(any("卫星数量偏低" in reason for reason in item.get("reasons", [])) for item in hotspots):
            advice.append("部分高风险区段卫星可见性不足，建议避开高楼遮挡侧或改用更开阔路线补采。")
        if sum(1 for item in hotspots if item.get("risk") == "high") >= 2:
            advice.append("高风险热点较集中，建议下次采集启用恢复模式并提升候选解预算。")
        focus = hotspots[:3]
        if focus:
            labels = [f"{item.get('title')}（{item.get('start_timestamp')}~{item.get('end_timestamp')}）" for item in focus]
            advice.append("重点关注区段：" + "；".join(labels))
        return advice[:5]

    def build_trajectory_payload(self, arguments: Dict[str, Any], board: Dict[str, Any]) -> Dict[str, Any]:
        epochs: List[EpochRecord] = board.get("raw_epochs", [])
        final_epoch_results = board.get("final_epoch_results", [])
        quality_per_epoch = board.get("quality_per_epoch", [])
        strategy_report = board.get("strategy_report", {})
        default_strategy = strategy_report.get("strategy_profile", "unknown")
        default_model = strategy_report.get("model_choice", "unknown")
        points: List[Dict[str, Any]] = []
        total_distance_m = 0.0
        last_valid = None

        def color_for_risk(risk: str) -> str:
            mapping = {
                "low": "#10b981",
                "medium": "#f59e0b",
                "high": "#ef4444",
                "unknown": "#64748b",
            }
            return mapping.get(str(risk), "#64748b")

        for idx, epoch in enumerate(epochs):
            if epoch.latitude is None or epoch.longitude is None:
                continue
            final = final_epoch_results[idx] if idx < len(final_epoch_results) else {}
            selected = final.get("selected_candidate", {})
            quality = quality_per_epoch[idx] if idx < len(quality_per_epoch) else {}
            point = {
                "seq": len(points),
                "epoch_index": idx,
                "timestamp": epoch.timestamp,
                "latitude": round(float(epoch.latitude), 7),
                "longitude": round(float(epoch.longitude), 7),
                "altitude_m": float(epoch.altitude_m) if epoch.altitude_m is not None else None,
                "speed_knots": float(epoch.speed_knots) if epoch.speed_knots is not None else None,
                "course_deg": float(epoch.course_deg) if epoch.course_deg is not None else None,
                "heading_raw_deg": float(selected.get("heading_deg")) if selected.get("heading_deg") is not None else None,
                "heading_smoothed_deg": float(final.get("smoothed_heading_deg")) if final.get("smoothed_heading_deg") is not None else None,
                "confidence": round(float(final.get("confidence", 0.0)), 4),
                "risk": str(final.get("risk", "unknown")),
                "risk_color": color_for_risk(str(final.get("risk", "unknown"))),
                "strategy_profile": str(final.get("strategy_profile", default_strategy)),
                "model_choice": str(final.get("model_choice", default_model)),
                "fix_success": bool(final.get("fix_success", False)),
                "jump_detected": bool(final.get("jump_detected", False)),
                "baseline_error_m": round(float(selected.get("baseline_error_m", 0.0)), 6),
                "dynamic_threshold_m": round(float(final.get("dynamic_threshold_m", 0.0)), 6),
                "quality_score": round(float(quality.get("quality_score", 0.0)), 4),
                "satellite_count": int(epoch.sats_used or epoch.total_sats_in_view or 0),
            }
            if last_valid is not None:
                total_distance_m += self.parser._haversine_m(last_valid["latitude"], last_valid["longitude"], point["latitude"], point["longitude"])
            last_valid = point
            points.append(point)

        segments: List[Dict[str, Any]] = []
        for idx in range(1, len(points)):
            prev = points[idx - 1]
            curr = points[idx]
            risk = curr["risk"] if curr["risk"] != "unknown" else prev["risk"]
            strategy = curr["strategy_profile"] or prev["strategy_profile"]
            segments.append({
                "seq": idx - 1,
                "path": [[prev["longitude"], prev["latitude"]], [curr["longitude"], curr["latitude"]]],
                "risk": risk,
                "color": color_for_risk(risk),
                "strategy_profile": strategy,
                "mean_confidence": round((prev["confidence"] + curr["confidence"]) / 2.0, 4),
                "jump_detected": bool(curr["jump_detected"]),
                "start_timestamp": prev["timestamp"],
                "end_timestamp": curr["timestamp"],
            })

        if points:
            min_lat = min(p["latitude"] for p in points)
            max_lat = max(p["latitude"] for p in points)
            min_lon = min(p["longitude"] for p in points)
            max_lon = max(p["longitude"] for p in points)
            center = {"latitude": round((min_lat + max_lat) / 2.0, 7), "longitude": round((min_lon + max_lon) / 2.0, 7)}
            bounds = {"southwest": [round(min_lon, 7), round(min_lat, 7)], "northeast": [round(max_lon, 7), round(max_lat, 7)]}
        else:
            center = None
            bounds = None

        hotspots = self._build_hotspots_from_points(points)
        collection_advice = self._build_collection_advice(hotspots)
        strategy_distribution = dict(Counter(p["strategy_profile"] for p in points))
        risk_distribution = dict(Counter(p["risk"] for p in points))
        trajectory = {
            "enabled": bool(points),
            "point_count": len(points),
            "points": points,
            "segments": segments,
            "hotspots": hotspots,
            "collection_advice": collection_advice,
            "start_point": points[0] if points else None,
            "end_point": points[-1] if points else None,
            "center": center,
            "bounds": bounds,
            "playback": {"default_interval_ms": 450, "max_index": max(len(points) - 1, 0), "initial_index": 0},
            "stats": {
                "track_length_m": round(total_distance_m, 2),
                "point_count": len(points),
                "segment_count": len(segments),
                "hotspot_count": len(hotspots),
                "high_risk_points": sum(1 for p in points if p["risk"] == "high"),
                "jump_points": sum(1 for p in points if p["jump_detected"]),
                "strategy_distribution": strategy_distribution,
                "risk_distribution": risk_distribution,
            },
        }
        board.setdefault("optional_context", {})["trajectory"] = trajectory
        return trajectory

    def diagnose_hotspot_window(self, arguments: Dict[str, Any], board: Dict[str, Any]) -> Dict[str, Any]:
        request = board.get("diagnosis_request", {})
        hotspot_id = str(arguments.get("hotspot_id") or request.get("hotspot_id") or "")
        trajectory = board.get("optional_context", {}).get("trajectory", {})
        hotspots = trajectory.get("hotspots", [])
        hotspot = next((item for item in hotspots if str(item.get("id")) == hotspot_id), None)
        if hotspot is None:
            return {
                "hotspot_id": hotspot_id,
                "title": "未找到热点",
                "diagnosis": "当前分析结果中没有匹配的风险热点，请先完成一次分析并选择热点列表中的项目。",
                "evidence": {},
                "recommendations": ["重新选择有效热点后再进行深挖诊断。"],
                "suggested_strategy": {"mode": "balanced_navigation"},
            }

        start_idx = int(hotspot.get("point_start_index", 0))
        end_idx = int(hotspot.get("point_end_index", start_idx))
        points = trajectory.get("points", [])
        window_points = [p for p in points if start_idx <= int(p.get("seq", -1)) <= end_idx]
        if not window_points:
            window_points = points[start_idx : end_idx + 1] if points else []

        def avg(values):
            values = [float(v) for v in values if v is not None]
            return round(sum(values) / float(len(values) or 1), 4) if values else 0.0

        final_results = board.get("final_epoch_results", [])
        epoch_indices = [int(p.get("epoch_index", -1)) for p in window_points]
        sep_values = []
        for idx in epoch_indices:
            if 0 <= idx < len(final_results):
                sep_values.append(final_results[idx].get("separation_score"))

        risk_counter = Counter(str(p.get("risk", "unknown")) for p in window_points)
        jump_count = sum(1 for p in window_points if p.get("jump_detected"))
        max_error = max([float(p.get("baseline_error_m", 0.0)) for p in window_points] or [0.0])
        max_threshold = max([float(p.get("dynamic_threshold_m", 0.0)) for p in window_points] or [0.0])
        avg_conf = avg([p.get("confidence") for p in window_points])
        avg_quality = avg([p.get("quality_score") for p in window_points])
        avg_sats = avg([p.get("satellite_count") for p in window_points])
        avg_sep = avg(sep_values)
        reasons = list(hotspot.get("reasons", []))

        primary_causes: List[str] = []
        if avg_conf < 0.70:
            primary_causes.append("局部置信度低于全局稳态水平")
        if avg_quality < 0.60:
            primary_causes.append("观测质量分数偏低")
        if avg_sats < 8.0:
            primary_causes.append("可用卫星数量不足或可见性下降")
        if jump_count > 0:
            primary_causes.append("窗口内出现航向跳变")
        if max_error > max(max_threshold * 0.95, 0.02):
            primary_causes.append("基线误差接近动态阈值")
        if avg_sep and avg_sep < 0.12:
            primary_causes.append("候选解分离度不足")
        if not primary_causes:
            primary_causes = reasons or ["该窗口风险主要来自中等风险历元连续出现"]

        recommendations: List[str] = []
        if jump_count > 0:
            recommendations.append("优先启用 continuity-first 策略，提高 temporal hold 强度，降低航向突跳。")
        if avg_sats < 8.0:
            recommendations.append("建议在该区段减速通过、延长采样时长，或避开明显遮挡侧进行补采。")
        if avg_sep and avg_sep < 0.12:
            recommendations.append("建议提高候选解数量并扩大搜索半径，降低模糊度候选混淆。")
        if max_error > max(max_threshold * 0.95, 0.02):
            recommendations.append("建议启用 recovery 模式，并放宽重试轮次以重新锁定稳定候选。")
        if not recommendations:
            recommendations.append("建议保持当前 balanced 策略，同时对该时间窗进行复核和补采确认。")

        suggested_strategy = {
            "mode": "continuity_first" if jump_count > 0 or avg_sats < 8.0 else "balanced_robust",
            "candidate_count": 14 if avg_sats < 8.0 or avg_sep < 0.12 else 10,
            "search_radius_deg": 14.0 if avg_sep < 0.12 else 10.0,
            "temporal_hold_strength": 0.86 if jump_count > 0 else 0.72,
            "enable_recovery_mode": bool(max_error > max(max_threshold * 0.95, 0.02) or avg_sats < 8.0),
        }
        evidence = {
            "time_window": f"{hotspot.get('start_timestamp')} ~ {hotspot.get('end_timestamp')}",
            "point_count": len(window_points),
            "risk_distribution": dict(risk_counter),
            "avg_confidence": avg_conf,
            "avg_quality_score": avg_quality,
            "avg_satellite_count": avg_sats,
            "avg_separation_score": avg_sep,
            "jump_count": jump_count,
            "max_baseline_error_m": round(max_error, 6),
            "max_dynamic_threshold_m": round(max_threshold, 6),
            "hotspot_reasons": reasons,
        }
        diagnosis = (
            f"{hotspot.get('title')} 的主要风险来自：{'、'.join(primary_causes)}。"
            f"该窗口平均置信度 {avg_conf:.2f}，平均卫星数 {avg_sats:.1f}，跳变 {jump_count} 次，"
            f"最大基线误差 {max_error:.4f} m。"
        )
        return {
            "hotspot_id": hotspot_id,
            "title": hotspot.get("title", hotspot_id),
            "diagnosis": diagnosis,
            "evidence": evidence,
            "recommendations": recommendations[:5],
            "suggested_strategy": suggested_strategy,
        }


    def compile_report_payload(self, arguments: Dict[str, Any], board: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "dataset": board.get("dataset", {}),
            "quality_report": board.get("quality_report", {}),
            "strategy_report": board.get("strategy_report", {}),
            "integrity_report": board.get("integrity_report", {}),
            "continuity_report": board.get("continuity_report", {}),
            "retry_round": board.get("retry_round", 0),
            "warnings": board.get("warnings", []),
            "agent_sequence": [trace.agent for trace in board.get("agent_trace", [])],
            "optional_context": board.get("optional_context", {}),
        }
