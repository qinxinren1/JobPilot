"""JobSpy-based job discovery: searches Indeed and LinkedIn.

Uses python-jobspy to scrape job boards, deduplicates results,
parses salary ranges, and stores everything in the JobPilot database.

Search queries, locations, and filtering rules are loaded from the user's
search configuration YAML (searches.yaml) rather than being hardcoded.
"""

import logging
import sqlite3
import time
from datetime import datetime, timezone

from jobspy import scrape_jobs

from jobpilot import config
from jobpilot.database import get_connection, init_db, store_jobs

log = logging.getLogger(__name__)


# -- Proxy parsing -----------------------------------------------------------

def parse_proxy(proxy_str: str) -> dict:
    """Parse host:port:user:pass into components."""
    parts = proxy_str.split(":")
    if len(parts) == 4:
        host, port, user, passwd = parts
        return {
            "host": host,
            "port": port,
            "user": user,
            "pass": passwd,
            "jobspy": f"{user}:{passwd}@{host}:{port}",
            "playwright": {
                "server": f"http://{host}:{port}",
                "username": user,
                "password": passwd,
            },
        }
    elif len(parts) == 2:
        host, port = parts
        return {
            "host": host,
            "port": port,
            "user": None,
            "pass": None,
            "jobspy": f"{host}:{port}",
            "playwright": {"server": f"http://{host}:{port}"},
        }
    else:
        raise ValueError(
            f"Proxy format not recognized: {proxy_str}. "
            f"Expected: host:port:user:pass or host:port"
        )


# -- Retry wrapper -----------------------------------------------------------

def _scrape_with_retry(kwargs: dict, max_retries: int = 2, backoff: float = 5.0):
    """Call scrape_jobs with retry on transient failures."""
    for attempt in range(max_retries + 1):
        try:
            return scrape_jobs(**kwargs)
        except Exception as e:
            err = str(e).lower()
            transient = any(k in err for k in ("timeout", "429", "proxy", "connection", "reset", "refused"))
            if transient and attempt < max_retries:
                wait = backoff * (attempt + 1)
                log.warning("Retry %d/%d in %.0fs: %s", attempt + 1, max_retries, wait, e)
                time.sleep(wait)
            else:
                raise


# -- Location filtering ------------------------------------------------------

def _load_location_config(search_cfg: dict) -> tuple[list[str], list[str]]:
    """Extract accept/reject location lists from search config.

    Falls back to sensible defaults if not defined in the YAML.
    """
    accept = search_cfg.get("location_accept", [])
    reject = search_cfg.get("location_reject_non_remote", [])
    return accept, reject


# -- Experience level filtering ----------------------------------------------

def _title_matches_level(title: str | None, levels: str | list[str]) -> bool:
    """Check if a job title matches any of the specified experience levels.
    
    Args:
        title: Job title string (case-insensitive matching)
        levels: One or more of 'entry-level', 'senior', 'manager', 'director', 'executive'
                Can also use legacy levels: 'junior', 'graduate', 'mid' (mapped to 'entry-level')
                Can be a string (single level) or list (multiple levels)
                If empty list or None, matches all (no filtering)
    
    Returns:
        True if title matches any of the levels, False otherwise.
        If levels is empty or None, always returns True (no filtering).
    """
    if not title:
        return True
    
    # Convert to list if single string
    if isinstance(levels, str):
        levels = [levels]
    
    # If levels is empty or None, match all (no filtering)
    if not levels or len(levels) == 0:
        return True
    
    # Backward compatibility: if 'all' is in the list, always match
    if "all" in levels:
        return True
    
    # Map legacy levels to new levels
    level_mapping = {
        "junior": "entry-level",
        "graduate": "entry-level",
        "mid": "entry-level",  # Mid-level maps to entry-level for now
    }
    
    # Convert legacy levels to new levels
    mapped_levels = []
    for level in levels:
        if level in level_mapping:
            mapped_levels.append(level_mapping[level])
        else:
            mapped_levels.append(level)
    
    title_lower = title.lower()
    
    # Keywords for each level
    level_keywords = {
        "entry-level": {
            # Include: entry, intern, trainee, new grad, fresh grad, graduate, junior, associate
            "include": ["entry", "entry-level", "entry level", "intern", "internship", "trainee", "new grad", "fresh grad", "graduate", "junior", "jr.", "jr ", "associate"],
            # Exclude: senior, lead, principal, staff, director, manager, head, chief, executive
            "exclude": ["senior", "lead", "principal", "staff", "director", "manager", "head", "chief", "executive", "vp", "vice president", "sr.", "sr "]
        },
        "senior": {
            "include": ["senior", "sr.", "sr ", "lead", "principal", "staff"],
            "exclude": ["director", "manager", "head", "chief", "executive", "vp", "vice president", "president", "ceo", "cto", "cfo"]
        },
        "manager": {
            "include": ["manager", "management", "mgr", "head of"],
            "exclude": ["director", "executive", "vp", "vice president", "president", "ceo", "cto", "cfo", "chief"]
        },
        "director": {
            "include": ["director", "head of"],
            "exclude": ["executive", "vp", "vice president", "president", "ceo", "cto", "cfo", "chief"]
        },
        "executive": {
            "include": ["executive", "vp", "vice president", "president", "ceo", "cto", "cfo", "chief"],
            "exclude": []
        }
    }
    
    # Check if title matches any of the specified levels
    for level in mapped_levels:
        if level not in level_keywords:
            continue
        
        keywords = level_keywords[level]
        matches = True
        
        # If include keywords exist, title must contain at least one
        if keywords["include"]:
            has_include = any(kw in title_lower for kw in keywords["include"])
            if not has_include:
                matches = False
                continue
        
        # Title must not contain any exclude keywords
        if keywords["exclude"]:
            has_exclude = any(kw in title_lower for kw in keywords["exclude"])
            if has_exclude:
                matches = False
                continue
        
        # If we get here, this level matches
        if matches:
            return True
    
    # None of the levels matched
    return False


