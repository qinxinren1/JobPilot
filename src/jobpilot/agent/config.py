"""Agent configuration: paths and settings for job application agent."""

import json
from pathlib import Path

# All files in ~/.jobpilot/
APP_DIR = Path.home() / ".jobpilot"

# Agent-specific paths
AGENT_JOBS_FILE = APP_DIR / "agent_jobs.json"      
AGENT_RESULTS_FILE = APP_DIR / "agent_results.json"  
AGENT_SETTINGS_FILE = APP_DIR / "agent_settings.json"  
AGENT_LOGS_DIR = APP_DIR / "agent_logs"            

# Shared paths (from main config)
PROFILE_PATH = APP_DIR / "profile.json"
TAILORED_DIR = APP_DIR / "tailored_resumes"
COVER_LETTER_DIR = APP_DIR / "cover_letters"
BASE_RESUMES_DIR = APP_DIR / "base_resumes"

# Chrome worker paths
CHROME_WORKER_DIR = APP_DIR / "agent_chrome_workers"
APPLY_WORKER_DIR = APP_DIR / "agent_apply_workers"


def ensure_agent_dirs():
    """Create agent-specific directories."""
    for d in [AGENT_LOGS_DIR, CHROME_WORKER_DIR, APPLY_WORKER_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def load_profile() -> dict:
    """Load user profile from ~/.jobpilot/profile.json."""
    if not PROFILE_PATH.exists():
        raise FileNotFoundError(f"Profile not found at {PROFILE_PATH}")
    return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))


def load_settings() -> dict:
    """Load agent settings from ~/.jobpilot/agent_settings.json."""
    if not AGENT_SETTINGS_FILE.exists():
        return {
            "workers": 1,
            "model": "sonnet",
            "headless": False,
            "min_score": 7,
            "poll_interval": 60,
            "viewport": "1280x720",
        }
    return json.loads(AGENT_SETTINGS_FILE.read_text(encoding="utf-8"))


def save_settings(settings: dict) -> None:
    """Save agent settings."""
    AGENT_SETTINGS_FILE.write_text(
        json.dumps(settings, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


def load_jobs() -> list[dict]:
    """Load job list from ~/.jobpilot/agent_jobs.json."""
    if not AGENT_JOBS_FILE.exists():
        return []
    return json.loads(AGENT_JOBS_FILE.read_text(encoding="utf-8"))


def save_jobs(jobs: list[dict]) -> None:
    """Save job list."""
    AGENT_JOBS_FILE.write_text(
        json.dumps(jobs, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


def load_results() -> list[dict]:
    """Load application results from ~/.jobpilot/agent_results.json."""
    if not AGENT_RESULTS_FILE.exists():
        return []
    return json.loads(AGENT_RESULTS_FILE.read_text(encoding="utf-8"))


def save_result(result: dict) -> None:
    """Append a result to results file."""
    results = load_results()
    results.append(result)
    AGENT_RESULTS_FILE.write_text(
        json.dumps(results, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )
