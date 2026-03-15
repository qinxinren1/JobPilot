"""Resume management module.

This module provides all resume-related functionality:
- Parsing uploaded resumes
- Formatting resume data
- Generating resume HTML/PDF
- Tailoring resumes for specific jobs
"""

from jobpilot.resume.formatter import convert_profile_to_resume_props
from jobpilot.resume.generator import (
    generate_resume_html,
    generate_resume_html_from_profile,
)
from jobpilot.resume.parser import (
    extract_text_from_pdf,
    merge_resume_data_with_llm,
    parse_resume_with_llm,
)

__all__ = [
    "convert_profile_to_resume_props",
    "generate_resume_html",
    "generate_resume_html_from_profile",
    "extract_text_from_pdf",
    "parse_resume_with_llm",
    "merge_resume_data_with_llm",
]