def _location_ok(location: str | None, accept: list[str], reject: list[str]) -> bool:
    """Check if a job location passes the user's location filter.

    Remote jobs are always accepted. Non-remote jobs must match an accept
    pattern and not match a reject pattern.
    
    If accept list is empty, all non-remote jobs are accepted (no filtering).
    """
    if not location:
        return True  # unknown location -- keep it, let scorer decide

    loc = location.lower()

    # Remote jobs always OK
    if any(r in loc for r in ("remote", "anywhere", "work from home", "wfh", "distributed")):
        return True

    # Reject non-remote matches
    for r in reject:
        if r.lower() in loc:
            return False

    # If accept list is empty, accept all (no filtering)
    if not accept or len(accept) == 0:
        return True

    # Accept matches
    for a in accept:
        if a.lower() in loc:
            return True

    # No match -- reject unknown (only if accept list was not empty)
    return False


# -- DB storage (JobSpy DataFrame -> SQLite) ---------------------------------

def store_jobspy_results(conn: sqlite3.Connection, df, source_label: str, experience_level: str | list[str] | None = None) -> tuple[int, int]:
    """Store JobSpy DataFrame results into the DB. Returns (new, existing).
    
    Args:
        conn: Database connection
        df: JobSpy DataFrame
        source_label: Label for the search query
        experience_level: Filter by experience level(s). Can be None/empty (no filtering), 
                         a single level string, or a list of levels. 
                         Valid levels: 'entry-level', 'senior', 'manager', 'director', 'executive'.
                         For backward compatibility, 'all' means no filtering.
    """
    now = datetime.now(timezone.utc).isoformat()
    new = 0
    existing = 0

    for _, row in df.iterrows():
        url = str(row.get("job_url", ""))
        if not url or url == "nan":
            continue

        title = str(row.get("title", "")) if str(row.get("title", "")) != "nan" else None
        
        # Filter by experience level
        if not _title_matches_level(title, experience_level):
            continue
        company = str(row.get("company", "")) if str(row.get("company", "")) != "nan" else None
        location_str = str(row.get("location", "")) if str(row.get("location", "")) != "nan" else None

        # Build salary string from min/max
        salary = None
        min_amt = row.get("min_amount")
        max_amt = row.get("max_amount")
        interval = str(row.get("interval", "")) if str(row.get("interval", "")) != "nan" else ""
        currency = str(row.get("currency", "")) if str(row.get("currency", "")) != "nan" else ""
        if min_amt and str(min_amt) != "nan":
            if max_amt and str(max_amt) != "nan":
                salary = f"{currency}{int(float(min_amt)):,}-{currency}{int(float(max_amt)):,}"
            else:
                salary = f"{currency}{int(float(min_amt)):,}"
            if interval:
                salary += f"/{interval}"

        description = str(row.get("description", "")) if str(row.get("description", "")) != "nan" else None
        site_name = str(row.get("site", source_label))
        is_remote = row.get("is_remote", False)

        site_label = f"{site_name}"
        if is_remote:
            location_str = f"{location_str} (Remote)" if location_str else "Remote"

        strategy = "jobspy"

        # If JobSpy gave us a full description, promote it directly
        full_description = None
        detail_scraped_at = None
        if description and len(description) > 200:
            full_description = description
            detail_scraped_at = now

        # Extract apply URL if JobSpy provided it
        apply_url = str(row.get("job_url_direct", "")) if str(row.get("job_url_direct", "")) != "nan" else None

        try:
            conn.execute(
                "INSERT INTO jobs (url, title, company, salary, description, location, site, strategy, discovered_at, "
                "full_description, application_url, detail_scraped_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (url, title, company, salary, description, location_str, site_label, strategy, now,
                 full_description, apply_url, detail_scraped_at),
            )
            new += 1
        except sqlite3.IntegrityError:
            existing += 1

    conn.commit()
    return new, existing


