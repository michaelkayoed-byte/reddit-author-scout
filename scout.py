
"""
Reddit Author Scout
Main workflow:
1. Check environment and project modules.
2. Extract leads from authorized local HTML files.
3. Optionally discover Reddit posts through approved API access.
4. Deduplicate and persist leads in SQLite.
5. Export only newly saved leads to CSV.

Run:
    python scout.py

Reddit API discovery is disabled by default. Enable it in PowerShell
only when the appropriate API access is authorized:
    $env:SCOUT_ENABLE_REDDIT_API = "1"
"""

import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# --------------------------------------------------
# 1. LOGGING
# --------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger("reddit-author-scout")

# --------------------------------------------------
# 2. PROJECT PATHS
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
INPUT_DIR = BASE_DIR / "input_html"
OUTPUT_DIR = BASE_DIR / "output"
DATABASE_PATH = BASE_DIR / "scout.db"

# Reddit API discovery is opt-in.
ENABLE_REDDIT_API = (
    os.getenv("SCOUT_ENABLE_REDDIT_API", "0").strip().lower()
    in {"1", "true", "yes"}
)


# --------------------------------------------------
# 3. ENVIRONMENT CHECKS
# --------------------------------------------------

def check_environment():
    """Check Python, dependencies, modules, and folders."""

    logger.info("=" * 65)
    logger.info("TEST 1: CHECKING ENVIRONMENT")
    logger.info("Python: %s", sys.version.split()[0])
    logger.info("Project: %s", BASE_DIR)

    if sys.version_info < (3, 10):
        logger.error("Python 3.10 or newer is required.")
        return False

    try:
        import bs4

        logger.info("Beautiful Soup available: %s", bs4.__version__)
    except ImportError:
        logger.error(
            "Beautiful Soup is missing. Install it with: "
            "python -m pip install beautifulsoup4"
        )
        return False

    try:
        import extractor
        import database
        import exporter

        logger.info("extractor.py: loaded")
        logger.info("database.py: loaded")
        logger.info("exporter.py: loaded")

    except Exception:
        logger.exception("Could not load a required project module.")
        return False

    if ENABLE_REDDIT_API:
        try:
            import praw  # noqa: F401
            import discovery  # noqa: F401

            logger.info("Reddit API modules: available")
        except ImportError:
            logger.exception(
                "Reddit API dependencies are missing. Install PRAW with: "
                "python -m pip install praw"
            )
            return False
        except Exception:
            logger.exception("Could not load discovery.py.")
            return False

    try:
        INPUT_DIR.mkdir(parents=True, exist_ok=True)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.exception("Could not create project folders.")
        return False

    logger.info("Input directory: %s", INPUT_DIR)
    logger.info("Output directory: %s", OUTPUT_DIR)
    logger.info("Database: %s", DATABASE_PATH)
    logger.info(
        "Reddit API discovery: %s",
        "ENABLED" if ENABLE_REDDIT_API else "DISABLED",
    )
    logger.info("TEST 1 PASSED")
    return True


# --------------------------------------------------
# 4. LOCAL HTML DISCOVERY AND EXTRACTION
# --------------------------------------------------

def discover_local_leads():
    """Extract qualified leads from saved HTML files."""

    from extractor import extract_from_directory

    html_files = list(INPUT_DIR.glob("*.html"))
    html_files += list(INPUT_DIR.glob("*.htm"))

    logger.info("=" * 65)
    logger.info("TEST 2: LOCAL HTML EXTRACTION")
    logger.info("HTML files found: %d", len(html_files))

    if not html_files:
        logger.warning(
            "No HTML files found in input_html/. "
            "Local HTML discovery will return zero leads."
        )
        return []

    for file_path in sorted(html_files):
        logger.info("Input file: %s", file_path.name)

    leads = extract_from_directory(INPUT_DIR)

    if leads is None:
        raise RuntimeError(
            "extract_from_directory() returned None; expected a list."
        )

    if not isinstance(leads, (list, tuple)):
        raise TypeError(
            "extract_from_directory() must return a list of lead dictionaries."
        )

    logger.info("Extracted records: %d", len(leads))
    logger.info("TEST 2 PASSED")
    return list(leads)


# --------------------------------------------------
# 5. OPTIONAL REDDIT API DISCOVERY
# --------------------------------------------------

