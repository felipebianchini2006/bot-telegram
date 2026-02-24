from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
PROFILES_PATH = DATA_DIR / "profiles.json"
SESSIONS_PATH = DATA_DIR / "sessions.enc"
RUNS_LOG_PATH = DATA_DIR / "runs.jsonl"
APP_CONFIG_PATH = DATA_DIR / "app_config.json"


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

