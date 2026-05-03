from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.agents.orchestrator import NavigationOrchestrator


def main() -> None:
    service = NavigationOrchestrator()
    response = service.analyze_dataset(
        dataset_name="google_mtv_local1",
        baseline_length_m=1.20,
        candidate_count=5,
        use_llm=False,
        enable_amap_geocode=False,
    )
    print("analysis", response.summary.total_epochs, response.summary.fix_rate)

    compare = service.compare_strategies(
        dataset_name="google_mtv_local1",
        baseline_length_m=1.20,
        candidate_count=5,
        use_llm=False,
        enable_amap_geocode=False,
        strategy_names=[],
    )
    print("compare", len(compare.items), compare.best_strategy)

    hotspots = response.optional_context.get("trajectory", {}).get("hotspots", [])
    if hotspots:
        diagnosis = service.diagnose_hotspot(hotspots[0]["id"], use_llm=False)
        print("diagnosis", diagnosis.hotspot_id, diagnosis.title)

    evaluation = service.evaluate_samples(baseline_length_m=1.20, candidate_count=5)
    print("evaluate", len(evaluation.items), evaluation.aggregate)

    report = service.export_report(fmt="html")
    print("report", report.filename, len(report.content))


if __name__ == "__main__":
    main()
