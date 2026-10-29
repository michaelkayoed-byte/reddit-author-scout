
"""
Reddit Author Scout — Extractor Module
======================================

Purpose:
    Parse saved HTML files and identify posts explicitly seeking:
    - Beta readers
    - Editors
    - Ghostwriters
    - Book marketers

Input:
    input_html/*.html
    input_html/*.htm

This module does not visit Reddit or open external links.
Google Docs URLs are captured as text only.

Diagnostic logging is built in.
"""

import logging
import re
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from bs4 import BeautifulSoup


logger = logging.getLogger("reddit-author-scout.extractor")


# --------------------------------------------------
# 1. SERVICE DETECTION RULES
# --------------------------------------------------

SERVICE_KEYWORDS = {
    "beta reader": [
        r"\bbeta[\s-]?readers?\b",
        r"\blooking for beta readers?\b",
        r"\bneed beta readers?\b",
    ],
    "editor": [
        r"\b(?:looking for|need|seeking|hiring|want)\s+(?:an?\s+)?(?:book\s+)?editors?\b",
        r"\b(?:developmental|copy|line|proofreading)\s+edit(?:or|ing|ors)\b",
        r"\bediting services?\b",
    ],
    "ghostwriter": [
        r"\bghostwriters?\b",
        r"\blooking for a ghostwriter\b",
        r"\bneed a ghostwriter\b",
        r"\bghostwriting services?\b",
    ],
    "book marketer": [
        r"\bbook marketers?\b",
        r"\bbook marketing services?\b",
        r"\blooking for (?:a )?book marketer\b",
        r"\bneed (?:a )?book marketing\b",
        r"\bbook promotion services?\b",
    ],
}


# --------------------------------------------------
# 2. GENERAL HELPERS
# --------------------------------------------------

def clean_text(value):
    """Normalize whitespace and safely convert values to text."""

    if value is None:
        return ""

    return re.sub(r"\s+", " ", str(value)).strip()


def canonical_url(url):
    """
    Normalize a URL for consistent storage and deduplication.
    Does not open or request the URL.
    """

    url = clean_text(url)

    if not url:
        return ""

    try:
        parsed = urlparse(url)

        if parsed.scheme not in ("http", "https"):
            return ""

        host = (parsed.hostname or "").lower()

        if not host:
            return ""

        if parsed.port:
            host = f"{host}:{parsed.port}"

        # Remove fragments and common tracking parameters.
        tracking_params = {
            "utm_source", "utm_medium", "utm_campaign",
            "utm_term", "utm_content", "ref", "ref_source",
        }

        query_parts = []
        for item in parsed.query.split("&"):
            if not item:
                continue

            key = item.split("=", 1)[0].lower()
            if key not in tracking_params:
                query_parts.append(item)

        query = "&".join(query_parts)

        path = parsed.path.rstrip("/")

        return urlunparse((
            "https",
            host,
            path,
            "",
            query,
            "",
        ))

    except (ValueError, TypeError):
        logger.warning("Could not normalize URL: %r", url)
        return ""


def extract_urls(text):
    """Find URLs in text without visiting them."""

    if not text:
        return []

    found = re.findall(
        r'https?://[^\s<>"\']+',
        text,
        flags=re.IGNORECASE,
    )

    cleaned = []
    for url in found:
        # Remove punctuation commonly attached to a URL in prose.
        url = url.rstrip(".,;:!?)\]}")

        if url not in cleaned:
            cleaned.append(url)

    return cleaned


def detect_services(text):
    """Return service categories supported by keyword evidence."""

    text_lower = clean_text(text).lower()
    matches = []

    for service, patterns in SERVICE_KEYWORDS.items():
        for pattern in patterns:
            if re.search(pattern, text_lower, flags=re.IGNORECASE):
                matches.append(service)
                break

    return matches


def extract_google_docs_urls(urls):
    """
    Keep Google Docs URLs as text only.
    This function never opens, clicks, downloads, or reads a document.
    """

    results = []

    for url in urls:
        try:
            host = (urlparse(url).hostname or "").lower()

            if host == "docs.google.com" or host == "drive.google.com":
                results.append(url)

        except ValueError:
            logger.warning("Invalid URL encountered while checking Docs link.")

    return results


