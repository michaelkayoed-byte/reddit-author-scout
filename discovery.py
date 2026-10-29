
"""
Reddit Author Scout — Discovery Module
======================================

Finds matching Reddit posts using PRAW and an authorized Reddit API
connection. Does not use Chromium, bypass access restrictions, or open
external links.

Environment variables:
    REDDIT_CLIENT_ID
    REDDIT_CLIENT_SECRET
    REDDIT_USER_AGENT

Optional settings:
    SCOUT_SUBREDDITS=all
    SCOUT_START_DATE=2026-10-20
    SCOUT_END_DATE=2026-10-28
    SCOUT_LIMIT_PER_QUERY=50

Date filtering uses the original post publication timestamp in UTC.
"""

import logging
import os
import re
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

try:
    import praw
except ImportError:
    praw = None

from extractor import (
    canonical_url,
    detect_services,
    extract_urls,
    extract_google_docs_urls,
    extract_social_links,
    extract_email_addresses,
    extract_phone_numbers,
)

logger = logging.getLogger("reddit-author-scout.discovery")


# --------------------------------------------------
# 1. SEARCH CONFIGURATION
# --------------------------------------------------

SEARCH_TERMS = [
    "beta reader",
    "beta readers",
    "looking for beta readers",
    "need beta reader",
    "looking for editor",
    "need an editor",
    "book editor",
    "ghostwriter",
    "looking for ghostwriter",
    "book marketing",
    "book marketer",
]

REQUEST_PATTERN = re.compile(
    r"\b("
    r"looking for|in search of|seeking|need|needs|needing|"
    r"want to hire|looking to hire|hiring|wanted|"
    r"anyone know|any recommendations|recommendations for|"
    r"where can i find|would love to find|"
    r"can anyone recommend|does anyone know"
    r")\b",
    re.IGNORECASE,
)


# --------------------------------------------------
# 2. API CONFIGURATION
# --------------------------------------------------

def create_reddit_client():
    """Create a read-only PRAW client from environment variables."""

    logger.info("TEST DISCOVERY 1/4: Checking API configuration.")

    if praw is None:
        raise RuntimeError(
            "PRAW is not installed. Run: "
            "python -m pip install praw"
        )

    client_id = os.getenv("REDDIT_CLIENT_ID", "").strip()
    client_secret = os.getenv("REDDIT_CLIENT_SECRET", "").strip()
    user_agent = os.getenv("REDDIT_USER_AGENT", "").strip()

    missing = []

    if not client_id:
        missing.append("REDDIT_CLIENT_ID")
    if not client_secret:
        missing.append("REDDIT_CLIENT_SECRET")
    if not user_agent:
        missing.append("REDDIT_USER_AGENT")

    if missing:
        raise RuntimeError(
            "Missing environment variables: "
            + ", ".join(missing)
            + ". Configure authorized Reddit API credentials first."
        )

    reddit = praw.Reddit(
        client_id=client_id,
        client_secret=client_secret,
        user_agent=user_agent,
        check_for_async=False,
    )

    # Read-only operation: this program will not post, vote, or message.
    reddit.read_only = True

    logger.info("TEST DISCOVERY 1/4 PASSED: Client configured.")
    return reddit


# --------------------------------------------------
# 3. DATE AND SUBREDDIT SETTINGS
# --------------------------------------------------

def parse_date(value, setting_name):
    """Parse a YYYY-MM-DD date, or return None when not provided."""

    if not value:
        return None

    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            f"{setting_name} must use YYYY-MM-DD format; got {value!r}"
        ) from exc


def get_date_window(start_date=None, end_date=None):
    """
    Return inclusive UTC start and exclusive UTC end datetimes.

    Defaults to the previous seven calendar days, including today.
    """

    today = datetime.now(timezone.utc).date()

    if start_date is None:
        start_date = parse_date(
            os.getenv("SCOUT_START_DATE", ""),
            "SCOUT_START_DATE",
        )

    if end_date is None:
        end_date = parse_date(
            os.getenv("SCOUT_END_DATE", ""),
            "SCOUT_END_DATE",
        )

    if end_date is None:
        end_date = today

    if start_date is None:
        start_date = end_date - timedelta(days=6)

    if start_date > end_date:
        raise ValueError("Start date cannot be after end date.")

    start_utc = datetime.combine(
        start_date, time.min, tzinfo=timezone.utc
    )
    end_utc = datetime.combine(
        end_date + timedelta(days=1), time.min, tzinfo=timezone.utc
    )

    return start_utc, end_utc


