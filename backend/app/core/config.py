from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List


ROOT_DIR = Path(__file__).resolve().parents[3]
DATA_DIR = ROOT_DIR / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"


def _load_env_file() -> None:
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


_load_env_file()


@dataclass
class Settings:
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8000"))
    cors_origins: List[str] = field(
        default_factory=lambda: [
            item.strip()
            for item in os.getenv(
                "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
            ).split(",")
            if item.strip()
        ]
    )
    llm_model_id: str = os.getenv("LLM_MODEL_ID", "")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_base_url: str = os.getenv("LLM_BASE_URL", "")
    llm_timeout: int = int(os.getenv("LLM_TIMEOUT", "60"))
    llm_enable_thinking: bool = os.getenv("LLM_ENABLE_THINKING", "false").lower() == "true"
    default_baseline_length_m: float = float(os.getenv("DEFAULT_BASELINE_LENGTH_M", "1.20"))
    default_candidate_count: int = int(os.getenv("DEFAULT_CANDIDATE_COUNT", "5"))
    max_retry_rounds: int = int(os.getenv("MAX_RETRY_ROUNDS", "2"))
    amap_web_key: str = os.getenv("AMAP_WEB_KEY", "")
    amap_js_key: str = os.getenv("AMAP_JS_KEY", "")
    amap_security_js_code: str = os.getenv("AMAP_SECURITY_JS_CODE", "")


settings = Settings()
