from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.agents.orchestrator import NavigationOrchestrator  # noqa: E402
from app.services.nmea_parser import NMEAParser  # noqa: E402


def test_parser_reads_epochs():
    parser = NMEAParser()
    source = ROOT / "data" / "raw" / "MTV.Local1.ublox-F9K.20200206-181434.nmea"
    reference = ROOT / "data" / "raw" / "MTV.Local1.SPAN.20200206-181434.gga"
    epochs = parser.parse_file(source, reference)
    assert len(epochs) > 100
    assert any(epoch.total_sats_in_view for epoch in epochs)
    assert any(epoch.horizontal_error_m is not None for epoch in epochs)


def test_detect_format():
    parser = NMEAParser()
    source = ROOT / "data" / "raw" / "gpskit_test.nmea"
    meta = parser.detect_file_format(source)
    assert meta["format_name"] == "nmea_text"
    assert meta["nmea_ratio"] > 0.9


def test_agentic_orchestrator_generates_trace():
    service = NavigationOrchestrator()
    result = service.analyze_dataset("google_mtv_local1", 1.2, 5, False, False)
    assert result.summary.total_epochs > 100
    assert 0.0 <= result.summary.fix_rate <= 1.0
    assert len(result.epochs) == result.summary.total_epochs
    assert len(result.agent_trace) >= 8
    assert any(trace.agent == "strategy_agent" for trace in result.agent_trace)
