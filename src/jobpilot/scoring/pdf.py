"""PDF conversion for resumes and cover letters using Playwright.

This module provides simple text-to-PDF conversion using Playwright.
For resume generation from profile data, use the htmldocs template via the API.
"""

import logging
from pathlib import Path

log = logging.getLogger(__name__)


def convert_to_pdf(
    text_path: Path, output_path: Path | None = None, html_only: bool = False
) -> Path:
    """Convert a text resume/cover letter to PDF.

    This is a simple converter that creates a basic HTML document from text
    and converts it to PDF using Playwright.

    Args:
        text_path: Path to the .txt file to convert.
        output_path: Optional override for the output path. Defaults to same
            name with .pdf extension.
        html_only: If True, output HTML instead of PDF.

    Returns:
        Path to the generated PDF (or HTML) file.
    """
    from playwright.sync_api import sync_playwright

    text_path = Path(text_path)
    text = text_path.read_text(encoding="utf-8")

    # Create simple HTML from text
    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
@page {{
    size: A4;
    margin: 1in;
}}
body {{
    font-family: 'Calibri', 'Segoe UI', Arial, sans-serif;
    font-size: 11pt;
    line-height: 1.6;
    color: #1a1a1a;
    white-space: pre-wrap;
}}
</style>
</head>
<body>
{text}
</body>
</html>"""

    if html_only:
        out = output_path or text_path.with_suffix(".html")
        out = Path(out)
        out.write_text(html, encoding="utf-8")
        log.info("HTML generated: %s", out)
        return out

    out = output_path or text_path.with_suffix(".pdf")
    out = Path(out)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(html, wait_until="networkidle")
        page.pdf(
            path=str(out),
            format="A4",
            print_background=True,
        )
        browser.close()

    log.info("PDF generated: %s", out)
    return out


def batch_convert(limit: int = 50) -> int:
    """Convert HTML files in TAILORED_DIR to PDFs (legacy .txt files also supported).

    Scans for .html files (and legacy .txt files), checks if a .pdf with the same
    stem already exists, and converts any that are missing.

    Args:
        limit: Maximum number of files to convert.

    Returns:
        Number of PDFs generated.
    """
    from jobpilot.config import TAILORED_DIR
    from playwright.sync_api import sync_playwright

    if not TAILORED_DIR.exists():
        log.warning("Tailored directory does not exist: %s", TAILORED_DIR)
        return 0

    # Look for HTML files first (new format), then legacy .txt files
    html_files = sorted(TAILORED_DIR.glob("*.html"))
    txt_files = sorted(TAILORED_DIR.glob("*.txt"))
    
    # Exclude _JOB.txt and _CL.txt files from resume conversion
    txt_candidates = [
        f for f in txt_files
        if not f.name.endswith("_JOB.txt") and not f.name.endswith("_CL.txt")
    ]
    
    candidates = list(html_files) + txt_candidates

    # Filter to those without a corresponding PDF
    to_convert: list[Path] = []
    for f in candidates:
        pdf_path = f.with_suffix(".pdf")
        if not pdf_path.exists():
            to_convert.append(f)
        if len(to_convert) >= limit:
            break

    if not to_convert:
        log.info("All files already have PDFs.")
        return 0

    log.info("Converting %d files to PDF...", len(to_convert))
    converted = 0
    
    with sync_playwright() as p:
        browser = p.chromium.launch()
        
        for f in to_convert:
            try:
                if f.suffix == ".html":
                    # HTML to PDF using Playwright
                    html_content = f.read_text(encoding="utf-8")
                    page = browser.new_page()
                    page.set_content(html_content, wait_until="networkidle")
                    page.pdf(
                        path=str(f.with_suffix(".pdf")),
                        format="A4",
                        print_background=True,
                    )
                    page.close()
                else:
                    # Legacy .txt to PDF using old converter
                    convert_to_pdf(f)
                converted += 1
            except Exception as e:
                log.error("Failed to convert %s: %s", f.name, e)
        
        browser.close()

    log.info("Done: %d/%d PDFs generated in %s", converted, len(to_convert), TAILORED_DIR)
    return converted