def discover_reddit_leads():
    """Discover posts only when explicitly enabled."""

    if not ENABLE_REDDIT_API:
        logger.info(
            "Reddit API discovery skipped. "
            "Set SCOUT_ENABLE_REDDIT_API=1 to enable it after authorization."
        )
        return []

    logger.info("=" * 65)
    logger.info("TEST 3: REDDIT API DISCOVERY")
    logger.info(
        "Starting authorized API discovery; this does not bypass "
        "Reddit access restrictions."
    )

    from discovery import discover_leads

    leads = discover_leads()

    if leads is None:
        raise RuntimeError("discover_leads() returned None.")

    if not isinstance(leads, (list, tuple)):
        raise TypeError(
            "discover_leads() must return a list of lead dictionaries."
        )

    logger.info("Reddit discovery returned %d records.", len(leads))
    logger.info("TEST 3 PASSED")
    return list(leads)


# --------------------------------------------------
# 6. SQLITE PERSISTENCE AND DEDUPLICATION
# --------------------------------------------------

def save_new_leads(leads):
    """Persist leads and return only newly inserted records."""

    from database import LeadDatabase

    logger.info("=" * 65)
    logger.info("TEST 4: SQLITE PERSISTENCE")

    # LeadDatabase is expected to accept the database path.
    db = LeadDatabase(DATABASE_PATH)
    db.initialize()

    logger.info("SQLite database initialized.")
    logger.info("Records submitted for deduplication: %d", len(leads))

    new_leads = db.save_new_leads(leads)

    if new_leads is None:
        raise RuntimeError(
            "database.save_new_leads() returned None; expected a list."
        )

    if not isinstance(new_leads, (list, tuple)):
        raise TypeError(
            "database.save_new_leads() must return newly inserted records."
        )

    new_leads = list(new_leads)

    logger.info("New records saved: %d", len(new_leads))
    logger.info(
        "Existing or duplicate records skipped: %d",
        max(0, len(leads) - len(new_leads)),
    )
    logger.info("TEST 4 PASSED")

    return db, new_leads


# --------------------------------------------------
# 7. CSV EXPORT
# --------------------------------------------------

def export_new_leads(new_leads):
    """Export only records inserted during this run."""

    from exporter import export_leads

    logger.info("=" * 65)
    logger.info("TEST 5: CSV EXPORT")

    if not new_leads:
        logger.info(
            "No new leads to export. No empty CSV will be created."
        )
        return None

    output_path = export_leads(
        new_leads,
        output_dir=OUTPUT_DIR,
    )

    if not output_path:
        raise RuntimeError(
            "New leads were saved, but the exporter returned no file."
        )

    if not Path(output_path).is_file():
        raise RuntimeError(
            "Exporter returned a path, but the CSV file does not exist: "
            f"{output_path}"
        )

    logger.info("New leads exported: %d", len(new_leads))
    logger.info("CSV file: %s", output_path)
    logger.info("TEST 5 PASSED")

    return output_path


# --------------------------------------------------
# 8. MAIN WORKFLOW
# --------------------------------------------------

def main():
    started = datetime.now()
    logger.info("=" * 65)
    logger.info("REDDIT AUTHOR SCOUT STARTING")
    logger.info("=" * 65)

    try:
        if not check_environment():
            logger.error("Environment checks failed. Scout stopped.")
            return 1

        all_leads = []

        # Local HTML processing is available without API credentials.
        try:
            all_leads.extend(discover_local_leads())
        except Exception:
            logger.exception("Local HTML extraction failed.")
            return 1

        # Live discovery is opt-in and requires authorized API access.
        if ENABLE_REDDIT_API:
            try:
                all_leads.extend(discover_reddit_leads())
            except Exception:
                logger.exception(
                    "Reddit API discovery failed. "
                    "Continuing with leads obtained from local HTML."
                )

        logger.info("=" * 65)
        logger.info("DISCOVERY SUMMARY")
        logger.info("Total candidate records: %d", len(all_leads))

        # The database performs persistent deduplication across runs.
        try:
            db, new_leads = save_new_leads(all_leads)
        except Exception:
            logger.exception("SQLite persistence failed. Scout stopped.")
            return 1

        try:
            csv_path = export_new_leads(new_leads)
        except Exception:
            logger.exception(
                "CSV export failed. Newly saved leads remain in SQLite."
            )
            return 1

        elapsed = (datetime.now() - started).total_seconds()

        logger.info("=" * 65)
        logger.info("FINAL RUN SUMMARY")
        logger.info("Candidate records: %d", len(all_leads))
        logger.info("New leads saved: %d", len(new_leads))
        logger.info("CSV created: %s", csv_path or "No new leads")
        logger.info("Database: %s", DATABASE_PATH)
        logger.info("Elapsed time: %.2f seconds", elapsed)
        logger.info("WORKFLOW COMPLETED")
        logger.info("=" * 65)

        return 0

    except KeyboardInterrupt:
        logger.warning("Run cancelled by user.")
        return 130

    except Exception:
        logger.exception("UNEXPECTED FAILURE: Scout crashed.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
