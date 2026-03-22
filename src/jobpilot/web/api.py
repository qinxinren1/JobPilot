"""FastAPI backend for JobPilot web interface."""

from __future__ import annotations

import json
import logging
import shutil
import yaml
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from jobpilot.config import (
    APP_DIR, PROFILE_PATH, RESUME_PATH, RESUME_PDF_PATH, 
    SEARCH_CONFIG_PATH, BASE_RESUMES_DIR, BASE_COVER_LETTERS_DIR, ensure_dirs, load_env
)
from jobpilot.resume.parser import (
    extract_text_from_pdf,
    parse_resume_with_llm,
    merge_resume_data_with_llm,
)
from jobpilot.scoring.utils import (
    generate_resume_template_filename,
    save_base_resume_txt,
)
from jobpilot.web.utils import (
    load_profile_or_raise,
    load_profile_safe,
    validate_file_type,
    sync_search_config_if_needed,
    unset_all_resume_defaults,
    RESUME_TEMPLATE_FIELDS,
)

# Initialize FastAPI app
app = FastAPI(
    title="JobPilot API",
    description="Web API for JobPilot job application pipeline",
    version="0.3.0",
)

# CORS middleware - allow React dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",  # Vite default port
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load environment variables
load_env()

# Ensure directories exist
ensure_dirs()


# Pydantic models for request/response
class ProfileUpdate(BaseModel):
    """Profile update request model."""
    profile: dict[str, Any]


class ProfileResponse(BaseModel):
    """Profile response model."""
    profile: dict[str, Any]
    exists: bool


# API Routes
@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "message": "JobPilot API is running"}