def extract_social_links(urls):
    """Collect explicitly supplied links to common public social platforms."""

    social_domains = {
        "instagram.com",
        "www.instagram.com",
        "facebook.com",
        "www.facebook.com",
        "x.com",
        "www.x.com",
        "twitter.com",
        "www.twitter.com",
        "tiktok.com",
        "www.tiktok.com",
        "linkedin.com",
        "www.linkedin.com",
        "youtube.com",
        "www.youtube.com",
        "youtu.be",
        "threads.net",
        "www.threads.net",
    }

    results = []

    for url in urls:
        try:
            host = (urlparse(url).hostname or "").lower()

            if host in social_domains and url not in results:
                results.append(url)

        except ValueError:
            continue

    return results


def extract_email_addresses(text):
    """Extract email addresses explicitly written in the supplied text."""

    if not text:
        return []

    pattern = r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"

    return list(dict.fromkeys(
        re.findall(pattern, text, flags=re.IGNORECASE)
    ))


def extract_phone_numbers(text):
    """
    Identify phone-like strings explicitly included in post text.
    These are candidates, not verified phone numbers.
    """

    if not text:
        return []

    pattern = r"(?<!\w)(?:\+\d{1,3}[\s().-]?)?(?:\d[\s().-]?){7,14}\d(?!\w)"

    candidates = []

    for value in re.findall(pattern, text):
        digits = re.sub(r"\D", "", value)

        if 8 <= len(digits) <= 15:
            normalized = clean_text(value)

            if normalized not in candidates:
                candidates.append(normalized)

    return candidates


# --------------------------------------------------
# 3. HTML EXTRACTION
# --------------------------------------------------

def first_text(soup, selectors):
    """Return the first non-empty text matching CSS selectors."""

    for selector in selectors:
        element = soup.select_one(selector)

        if element:
            value = clean_text(element.get_text(" ", strip=True))

            if value:
                return value

    return ""


def first_attribute(soup, selectors, attribute):
    """Return the first non-empty attribute matching selectors."""

    for selector in selectors:
        element = soup.select_one(selector)

        if element:
            value = clean_text(element.get(attribute, ""))

            if value:
                return value

    return ""


def parse_html_file(file_path):
    """
    Parse one saved HTML file.

    Returns:
        A list of extracted post dictionaries.

    Note:
        Reddit page layouts vary. This parser supports common Reddit
        HTML attributes and metadata, but may need adjustment for the
        exact HTML format you save.
    """

    file_path = Path(file_path)

    logger.info("PARSING: %s", file_path.name)

    try:
        html = file_path.read_text(encoding="utf-8", errors="replace")
        soup = BeautifulSoup(html, "html.parser")

    except OSError:
        logger.exception("Could not read HTML file: %s", file_path)
        return []

    posts = []

    # New Reddit post containers often expose shreddit-post.
    # Also support article containers and older Reddit post links.
    containers = soup.select(
        "shreddit-post, article[data-testid='post-container']"
    )

    if not containers:
        logger.warning(
            "%s: No recognized post containers found. "
            "The page layout may require a selector adjustment.",
            file_path.name,
        )
        return []

    logger.info(
        "%s: Found %d possible post containers.",
        file_path.name,
        len(containers),
    )

    for index, container in enumerate(containers, start=1):
        try:
            title = (
                clean_text(container.get("post-title", ""))
                or first_text(container, [
                    "h1",
                    "h2",
                    "[slot='title']",
                    "[data-testid='post-title']",
                ])
            )

            body = (
                clean_text(container.get("post-text", ""))
                or first_text(container, [
                    "[slot='text-body']",
                    "[data-testid='post-content']",
                    "div.md",
                ])
            )

            username = (
                clean_text(container.get("author", ""))
                or first_attribute(container, [
                    "a[href*='/user/']",
                    "a[href*='/u/']",
                ], "href")
            )

            # Convert a profile href to its final path component.
            if username.startswith("/"):
                parts = username.strip("/").split("/")
                if len(parts) >= 2 and parts[0] in ("user", "u"):
                    username = parts[1]

            subreddit = clean_text(container.get("subreddit-name", ""))

            if not subreddit:
                subreddit = first_attribute(
                    container,
                    ["a[href*='/r/']"],
                    "href",
                )

                if subreddit.startswith("/r/"):
                    subreddit = subreddit.split("/")[2]

            post_url = (
                clean_text(container.get("permalink", ""))
                or first_attribute(container, [
                    "a[href*='/comments/']",
                ], "href")
            )

            if post_url.startswith("/"):
                post_url = "https://www.reddit.com" + post_url

            post_url = canonical_url(post_url)

            post_id = clean_text(container.get("id", ""))

            # Use Reddit's post ID if available; otherwise derive it
            # from a recognized comments permalink.
            if not post_id:
                match = re.search(r"/comments/([a-z0-9]+)/", post_url)
                if match:
                    post_id = match.group(1)

            published_at = (
                clean_text(container.get("created-timestamp", ""))
                or first_attribute(container, ["time"], "datetime")
            )

            full_text = clean_text(f"{title} {body}")
            services = detect_services(full_text)

            urls = extract_urls(body)
            docs_urls = extract_google_docs_urls(urls)
            social_links = extract_social_links(urls)
            emails = extract_email_addresses(body)
            phones = extract_phone_numbers(body)

            # Keep only posts matching one or more target services.
            if not services:
                logger.info(
                    "SKIPPED post %d in %s: no target service detected.",
                    index,
                    file_path.name,
                )
                continue

            lead = {
                "reddit_username": username,
                "profile_url": (
                    f"https://www.reddit.com/user/{username}/"
                    if username and not username.startswith("[")
                    else ""
                ),
                "post_title": title,
                "post_text": body,
                "service_needed": "; ".join(services),
                "email": "; ".join(emails),
                "social_links": "; ".join(social_links),
                "phone": "; ".join(phones),
                "google_docs_urls": "; ".join(docs_urls),
                "subreddit": subreddit,
                "post_date": published_at,
                "post_url": post_url,
                "post_id": post_id,
                "intent_evidence": (
                    "Matched service keywords: " + ", ".join(services)
                ),
                "source_html": file_path.name,
            }

            posts.append(lead)

            logger.info(
                "QUALIFIED post %d: services=%s | title=%r",
                index,
                ", ".join(services),
                title[:100],
            )

        except Exception:
            logger.exception(
                "Failed to extract post %d from %s. Continuing.",
                index,
                file_path.name,
            )

    logger.info(
        "COMPLETED: %s | qualified=%d | containers=%d",
        file_path.name,
        len(posts),
        len(containers),
    )

    return posts


# --------------------------------------------------
# 4. BATCH EXTRACTION
# --------------------------------------------------

def extract_from_directory(input_dir):
    """Parse all HTML files in a directory and return qualified leads."""

    input_dir = Path(input_dir)

    logger.info("=" * 55)
    logger.info("EXTRACTOR STARTED")
    logger.info("Input directory: %s", input_dir)

    if not input_dir.exists():
        logger.error("Input directory does not exist: %s", input_dir)
        return []

    if not input_dir.is_dir():
        logger.error("Input path is not a directory: %s", input_dir)
        return []

    files = sorted(
        list(input_dir.glob("*.html"))
        + list(input_dir.glob("*.htm"))
    )

    logger.info("TEST EXTRACTOR 1/2: HTML files found=%d", len(files))

    if not files:
        logger.warning("No HTML files to process.")
        return []

    all_leads = []
    failed_files = 0

    for file_path in files:
        try:
            all_leads.extend(parse_html_file(file_path))
        except Exception:
            failed_files += 1
            logger.exception("File processing failed: %s", file_path.name)

    logger.info("TEST EXTRACTOR 2/2: Batch processing finished.")
    logger.info("Files processed: %d", len(files))
    logger.info("Files with unhandled errors: %d", failed_files)
    logger.info("Qualified lead records: %d", len(all_leads))
    logger.info("EXTRACTOR FINISHED")

    return all_leads


# --------------------------------------------------
# 5. MODULE DIAGNOSTIC
# --------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    logger.info("TEST EXTRACTOR: Starting standalone diagnostic.")

    project_dir = Path(__file__).resolve().parent
    input_dir = project_dir / "input_html"

    results = extract_from_directory(input_dir)

    logger.info(
        "DIAGNOSTIC RESULT: Extractor returned %d qualified records.",
        len(results),
    )
    logger.info(
        "Note: results are currently in memory; database and CSV export "
        "will be connected in later stages."
    )
