
"""
Reddit Author Scout — CSV Exporter
==================================

Responsibilities:
- Export newly qualified leads to timestamped CSV files.
- Support UTF-8 with BOM for better Excel compatibility.
- Preserve Google Docs URLs as text.
- Report export counts, output paths, and failures.
- Never open or download linked documents.

Usage from the main program:
    from exporter import export_leads

    exported_file = export_leads(new_leads)

The exporter expects a list of dictionaries.
"""

import csv
import logging
import os
import re
from datetime import datetime
from pathlib import Path


logger = logging.getLogger("reddit-author-scout.exporter")

PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = PROJECT_DIR / "output"

# Stable column order for consistent spreadsheets.
CSV_COLUMNS = [
    "reddit_username",
    "profile_url",
    "post_title",
    "post_text",
    "service_needed",
    "email",
    "social_links",
    "phone",
    "google_docs_urls",
    "subreddit",
    "post_date",
    "post_url",
    "post_id",
    "intent_evidence",
    "discovery_date",
    "source_html",
]


def safe_csv_value(value):
    """
    Convert a value to a safe, readable CSV string.

    Spreadsheet formula protection is applied to text fields that
    begin with formula-triggering characters. This helps prevent
    untrusted post text from executing as a spreadsheet formula.
    """

    if value is None:
        return ""

    if isinstance(value, (list, tuple, set)):
        value = "; ".join(str(item) for item in value)

    text = str(value)

    # Avoid spreadsheet formula injection from untrusted text.
    if text.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        text = "'" + text

    return text


def build_output_path(output_dir=None, filename=None):
    """Create a timestamped CSV path unless a filename is supplied."""

    output_dir = Path(output_dir or DEFAULT_OUTPUT_DIR)

    if filename:
        filename = Path(filename)

        # Keep output files inside the chosen output directory.
        if filename.name != str(filename):
            raise ValueError(
                "filename must be a filename only, not a directory path."
            )

        if filename.suffix.lower() != ".csv":
            filename = filename.with_suffix(".csv")

    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"new_leads_{timestamp}.csv"

    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / filename


def validate_leads(leads):
    """Validate input and return valid lead dictionaries."""

    if leads is None:
        raise ValueError("leads cannot be None; provide a list of records.")

    if not isinstance(leads, (list, tuple)):
        raise TypeError("leads must be a list or tuple of dictionaries.")

    valid_leads = []
    skipped = 0

    for index, lead in enumerate(leads, start=1):
        if not isinstance(lead, dict):
            logger.warning(
                "Skipping export row %d: expected a dictionary, got %s.",
                index,
                type(lead).__name__,
            )
            skipped += 1
            continue

        valid_leads.append(lead)

    logger.info(
        "Input validation complete: valid=%d | skipped=%d",
        len(valid_leads),
        skipped,
    )

    return valid_leads


