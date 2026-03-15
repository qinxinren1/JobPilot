"""Job application agent module.

Independent agent for autonomous job applications.
All data stored in ~/.jobpilot/ directory.
"""

from jobpilot.agent.apply_agent import run_agent
from jobpilot.agent.ats_detector import detect_ats_type, get_ats_specific_instructions, is_manual_ats
from jobpilot.agent.config import (
    load_jobs, save_jobs, load_results, save_result,
    load_settings, save_settings, load_profile,
    ensure_agent_dirs
)
from jobpilot.agent.prompts import build_prompt

__all__ = [
    "run_agent",
    "detect_ats_type",
    "get_ats_specific_instructions",
    "is_manual_ats",
    "load_jobs",
    "save_jobs",
    "load_results",
    "save_result",
    "load_settings",
    "save_settings",
    "load_profile",
    "ensure_agent_dirs",
    "build_prompt",
]
