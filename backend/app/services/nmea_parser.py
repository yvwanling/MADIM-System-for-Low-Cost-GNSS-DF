from __future__ import annotations

import csv
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import DefaultDict, Dict, Iterable, List, Optional, Tuple


@dataclass
class EpochRecord:
    timestamp: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    altitude_m: Optional[float] = None
    speed_knots: Optional[float] = None
    course_deg: Optional[float] = None
    fix_quality: Optional[int] = None
    sats_used: Optional[int] = None
    hdop: Optional[float] = None
    pdop: Optional[float] = None
    vdop: Optional[float] = None
    total_sats_in_view: Optional[int] = None
    avg_cn0: Optional[float] = None
    horizontal_error_m: Optional[float] = None
    ref_latitude: Optional[float] = None
    ref_longitude: Optional[float] = None
    ref_altitude_m: Optional[float] = None
    heading_proxy_deg: Optional[float] = None
    source_count: int = 0
    _gsa_samples: List[Tuple[float, float, float]] = field(default_factory=list)
    _cn0_samples: List[float] = field(default_factory=list)


class NMEAParser:
    """Parse open NMEA files into epoch-level navigation features.

    The project remains educational: it does not reconstruct carrier-phase RTK, but it
    extracts route, DOP, satellite and velocity proxies that the agent layer can reason
    about when simulating GNSS ambiguity-resolution workflows.
    """

    def _safe_float(self, value: str) -> Optional[float]:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _safe_int(self, value: str) -> Optional[int]:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _parse_lat_lon(self, raw: str, hemi: str) -> Optional[float]:
        if not raw:
            return None
        try:
            if hemi in ("N", "S"):
                deg = int(raw[:2])
                minutes = float(raw[2:])
            else:
                deg = int(raw[:3])
                minutes = float(raw[3:])
            value = deg + minutes / 60.0
            if hemi in ("S", "W"):
                value = -value
            return value
        except ValueError:
            return None

    def _strip_checksum(self, sentence: str) -> str:
        if "*" in sentence:
            sentence = sentence.split("*", 1)[0]
        return sentence.strip()

    def detect_file_format(self, file_path: Path) -> Dict[str, object]:
        suffix = file_path.suffix.lower()
        preview = file_path.read_text(encoding="utf-8", errors="ignore").splitlines()[:20]
        line_count = 0
        nmea_like = 0
        sentence_counter: Counter[str] = Counter()
        for line in file_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line_count += 1
            line = line.strip()
            if line.startswith("$") and "," in line:
                nmea_like += 1
                sentence = self._strip_checksum(line).split(",")[0]
                if len(sentence) >= 6:
                    sentence_counter[sentence[3:]] += 1
        format_name = "nmea_text" if nmea_like > 0 else "unknown"
        return {
            "file_name": file_path.name,
            "suffix": suffix,
            "line_count": line_count,
            "preview": preview,
            "format_name": format_name,
            "nmea_ratio": round(nmea_like / float(line_count or 1), 4),
            "sentence_counter": dict(sentence_counter),
        }

    def _parse_timestamp(self, time_raw: str, date_raw: Optional[str]) -> Optional[str]:
        if not time_raw:
            return None
        try:
            hh = int(time_raw[0:2])
            mm = int(time_raw[2:4])
            ss = int(float(time_raw[4:]))
            micros = int(round((float(time_raw[4:]) - ss) * 1_000_000))
            if date_raw and len(date_raw) == 6:
                dt = datetime.strptime(date_raw, "%d%m%y")
                dt = dt.replace(hour=hh, minute=mm, second=ss, microsecond=micros)
                return dt.isoformat()
            return f"1970-01-01T{hh:02d}:{mm:02d}:{ss:02d}.{micros:06d}"
        except Exception:
            return None

    def _bearing_deg(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        lat1_r = math.radians(lat1)
        lat2_r = math.radians(lat2)
        dlon = math.radians(lon2 - lon1)
        y = math.sin(dlon) * math.cos(lat2_r)
        x = math.cos(lat1_r) * math.sin(lat2_r) - math.sin(lat1_r) * math.cos(lat2_r) * math.cos(dlon)
        return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0

    def _haversine_m(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        r = 6371000.0
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (
            math.sin(dlat / 2.0) ** 2
            + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2.0) ** 2
        )
        c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return r * c

    def parse_file(self, file_path: Path, reference_path: Optional[Path] = None) -> List[EpochRecord]:
        epochs: DefaultDict[str, EpochRecord] = defaultdict(lambda: EpochRecord(timestamp=""))
        current_date: Optional[str] = None
        with Path(file_path).open("r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                line = line.strip()
                if not line.startswith("$"):
                    continue
                sentence = self._strip_checksum(line)
                parts = sentence.split(",")
                msg = parts[0][3:] if len(parts[0]) >= 6 else ""

                if msg == "RMC":
                    current_date = parts[9] if len(parts) > 9 else current_date
                    timestamp = self._parse_timestamp(parts[1], current_date)
                    if not timestamp:
                        continue
                    epoch = epochs[timestamp]
                    epoch.timestamp = timestamp
                    epoch.latitude = self._parse_lat_lon(parts[3], parts[4])
                    epoch.longitude = self._parse_lat_lon(parts[5], parts[6])
                    epoch.speed_knots = self._safe_float(parts[7])
                    epoch.course_deg = self._safe_float(parts[8])
                    epoch.source_count += 1
                elif msg == "GGA":
                    timestamp = self._parse_timestamp(parts[1], current_date)
                    if not timestamp:
                        continue
                    epoch = epochs[timestamp]
                    epoch.timestamp = timestamp
                    epoch.latitude = epoch.latitude or self._parse_lat_lon(parts[2], parts[3])
                    epoch.longitude = epoch.longitude or self._parse_lat_lon(parts[4], parts[5])
                    epoch.fix_quality = self._safe_int(parts[6])
                    epoch.sats_used = self._safe_int(parts[7])
                    epoch.hdop = self._safe_float(parts[8])
                    epoch.altitude_m = self._safe_float(parts[9])
                    epoch.source_count += 1
                elif msg == "GSA":
                    timestamp_guess = next(reversed(epochs.keys())) if epochs else None
                    if not timestamp_guess:
                        continue
                    epoch = epochs[timestamp_guess]
                    pdop = self._safe_float(parts[-4]) if len(parts) >= 4 else None
                    hdop = self._safe_float(parts[-3]) if len(parts) >= 3 else None
                    vdop = self._safe_float(parts[-2]) if len(parts) >= 2 else None
                    if pdop is not None and hdop is not None and vdop is not None:
                        epoch._gsa_samples.append((pdop, hdop, vdop))
                elif msg == "GSV":
                    timestamp_guess = next(reversed(epochs.keys())) if epochs else None
                    if not timestamp_guess:
                        continue
                    epoch = epochs[timestamp_guess]
                    total_in_view = self._safe_int(parts[3]) if len(parts) > 3 else None
                    if total_in_view is not None:
                        epoch.total_sats_in_view = max(epoch.total_sats_in_view or 0, total_in_view)
                    for idx in range(7, len(parts), 4):
                        cn0 = self._safe_float(parts[idx])
                        if cn0 is not None:
                            epoch._cn0_samples.append(cn0)

        epoch_list = [epochs[key] for key in sorted(epochs.keys())]

        for i, epoch in enumerate(epoch_list):
            if epoch._gsa_samples:
                count = float(len(epoch._gsa_samples))
                epoch.pdop = sum(item[0] for item in epoch._gsa_samples) / count
                epoch.hdop = epoch.hdop or (sum(item[1] for item in epoch._gsa_samples) / count)
                epoch.vdop = sum(item[2] for item in epoch._gsa_samples) / count
            if epoch._cn0_samples:
                epoch.avg_cn0 = sum(epoch._cn0_samples) / float(len(epoch._cn0_samples))
            if epoch.course_deg is None and i > 0:
                prev = epoch_list[i - 1]
                if None not in (prev.latitude, prev.longitude, epoch.latitude, epoch.longitude):
                    epoch.course_deg = self._bearing_deg(prev.latitude, prev.longitude, epoch.latitude, epoch.longitude)
            epoch.heading_proxy_deg = epoch.course_deg

        if reference_path:
            ref_map = self.parse_reference_gga(reference_path)
            for epoch in epoch_list:
                ref = ref_map.get(epoch.timestamp)
                if ref:
                    epoch.ref_latitude, epoch.ref_longitude, epoch.ref_altitude_m = ref
                    if None not in (epoch.latitude, epoch.longitude, epoch.ref_latitude, epoch.ref_longitude):
                        epoch.horizontal_error_m = self._haversine_m(
                            epoch.latitude,
                            epoch.longitude,
                            epoch.ref_latitude,
                            epoch.ref_longitude,
                        )
        return epoch_list

    def parse_reference_gga(self, file_path: Path) -> Dict[str, Tuple[Optional[float], Optional[float], Optional[float]]]:
        ref_map: Dict[str, Tuple[Optional[float], Optional[float], Optional[float]]] = {}
        current_date = "070220"
        with Path(file_path).open("r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                line = line.strip()
                if not line.startswith("$"):
                    continue
                sentence = self._strip_checksum(line)
                parts = sentence.split(",")
                msg = parts[0][3:] if len(parts[0]) >= 6 else ""
                if msg != "GGA":
                    continue
                timestamp = self._parse_timestamp(parts[1], current_date)
                if not timestamp:
                    continue
                ref_map[timestamp] = (
                    self._parse_lat_lon(parts[2], parts[3]),
                    self._parse_lat_lon(parts[4], parts[5]),
                    self._safe_float(parts[9]),
                )
        return ref_map

    def summarize_dataset(self, epochs: Iterable[EpochRecord]) -> Dict[str, object]:
        epochs = list(epochs)
        valid_positions = sum(1 for e in epochs if e.latitude is not None and e.longitude is not None)
        sats = [float(e.sats_used or e.total_sats_in_view or 0) for e in epochs if (e.sats_used or e.total_sats_in_view)]
        cn0 = [float(e.avg_cn0) for e in epochs if e.avg_cn0 is not None]
        hdop = [float(e.hdop) for e in epochs if e.hdop is not None]
        return {
            "epoch_count": len(epochs),
            "valid_positions": valid_positions,
            "avg_satellite_count": round(sum(sats) / float(len(sats) or 1), 3),
            "avg_cn0": round(sum(cn0) / float(len(cn0) or 1), 3) if cn0 else None,
            "avg_hdop": round(sum(hdop) / float(len(hdop) or 1), 3) if hdop else None,
            "time_span": {
                "start": epochs[0].timestamp if epochs else None,
                "end": epochs[-1].timestamp if epochs else None,
            },
        }

    def write_processed_csv(self, epochs: Iterable[EpochRecord], output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "timestamp",
                    "latitude",
                    "longitude",
                    "altitude_m",
                    "speed_knots",
                    "course_deg",
                    "fix_quality",
                    "sats_used",
                    "hdop",
                    "pdop",
                    "vdop",
                    "total_sats_in_view",
                    "avg_cn0",
                    "horizontal_error_m",
                ]
            )
            for item in epochs:
                writer.writerow(
                    [
                        item.timestamp,
                        item.latitude,
                        item.longitude,
                        item.altitude_m,
                        item.speed_knots,
                        item.course_deg,
                        item.fix_quality,
                        item.sats_used,
                        item.hdop,
                        item.pdop,
                        item.vdop,
                        item.total_sats_in_view,
                        item.avg_cn0,
                        item.horizontal_error_m,
                    ]
                )
