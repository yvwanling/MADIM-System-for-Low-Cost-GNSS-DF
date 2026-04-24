from __future__ import annotations

from typing import Any, Dict, List

from app.agents.base import BaseAgent
from app.tools.navigation_tools import ToolRegistry


class IngestionAgent(BaseAgent):
    name = "ingestion_agent"
    role = "数据接入 Agent"
    objective = "识别输入文件格式、解析 NMEA 数据、生成可供后续智能体使用的历元级输入。"

    def __init__(self, registry: ToolRegistry):
        super().__init__(registry)

    def available_tools(self) -> List[str]:
        return ["detect_file_format", "parse_nmea_dataset", "summarize_dataset"]

    def build_llm_context(self, board: Dict[str, Any]) -> Dict[str, Any]:
        return {"dataset": board.get("dataset", {})}

    def fallback_plan(self, board: Dict[str, Any]) -> Dict[str, Any]:
        dataset = board["dataset"]
        return {
            "decision_summary": "先检测文件格式，再解析 NMEA 历元，最后汇总数据集基本统计信息。",
            "tool_calls": [
                {"tool": "detect_file_format", "arguments": {"file_path": dataset["file_path"]}},
                {
                    "tool": "parse_nmea_dataset",
                    "arguments": {
                        "file_path": dataset["file_path"],
                        "reference_path": dataset.get("reference_path"),
                    },
                },
                {"tool": "summarize_dataset", "arguments": {}},
            ],
            "handoff_to": "quality_control_agent",
        }

    def finalize(self, board: Dict[str, Any], results: Dict[str, Dict[str, Any]], decision_summary: str) -> Dict[str, Any]:
        board["ingestion_report"] = {
            "format": results.get("detect_file_format", {}),
            "parsed": results.get("parse_nmea_dataset", {}),
            "summary": results.get("summarize_dataset", {}),
        }
        return board["ingestion_report"]
