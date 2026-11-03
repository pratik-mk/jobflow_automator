import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
CANDIDATE_FILE = CONFIG_DIR / "candidate.json"
BASELINE_FILE = CONFIG_DIR / "baseline_resume.md"
PROMPTS_DIR = BASE_DIR / "prompts"
load_dotenv(BASE_DIR / ".env")


def load_tunables() -> dict:
    return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))


def save_tunables(data: dict) -> None:
    SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_candidate() -> dict:
    return json.loads(CANDIDATE_FILE.read_text(encoding="utf-8"))


def save_candidate(data: dict) -> None:
    CANDIDATE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def load_baseline() -> str:
    return BASELINE_FILE.read_text(encoding="utf-8")


def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


def _path(value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else BASE_DIR / p


@dataclass
class Settings:
    cursor_api_key: str = os.getenv("CURSOR_API_KEY", "").strip()
    sheets_credentials_file: Path = _path(os.getenv("GOOGLE_SHEETS_CREDENTIALS_FILE", "config/credentials.json"))
    sheet_url: str = os.getenv("GOOGLE_SHEET_URL", "")
    store_primary: str = os.getenv("STORE_PRIMARY", "sheets")
    store_mirrors: list[str] = field(
        default_factory=lambda: [s.strip() for s in os.getenv("STORE_MIRRORS", "sqlite").split(",") if s.strip()]
    )
    sqlite_path: Path = _path(os.getenv("SQLITE_PATH", "data/jobs.db"))
    tunables: dict = field(default_factory=load_tunables)

    base_dir: Path = BASE_DIR
    output_dir: Path = BASE_DIR / "output"
    templates_dir: Path = BASE_DIR / "templates"
    sandbox_dir: Path = BASE_DIR / ".agent_sandbox"
    logs_dir: Path = BASE_DIR / "logs"

    def section(self, name: str) -> dict:
        return self.tunables.get(name, {})


def load_settings() -> Settings:
    s = Settings()
    if not s.cursor_api_key:
        raise RuntimeError("Missing CURSOR_API_KEY in .env")
    if "sheets" in [s.store_primary, *s.store_mirrors] and not s.sheet_url:
        raise RuntimeError("Missing GOOGLE_SHEET_URL in .env (or remove 'sheets' from STORE_PRIMARY/STORE_MIRRORS)")
    return s