@app.get("/api/profile", response_model=ProfileResponse)
async def get_profile():
    """Get user profile."""
    try:
        if not PROFILE_PATH.exists():
            return ProfileResponse(profile={}, exists=False)
        
        profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        return ProfileResponse(profile=profile, exists=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load profile: {str(e)}")


@app.post("/api/profile")
async def update_profile(update: ProfileUpdate):
    """Update user profile."""
    try:
        # Validate profile structure (basic check)
        profile = update.profile
        
        # Ensure APP_DIR exists
        ensure_dirs()
        
        # Auto-sync: target_roles is the single source of truth
        sync_search_config_if_needed(profile)
        
        # Save profile (with synced categories)
        PROFILE_PATH.write_text(
            json.dumps(profile, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        
        return {"status": "ok", "message": "Profile updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update profile: {str(e)}")


@app.get("/api/profile/section/{section_name}")
async def get_profile_section(section_name: str):
    """Get a specific section of the profile."""
    try:
        if not PROFILE_PATH.exists():
            raise HTTPException(status_code=404, detail="Profile not found")
        
        profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        section = profile.get(section_name)
        
        if section is None:
            raise HTTPException(status_code=404, detail=f"Section '{section_name}' not found")
        
        return {section_name: section}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load section: {str(e)}")


@app.patch("/api/profile/section/{section_name}")
async def update_profile_section(section_name: str, section_data: dict[str, Any]):
    """Update a specific section of the profile."""
    try:
        # Load existing profile
        profile = load_profile_safe()
        
        # Update section
        profile[section_name] = section_data
        
        # Auto-sync: target_roles is the single source of truth
        sync_search_config_if_needed(profile, section_name=section_name)
        
        # Save (with synced categories)
        ensure_dirs()
        PROFILE_PATH.write_text(
            json.dumps(profile, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        
        return {"status": "ok", "message": f"Section '{section_name}' updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update section: {str(e)}")


# ---------------------------------------------------------------------------
# Initialization endpoints
# ---------------------------------------------------------------------------

@app.post("/api/init")
async def initialize_setup(
    resume_file: UploadFile = File(None),
    profile: str = Form(...),
    search_config: str = Form(...),
):
    """Initialize JobPilot: upload resume, set profile, and configure search.
    
    Args:
        resume_file: Optional resume file (PDF or TXT)
        profile: JSON string containing profile data
        search_config: JSON string containing search configuration
        
    Returns:
        Initialization status and current tier
    """
    try:
        ensure_dirs()
        
        # 1. Handle resume file (optional)
        if resume_file and resume_file.filename:
            await _save_resume_file(resume_file)
        
        # 2. Save Profile
        profile_data = json.loads(profile)
        PROFILE_PATH.write_text(
            json.dumps(profile_data, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        
        # 3. Save Search Config
        search_data = json.loads(search_config)
        _save_search_config(search_data)
        
        # Return initialization status
        from jobpilot.config import get_tier, TIER_LABELS
        tier = get_tier()
        
        return {
            "status": "ok",
            "message": "Initialization complete",
            "tier": tier,
            "tier_label": TIER_LABELS[tier]
        }
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Initialization failed: {str(e)}")


@app.get("/api/init/status")
async def get_init_status():
    """Check initialization status.
    
    Returns:
        Status of each initialization component and current tier
    """
    try:
        from jobpilot.config import get_tier, TIER_LABELS
        import os
        
        status = {
            "resume": RESUME_PATH.exists() or RESUME_PDF_PATH.exists(),
            "profile": PROFILE_PATH.exists(),
            "search_config": SEARCH_CONFIG_PATH.exists(),
            "ai_configured": any(os.environ.get(k) for k in 
                                ("GEMINI_API_KEY", "OPENAI_API_KEY", "LLM_URL")),
            "tier": get_tier(),
            "tier_label": TIER_LABELS[get_tier()],
        }
        return status
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get status: {str(e)}")


@app.get("/api/search-config")
async def get_search_config():
    """Get search configuration. Auto-generates from target_roles if available."""
    from jobpilot.config import load_search_config
    
    # Try to auto-generate from target_roles if available
    profile = load_profile_safe()
    target_roles = profile.get("target_roles") if profile else None
    
    if target_roles:
        try:
            config = _generate_search_config_from_target_roles(profile, preserve_existing=True)
            _save_search_config(config)
            return {"config": config}
        except Exception as e:
            log.debug(f"Failed to auto-generate from target_roles, using existing config: {e}")
    
    # Fall back to loading existing config
    try:
        config = load_search_config()
        return {"config": config}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load search config: {str(e)}")


@app.post("/api/search-config")
async def update_search_config(config: dict[str, Any]):
    """Update search configuration."""
    try:
        _save_search_config(config)
        return {"status": "ok", "message": "Search config updated successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update search config: {str(e)}")


@app.post("/api/search-config/sync-from-target-roles")
async def sync_search_config_from_target_roles():
    """Sync searches.yaml from target_roles in profile."""
    profile = load_profile_or_raise()
    target_roles = profile.get("target_roles", {})
    
    if not target_roles:
        raise HTTPException(status_code=400, detail="No target_roles found in profile")
    
    try:
        search_config = _generate_search_config_from_target_roles(profile, preserve_existing=True)
        _save_search_config(search_config)
        
        return {
            "status": "ok",
            "message": "Search config synced from target_roles successfully",
            "queries_count": len(search_config.get("queries", []))
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to sync search config: {str(e)}")


# ---------------------------------------------------------------------------
# Helper functions for initialization
# ---------------------------------------------------------------------------

async def _save_resume_file(file: UploadFile):
    """Save resume file (PDF or TXT)."""
    file_ext = validate_file_type(
        file,
        allowed_extensions=[".pdf", ".txt"],
        error_message="Unsupported file type. Please upload a PDF or TXT file."
    )
    
    content = await file.read()
    
    if file_ext == ".pdf":
        RESUME_PDF_PATH.write_bytes(content)
        # Extract text from PDF
        from jobpilot.resume.parser import extract_text_from_pdf
        text = extract_text_from_pdf(RESUME_PDF_PATH)
        RESUME_PATH.write_text(text, encoding="utf-8")
    else:
        RESUME_PATH.write_bytes(content)




def _generate_search_config_from_target_roles(profile: dict, preserve_existing: bool = True) -> dict:
    """Generate search configuration from target_roles in profile.
    
    Uses target_roles.name as tier 1 queries and experience_filter as tier 2 queries.
    This unifies the category system: target_roles = resume categories = search queries.
    
    Args:
        profile: User profile dict containing target_roles.
        preserve_existing: If True, preserve existing locations and defaults from current searches.yaml.
        
    Returns:
        Search configuration dict ready to be saved.
    """
    from jobpilot.config import load_search_config, SEARCH_CONFIG_PATH
    
    target_roles = profile.get("target_roles", {})
    
    # Load existing config to preserve locations and defaults
    existing_config = {}
    if preserve_existing and SEARCH_CONFIG_PATH.exists():
        try:
            existing_config = load_search_config()
        except Exception:
            pass
    
    # Build queries from target_roles (unified category system)
    # IMPORTANT: Only use target_roles.name as queries (one query per target role)
    queries = []
    for role_key, role in target_roles.items():
        # Only use name field from target_roles - one query per role
        name = role.get("name", role_key)
        if name and name.strip():  # Only add if name exists and is not empty
            queries.append({
                "query": name.strip(),
                "tier": 1
            })
        # Note: experience_filter is NOT used for search queries - only name is used
    
    # Use existing defaults and locations, or set defaults
    defaults = existing_config.get("defaults", {})
    if not defaults:
        defaults = {
            "location": "Netherlands",
            "distance": 0,
            "hours_old": 72,
            "results_per_site": 50,
            "experience_level": []
        }
    
    locations = existing_config.get("locations", [])
    if not locations:
        locations = [{"location": defaults.get("location", "Netherlands"), "remote": defaults.get("distance", 0) == 0}]
    
    # Preserve other config fields
    config = {
        "defaults": defaults,
        "locations": locations,
        "queries": queries
    }
    
    # Preserve other fields from existing config
    for key in ["location", "country", "boards", "exclude_titles"]:
        if key in existing_config:
            config[key] = existing_config[key]
    
    return config


def _save_search_config(config: dict):
    """Save search configuration as YAML.
    
    Accepts both legacy format and full YAML structure:
    Legacy:
    {
        "location": "Netherlands",
        "distance": 0,
        "roles": ["Software Engineer", "Backend Developer"]
    }
    
    Full structure:
    {
        "defaults": {
            "location": "Netherlands",
            "distance": 0,
            "hours_old": 72,
            "results_per_site": 50
        },
        
        "locations": [
            {"location": "Netherlands", "remote": false}
        ],
        "queries": [
            {"query": "software engineer", "tier": 1}
        ]
    }
    """
    # Handle full structure
    if "defaults" in config:
        defaults = config.get("defaults", {})
        location = defaults.get("location", "Netherlands")
        distance = defaults.get("distance", 0)
        hours_old = defaults.get("hours_old", 72)
        results_per_site = defaults.get("results_per_site", 50)
        experience_level = defaults.get("experience_level", [])
        # Convert single string to list for backward compatibility
        if isinstance(experience_level, str):
            experience_level = [experience_level]
        if not isinstance(experience_level, list):
            experience_level = []
        # Backward compatibility: if 'all' is specified, convert to empty list (no filtering)
        if "all" in experience_level:
            experience_level = []
    else:
        # Legacy format
        location = config.get("location", "Netherlands")
        distance = config.get("distance", 0)
        hours_old = 72
        results_per_site = 50
        experience_level = []
    
    # Handle locations
    if "locations" in config and isinstance(config["locations"], list) and len(config["locations"]) > 0:
        locations = config["locations"]
    else:
        # Legacy format - create location from single location
        locations = [{"location": location, "remote": distance == 0}]
    
    # Handle queries
    if "queries" in config and isinstance(config["queries"], list) and len(config["queries"]) > 0:
        queries = config["queries"]
    elif "roles" in config and isinstance(config["roles"], list):
        # Legacy format - convert roles to queries with tier
        roles = config["roles"]
        if not roles:
            roles = ["Software Engineer"]
        queries = [{"query": role, "tier": min(i + 1, 3)} for i, role in enumerate(roles)]
    else:
        queries = [{"query": "Software Engineer", "tier": 1}]
    
    # Build YAML content
    lines = [
        "# JobPilot search configuration",
        "# Edit this file to refine your job search queries.",
        "",
        "defaults:",
        f'  location: "{location}"',
        f"  distance: {distance}",
        f"  hours_old: {hours_old}",
        f"  results_per_site: {results_per_site if results_per_site is not None else 0}",
        f"  experience_level: {experience_level}",
        "",
        "locations:",
    ]
    
    for loc in locations:
        loc_name = loc.get("location", location)
        remote = loc.get("remote", False)
        lines.append(f'  - location: "{loc_name}"')
        lines.append(f"    remote: {str(remote).lower()}")
    
    lines.append("")
    lines.append("queries:")
    
    for query in queries:
        query_str = query.get("query", "")
        tier = query.get("tier", 1)
        lines.append(f'  - query: "{query_str}"')
        lines.append(f"    tier: {tier}")
    
    SEARCH_CONFIG_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


@app.post("/api/resume/upload")
async def upload_resume(file: UploadFile = File(...)):
    """Upload and parse a resume file (PDF or TXT) using LLM.
    
    Saves resume history and merges with existing profile data using LLM.
    
    Args:
        file: The resume file to upload.
        
    Returns:
        Extracted profile data, merged data, and saved file paths.
    """
    from datetime import datetime, timezone
    from jobpilot.database import get_connection, init_resume_history_table
    import logging
    
    try:
        ensure_dirs()
        
        # Validate file type
        file_ext = validate_file_type(
            file,
            allowed_extensions=[".pdf", ".txt"],
            error_message="Unsupported file type. Please upload a PDF or TXT file."
        )
        
        # Save uploaded file with timestamp
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        if file_ext == ".pdf":
            saved_path = APP_DIR / f"resume_{timestamp}.pdf"
            # Also save as current resume
            with open(saved_path, "wb") as f:
                shutil.copyfileobj(file.file, f)
            RESUME_PDF_PATH.write_bytes(saved_path.read_bytes())
        else:
            saved_path = APP_DIR / f"resume_{timestamp}.txt"
            # Also save as current resume
            with open(saved_path, "wb") as f:
                shutil.copyfileobj(file.file, f)
            RESUME_PATH.write_bytes(saved_path.read_bytes())
        
        # Extract text
        if file_ext == ".pdf":
            text = extract_text_from_pdf(saved_path)
            # Also save as text file
            RESUME_PATH.write_text(text, encoding="utf-8")
        else:
            text = saved_path.read_text(encoding="utf-8")
        
        # Parse resume using LLM only
        try:
            extracted_data = parse_resume_with_llm(text)
        except Exception as e:
            logging.error(f"LLM parsing failed: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to parse resume with LLM: {str(e)}. Please ensure your API key is configured correctly."
            )
        
        # Save to resume history
        conn = get_connection()
        init_resume_history_table(conn)
        
        conn.execute(
            "INSERT INTO resume_history (uploaded_at, file_path, file_type, extracted_data, resume_text) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                datetime.now(timezone.utc).isoformat(),
                str(saved_path),
                file_ext[1:],  # Remove the dot
                json.dumps(extracted_data, ensure_ascii=False),
                text[:10000]  # Store first 10k chars
            )
        )
        conn.commit()
        
        # Load existing profile and merge using LLM
        existing_profile = {}
        if PROFILE_PATH.exists():
            try:
                existing_profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
                logging.info("=" * 80)
                logging.info("RESUME UPLOAD - Loading existing profile")
                existing_exp_count = len(existing_profile.get("experience", {}).get("work_experiences", [])) or len(existing_profile.get("work_experiences", []))
                existing_proj_count = len(existing_profile.get("experience", {}).get("projects", [])) or len(existing_profile.get("projects", []))
                existing_edu_count = len(existing_profile.get("experience", {}).get("education", [])) or len(existing_profile.get("education", []))
                logging.info(f"Existing profile has: {existing_exp_count} work experiences, {existing_proj_count} projects, {existing_edu_count} education entries")
            except Exception as e:
                logging.warning(f"Failed to load existing profile: {e}")
        else:
            logging.info("=" * 80)
            logging.info("RESUME UPLOAD - No existing profile found, creating new one")
        
        # Log extracted data from new resume
        logging.info("=" * 80)
        logging.info("RESUME UPLOAD - Extracted data from new resume")
        new_exp_count = len(extracted_data.get("work_experiences", [])) or len(extracted_data.get("experience", {}).get("work_experiences", []))
        new_proj_count = len(extracted_data.get("projects", [])) or len(extracted_data.get("experience", {}).get("projects", []))
        new_edu_count = len(extracted_data.get("education", [])) or len(extracted_data.get("experience", {}).get("education", []))
        logging.info(f"New resume has: {new_exp_count} work experiences, {new_proj_count} projects, {new_edu_count} education entries")
        
        # Merge new data with existing profile using LLM
        logging.info("=" * 80)
        logging.info("RESUME UPLOAD - Starting LLM merge process")
        merged_profile = merge_resume_data_with_llm(existing_profile, extracted_data)
        
        # Log final merged result
        logging.info("=" * 80)
        logging.info("RESUME UPLOAD - Merge completed")
        merged_exp_count = len(merged_profile.get("experience", {}).get("work_experiences", [])) or len(merged_profile.get("work_experiences", []))
        merged_proj_count = len(merged_profile.get("experience", {}).get("projects", [])) or len(merged_profile.get("projects", []))
        merged_edu_count = len(merged_profile.get("experience", {}).get("education", [])) or len(merged_profile.get("education", []))
        logging.info(f"Final merged profile has: {merged_exp_count} work experiences, {merged_proj_count} projects, {merged_edu_count} education entries")
        logging.info("=" * 80)
        
        # Save merged profile (structure is already normalized in merge_resume_data_with_llm)
        PROFILE_PATH.write_text(
            json.dumps(merged_profile, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        
        return {
            "status": "ok",
            "message": "Resume uploaded, parsed, and merged successfully",
            "extracted_data": extracted_data,
            "merged_data": merged_profile,
            "resume_text": text[:1000],  # First 1000 chars for preview
            "saved_paths": {
                "pdf": str(RESUME_PDF_PATH) if file_ext == ".pdf" else None,
                "txt": str(RESUME_PATH),
                "history": str(saved_path)
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process resume: {str(e)}")





# ============================================================================
# Resume API
# ============================================================================

class GenerateResumeRequest(BaseModel):
    """Request model for generating a resume."""
    role_category: str  # Required: target_roles key (e.g., "frontend", "backend")
    job_position: str = ""  # Optional: job position/title
    profile_data: dict[str, Any] | None = None  # Optional: filtered profile data


@app.post("/api/resume/generate")
async def generate_resume(request: GenerateResumeRequest):
    """Generate a resume PDF for a specific role category.
    
    This is the simplified, unified endpoint for generating resumes.
    It replaces the old /api/resumes/generate and /api/profile/generate-base-resume.
    
    Args:
        request: Request with role_category (required), job_position (optional), 
                 and profile_data (optional, uses file if not provided).
        
    Returns:
        Generated resume file paths (PDF, HTML, TXT).
    """
    try:
        ensure_dirs()
        
        role_category = request.role_category
        if not role_category:
            raise HTTPException(status_code=400, detail="role_category is required")
        
        # Load profile (from request or file)
        if request.profile_data:
            profile = request.profile_data
        else:
            profile = load_profile_or_raise()
        
        # Validate role_category exists
        target_roles = profile.get("target_roles", {})
        if role_category not in target_roles:
            raise HTTPException(
                status_code=400,
                detail=f"Role category '{role_category}' not found in target_roles. "
                       "Please configure it in your profile first."
            )
        
        role_config = target_roles[role_category]
        role_name = role_config.get("name", role_category)
        job_position = request.job_position or role_name
        
        # Generate resume HTML
        from jobpilot.resume.generator import generate_resume_html_from_profile
        resume_html = generate_resume_html_from_profile(profile, job_position)
        
        # Generate filename based on role_category
        from jobpilot.config import BASE_RESUMES_DIR
        role_dir = BASE_RESUMES_DIR / role_category
        role_dir.mkdir(parents=True, exist_ok=True)
        
        # Save HTML file
        html_path = role_dir / "resume.html"
        html_path.write_text(resume_html, encoding="utf-8")
        
        # Generate PDF
        pdf_path = role_dir / "resume.pdf"
        import asyncio
        from playwright.sync_api import sync_playwright
        
        def render_html_to_pdf(html: str, output_path: Path) -> None:
            """Render HTML to PDF using Playwright."""
            with sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page()
                page.set_content(html, wait_until="networkidle")
                page.pdf(
                    path=str(output_path),
                    format="A4",
                    print_background=True,
                )
                browser.close()
        
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, render_html_to_pdf, resume_html, pdf_path)
        
        # Generate and save TXT (base resume)
        txt_path = role_dir / "resume.txt"
        try:
            from jobpilot.resume.formatter import generate_resume_text_from_profile
            resume_text = generate_resume_text_from_profile(profile)
            txt_path.write_text(resume_text, encoding="utf-8")
            
            # Update profile with base_resume_path
            profile_for_update = load_profile_or_raise()
            save_base_resume_txt(resume_text, role_category, profile_for_update)
        except Exception as e:
            log.warning(f"Failed to save TXT resume: {e}")
        
        return {
            "status": "ok",
            "message": f"Resume generated successfully for {role_name}",
            "role_category": role_category,
            "role_name": role_name,
            "pdf_path": str(pdf_path),
            "html_path": str(html_path),
            "txt_path": str(txt_path) if txt_path.exists() else None,
        }
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_detail = f"Failed to generate resume: {str(e)}\n{traceback.format_exc()}"
        raise HTTPException(status_code=500, detail=error_detail)


@app.post("/api/resume/preview")
async def preview_resume(request: dict[str, Any]):
    """Preview resume HTML without generating files.
    
    This endpoint allows you to preview how a resume will look before generating it.
    
    Args:
        request: Request body with 'profile' (filtered profile data) and 'job_position'.
        
    Returns:
        HTML string for preview.
    """
    try:
        profile = request.get("profile", {})
        job_position = request.get("job_position", "")
        
        # Generate resume HTML using htmldocs
        from jobpilot.resume.generator import generate_resume_html_from_profile
        resume_html = generate_resume_html_from_profile(profile, job_position)
        
        return {"html": resume_html, "status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate preview: {str(e)}")


class PreviewResumeRequest(BaseModel):
    """Request model for resume preview."""
    profile: dict[str, Any] = {}
    job_position: str = ""
    
    class Config:
        # Allow extra fields and be more lenient with validation
        extra = "allow"
        # Use enum values for validation
        use_enum_values = True


@app.get("/api/jobs")
async def get_jobs(
    stage: str = "all",
    min_score: int | None = None,
    limit: int = 100,
    status: str | None = None,
    search: str | None = None
):
    """Get jobs/applications from the database.
    
    Args:
        stage: Filter by pipeline stage (discovered, enriched, scored, tailored, applied, all).
        min_score: Minimum fit score filter.
        limit: Maximum number of jobs to return.
        status: Filter by apply status (applied, failed, expired, etc.).
        search: Search term to match against job title and company name.
        
    Returns:
        List of job dictionaries.
    """
    from jobpilot.database import get_connection, get_jobs_by_stage, init_db
    
    try:
        # Ensure database is initialized
        conn = init_db()
        
        # Handle "failed" as a status filter, not a stage
        if stage == "failed":
            status = "failed"
            stage = "all"
        
        # Build query based on filters
        valid_stages = ["discovered", "enriched", "scored", "tailored", "applied", "pending_detail", "pending_score", "pending_tailor", "pending_apply"]
        
        if stage != "all" and stage in valid_stages:
            # Use the existing get_jobs_by_stage function, then filter by status and search if needed
            jobs = get_jobs_by_stage(conn, stage=stage, min_score=min_score, limit=limit * 2)  # Get more to filter
            
            # Apply status filter if specified
            if status:
                jobs = [j for j in jobs if j.get('apply_status') == status]
            
            # Apply search filter if specified
            if search:
                search_lower = search.lower()
                jobs = [
                    j for j in jobs
                    if (j.get('title') and search_lower in j.get('title', '').lower()) or
                       (j.get('company') and search_lower in j.get('company', '').lower())
                ]
            
            # Apply limit after filtering
            if limit > 0:
                jobs = jobs[:limit]
        else:
            # Query all jobs with optional filters
            query = "SELECT * FROM jobs WHERE 1=1"
            params = []
            
            if min_score is not None:
                query += " AND fit_score >= ?"
                params.append(min_score)
            
            if status:
                query += " AND apply_status = ?"
                params.append(status)
            
            if search:
                query += " AND (LOWER(title) LIKE ? OR LOWER(company) LIKE ?)"
                search_pattern = f"%{search.lower()}%"
                params.append(search_pattern)
                params.append(search_pattern)
            
            query += " ORDER BY fit_score DESC NULLS LAST, discovered_at DESC"
            
            if limit > 0:
                query += " LIMIT ?"
                params.append(limit)
            
            rows = conn.execute(query, params).fetchall()
            
            if rows:
                columns = rows[0].keys()
                jobs = [dict(zip(columns, row)) for row in rows]
            else:
                jobs = []
        
        # Convert to list of dicts and ensure all fields are JSON-serializable
        result = []
        for job in jobs:
            job_dict = {}
            for key, value in job.items():
                # Convert None to null, keep other values as-is
                job_dict[key] = value
            result.append(job_dict)
        
        return {"jobs": result, "count": len(result)}
    except Exception as e:
        import traceback
        error_detail = f"Failed to fetch jobs: {str(e)}\n{traceback.format_exc()}"
        raise HTTPException(status_code=500, detail=error_detail)


@app.delete("/api/jobs/{job_url:path}")
async def delete_job(job_url: str):
    """Delete a job from the database.
    
    Args:
        job_url: URL of the job to delete (URL-encoded).
        
    Returns:
        Success message.
    """
    from jobpilot.database import get_connection, init_db
    
    try:
        conn = init_db()
        
        # Check if job exists
        row = conn.execute(
            "SELECT url FROM jobs WHERE url = ?",
            (job_url,)
        ).fetchone()
        
        if not row:
            raise HTTPException(status_code=404, detail="Job not found")
        
        # Delete from database
        conn.execute("DELETE FROM jobs WHERE url = ?", (job_url,))
        conn.commit()
        
        return {"status": "ok", "message": "Job deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_detail = f"Failed to delete job: {str(e)}\n{traceback.format_exc()}"
        raise HTTPException(status_code=500, detail=error_detail)


@app.delete("/api/jobs/remote/all")
async def delete_all_remote_jobs():
    """Delete all remote jobs from the database.
    
    Identifies remote jobs by checking if location contains:
    "remote", "anywhere", "work from home", "wfh", "distributed"
    (case-insensitive).
    
    Returns:
        Success message with count of deleted jobs.
    """
    from jobpilot.database import get_connection, init_db
    
    try:
        conn = init_db()
        
        # Find all remote jobs
        # Check location field for remote keywords (case-insensitive)
        remote_keywords = ["remote", "anywhere", "work from home", "wfh", "distributed"]
        
        # Build SQL query to match any remote keyword
        conditions = " OR ".join([f"LOWER(location) LIKE ?" for _ in remote_keywords])
        params = [f"%{kw}%" for kw in remote_keywords]
        
        # First, count how many will be deleted
        count_query = f"SELECT COUNT(*) FROM jobs WHERE location IS NOT NULL AND ({conditions})"
        count = conn.execute(count_query, params).fetchone()[0]
        
        if count == 0:
            return {
                "status": "ok",
                "message": "No remote jobs found",
                "deleted_count": 0
            }
        
        # Delete remote jobs
        delete_query = f"DELETE FROM jobs WHERE location IS NOT NULL AND ({conditions})"
        conn.execute(delete_query, params)
        conn.commit()
        
        return {
            "status": "ok",
            "message": f"Deleted {count} remote job(s)",
            "deleted_count": count
        }
    except Exception as e:
        import traceback
        error_detail = f"Failed to delete remote jobs: {str(e)}\n{traceback.format_exc()}"
        raise HTTPException(status_code=500, detail=error_detail)


@app.post("/api/jobs/add")
async def add_job_by_url(request: dict):
    """Add a job from any URL. Uses the same enrichment logic as the apply pipeline.
    
    Args:
        request: Dict with 'url' key containing job URL.
                 Optional 'auto_score' (bool) to also score and tailor the job (default: False).
                 Optional 'min_score' (int) minimum score threshold for tailoring (default: 7).
        
    Returns:
        Success message with job details.
    """
    from jobpilot.apply.launcher import _auto_enrich_and_tailor
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    
    url = request.get("url", "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")
    
    auto_score = request.get("auto_score", False)
    min_score = request.get("min_score", 7)
    
    # Check if job already exists
    from jobpilot.database import get_connection
    conn = get_connection()
    existing = conn.execute(
        "SELECT url, full_description, tailored_resume_path, fit_score FROM jobs WHERE url = ? OR application_url = ?",
        (url, url)
    ).fetchone()
    
    if existing:
        if existing["tailored_resume_path"]:
            return {
                "status": "ok",
                "message": "Job already exists with tailored resume",
                "job_url": existing["url"],
                "new": False,
                "enriched": bool(existing["full_description"]),
                "tailored": True,
                "fit_score": existing["fit_score"]
            }
        elif existing["full_description"]:
            return {
                "status": "ok",
                "message": "Job already exists and is enriched",
                "job_url": existing["url"],
                "new": False,
                "enriched": True,
                "tailored": False,
                "fit_score": existing["fit_score"]
            }
    
    # If auto_score is False, only do enrich (set min_score to 0 so it doesn't return None)
    # If auto_score is True, do full pipeline (enrich + score + tailor if score >= min_score)
    try:
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor() as executor:
            # Use min_score=0 when auto_score=False to ensure function returns job even if score is low
            effective_min_score = 0 if not auto_score else min_score
            job = await loop.run_in_executor(
                executor,
                _auto_enrich_and_tailor,
                url,
                0,  # worker_id
                effective_min_score
            )
        
        if not job:
            raise HTTPException(status_code=500, detail="Failed to enrich job")
        
        enriched = bool(job.get("full_description"))
        tailored = bool(job.get("tailored_resume_path"))
        score = job.get("fit_score")
        
        message = "Job added successfully"
        if enriched:
            message += " and enriched"
        if tailored:
            message += f" and tailored (score: {score}/10)"
        elif auto_score and score is not None:
            message += f" and scored ({score}/10, below threshold for tailoring)"
        
        return {
            "status": "ok",
            "message": message,
            "job_url": job["url"],
            "new": True,
            "enriched": enriched,
            "tailored": tailored,
            "fit_score": score
        }
    except Exception as e:
        log.error(f"Failed to add job: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to add job: {str(e)}")


@app.post("/api/pipeline/run")
async def run_pipeline_api(request: dict[str, Any]):
    """Run pipeline stages.
    
    Request body:
        {
            "stages": ["discover", "enrich"] or null for all,
            "min_score": 7,
            "workers": 1,
            "stream": false,
            "validation": "normal"
        }
    """
    try:
        from jobpilot.pipeline import run_pipeline
        
        # Extract parameters from request
        stage_list = request.get("stages")
        if not stage_list:
            stage_list = ["all"]
        
        min_score = request.get("min_score", 7)
        workers = request.get("workers", 1)
        stream = request.get("stream", False)
        validation = request.get("validation", "normal")
        
        # Run pipeline (this is synchronous, but we'll run it in a thread pool)
        import asyncio
        loop = asyncio.get_event_loop()
        
        def run_sync():
            return run_pipeline(
                stages=stage_list,
                min_score=min_score,
                dry_run=False,
                stream=stream,
                workers=workers,
                validation_mode=validation,
            )
        
        result = await loop.run_in_executor(None, run_sync)
        
        return {
            "status": "ok",
            "result": result,
        }
    except Exception as e:
        import traceback
        error_detail = f"Pipeline failed: {str(e)}\n{traceback.format_exc()}"
        raise HTTPException(status_code=500, detail=error_detail)


# ---------------------------------------------------------------------------
# Cover Letter Templates endpoints
# ---------------------------------------------------------------------------

def _get_cover_letter_template_path(role_category: str) -> Path:
    """Get file path for a cover letter template by role_category.
    
    Uses the same format as cover_letter.py lookup: {role_category}.txt
    (role_category may contain spaces, which is fine for Path operations)
    """
    return BASE_COVER_LETTERS_DIR / f"{role_category}.txt"


@app.get("/api/cover-letters")
async def get_cover_letter_templates():
    """Get all cover letter templates (list of role_categories that have templates)."""
    try:
        ensure_dirs()
        templates = []
        
        # Get all .txt files in cover letters directory
        if BASE_COVER_LETTERS_DIR.exists():
            for file_path in BASE_COVER_LETTERS_DIR.glob("*.txt"):
                # Skip metadata files
                if file_path.name == "templates_meta.json":
                    continue
                
                role_category = file_path.stem
                try:
                    content = file_path.read_text(encoding="utf-8")
                    templates.append({
                        "role_category": role_category,
                        "content": content
                    })
                except Exception:
                    pass
        
        return {"templates": templates}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get cover letter templates: {str(e)}")


@app.get("/api/cover-letters/{role_category}")
async def get_cover_letter_template(role_category: str):
    """Get cover letter template for a specific role_category."""
    try:
        ensure_dirs()
        file_path = _get_cover_letter_template_path(role_category)
        
        if not file_path.exists():
            raise HTTPException(status_code=404, detail=f"Cover letter template not found for role_category: {role_category}")
        
        content = file_path.read_text(encoding="utf-8")
        return {
            "role_category": role_category,
            "content": content
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get cover letter template: {str(e)}")


class CoverLetterTemplateRequest(BaseModel):
    content: str


@app.put("/api/cover-letters/{role_category}")
async def set_cover_letter_template(role_category: str, request: CoverLetterTemplateRequest):
    """Set cover letter template for a role_category."""
    try:
        if not request.content:
            raise HTTPException(status_code=400, detail="Content is required")
        
        ensure_dirs()
        file_path = _get_cover_letter_template_path(role_category)
        file_path.write_text(request.content, encoding="utf-8")
        
        return {
            "status": "ok",
            "message": f"Cover letter template set for {role_category}",
            "role_category": role_category
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to set cover letter template: {str(e)}")


@app.delete("/api/cover-letters/{role_category}")
async def delete_cover_letter_template(role_category: str):
    """Delete cover letter template for a role_category."""
    try:
        ensure_dirs()
        file_path = _get_cover_letter_template_path(role_category)
        
        if not file_path.exists():
            raise HTTPException(status_code=404, detail=f"Cover letter template not found for role_category: {role_category}")
        
        file_path.unlink()
        
        return {"status": "ok", "message": f"Cover letter template deleted for {role_category}"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete cover letter template: {str(e)}")


# ---------------------------------------------------------------------------
# Auto-Apply endpoints
# ---------------------------------------------------------------------------

@app.post("/api/apply/start")
async def start_auto_apply(request: dict[str, Any]):
    """Start auto-apply pipeline.
    
    Request body:
        {
            "limit": 10,  # Max jobs to apply to (0 = continuous)
            "workers": 1,  # Number of parallel workers
            "min_score": 7,  # Minimum fit score
            "model": "sonnet",  # Claude model name
            "headless": False,  # Run Chrome headless
            "dry_run": False,  # Preview without submitting
            "continuous": False,  # Run forever
            "url": null  # Optional: apply to specific URL
        }
    """
    try:
        from jobpilot.apply.launcher import main as apply_main
        import asyncio
        from concurrent.futures import ThreadPoolExecutor
        
        # Extract parameters
        limit = request.get("limit", 1)
        workers = request.get("workers", 1)
        min_score = request.get("min_score", 7)
        model = request.get("model", "sonnet")
        headless = request.get("headless", False)
        dry_run = request.get("dry_run", False)
        continuous = request.get("continuous", False)
        target_url = request.get("url")
        poll_interval = request.get("poll_interval", 60)
        
        # Run apply in background thread (non-blocking)
        def run_apply():
            apply_main(
                limit=limit,
                target_url=target_url,
                min_score=min_score,
                headless=headless,
                model=model,
                dry_run=dry_run,
                continuous=continuous,
                poll_interval=poll_interval,
                workers=workers
            )
        
        # Start in background thread
        loop = asyncio.get_event_loop()
        loop.run_in_executor(None, run_apply)
        
        return {
            "status": "ok",
            "message": "Auto-apply started",
            "config": {
                "limit": limit,
                "workers": workers,
                "min_score": min_score,
                "model": model,
                "headless": headless,
                "dry_run": dry_run,
                "continuous": continuous
            }
        }
    except Exception as e:
        import traceback
        error_detail = f"Failed to start auto-apply: {str(e)}\n{traceback.format_exc()}"
        raise HTTPException(status_code=500, detail=error_detail)


@app.get("/api/apply/status")
async def get_apply_status():
    """Get current auto-apply status from dashboard."""
    try:
        from jobpilot.apply.dashboard import get_state, get_totals
        
        # Get status for all workers (assuming max 10 workers)
        workers_status = []
        for i in range(10):
            state = get_state(i)
            if state:
                workers_status.append({
                    "worker_id": i,
                    "status": state.status,
                    "job_title": state.job_title or "",
                    "company": state.company or "",
                    "score": state.score,
                    "actions": state.actions,
                    "last_action": state.last_action or "",
                    "jobs_applied": state.jobs_applied,
                    "jobs_failed": state.jobs_failed,
                    "total_cost": round(state.total_cost, 3)
                })
        
        totals = get_totals()
        
        return {
            "status": "ok",
            "workers": workers_status,
            "totals": {
                "applied": totals.get("applied", 0),
                "failed": totals.get("failed", 0),
                "cost": round(totals.get("cost", 0.0), 3)
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get apply status: {str(e)}")


# Serve static files in production (optional)
# In development, React dev server handles this
static_dir = Path(__file__).parent.parent.parent.parent / "frontend" / "dist"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
