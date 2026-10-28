"""Configuration from environment variables only (see .env.example). Nothing here is hardcoded."""

import os
import re
from dataclasses import dataclass
from pathlib import Path

ENV_KEYS = (
    "LLM_API_KEY",
    "LLM_BASE_URL",
    "LLM_MODEL",
    "SPLUNK_HOST",
    "SPLUNK_PORT",
    "SPLUNK_SEARCH_TOKEN",
    "SPLUNK_DEPLOY_TOKEN",
    "PARSEWRIGHT_PACKAGES_DIR",
    "PARSEWRIGHT_TEST_INDEX",
    "PARSEWRIGHT_RUN_TOKEN_CEILING",
    "PARSEWRIGHT_RUNS_DIR",
    "PARSEWRIGHT_JOB_INGEST_MB",
    "PARSEWRIGHT_DAILY_INGEST_MB",
)
REPO = Path(__file__).resolve().parents[2]
KEY_LINE = re.compile(r"[A-Z][A-Z0-9_]*")


def load_env_file(path: Path) -> None:
    """Export the known keys from a .env file without overriding the real environment.

    The file is read as plain KEY=value lines and never executed or expanded.
    """
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        key = key.strip()
        if sep and key in ENV_KEYS and KEY_LINE.fullmatch(key) and key not in os.environ:
            os.environ[key] = value.strip()


def _require(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise RuntimeError(f"{name} is not set (see .env.example)")
    return value


@dataclass(frozen=True)
class Settings:
    llm_api_key: str
    llm_base_url: str
    llm_model: str
    splunk_host: str
    splunk_port: int
    splunk_search_token: str
    splunk_deploy_token: str
    packages_dir: Path
    test_index: str
    run_token_ceiling: int
    runs_dir: Path = REPO / ".runs"
    job_ingest_mb: float = 20
    daily_ingest_mb: float = 500

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            llm_api_key=_require("LLM_API_KEY"),
            llm_base_url=_require("LLM_BASE_URL"),
            llm_model=_require("LLM_MODEL"),
            splunk_host=_require("SPLUNK_HOST"),
            splunk_port=int(os.environ.get("SPLUNK_PORT", "8089")),
            splunk_search_token=_require("SPLUNK_SEARCH_TOKEN"),
            splunk_deploy_token=_require("SPLUNK_DEPLOY_TOKEN"),
            packages_dir=Path(_require("PARSEWRIGHT_PACKAGES_DIR")),
            test_index=_require("PARSEWRIGHT_TEST_INDEX"),
            run_token_ceiling=int(os.environ.get("PARSEWRIGHT_RUN_TOKEN_CEILING", "300000")),
            runs_dir=Path(os.environ.get("PARSEWRIGHT_RUNS_DIR") or REPO / ".runs"),
            job_ingest_mb=float(os.environ.get("PARSEWRIGHT_JOB_INGEST_MB", "20")),
            daily_ingest_mb=float(os.environ.get("PARSEWRIGHT_DAILY_INGEST_MB", "500")),
        )

    def __repr__(self) -> str:  # never print tokens or keys
        return (
            f"Settings(model={self.llm_model!r}, splunk={self.splunk_host!r}, "
            f"index={self.test_index!r})"
        )