def get_subreddit_names(subreddits=None):
    """Read a comma-separated subreddit list from configuration."""

    if subreddits is None:
        raw = os.getenv("SCOUT_SUBREDDITS", "all")
        subreddits = [
            item.strip()
            for item in raw.split(",")
            if item.strip()
        ]

    if isinstance(subreddits, str):
        subreddits = [
            item.strip()
            for item in subreddits.split(",")
            if item.strip()
        ]

    if not subreddits:
        raise ValueError(
            "Configure at least one subreddit or use 'all'."
        )

    if any(
        not re.fullmatch(r"[A-Za-z0-9_]+", name)
        for name in subreddits
    ):
        raise ValueError(
            "Subreddit names may contain only letters, digits, and underscores."
        )

    return list(dict.fromkeys(subreddits))


# --------------------------------------------------
# 4. QUALIFICATION AND RECORD CREATION
# --------------------------------------------------

def is_explicit_request(title, body):
    """Require language suggesting the author is seeking a service."""

    text = f"{title} {body}".strip()
    return bool(REQUEST_PATTERN.search(text))


def submission_to_lead(submission, discovery_time):
    """Convert one Reddit submission into the shared lead format."""

    title = str(getattr(submission, "title", "") or "").strip()
    body = str(getattr(submission, "selftext", "") or "").strip()
    combined_text = f"{title}\n{body}".strip()

    services = detect_services(combined_text)

    if not services:
        return None

    if not is_explicit_request(title, body):
        return None

    author = getattr(submission, "author", None)
    username = str(author.name) if author is not None else ""

    subreddit_obj = getattr(submission, "subreddit", None)
    subreddit_name = (
        str(subreddit_obj.display_name)
        if subreddit_obj is not None
        else ""
    )

    permalink = str(getattr(submission, "permalink", "") or "")
    if permalink.startswith("/"):
        permalink = "https://www.reddit.com" + permalink

    post_url = canonical_url(permalink)

    post_id = str(getattr(submission, "id", "") or "")

    created_timestamp = getattr(submission, "created_utc", None)
    post_date = ""

    if created_timestamp is not None:
        post_date = datetime.fromtimestamp(
            float(created_timestamp),
            tz=timezone.utc,
        ).isoformat(timespec="seconds")

    urls = extract_urls(body)

    # Links are recorded as text; no destination is visited.
    docs_urls = extract_google_docs_urls(urls)
    social_links = extract_social_links(urls)
    emails = extract_email_addresses(body)
    phones = extract_phone_numbers(body)

    return {
        "reddit_username": username,
        "profile_url": (
            f"https://www.reddit.com/user/{username}/"
            if username else ""
        ),
        "post_title": title,
        "post_text": body,
        "service_needed": "; ".join(services),
        "email": "; ".join(emails),
        "social_links": "; ".join(social_links),
        "phone": "; ".join(phones),
        "google_docs_urls": "; ".join(docs_urls),
        "subreddit": subreddit_name,
        "post_date": post_date,
        "post_url": post_url,
        "post_id": post_id,
        "intent_evidence": (
            "Service keyword match: "
            + ", ".join(services)
            + "; request-language match"
        ),
        "source_html": "reddit_api",
        "discovery_date": discovery_time,
    }


# --------------------------------------------------
# 5. AUTOMATIC DISCOVERY
# --------------------------------------------------