def export_leads(
    leads,
    output_dir=None,
    filename=None,
    columns=None,
):
    """
    Export leads to CSV.

    Args:
        leads: List of lead dictionaries.
        output_dir: Destination directory. Defaults to output/.
        filename: Optional filename, e.g. leads.csv.
        columns: Optional ordered list of CSV columns.

    Returns:
        str: Full path to the exported file.
        None: If there are no valid leads to export.

    Raises:
        ValueError / TypeError: Invalid arguments.
        OSError / csv.Error: File-writing failures.
    """

    logger.info("=" * 55)
    logger.info("CSV EXPORT STARTED")

    valid_leads = validate_leads(leads)

    if not valid_leads:
        logger.warning("No valid leads to export. No CSV created.")
        return None

    selected_columns = list(columns or CSV_COLUMNS)

    if not selected_columns:
        raise ValueError("At least one CSV column is required.")

    if len(set(selected_columns)) != len(selected_columns):
        raise ValueError("CSV column names must not contain duplicates.")

    for column in selected_columns:
        if not isinstance(column, str) or not column.strip():
            raise ValueError("Every CSV column must be a non-empty string.")

    output_path = build_output_path(
        output_dir=output_dir,
        filename=filename,
    )

    temporary_path = output_path.with_name(
        output_path.name + ".tmp"
    )

    logger.info("Destination: %s", output_path)
    logger.info("Records to export: %d", len(valid_leads))
    logger.info("Columns: %d", len(selected_columns))
    logger.info("TEST EXPORT 1/3 PASSED: Input validated.")

    try:
        # Write to a temporary file first, so a failed export does not
        # leave a partially written file at the final destination.
        with temporary_path.open(
            "w",
            newline="",
            encoding="utf-8-sig",
        ) as csv_file:
            writer = csv.DictWriter(
                csv_file,
                fieldnames=selected_columns,
                extrasaction="ignore",
                quoting=csv.QUOTE_MINIMAL,
            )

            writer.writeheader()

            for row_number, lead in enumerate(valid_leads, start=1):
                row = {
                    column: safe_csv_value(lead.get(column, ""))
                    for column in selected_columns
                }

                writer.writerow(row)

                logger.debug(
                    "Prepared CSV row %d: %s",
                    row_number,
                    lead.get("post_id") or lead.get("post_url") or "no ID",
                )

        if not temporary_path.exists():
            raise OSError("Temporary CSV file was not created.")

        if temporary_path.stat().st_size == 0:
            raise OSError("Temporary CSV file is empty.")

        logger.info("TEST EXPORT 2/3 PASSED: CSV written successfully.")

        # Replace the final file only after the write has completed.
        os.replace(temporary_path, output_path)

        if not output_path.exists():
            raise OSError("Final CSV file was not found after replacement.")

        logger.info("TEST EXPORT 3/3 PASSED: Final file verified.")
        logger.info("Exported rows: %d", len(valid_leads))
        logger.info("File size: %d bytes", output_path.stat().st_size)
        logger.info("CSV EXPORT COMPLETED: %s", output_path)

        return str(output_path)

    except Exception:
        logger.exception("CSV EXPORT FAILED.")

        try:
            if temporary_path.exists():
                temporary_path.unlink()
        except OSError:
            logger.exception("Could not clean up temporary export file.")

        raise


def export_database_results(
    database,
    start_date=None,
    end_date=None,
    service=None,
    output_dir=None,
    filename=None,
):
    """
    Export records returned by database.get_leads().

    Note:
        This exports matching stored records, not necessarily only
        newly inserted records. For new-only exports, pass the list
        returned by database.save_new_leads() to export_leads().
    """

    logger.info("Preparing export from database query.")

    leads = database.get_leads(
        start_date=start_date,
        end_date=end_date,
        service=service,
    )

    logger.info("Database query returned %d records.", len(leads))

    return export_leads(
        leads,
        output_dir=output_dir,
        filename=filename,
    )


# --------------------------------------------------
# STANDALONE DIAGNOSTIC
# --------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    logger.info("=" * 55)
    logger.info("EXPORTER DIAGNOSTIC STARTED")

    try:
        # Use a clearly labeled demonstration record.
        # This is NOT a real lead and must not enter the main database.
        demo_lead = {
            "reddit_username": "example_user",
            "profile_url": "https://www.reddit.com/user/example_user/",
            "post_title": "DEMO ONLY - Looking for beta readers",
            "post_text": "Synthetic record used to verify CSV export.",
            "service_needed": "beta reader",
            "email": "",
            "social_links": "",
            "phone": "",
            "google_docs_urls": "https://docs.google.com/document/d/EXAMPLE",
            "subreddit": "example",
            "post_date": "2026-01-15",
            "post_url": "https://www.reddit.com/comments/example/",
            "post_id": "export_diagnostic_example",
            "intent_evidence": "DEMO ONLY - synthetic diagnostic record",
            "discovery_date": datetime.now().astimezone().isoformat(
                timespec="seconds"
            ),
            "source_html": "diagnostic_demo",
        }

        diagnostic_dir = PROJECT_DIR / "output" / "diagnostics"

        result = export_leads(
            [demo_lead],
            output_dir=diagnostic_dir,
            filename="exporter_diagnostic.csv",
        )

        if not result:
            raise RuntimeError("Diagnostic export returned no file.")

        logger.info("DIAGNOSTIC RESULT: PASSED")
        logger.info("Diagnostic file: %s", result)
        logger.info(
            "This demonstration record is synthetic and was not saved "
            "to the lead database."
        )

    except Exception:
        logger.exception("EXPORTER DIAGNOSTIC RESULT: FAILED")
        raise SystemExit(1)
