import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agents.orchestrator import NavigationOrchestrator  # noqa: E402


def main() -> None:
    service = NavigationOrchestrator()
    result = service.analyze_dataset(
        dataset_name="google_mtv_local1",
        baseline_length_m=1.2,
        candidate_count=5,
        use_llm=False,
        enable_amap_geocode=False,
    )
    report_path = ROOT / "docs" / "functional_test_report.json"
    report_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    print(json.dumps(result.summary.model_dump(), ensure_ascii=False, indent=2))
    print(f"Functional test report saved to: {report_path}")


if __name__ == "__main__":
    main()
