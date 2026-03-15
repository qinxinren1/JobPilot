"""Unified resume HTML generation interface.

This module provides a single entry point for generating resume HTML from
either profile data or tailored resume data.
"""

import json
import subprocess
from pathlib import Path
from typing import Any

from jobpilot.resume.formatter import convert_profile_to_resume_props


def generate_resume_html(resume_props: dict[str, Any]) -> str:
    """Generate resume HTML from Resume component props.
    
    This is the unified interface - all resume generation goes through here.
    
    Args:
        resume_props: Resume component props dict with name, summary, contact,
                     experience, projects, education, skills.
        
    Returns:
        HTML string ready for PDF rendering.
        
    Raises:
        RuntimeError: If script not found or generation fails.
    """
    # Get script path (now in resume/scripts/)
    script_path = Path(__file__).parent / "scripts" / "generate_resume_html.js"
    
    if not script_path.exists():
        raise RuntimeError(f"Resume generation script not found at {script_path}")
    
    # Prepare resume props JSON (direct format, no conversion needed)
    resume_props_json = json.dumps(resume_props, ensure_ascii=False)
    
    # Get project root (4 levels up from resume/scripts/)
    project_root = script_path.parent.parent.parent.parent
    
    # Call Node.js script with resume props directly
    try:
        result = subprocess.run(
            ["node", str(script_path), resume_props_json],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
            cwd=str(project_root)  # Run from project root
        )
        return result.stdout
    except subprocess.TimeoutExpired:
        raise RuntimeError("Resume generation timed out")
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr or e.stdout or str(e)
        raise RuntimeError(f"Failed to generate resume HTML: {error_msg}")


def generate_resume_html_from_profile(profile: dict[str, Any], job_position: str = "") -> str:
    """Generate resume HTML from profile data.
    
    Convenience function that converts profile to resume props and generates HTML.
    
    Args:
        profile: User profile dict.
        job_position: Optional job position/title for the resume.
        
    Returns:
        HTML string ready for PDF rendering.
    """
    resume_props = convert_profile_to_resume_props(profile, job_position)
    return generate_resume_html(resume_props)
