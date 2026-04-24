from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.nmea_parser import NMEAParser  # noqa: E402


def main() -> None:
    parser = NMEAParser()
    source = ROOT / "data" / "raw" / "MTV.Local1.ublox-F9K.20200206-181434.nmea"
    reference = ROOT / "data" / "raw" / "MTV.Local1.SPAN.20200206-181434.gga"
    output = ROOT / "data" / "processed" / "google_mtv_local1_processed.csv"
    epochs = parser.parse_file(source, reference)
    parser.write_processed_csv(epochs, output)
    print(f"Wrote {len(epochs)} epochs to {output}")


if __name__ == "__main__":
    main()