# -- Single search execution -------------------------------------------------

def _run_one_search(
    search: dict,
    sites: list[str],
    results_per_site: int | None,
    hours_old: int,
    proxy_config: dict | None,
    defaults: dict,
    max_retries: int,
    accept_locs: list[str],
    reject_locs: list[str],
) -> dict:
    """Run a single search query and store results in DB.
    
    Args:
        results_per_site: Maximum results per site. Set to 0 or None to get all available results.
    """
    s = search
    label = f"\"{s['query']}\" in {s['location']} {'(remote)' if s.get('remote') else ''}"
    if "tier" in s:
        label += f" [tier {s['tier']}]"

    # Filter sites to only allow linkedin and indeed
    allowed_sites = ["linkedin", "indeed"]
    filtered_sites = [si for si in sites if si in allowed_sites]
    
    if not filtered_sites:
        log.warning("[%s] No valid sites (only linkedin and indeed are supported), skipping", label)
        return {"new": 0, "existing": 0, "errors": 1, "filtered": 0, "total": 0, "label": label}
    
    if len(filtered_sites) < len(sites):
        removed = [si for si in sites if si not in allowed_sites]
        log.warning("[%s] Removed unsupported sites: %s (only linkedin and indeed are supported)", label, ", ".join(removed))

    # If results_per_site is 0 or None, set to a large number to get all results
    # JobSpy doesn't support unlimited, so we use a large number as a workaround
    if results_per_site and results_per_site > 0:
        effective_results = results_per_site
        results_info = f"{effective_results} per site"
    else:
        effective_results = 10000  # Large number to get all available results
        results_info = "all available"
    
    kwargs = {
        "site_name": filtered_sites,
        "search_term": s["query"],
        "location": s["location"],
        "results_wanted": effective_results,
        "hours_old": hours_old,
        "description_format": "markdown",
        "country_indeed": defaults.get("country_indeed", "netherlands"),
        "verbose": 0,
    }
    if s.get("remote"):
        kwargs["is_remote"] = True
    if proxy_config:
        kwargs["proxies"] = [proxy_config["jobspy"]]
    if "linkedin" in filtered_sites:
        kwargs["linkedin_fetch_description"] = True
        log.info("[%s] LinkedIn full description enabled (may be slow)", label)
    
    try:
        log.info("[%s] Waiting for sites to complete...", label)
        df = _scrape_with_retry(kwargs, max_retries=max_retries)
        log.info("[%s] All sites completed: %d results", label, len(df))
        if "site" in df.columns and len(df) > 0:
            site_counts = df["site"].value_counts()
            for site, count in site_counts.items():
                log.info("[%s]   %s: %d results", label, site, count)
    except Exception as e:
        log.error("[%s] Search failed: %s", label, e)
        return {"new": 0, "existing": 0, "errors": 1, "filtered": 0, "total": 0, "label": label}

    if len(df) == 0:
        log.info("[%s] 0 results", label)
        return {"new": 0, "existing": 0, "errors": 0, "filtered": 0, "total": 0, "label": label}

    log.info("[%s] Starting filtering and storage...", label)
    # Filter by location before storing
    before = len(df)
    df = df[df.apply(lambda row: _location_ok(
        str(row.get("location", "")) if str(row.get("location", "")) != "nan" else None,
        accept_locs, reject_locs,
    ), axis=1)]
    location_filtered = before - len(df)
    
    # Filter by experience level (same logic as search_jobs)
    experience_level_raw = defaults.get("experience_level", [])
    # Convert to list if single string (backward compatibility)
    if isinstance(experience_level_raw, str):
        experience_level_list = [experience_level_raw]
    elif isinstance(experience_level_raw, list):
        experience_level_list = experience_level_raw
    else:
        experience_level_list = []
    
    # Backward compatibility: if 'all' is specified, don't filter
    if "all" in experience_level_list:
        experience_level_list = []
    
    level_filtered = 0
    if len(experience_level_list) > 0:
        before_level = len(df)
        df = df[df.apply(lambda row: _title_matches_level(
            str(row.get("title", "")) if str(row.get("title", "")) != "nan" else None,
            experience_level_list
        ), axis=1)]
        level_filtered = before_level - len(df)
        if level_filtered > 0:
            log.info("[%s] Filtered %d jobs by experience level (%s)", label, level_filtered, ", ".join(experience_level_list))
    filtered = location_filtered + level_filtered

    conn = get_connection()
    # Pass None if empty list (same as search_jobs)
    experience_level_for_store = experience_level_list if experience_level_list else None
    new, existing = store_jobspy_results(conn, df, s["query"], experience_level_for_store)

    msg = f"[{label}] {before} results -> {new} new, {existing} dupes"
    if location_filtered:
        msg += f", {location_filtered} filtered (location)"
    if level_filtered:
        level_str = ", ".join(experience_level_list) if isinstance(experience_level_list, list) else str(experience_level_list)
        msg += f", {level_filtered} filtered (level: {level_str})"

    return {"new": new, "existing": existing, "errors": 0, "filtered": filtered, "total": before, "label": label}