def discover_leads(
    start_date=None,
    end_date=None,
    subreddits=None,
    limit_per_query=None,
):
    """
    Search Reddit for relevant posts.

    Returns:
        List of unique qualified lead dictionaries.

    Requires authorized API access. Search failures are logged;
    results from other successful searches are retained.
    """

    logger.info("=" * 60)
    logger.info("REDDIT DISCOVERY STARTED")

    reddit = create_reddit_client()

    start_utc, end_utc = get_date_window(start_date, end_date)
    subreddit_names = get_subreddit_names(subreddits)

    if limit_per_query is None:
        raw_limit = os.getenv("SCOUT_LIMIT_PER_QUERY", "50")

        try:
            limit_per_query = int(raw_limit)
        except ValueError as exc:
            raise ValueError(
                "SCOUT_LIMIT_PER_QUERY must be a whole number."
            ) from exc

    if not 1 <= limit_per_query <= 100:
        raise ValueError(
            "limit_per_query must be between 1 and 100."
        )

    logger.info("Date range (UTC): %s through %s",
                start_utc.date(), (end_utc - timedelta(days=1)).date())
    logger.info("Search targets: %s", ", ".join(subreddit_names))
    logger.info("Search phrases: %d", len(SEARCH_TERMS))
    logger.info("Per-query result limit: %d", limit_per_query)
    logger.info("TEST DISCOVERY 2/4 PASSED: Search settings validated.")

    discovery_time = datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    )

    # Key by Reddit submission ID so overlapping search phrases
    # cannot create multiple records for the same post.
    unique_leads = {}
    queries_attempted = 0
    queries_failed = 0
    posts_seen = 0

    for subreddit_name in subreddit_names:
        try:
            subreddit = reddit.subreddit(subreddit_name)
        except Exception:
            queries_failed += len(SEARCH_TERMS)
            logger.exception(
                "Could not initialize subreddit %s.",
                subreddit_name,
            )
            continue

        for phrase in SEARCH_TERMS:
            queries_attempted += 1

            try:
                logger.info(
                    "SEARCH [%d]: r/%s | phrase=%r",
                    queries_attempted,
                    subreddit_name,
                    phrase,
                )

                submissions = subreddit.search(
                    phrase,
                    sort="new",
                    time_filter="all",
                    limit=limit_per_query,
                )

                for submission in submissions:
                    posts_seen += 1

                    created_timestamp = getattr(
                        submission, "created_utc", None
                    )

                    if created_timestamp is None:
                        logger.debug(
                            "Skipped post without publication timestamp."
                        )
                        continue

                    post_time = datetime.fromtimestamp(
                        float(created_timestamp),
                        tz=timezone.utc,
                    )

                    if not (start_utc <= post_time < end_utc):
                        continue

                    post_id = str(
                        getattr(submission, "id", "") or ""
                    )

                    if not post_id:
                        logger.warning(
                            "Skipped post without a stable post ID."
                        )
                        continue

                    if post_id in unique_leads:
                        continue

                    try:
                        lead = submission_to_lead(
                            submission,
                            discovery_time,
                        )
                    except Exception:
                        logger.exception(
                            "Could not qualify submission ID %s.",
                            post_id,
                        )
                        continue

                    if lead is None:
                        continue

                    unique_leads[post_id] = lead

                    logger.info(
                        "QUALIFIED: id=%s | r/%s | service=%s | title=%r",
                        post_id,
                        lead["subreddit"],
                        lead["service_needed"],
                        lead["post_title"][:100],
                    )

            except Exception:
                queries_failed += 1
                logger.exception(
                    "Search failed: r/%s | phrase=%r. "
                    "Continuing with remaining searches.",
                    subreddit_name,
                    phrase,
                )

    logger.info("TEST DISCOVERY 3/4: Search cycle completed.")
    logger.info("Queries attempted: %d", queries_attempted)
    logger.info("Queries failed: %d", queries_failed)
    logger.info("Post results examined: %d", posts_seen)
    logger.info("Unique qualified leads: %d", len(unique_leads))

    if queries_attempted and queries_failed == queries_attempted:
        raise RuntimeError(
            "All Reddit searches failed. Check API access, credentials, "
            "network connectivity, and Reddit's current access requirements. "
            "See the preceding terminal errors."
        )

    logger.info("TEST DISCOVERY 4/4 PASSED: Discovery cycle finished.")
    logger.info("REDDIT DISCOVERY COMPLETED")

    return list(unique_leads.values())


# --------------------------------------------------
# 6. STANDALONE DIAGNOSTIC / DISCOVERY RUN
# --------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    try:
        leads = discover_leads()

        logger.info(
            "DISCOVERY RESULT: %d qualified leads returned.",
            len(leads),
        )

        # This module does not write to the database or CSV.
        # scout.py will coordinate those steps.
        logger.info(
            "Next integration: pass returned leads to "
            "database.save_new_leads(), then exporter.export_leads()."
        )

    except Exception:
        logger.exception("DISCOVERY FAILED.")
        raise SystemExit(1)
