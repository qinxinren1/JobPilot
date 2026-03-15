"""ATS (Applicant Tracking System) type detection.

Detects Greenhouse, Lever, Workday, and other ATS platforms
by analyzing URL patterns and page characteristics.
"""

import re
from typing import Optional


def detect_ats_type(url: str, page_content: str = "", dom_selectors: list[str] = None) -> str:
    """Detect ATS type from URL and page content.
    
    Args:
        url: Application URL
        page_content: HTML content (optional)
        dom_selectors: List of found DOM selectors (optional)
    
    Returns:
        ATS type: 'greenhouse', 'lever', 'workday', 'taleo', 
                 'icims', 'smartrecruiters', 'custom', 'unknown'
    """
    url_lower = url.lower()
    
    # URL pattern matching (most reliable)
    patterns = {
        'greenhouse': [
            r'greenhouse\.io',
            r'boards\.greenhouse\.io',
            r'jobs\.greenhouse\.io',
        ],
        'lever': [
            r'jobs\.lever\.co',
            r'lever\.co/.*apply',
        ],
        'workday': [
            r'myworkdayjobs\.com',
            r'workday\.com/.*careers',
            r'wd\d+\.myworkdayjobs\.com',
        ],
        'taleo': [
            r'taleo\.net',
            r'\.taleo\.com',
        ],
        'icims': [
            r'\.icims\.com',
            r'careers-.*\.icims\.com',
        ],
        'smartrecruiters': [
            r'smartrecruiters\.com',
            r'\.smartrecruiters\.com',
        ],
        'jobvite': [
            r'jobvite\.com',
            r'\.jobvite\.com',
        ],
        'bamboohr': [
            r'bamboohr\.com',
            r'\.bamboohr\.com',
        ],
    }
    
    for ats_type, pattern_list in patterns.items():
        for pattern in pattern_list:
            if re.search(pattern, url_lower):
                return ats_type
    
    # DOM-based detection (if page content available)
    if page_content:
        content_lower = page_content.lower()
        
        # Greenhouse indicators
        if any(indicator in content_lower for indicator in [
            'greenhouse.io',
            'gh-',
            'data-gh-',
        ]):
            return 'greenhouse'
        
        # Lever indicators
        if any(indicator in content_lower for indicator in [
            'lever.co',
            'lever-',
            'data-lever-',
        ]):
            return 'lever'
        
        # Workday indicators
        if any(indicator in content_lower for indicator in [
            'workday.com',
            'wd-',
            'data-automation-id',
        ]):
            return 'workday'
    
    # DOM selector-based detection
    if dom_selectors:
        selector_str = ' '.join(dom_selectors).lower()
        
        if 'greenhouse' in selector_str or 'gh-' in selector_str:
            return 'greenhouse'
        if 'lever' in selector_str:
            return 'lever'
        if 'workday' in selector_str or 'wd-' in selector_str:
            return 'workday'
    
    return 'unknown'


def get_ats_specific_instructions(ats_type: str) -> str:
    """Get ATS-specific application instructions.
    
    Returns instructions tailored to each ATS platform's quirks.
    """
    instructions = {
        'greenhouse': """
Greenhouse-specific notes:
- Often has multi-step form with progress indicator
- Resume upload usually triggers auto-fill
- Check all auto-filled fields carefully (often incorrect)
- May have "Add another" button for multiple entries
- Final review page before submit
""",
        'lever': """
Lever-specific notes:
- Resume upload page is separate from form
- Wait for resume parsing to complete before proceeding
- Form fields may be in accordion sections
- Often has "Add" buttons for work history/education
- Check for optional vs required fields
""",
        'workday': """
Workday-specific notes:
- Very long multi-page forms (5-10 pages)
- Resume upload triggers extensive auto-fill
- Many conditional fields based on previous answers
- Wait for each page to fully load before interacting
- "Next" button may be disabled until all required fields filled
- Final review page shows all entered data
""",
        'taleo': """
Taleo-specific notes:
- Often requires account creation first
- Multi-tab form interface
- Resume parsing can be slow
- May have security questions
""",
        'icims': """
iCIMS-specific notes:
- Resume upload on first page
- Auto-fill from resume
- May have skills assessment
- Check for duplicate entries
""",
    }
    
    return instructions.get(ats_type, "")


def is_manual_ats(url: str) -> bool:
    """Check if this ATS requires manual application (unsolvable CAPTCHAs)."""
    manual_patterns = [
        r'ibegin\.tcsapps\.com',
        # Add more manual-only ATS patterns here
    ]
    
    url_lower = url.lower()
    return any(re.search(pattern, url_lower) for pattern in manual_patterns)