# -- Single query search -----------------------------------------------------

def search_jobs(
    query: str,
    location: str,
    sites: list[str] | None = None,
    remote_only: bool = False,
    results_per_site: int | None = 50,
    hours_old: int = 72,
    proxy: str | None = None,
    country_indeed: str = "netherlands",
    experience_level: str | list[str] | None = None,
) -> dict:
    """Run a single job search via JobSpy and store results in DB.
    
    Args:
        query: Search query string
        location: Location string
        sites: List of sites to search (default: ["indeed", "linkedin"])
        remote_only: If True, only search for remote jobs
        results_per_site: Maximum results per site. Set to 0 or None to get all available results.
        hours_old: Only jobs posted within this many hours
        proxy: Proxy string (host:port:user:pass or host:port)
        country_indeed: Country code for Indeed searches
        experience_level: Filter by experience level(s). Can be None/empty (no filtering),
                         a single level string, or a list of levels.
                         Valid levels: 'entry-level', 'senior', 'manager', 'director', 'executive'.
                         For backward compatibility, 'all' means no filtering.
    """
    if sites is None:
        sites = ["indeed", "linkedin"]

    proxy_config = parse_proxy(proxy) if proxy else None

    # Convert experience_level to list if needed
    if isinstance(experience_level, str):
        experience_level_list = [experience_level]
    elif isinstance(experience_level, list):
        experience_level_list = experience_level
    else:
        experience_level_list = []
    
    # Backward compatibility: if 'all' is specified, don't filter
    if "all" in experience_level_list:
        experience_level_list = []

    log.info("Search: \"%s\" in %s | sites=%s | remote=%s | results=%s | level=%s", 
             query, location, sites, remote_only, results_info, experience_level_list or "all")

    # If results_per_site is 0 or None, set to a large number to get all results
    # JobSpy doesn't support unlimited, so we use a large number as a workaround
    if results_per_site and results_per_site > 0:
        effective_results = results_per_site
        results_info = f"{effective_results} per site"
    else:
        effective_results = 10000  # Large number to get all available results
        results_info = "all available"
    
    kwargs = {
        "site_name": sites,
        "search_term": query,
        "location": location,
        "results_wanted": effective_results,
        "hours_old": hours_old,
        "description_format": "markdown",
        "country_indeed": country_indeed,
        "verbose": 2,
    }

    if remote_only:
        kwargs["is_remote"] = True

    if proxy_config:
        kwargs["proxies"] = [proxy_config["jobspy"]]

    if "linkedin" in sites:
        kwargs["linkedin_fetch_description"] = True

    try:
        df = scrape_jobs(**kwargs)
    except Exception as e:
        log.error("JobSpy search failed: %s", e)
        return {"error": str(e), "total": 0, "new": 0, "existing": 0, "filtered": 0}

    total = len(df)
    log.info("JobSpy returned %d results", total)

    if total == 0:
        return {"total": 0, "new": 0, "existing": 0, "filtered": 0}

    if "site" in df.columns:
        site_counts = df["site"].value_counts()
        for site, count in site_counts.items():
            log.info("  %s: %d", site, count)

    # Filter by experience level before storing
    level_filtered = 0
    if len(experience_level_list) > 0:
        before_level = len(df)
        df = df[df.apply(lambda row: _title_matches_level(
            str(row.get("title", "")) if str(row.get("title", "")) != "nan" else None,
            experience_level_list
        ), axis=1)]
        level_filtered = before_level - len(df)
        if level_filtered > 0:
            log.info("Filtered %d jobs by experience level (%s)", level_filtered, ", ".join(experience_level_list))

    conn = init_db()
    new, existing = store_jobspy_results(conn, df, query, experience_level_list if experience_level_list else None)
    log.info("Stored: %d new, %d already in DB", new, existing)
    if level_filtered > 0:
        log.info("Filtered: %d jobs (experience level)", level_filtered)

    db_total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    pending = conn.execute("SELECT COUNT(*) FROM jobs WHERE detail_scraped_at IS NULL").fetchone()[0]
    log.info("DB total: %d jobs, %d pending detail scrape", db_total, pending)

    return {"total": total, "new": new, "existing": existing, "filtered": level_filtered}


