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
load_env() # Load environment variables

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
        if "target_roles" in profile:
            # Sync searches.yaml from target_roles
            try:
                search_config = _generate_search_config_from_target_roles(profile, preserve_existing=True)
                _save_search_config(search_config)
            except Exception as e:
                # Log but don't fail the profile update
                import logging
                logging.warning(f"Failed to auto-sync searches.yaml from target_roles: {e}")
        
        # Save profile (with synced categories)
        PROFILE_PATH.write_text(
            json.dumps(profile, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        
        return {"status": "ok", "message": "Profile updated successfully"}
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
        if PROFILE_PATH.exists():
            profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        else:
            profile = {}
        
        # Update section
        profile[section_name] = section_data
        
        # Auto-sync: target_roles is the single source of truth
        if section_name == "target_roles":
            # Sync searches.yaml from target_roles
            try:
                search_config = _generate_search_config_from_target_roles(profile, preserve_existing=True)
                _save_search_config(search_config)
            except Exception as e:
                # Log but don't fail the section update
                import logging
                logging.warning(f"Failed to auto-sync searches.yaml from target_roles: {e}")
        
        # Save (with synced categories)
        ensure_dirs()
        PROFILE_PATH.write_text(
            json.dumps(profile, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        
        return {"status": "ok", "message": f"Section '{section_name}' updated successfully"}
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
    try:
        from jobpilot.config import load_search_config
        
        # If profile exists with target_roles, auto-generate queries from target_roles.name
        if PROFILE_PATH.exists():
            try:
                profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
                target_roles = profile.get("target_roles", {})
                
                if target_roles:
                    # Auto-generate search config from target_roles (queries from name field)
                    config = _generate_search_config_from_target_roles(profile, preserve_existing=True)
                    # Save the generated config to keep it in sync
                    _save_search_config(config)
                    return {"config": config}
            except Exception as e:
                # If generation fails, fall back to loading existing config
                import logging
                logging.debug(f"Failed to auto-generate from target_roles, using existing config: {e}")
        
        # Fall back to loading existing config
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
    try:
        if not PROFILE_PATH.exists():
            raise HTTPException(status_code=400, detail="Profile not found")
        
        profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        target_roles = profile.get("target_roles", {})
        
        if not target_roles:
            raise HTTPException(status_code=400, detail="No target_roles found in profile")
        
        search_config = _generate_search_config_from_target_roles(profile, preserve_existing=True)
        _save_search_config(search_config)
        
        return {
            "status": "ok",
            "message": "Search config synced from target_roles successfully",
            "queries_count": len(search_config.get("queries", []))
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to sync search config: {str(e)}")


# ---------------------------------------------------------------------------
# Helper functions for initialization
# ---------------------------------------------------------------------------

async def _save_resume_file(file: UploadFile):
    """Save resume file (PDF or TXT)."""
    if file.filename is None:
        raise HTTPException(status_code=400, detail="No filename provided")
    
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in [".pdf", ".txt"]:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Please upload a PDF or TXT file."
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
        f"  results_per_site: {results_per_site}",
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
        if file.filename is None:
            raise HTTPException(status_code=400, detail="No filename provided")
        
        file_ext = Path(file.filename).suffix.lower()
        if file_ext not in [".pdf", ".txt"]:
            raise HTTPException(
                status_code=400,
                detail="Unsupported file type. Please upload a PDF or TXT file."
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


@app.get("/api/resume/history")
async def get_resume_history(limit: int = 10):
    """Get resume upload history.
    
    Args:
        limit: Maximum number of history entries to return (default: 10).
        
    Returns:
        List of resume upload history entries.
    """
    from jobpilot.database import get_connection, init_resume_history_table
    
    conn = get_connection()
    init_resume_history_table(conn)
    
    rows = conn.execute(
        "SELECT id, uploaded_at, file_path, file_type FROM resume_history "
        "ORDER BY uploaded_at DESC LIMIT ?",
        (limit,)
    ).fetchall()
    
    history = []
    for row in rows:
        history.append({
            "id": row[0],
            "uploaded_at": row[1],
            "file_path": row[2],
            "file_type": row[3]
        })
    
    return {"history": history}


@app.get("/api/resumes")
async def get_resumes():
    """Get all resume templates.
    
    Returns:
        List of resume templates with metadata.
    """
    from jobpilot.database import get_connection, init_resume_templates_table
    
    conn = get_connection()
    init_resume_templates_table(conn)
    
    rows = conn.execute(
        "SELECT id, name, job_position, job_type, role_category, file_path, pdf_path, uploaded_at, is_default, file_size, file_type "
        "FROM resume_templates ORDER BY is_default DESC, uploaded_at DESC"
    ).fetchall()
    
    resumes = []
    for row in rows:
        resumes.append({
            "id": row[0],
            "name": row[1],
            "job_position": row[2],
            "job_type": row[3],
            "role_category": row[4],
            "file_path": row[5],
            "pdf_path": row[6],
            "uploaded_at": row[7],
            "is_default": bool(row[8]),
            "file_size": row[9],
            "file_type": row[10]
        })
    
    return {"resumes": resumes}


@app.post("/api/resumes/upload")
async def upload_resume_template(
    file: UploadFile = File(...),
    name: str = Form(""),
    job_position: str = Form(""),
    job_type: str = Form(""),
    role_category: str = Form(""),
    is_default: str = Form("false")
):
    """Upload a new resume template with metadata.
    
    Args:
        file: The resume PDF file to upload.
        name: Name/label for this resume template.
        job_position: Job position this resume is for (e.g., "Software Engineer", "Data Scientist").
        job_type: Job type (e.g., "Full-time", "Contract", "Intern").
        role_category: Target role category key from target_roles (e.g., "frontend", "backend").
        is_default: Whether this should be set as the default resume.
        
    Returns:
        Created resume template information.
    """
    from datetime import datetime, timezone
    from jobpilot.database import get_connection, init_resume_templates_table
    
    try:
        ensure_dirs()
        
        # Validate file type
        if file.filename is None:
            raise HTTPException(status_code=400, detail="No filename provided")
        
        file_ext = Path(file.filename).suffix.lower()
        if file_ext != ".pdf":
            raise HTTPException(
                status_code=400,
                detail="Only PDF files are supported for resume templates."
            )
        
        # Generate filename: Name_Category format (no timestamp, overwrite if same category)
        # Load profile to get name
        from jobpilot.config import load_profile
        try:
            profile = load_profile()
            personal = profile.get("personal", {})
            full_name = personal.get("full_name", "").strip()
            safe_name = "".join(c for c in full_name if c.isalnum() or c in (' ', '-', '_')).strip()
            safe_name = safe_name.replace(" ", "_") if safe_name else "Resume"
        except Exception:
            # Fallback if profile not available
            safe_name = "".join(c for c in (name or "Resume") if c.isalnum() or c in (' ', '-', '_')).strip()[:50]
            safe_name = safe_name.replace(" ", "_") if safe_name else "Resume"
        
        # Use role_category if provided, otherwise use name parameter
        if role_category:
            file_base_name = f"{safe_name}_{role_category}"
        else:
            # Fallback: use name parameter
            fallback_name = "".join(c for c in (name or "Resume") if c.isalnum() or c in (' ', '-', '_')).strip()[:50]
            fallback_name = fallback_name.replace(" ", "_") if fallback_name else "Resume"
            file_base_name = fallback_name
        
        saved_filename = f"{file_base_name}.pdf"
        saved_path = BASE_RESUMES_DIR / saved_filename
        saved_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Save file
        file_size = 0
        with open(saved_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
            file_size = saved_path.stat().st_size
        
        # If this is set as default, unset other defaults
        conn = get_connection()
        init_resume_templates_table(conn)
        
        # Convert string to boolean
        is_default_bool = is_default.lower() == "true"
        
        if is_default_bool:
            conn.execute("UPDATE resume_templates SET is_default = 0")
            conn.commit()
        
        # Insert into database
        conn.execute(
            "INSERT INTO resume_templates (name, job_position, job_type, role_category, file_path, pdf_path, uploaded_at, is_default, file_size, file_type) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                name or saved_filename,
                job_position or None,
                job_type or None,
                role_category or None,
                str(saved_path),
                str(saved_path),  # For PDFs, pdf_path is same as file_path
                datetime.now(timezone.utc).isoformat(),
                1 if is_default_bool else 0,
                file_size,
                "pdf"
            )
        )
        conn.commit()
        
        # Get the inserted record
        row = conn.execute(
            "SELECT id, name, job_position, job_type, role_category, file_path, pdf_path, uploaded_at, is_default, file_size, file_type "
            "FROM resume_templates WHERE id = last_insert_rowid()"
        ).fetchone()
        
        # Auto-link to target_roles.base_resume_path if role_category is provided
        if role_category:
            try:
                from jobpilot.scoring.scorer import _extract_text_from_html
                from jobpilot.config import load_profile
                from jobpilot.resume.parser import extract_text_from_pdf
                
                # Extract text from PDF template
                resume_text = extract_text_from_pdf(saved_path)
                
                # Update target_roles in profile
                profile = load_profile()
                
                # Save to base_resumes directory
                # Format: Name_Category.txt (no timestamp, overwrite if same category)
                personal = profile.get("personal", {})
                full_name = personal.get("full_name", "").strip()
                safe_name = "".join(c for c in full_name if c.isalnum() or c in (' ', '-', '_')).strip()
                safe_name = safe_name.replace(" ", "_") if safe_name else "Resume"
                base_resume_path = BASE_RESUMES_DIR / f"{safe_name}_{role_category}.txt"
                BASE_RESUMES_DIR.mkdir(parents=True, exist_ok=True)
                base_resume_path.write_text(resume_text, encoding="utf-8")
                target_roles = profile.get("target_roles", {})
                
                if role_category in target_roles:
                    target_roles[role_category]["base_resume_path"] = str(base_resume_path)
                    profile["target_roles"] = target_roles
                    PROFILE_PATH.write_text(
                        json.dumps(profile, indent=2, ensure_ascii=False),
                        encoding="utf-8"
                    )
                    log.info(f"Auto-linked resume template to target_roles['{role_category}'].base_resume_path")
            except Exception as e:
                # Log but don't fail the template upload
                log.warning(f"Failed to auto-link resume template to base_resume_path: {e}")
        
        return {
            "status": "ok",
            "message": "Resume template uploaded successfully",
            "resume": {
                "id": row[0],
                "name": row[1],
                "job_position": row[2],
                "job_type": row[3],
                "role_category": row[4],
                "file_path": row[5],
                "pdf_path": row[6],
                "uploaded_at": row[7],
                "is_default": bool(row[8]),
                "file_size": row[9],
                "file_type": row[10]
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to upload resume template: {str(e)}")


@app.delete("/api/resumes/{resume_id}")
async def delete_resume_template(resume_id: int):
    """Delete a resume template.
    
    Args:
        resume_id: ID of the resume template to delete.
        
    Returns:
        Success message.
    """
    from jobpilot.database import get_connection, init_resume_templates_table
    
    conn = get_connection()
    init_resume_templates_table(conn)
    
    # Get file path before deleting
    row = conn.execute(
        "SELECT file_path FROM resume_templates WHERE id = ?",
        (resume_id,)
    ).fetchone()
    
    if not row:
        raise HTTPException(status_code=404, detail="Resume template not found")
    
    file_path = Path(row[0])
    
    # Delete from database
    conn.execute("DELETE FROM resume_templates WHERE id = ?", (resume_id,))
    conn.commit()
    
    # Delete file if it exists
    if file_path.exists():
        try:
            file_path.unlink()
        except Exception as e:
            # Log but don't fail if file deletion fails
            import logging
            logging.warning(f"Failed to delete resume file {file_path}: {e}")
    
    return {"status": "ok", "message": "Resume template deleted successfully"}


@app.patch("/api/resumes/{resume_id}/default")
async def set_default_resume(resume_id: int):
    """Set a resume template as the default.
    
    Args:
        resume_id: ID of the resume template to set as default.
        
    Returns:
        Success message.
    """
    from jobpilot.database import get_connection, init_resume_templates_table
    
    conn = get_connection()
    init_resume_templates_table(conn)
    
    # Check if resume exists
    row = conn.execute(
        "SELECT id FROM resume_templates WHERE id = ?",
        (resume_id,)
    ).fetchone()
    
    if not row:
        raise HTTPException(status_code=404, detail="Resume template not found")
    
    # Unset all defaults
    conn.execute("UPDATE resume_templates SET is_default = 0")
    
    # Set this one as default
    conn.execute(
        "UPDATE resume_templates SET is_default = 1 WHERE id = ?",
        (resume_id,)
    )
    conn.commit()
    
    return {"status": "ok", "message": "Default resume updated successfully"}


@app.patch("/api/resumes/{resume_id}")
async def update_resume_template(
    resume_id: int,
    updates: dict[str, Any]
):
    """Update resume template metadata.
    
    Args:
        resume_id: ID of the resume template to update.
        name: New name for the resume.
        job_position: New job position.
        job_type: New job type.
        
    Returns:
        Updated resume template information.
    """
    from jobpilot.database import get_connection, init_resume_templates_table
    
    conn = get_connection()
    init_resume_templates_table(conn)
    
    # Check if resume exists
    row = conn.execute(
        "SELECT id FROM resume_templates WHERE id = ?",
        (resume_id,)
    ).fetchone()
    
    if not row:
        raise HTTPException(status_code=404, detail="Resume template not found")
    
    # Build update query dynamically
    update_fields = []
    params = []
    
    if "name" in updates:
        update_fields.append("name = ?")
        params.append(updates["name"])
    
    if "job_position" in updates:
        update_fields.append("job_position = ?")
        params.append(updates["job_position"] if updates["job_position"] else None)
    
    if "job_type" in updates:
        update_fields.append("job_type = ?")
        params.append(updates["job_type"] if updates["job_type"] else None)
    
    if "role_category" in updates:
        update_fields.append("role_category = ?")
        params.append(updates["role_category"] if updates["role_category"] else None)
    
    if not update_fields:
        raise HTTPException(status_code=400, detail="No fields to update")
    
    params.append(resume_id)
    
    query = f"UPDATE resume_templates SET {', '.join(update_fields)} WHERE id = ?"
    conn.execute(query, params)
    conn.commit()
    
    # Get updated record
    row = conn.execute(
        "SELECT id, name, job_position, job_type, role_category, file_path, pdf_path, uploaded_at, is_default, file_size, file_type "
        "FROM resume_templates WHERE id = ?",
        (resume_id,)
    ).fetchone()
    
    return {
        "status": "ok",
        "message": "Resume template updated successfully",
        "resume": {
            "id": row[0],
            "name": row[1],
            "job_position": row[2],
            "job_type": row[3],
            "role_category": row[4],
            "file_path": row[5],
            "pdf_path": row[6],
            "uploaded_at": row[7],
            "is_default": bool(row[8]),
            "file_size": row[9],
            "file_type": row[10]
        }
    }


def _generate_resume_html_with_htmldocs(profile: dict, job_position: str = "") -> str:
    """Generate resume HTML using htmldocs template.
    
    Args:
        profile: User profile dict.
        job_position: Optional job position/title for the resume.
        
    Returns:
        HTML string ready for PDF rendering.
    """
    from jobpilot.resume.generator import generate_resume_html_from_profile
    
    return generate_resume_html_from_profile(profile, job_position)




@app.post("/api/resumes/generate")
async def generate_resume_from_profile(
    name: str = Form(""),
    job_position: str = Form(""),
    job_type: str = Form(""),
    role_category: str = Form(""),
    is_default: str = Form("false"),
    profile_data: str = Form("")  # Optional filtered profile JSON
):
    """Generate a resume PDF from profile data and save as template.
    
    Args:
        name: Name/label for this resume template.
        job_position: Job position/title for the resume.
        job_type: Job type (e.g., "Full-time", "Contract", "Intern").
        role_category: Target role category key from target_roles (e.g., "frontend", "backend").
        is_default: Whether this should be set as the default resume.
        profile_data: Optional JSON string of filtered profile data (for ResumeFacts categories).
        
    Returns:
        Created resume template information.
    """
    from datetime import datetime, timezone
    from jobpilot.database import get_connection, init_resume_templates_table
    
    try:
        ensure_dirs()
        
        # Use provided profile_data if available, otherwise load from file
        if profile_data:
            try:
                profile = json.loads(profile_data)
            except json.JSONDecodeError:
                raise HTTPException(status_code=400, detail="Invalid profile_data JSON")
        else:
            # Load profile from file (existing behavior)
            if not PROFILE_PATH.exists():
                raise HTTPException(status_code=400, detail="Profile not found. Please complete your profile first.")
            profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        
        # Generate resume HTML using htmldocs
        resume_html = _generate_resume_html_with_htmldocs(profile, job_position)
        
        # Generate filename: Name_Category format (no timestamp, overwrite if same category)
        personal = profile.get("personal", {})
        full_name = personal.get("full_name", "").strip()
        safe_name = "".join(c for c in full_name if c.isalnum() or c in (' ', '-', '_')).strip()
        safe_name = safe_name.replace(" ", "_") if safe_name else "Resume"
        
        # Use role_category if provided, otherwise use a default
        if role_category:
            file_base_name = f"{safe_name}_{role_category}"
        else:
            # Fallback: use name parameter or default
            fallback_name = "".join(c for c in (name or "Resume") if c.isalnum() or c in (' ', '-', '_')).strip()[:50]
            fallback_name = fallback_name.replace(" ", "_") if fallback_name else "Resume"
            file_base_name = fallback_name
        
        # Save HTML file
        html_path = BASE_RESUMES_DIR / f"{file_base_name}.html"
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text(resume_html, encoding="utf-8")
        
        # Final PDF path
        final_pdf_path = BASE_RESUMES_DIR / f"{file_base_name}.pdf"
        
        # Convert HTML to PDF using Playwright - run in thread pool
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
        await loop.run_in_executor(None, render_html_to_pdf, resume_html, final_pdf_path)
        
        # Get file size (use PDF size)
        file_size = final_pdf_path.stat().st_size
        
        # Save to database
        conn = get_connection()
        init_resume_templates_table(conn)
        
        # Convert string to boolean
        is_default_bool = is_default.lower() == "true"
        
        if is_default_bool:
            conn.execute("UPDATE resume_templates SET is_default = 0")
            conn.commit()
        
        # Insert into database
        # file_path stores HTML, pdf_path stores PDF
        conn.execute(
            "INSERT INTO resume_templates (name, job_position, job_type, role_category, file_path, pdf_path, uploaded_at, is_default, file_size, file_type) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                name or f"Generated Resume {file_base_name}",
                job_position or None,
                job_type or None,
                role_category or None,
                str(html_path),  # HTML file path
                str(final_pdf_path),  # PDF file path
                datetime.now(timezone.utc).isoformat(),
                1 if is_default_bool else 0,
                file_size,
                "html"  # file_type indicates the source format
            )
        )
        conn.commit()
        
        # Get the inserted record
        row = conn.execute(
            "SELECT id, name, job_position, job_type, role_category, file_path, pdf_path, uploaded_at, is_default, file_size, file_type "
            "FROM resume_templates WHERE id = last_insert_rowid()"
        ).fetchone()
        
        # Auto-link to target_roles.base_resume_path if role_category is provided
        if role_category:
            try:
                from jobpilot.scoring.scorer import _extract_text_from_html
                from jobpilot.config import load_profile
                
                # Extract text from HTML template
                resume_text = _extract_text_from_html(html_path)
                
                # Update target_roles in profile
                profile = load_profile()
                
                # Save to base_resumes directory
                # Format: Name_Category.txt (no timestamp, overwrite if same category)
                personal = profile.get("personal", {})
                full_name = personal.get("full_name", "").strip()
                safe_name = "".join(c for c in full_name if c.isalnum() or c in (' ', '-', '_')).strip()
                safe_name = safe_name.replace(" ", "_") if safe_name else "Resume"
                base_resume_path = BASE_RESUMES_DIR / f"{safe_name}_{role_category}.txt"
                BASE_RESUMES_DIR.mkdir(parents=True, exist_ok=True)
                base_resume_path.write_text(resume_text, encoding="utf-8")
                target_roles = profile.get("target_roles", {})
                
                if role_category in target_roles:
                    target_roles[role_category]["base_resume_path"] = str(base_resume_path)
                    profile["target_roles"] = target_roles
                    PROFILE_PATH.write_text(
                        json.dumps(profile, indent=2, ensure_ascii=False),
                        encoding="utf-8"
                    )
                    log.info(f"Auto-linked resume template to target_roles['{role_category}'].base_resume_path")
            except Exception as e:
                # Log but don't fail the template save
                import logging
                logging.warning(f"Failed to auto-link resume template to base_resume_path: {e}")
        
        return {
            "status": "ok",
            "message": "Resume generated successfully from profile",
            "resume": {
                "id": row[0],
                "name": row[1],
                "job_position": row[2],
                "job_type": row[3],
                "role_category": row[4],
                "file_path": row[5],
                "pdf_path": row[6],
                "uploaded_at": row[7],
                "is_default": bool(row[8]),
                "file_size": row[9],
                "file_type": row[10]
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_detail = f"Failed to generate resume: {str(e)}\n{traceback.format_exc()}"
        raise HTTPException(status_code=500, detail=error_detail)


class GenerateBaseResumeRequest(BaseModel):
    role_key: str


class PreviewResumeRequest(BaseModel):
    """Request model for resume preview."""
    profile: dict[str, Any]
    job_position: str = ""


@app.post("/api/profile/preview-resume")
async def preview_resume(request: PreviewResumeRequest):
    """Generate a resume HTML preview from profile data.
    
    Args:
        request: Request body with 'profile' (filtered profile data) and 'job_position'.
        
    Returns:
        HTML string for preview.
    """
    try:
        profile = request.profile
        job_position = request.job_position or ""
        
        # Generate resume HTML using htmldocs
        resume_html = _generate_resume_html_with_htmldocs(profile, job_position)
        
        return {"html": resume_html, "status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate preview: {str(e)}")


@app.post("/api/profile/generate-base-resume")
async def generate_base_resume(request: GenerateBaseResumeRequest):
    """Generate a base resume text file from profile for a specific target role.
    
    Args:
        request: Request body with 'role_key' specifying which role to generate resume for.
        
    Returns:
        Status, message, and path to the generated base resume file.
    """
    from jobpilot.config import load_profile
    from jobpilot.resume.formatter import convert_profile_to_resume_props
    from jobpilot.resume.generator import generate_resume_html_from_profile
    
    try:
        ensure_dirs()
        
        role_key = request.role_key
        if not role_key:
            raise HTTPException(status_code=400, detail="role_key is required")
        
        # Load profile
        if not PROFILE_PATH.exists():
            raise HTTPException(status_code=400, detail="Profile not found. Please complete your profile first.")
        
        profile = load_profile()
        target_roles = profile.get("target_roles", {})
        
        if role_key not in target_roles:
            raise HTTPException(
                status_code=400,
                detail=f"Role '{role_key}' not found in target_roles. Please configure it first."
            )
        
        role_config = target_roles[role_key]
        role_name = role_config.get("name", role_key)
        
        # Generate resume text directly from profile (optimized for this role)
        # Build text resume from profile data, emphasizing role-specific skills
        from jobpilot.resume.formatter import (
            convert_profile_to_resume_props,
            format_contact_line,
            format_location,
            extract_handle_from_url,
        )
        
        personal = profile.get("personal", {})
        experience_data = profile.get("experience", {})
        skills_boundary = profile.get("skills_boundary", {})
        resume_facts = profile.get("resume_facts", {})
        
        lines: list[str] = []
        
        # Header
        lines.append(personal.get("full_name", ""))
        lines.append(role_name)  # Use role name as title
        
        # Contact - reuse formatter utilities
        contact_line = format_contact_line(personal, use_handles=False)
        if contact_line:
            lines.append(contact_line)
        lines.append("")
        
        # Summary (role-specific)
        summary_parts = []
        if experience_data.get("years_of_experience_total"):
            summary_parts.append(f"{experience_data['years_of_experience_total']} years of experience")
        summary_parts.append(f"Seeking {role_name} positions")
        if role_config.get("skills_emphasis"):
            skills_str = ", ".join(role_config["skills_emphasis"][:3])
            summary_parts.append(f"Expertise in {skills_str}")
        lines.append("SUMMARY")
        lines.append(". ".join(summary_parts) + ".")
        lines.append("")
        
        # Technical Skills (emphasize role-specific skills)
        lines.append("TECHNICAL SKILLS")
        if role_config.get("skills_emphasis"):
            # Put emphasized skills first
            emphasized = role_config["skills_emphasis"]
            other_skills = []
            for category, items in skills_boundary.items():
                if isinstance(items, list):
                    for item in items:
                        if item not in emphasized:
                            other_skills.append(item)
            all_skills = emphasized + other_skills
            lines.append(", ".join(all_skills[:20]))  # Limit to top 20
        else:
            # Default: show all skills
            all_skills = []
            for category, items in skills_boundary.items():
                if isinstance(items, list):
                    all_skills.extend(items)
            lines.append(", ".join(all_skills[:20]))
        lines.append("")
        
        # Experience
        lines.append("EXPERIENCE")
        work_experiences = experience_data.get("work_experiences", [])
        for exp in work_experiences[:5]:  # Limit to 5 most recent
            title = exp.get("title", "")
            company = exp.get("company", "")
            if title and company:
                lines.append(f"{title} at {company}")
            elif title:
                lines.append(title)
            if exp.get("location"):
                lines.append(exp.get("location", ""))
            dates = f"{exp.get('start_date', '')} - {exp.get('end_date', 'Present' if exp.get('current') else '')}"
            if dates.strip() != "-":
                lines.append(dates)
            for bullet in exp.get("bullets", [])[:4]:  # Limit bullets
                lines.append(f"- {bullet}")
            lines.append("")
        
        # Projects
        lines.append("PROJECTS")
        projects = experience_data.get("projects", [])
        for proj in projects[:3]:  # Limit to 3 projects
            name = proj.get("name", "")
            if name:
                lines.append(name)
            if proj.get("description"):
                lines.append(proj.get("description", ""))
            for bullet in proj.get("bullets", [])[:2]:  # Limit bullets
                lines.append(f"- {bullet}")
            lines.append("")
        
        # Education
        lines.append("EDUCATION")
        education_list = experience_data.get("education", [])
        for edu in education_list:
            school = edu.get("school", "")
            degree = edu.get("degree", "")
            if school and degree:
                lines.append(f"{school} | {degree}")
            elif school:
                lines.append(school)
        
        resume_text = "\n".join(lines)
        
        # Save to base_resumes directory
        # Format: Name_Category.txt (no timestamp, overwrite if same category)
        full_name = personal.get("full_name", "").strip()
        safe_name = "".join(c for c in full_name if c.isalnum() or c in (' ', '-', '_')).strip()
        safe_name = safe_name.replace(" ", "_") if safe_name else "Resume"
        base_resume_path = BASE_RESUMES_DIR / f"{safe_name}_{role_key}.txt"
        base_resume_path.write_text(resume_text, encoding="utf-8")
        
        # Update profile with the path if it's different
        if role_config.get("base_resume_path") != str(base_resume_path):
            target_roles[role_key]["base_resume_path"] = str(base_resume_path)
            profile["target_roles"] = target_roles
            PROFILE_PATH.write_text(json.dumps(profile, indent=2), encoding="utf-8")
        
        return {
            "status": "ok",
            "message": f"Base resume generated successfully for {role_name}",
            "path": str(base_resume_path),
        }
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_detail = f"Failed to generate base resume: {str(e)}\n{traceback.format_exc()}"
        raise HTTPException(status_code=500, detail=error_detail)


@app.post("/api/profile/upload-base-resume")
async def upload_base_resume(
    file: UploadFile = File(...),
    role_key: str = Form(...),
    path: str = Form("")
):
    """Upload a base resume file for a specific target role.
    
    Args:
        file: The resume file to upload (TXT or PDF).
        role_key: The target role key this resume is for.
        path: Optional custom path. If not provided, uses default path.
        
    Returns:
        Status, message, and path to the saved base resume file.
    """
    from jobpilot.config import load_profile
    
    try:
        ensure_dirs()
        
        if not role_key:
            raise HTTPException(status_code=400, detail="role_key is required")
        
        # Load profile
        if not PROFILE_PATH.exists():
            raise HTTPException(status_code=400, detail="Profile not found. Please complete your profile first.")
        
        profile = load_profile()
        target_roles = profile.get("target_roles", {})
        
        if role_key not in target_roles:
            raise HTTPException(
                status_code=400,
                detail=f"Role '{role_key}' not found in target_roles. Please configure it first."
            )
        
        # Validate file type
        if file.filename is None:
            raise HTTPException(status_code=400, detail="No filename provided")
        
        file_ext = Path(file.filename).suffix.lower()
        if file_ext not in [".txt", ".pdf"]:
            raise HTTPException(
                status_code=400,
                detail="Unsupported file type. Please upload a TXT or PDF file."
            )
        
        # Determine save path
        if path:
            base_resume_path = Path(path).expanduser()
        else:
            # Format: Name_Category.txt (no timestamp, overwrite if same category)
            personal = profile.get("personal", {})
            full_name = personal.get("full_name", "").strip()
            safe_name = "".join(c for c in full_name if c.isalnum() or c in (' ', '-', '_')).strip()
            safe_name = safe_name.replace(" ", "_") if safe_name else "Resume"
            base_resume_path = BASE_RESUMES_DIR / f"{safe_name}_{role_key}.txt"
        
        # Ensure directory exists
        base_resume_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Save file
        if file_ext == ".pdf":
            # Extract text from PDF
            from jobpilot.resume.parser import extract_text_from_pdf
            with open(base_resume_path.with_suffix(".pdf"), "wb") as f:
                shutil.copyfileobj(file.file, f)
            text = extract_text_from_pdf(base_resume_path.with_suffix(".pdf"))
            base_resume_path.write_text(text, encoding="utf-8")
        else:
            # Save as text
            content = await file.read()
            base_resume_path.write_text(content.decode("utf-8"), encoding="utf-8")
        
        # Update profile with the path
        target_roles[role_key]["base_resume_path"] = str(base_resume_path)
        profile["target_roles"] = target_roles
        PROFILE_PATH.write_text(json.dumps(profile, indent=2), encoding="utf-8")
        
        return {
            "status": "ok",
            "message": f"Base resume uploaded successfully for {target_roles[role_key]['name']}",
            "path": str(base_resume_path),
        }
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_detail = f"Failed to upload base resume: {str(e)}\n{traceback.format_exc()}"
        raise HTTPException(status_code=500, detail=error_detail)


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


@app.post("/api/jobs/add-linkedin")
async def add_linkedin_job(request: dict):
    """Add a job from a LinkedIn URL using enrichment module to parse it.
    
    Supports multiple LinkedIn URL formats:
    - Direct job: https://www.linkedin.com/jobs/view/1234567890
    - Collections: https://www.linkedin.com/jobs/collections/recommended/?currentJobId=1234567890
    - Search results: https://www.linkedin.com/jobs/search-results/?currentJobId=1234567890&...
    
    Args:
        request: Dict with 'url' key containing LinkedIn job URL.
        
    Returns:
        Success message with job details.
    """
    from jobpilot.database import init_db
    from jobpilot.enrichment.detail import scrape_detail_page
    from datetime import datetime, timezone
    from urllib.parse import urlparse, parse_qs
    from playwright.sync_api import sync_playwright
    import logging
    
    log = logging.getLogger(__name__)
    
    try:
        linkedin_url = request.get("url", "").strip()
        if not linkedin_url:
            raise HTTPException(status_code=400, detail="URL is required")
        
        # Normalize the URL - extract job ID and convert to standard format
        normalized_url = linkedin_url
        
        # Check if it's a search results URL with currentJobId parameter
        if "linkedin.com/jobs/search-results" in linkedin_url or "linkedin.com/jobs/collections" in linkedin_url:
            parsed = urlparse(linkedin_url)
            params = parse_qs(parsed.query)
            
            if "currentJobId" in params:
                job_id = params["currentJobId"][0]
                # Convert to standard view URL format
                normalized_url = f"https://www.linkedin.com/jobs/view/{job_id}"
            else:
                raise HTTPException(status_code=400, detail="Could not extract job ID from LinkedIn URL")
        
        # Validate it's a LinkedIn job URL
        if "linkedin.com/jobs" not in normalized_url:
            raise HTTPException(status_code=400, detail="Invalid LinkedIn job URL")
        
        conn = init_db()
        now = datetime.now(timezone.utc).isoformat()
        
        # Check if job already exists (check both original and normalized URL)
        existing = conn.execute(
            "SELECT url FROM jobs WHERE url = ? OR url = ?",
            (linkedin_url, normalized_url)
        ).fetchone()
        
        if existing:
            return {
                "status": "ok",
                "message": "Job already exists in database",
                "job_url": existing[0],
                "new": False
            }
        
        # Create a basic job entry first
        conn.execute(
            "INSERT INTO jobs (url, title, description, site, strategy, discovered_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (normalized_url, None, None, "linkedin", "manual", now),
        )
        conn.commit()
        
        log.info(f"Scraping LinkedIn job with enrichment module: {normalized_url}")
        
        # Use enrichment module to scrape the job details
        # Run in a thread to avoid blocking the async event loop
        import asyncio
        from concurrent.futures import ThreadPoolExecutor
        
        def scrape_job_sync():
            """Synchronous scraping function to run in thread pool."""
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )
                page = context.new_page()
                
                # Use the enrichment module's scrape_detail_page function
                result = scrape_detail_page(page, normalized_url)
                
                # Extract title from the page before closing
                title = None
                try:
                    title = page.title()
                    # Clean up title (remove " | LinkedIn" suffix)
                    if title and " | LinkedIn" in title:
                        title = title.replace(" | LinkedIn", "").strip()
                except Exception:
                    pass
                
                result["extracted_title"] = title
                browser.close()
                return result
        
        try:
            # Run synchronous Playwright code in thread pool
            loop = asyncio.get_event_loop()
            with ThreadPoolExecutor() as executor:
                result = await loop.run_in_executor(executor, scrape_job_sync)
            
            # Update the job with scraped information
            if result.get("status") in ("ok", "partial"):
                # Get title from the result (extracted before closing browser)
                title = result.get("extracted_title")
                
                conn.execute(
                    "UPDATE jobs SET full_description = ?, application_url = ?, "
                    "detail_scraped_at = ?, title = ?, detail_error = NULL "
                    "WHERE url = ?",
                    (
                        result.get("full_description"),
                        result.get("application_url"),
                        now,
                        title,
                        normalized_url
                    ),
                )
                conn.commit()
                
                tier = result.get("tier_used", "unknown")
                desc_len = len(result.get("full_description") or "")
                
                return {
                    "status": "ok",
                    "message": f"Job parsed and added successfully (Tier {tier}, {desc_len} chars).",
                    "job_url": normalized_url,
                    "new": True,
                    "tier": tier,
                    "description_length": desc_len
                }
            else:
                # Enrichment failed, but job is still added
                error_msg = result.get("error", "unknown error")
                conn.execute(
                    "UPDATE jobs SET detail_error = ? WHERE url = ?",
                    (error_msg, normalized_url)
                )
                conn.commit()
                
                return {
                    "status": "ok",
                    "message": f"Job added but enrichment failed: {error_msg}. You can try enrichment again later.",
                    "job_url": normalized_url,
                    "new": True,
                    "error": error_msg
                }
                
        except Exception as e:
            log.error(f"Enrichment scraping failed: {e}")
            import traceback
            error_detail = str(e)
            conn.execute(
                "UPDATE jobs SET detail_error = ? WHERE url = ?",
                (error_detail[:200], normalized_url)
            )
            conn.commit()
            
            return {
                "status": "ok",
                "message": f"Job added but enrichment failed: {error_detail}. You can try enrichment again later.",
                "job_url": normalized_url,
                "new": True,
                "error": error_detail
            }
            
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_detail = f"Failed to add LinkedIn job: {str(e)}\n{traceback.format_exc()}"
        raise HTTPException(status_code=500, detail=error_detail)


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

# Metadata file for cover letter templates
COVER_LETTER_TEMPLATES_META = BASE_COVER_LETTERS_DIR / "templates_meta.json"

def _load_cover_letter_templates_meta() -> dict:
    """Load cover letter templates metadata from JSON file."""
    ensure_dirs()
    if not COVER_LETTER_TEMPLATES_META.exists():
        return {"templates": [], "next_id": 1}
    try:
        data = json.loads(COVER_LETTER_TEMPLATES_META.read_text(encoding="utf-8"))
        # Ensure next_id exists for backward compatibility
        if "next_id" not in data:
            max_id = max([t.get("id", 0) for t in data.get("templates", [])], default=0)
            data["next_id"] = max_id + 1
        return data
    except Exception:
        return {"templates": [], "next_id": 1}

def _save_cover_letter_templates_meta(data: dict):
    """Save cover letter templates metadata to JSON file."""
    ensure_dirs()
    COVER_LETTER_TEMPLATES_META.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

def _get_cover_letter_template_file_path(template_id: int, role_category: str) -> Path:
    """Get file path for a cover letter template."""
    # Generate safe filename from role_category
    safe_name = "".join(c for c in role_category if c.isalnum() or c in (' ', '-', '_')).strip()
    safe_name = safe_name.replace(" ", "_") if safe_name else "template"
    return BASE_COVER_LETTERS_DIR / f"{template_id}_{safe_name}.txt"

@app.get("/api/cover-letters")
async def get_cover_letter_templates():
    """Get all cover letter templates."""
    try:
        ensure_dirs()
        meta = _load_cover_letter_templates_meta()
        templates = []
        
        for template in meta.get("templates", []):
            file_path = Path(template.get("file_path", ""))
            content = ""
            if file_path.exists():
                try:
                    content = file_path.read_text(encoding="utf-8")
                except Exception:
                    pass
            
            templates.append({
                "id": template.get("id"),
                "name": template.get("name", ""),
                "role_category": template.get("role_category", ""),
                "content": content,
                "created_at": template.get("created_at", ""),
                "updated_at": template.get("updated_at", ""),
                "is_default": template.get("is_default", False)
            })
        
        # Sort by is_default DESC, updated_at DESC
        templates.sort(key=lambda x: (not x["is_default"], x["updated_at"] or ""), reverse=True)
        
        return {"templates": templates}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get cover letter templates: {str(e)}")


class CreateCoverLetterTemplateRequest(BaseModel):
    name: str  # Auto-generated from role_category, but kept for backward compatibility
    role_category: str
    content: str
    is_default: bool = False


@app.post("/api/cover-letters")
async def create_cover_letter_template(request: CreateCoverLetterTemplateRequest):
    """Create a new cover letter template.
    
    Args:
        request: Template data with name, role_category, content, and is_default.
        
    Returns:
        Created template information.
    """
    from datetime import datetime, timezone
    
    try:
        if not request.role_category or not request.content:
            raise HTTPException(status_code=400, detail="Role category and content are required")
        
        ensure_dirs()
        meta = _load_cover_letter_templates_meta()
        
        # Auto-generate name from role_category
        from jobpilot.config import load_profile
        role_name = request.role_category
        try:
            profile = load_profile()
            target_roles = profile.get("target_roles", {})
            role_config = target_roles.get(request.role_category, {})
            role_name = role_config.get("name", request.role_category)
        except Exception:
            # Fallback to role_category as name
            role_name = request.role_category
        
        # If this is set as default, unset other defaults
        if request.is_default:
            for template in meta.get("templates", []):
                template["is_default"] = False
        
        # Generate new ID
        template_id = meta.get("next_id", 1)
        meta["next_id"] = template_id + 1
        
        now = datetime.now(timezone.utc).isoformat()
        
        # Save content to file
        file_path = _get_cover_letter_template_file_path(template_id, request.role_category)
        file_path.write_text(request.content, encoding="utf-8")
        
        # Add template metadata
        new_template = {
            "id": template_id,
            "name": role_name,
            "role_category": request.role_category,
            "file_path": str(file_path),
            "created_at": now,
            "updated_at": now,
            "is_default": request.is_default
        }
        meta["templates"].append(new_template)
        _save_cover_letter_templates_meta(meta)
        
        return {
            "status": "ok",
            "message": "Cover letter template created successfully",
            "template": {
                "id": new_template["id"],
                "name": new_template["name"],
                "role_category": new_template["role_category"],
                "content": request.content,
                "created_at": new_template["created_at"],
                "updated_at": new_template["updated_at"],
                "is_default": new_template["is_default"]
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_detail = f"Failed to create cover letter template: {str(e)}\n{traceback.format_exc()}"
        raise HTTPException(status_code=500, detail=error_detail)


class UpdateCoverLetterTemplateRequest(BaseModel):
    name: str = None
    role_category: str = None
    content: str = None
    is_default: bool = None


@app.patch("/api/cover-letters/{template_id}")
async def update_cover_letter_template(template_id: int, request: UpdateCoverLetterTemplateRequest):
    """Update a cover letter template."""
    from datetime import datetime, timezone
    
    try:
        ensure_dirs()
        meta = _load_cover_letter_templates_meta()
        
        # Find template
        template = None
        for t in meta.get("templates", []):
            if t.get("id") == template_id:
                template = t
                break
        
        if not template:
            raise HTTPException(status_code=404, detail="Cover letter template not found")
        
        # Update fields
        updated = False
        
        if request.role_category is not None:
            template["role_category"] = request.role_category
            # Auto-update name when role_category changes
            if request.role_category:
                from jobpilot.config import load_profile
                try:
                    profile = load_profile()
                    target_roles = profile.get("target_roles", {})
                    role_config = target_roles.get(request.role_category, {})
                    template["name"] = role_config.get("name", request.role_category)
                except Exception:
                    template["name"] = request.role_category
            updated = True
        
        # Allow manual name update if provided
        if request.name is not None:
            if request.role_category is None:
                template["name"] = request.name
                updated = True
        
        if request.content is not None:
            # Update content file
            file_path = Path(template.get("file_path", ""))
            if not file_path.exists():
                # Create new file path if old one doesn't exist
                file_path = _get_cover_letter_template_file_path(template_id, template.get("role_category", ""))
                template["file_path"] = str(file_path)
            file_path.write_text(request.content, encoding="utf-8")
            updated = True
        
        if request.is_default is not None:
            if request.is_default:
                # Unset all defaults first
                for t in meta.get("templates", []):
                    t["is_default"] = False
            template["is_default"] = request.is_default
            updated = True
        
        if updated:
            template["updated_at"] = datetime.now(timezone.utc).isoformat()
            _save_cover_letter_templates_meta(meta)
        
        # Read content from file
        file_path = Path(template.get("file_path", ""))
        content = ""
        if file_path.exists():
            try:
                content = file_path.read_text(encoding="utf-8")
            except Exception:
                pass
        
        return {
            "status": "ok",
            "message": "Cover letter template updated successfully",
            "template": {
                "id": template["id"],
                "name": template["name"],
                "role_category": template["role_category"],
                "content": content,
                "created_at": template.get("created_at", ""),
                "updated_at": template.get("updated_at", ""),
                "is_default": template.get("is_default", False)
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update cover letter template: {str(e)}")


@app.delete("/api/cover-letters/{template_id}")
async def delete_cover_letter_template(template_id: int):
    """Delete a cover letter template."""
    try:
        ensure_dirs()
        meta = _load_cover_letter_templates_meta()
        
        # Find and remove template
        template = None
        for i, t in enumerate(meta.get("templates", [])):
            if t.get("id") == template_id:
                template = t
                # Delete content file
                file_path = Path(template.get("file_path", ""))
                if file_path.exists():
                    try:
                        file_path.unlink()
                    except Exception:
                        pass
                # Remove from metadata
                meta["templates"].pop(i)
                break
        
        if not template:
            raise HTTPException(status_code=404, detail="Cover letter template not found")
        
        _save_cover_letter_templates_meta(meta)
        
        return {"status": "ok", "message": "Cover letter template deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete cover letter template: {str(e)}")


@app.patch("/api/cover-letters/{template_id}/default")
async def set_default_cover_letter_template(template_id: int):
    """Set a cover letter template as the default."""
    from datetime import datetime, timezone
    
    try:
        ensure_dirs()
        meta = _load_cover_letter_templates_meta()
        
        # Find template
        template = None
        for t in meta.get("templates", []):
            if t.get("id") == template_id:
                template = t
                break
        
        if not template:
            raise HTTPException(status_code=404, detail="Cover letter template not found")
        
        # Unset all defaults
        for t in meta.get("templates", []):
            t["is_default"] = False
        
        # Set this one as default
        template["is_default"] = True
        template["updated_at"] = datetime.now(timezone.utc).isoformat()
        
        _save_cover_letter_templates_meta(meta)
        
        return {"status": "ok", "message": "Default cover letter template updated"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to set default cover letter template: {str(e)}")


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