# -- Full crawl (all queries x all locations) --------------------------------

def _full_crawl(
    search_cfg: dict,
    tiers: list[int] | None = None,
    locations: list[str] | None = None,
    sites: list[str] | None = None,
    results_per_site: int | None = 100,
    hours_old: int = 72,
    proxy: str | None = None,
    max_retries: int = 2,
) -> dict:
    """Run all search queries from search config across all locations.
    
    Args:
        results_per_site: Maximum results per site. Set to 0 or None to get all available results.
    """
    if sites is None:
        sites = ["indeed", "linkedin"]

    # Build search combinations from config
    queries = search_cfg.get("queries", [])
    locs = search_cfg.get("locations", [])
    defaults = search_cfg.get("defaults", {})
    accept_locs, reject_locs = _load_location_config(search_cfg)

    if tiers:
        queries = [q for q in queries if q.get("tier") in tiers]
    if locations:
        locs = [loc for loc in locs if loc.get("label") in locations]

    searches = []
    for q in queries:
        for loc in locs:
            searches.append({
                "query": q["query"],
                "location": loc["location"],
                "remote": loc.get("remote", False),
                "tier": q.get("tier", 0),
            })

    proxy_config = parse_proxy(proxy) if proxy else None

    # Determine results info for logging
    if results_per_site and results_per_site > 0:
        results_info = f"{results_per_site} per site"
    else:
        results_info = "all available"
    
    log.info("Full crawl: %d search combinations", len(searches))
    log.info("Sites: %s | Results: %s | Hours old: %d",
             ", ".join(sites), results_info, hours_old)

    # Ensure DB schema is ready
    init_db()

    total_new = 0
    total_existing = 0
    total_errors = 0
    completed = 0

    for s in searches:
        result = _run_one_search(
            s, sites, results_per_site, hours_old,
            proxy_config, defaults, max_retries,
            accept_locs, reject_locs,
        )
        completed += 1
        total_new += result["new"]
        total_existing += result["existing"]
        total_errors += result["errors"]

        if completed % 5 == 0 or completed == len(searches):
            log.info("Progress: %d/%d queries done (%d new, %d dupes, %d errors)",
                     completed, len(searches), total_new, total_existing, total_errors)

    # Final stats
    conn = get_connection()
    db_total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]

    log.info("Full crawl complete: %d new | %d dupes | %d errors | %d total in DB",
             total_new, total_existing, total_errors, db_total)

    return {
        "new": total_new,
        "existing": total_existing,
        "errors": total_errors,
        "db_total": db_total,
        "queries": len(searches),
    }


# -- Public entry point ------------------------------------------------------

def run_discovery(cfg: dict | None = None) -> dict:
    """Main entry point for JobSpy-based job discovery.

    Loads search queries and locations from the user's search config YAML,
    then runs a full crawl across all configured job boards.

    Args:
        cfg: Override the search configuration dict. If None, loads from
             the user's searches.yaml file.

    Returns:
        Dict with stats: new, existing, errors, db_total, queries.
    """
    if cfg is None:
        cfg = config.load_search_config()

    if not cfg:
        log.warning("No search configuration found. Please configure in web interface.")
        return {"new": 0, "existing": 0, "errors": 0, "db_total": 0, "queries": 0}

    proxy = cfg.get("proxy")
    sites = cfg.get("sites")
    results_per_site = cfg.get("defaults", {}).get("results_per_site", 100)
    hours_old = cfg.get("defaults", {}).get("hours_old", 72)
    tiers = cfg.get("tiers")
    locations = cfg.get("location_labels")

    return _full_crawl(
        search_cfg=cfg,
        tiers=tiers,
        locations=locations,
        sites=sites,
        results_per_site=results_per_site,
        hours_old=hours_old,
        proxy=proxy,
    )
