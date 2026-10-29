
"""
Reddit Author Scout — Database Module
=====================================

Responsibilities:
- Create and maintain a persistent SQLite database.
- Store qualified author-service leads.
- Prevent duplicate posts across runs.
- Return only newly inserted leads for CSV export.
- Log database operations and failures.

The database file (scout.db) is created automatically.
SQLite is included with Python; no additional database package is needed.
"""

import logging
import sqlite3
from pathlib import Path
from contextlib import contextmanager


logger = logging.getLogger("reddit-author-scout.database")

PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = PROJECT_DIR / "scout.db"


# --------------------------------------------------
# 1. DATABASE SCHEMA
# --------------------------------------------------

CREATE_LEADS_TABLE = """
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    post_key TEXT NOT NULL UNIQUE,
    post_id TEXT DEFAULT '',
    post_url TEXT DEFAULT '',

    reddit_username TEXT DEFAULT '',
    profile_url TEXT DEFAULT '',
    post_title TEXT DEFAULT '',
    post_text TEXT DEFAULT '',

    service_needed TEXT DEFAULT '',
    email TEXT DEFAULT '',
    social_links TEXT DEFAULT '',
    phone TEXT DEFAULT '',
    google_docs_urls TEXT DEFAULT '',

    subreddit TEXT DEFAULT '',
    post_date TEXT DEFAULT '',
    intent_evidence TEXT DEFAULT '',
    source_html TEXT DEFAULT '',

    discovery_date TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_DATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_leads_post_date
ON leads(post_date);
"""

CREATE_SERVICE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_leads_service
ON leads(service_needed);
"""


# --------------------------------------------------
# 2. DATABASE CONNECTION
# --------------------------------------------------

class LeadDatabase:
    """Manage persistent lead storage in SQLite."""

    def __init__(self, db_path=None):
        self.db_path = Path(db_path or DEFAULT_DB_PATH).resolve()
        logger.info("Database path: %s", self.db_path)

    @contextmanager
    def connect(self):
        """
        Open a database connection and safely commit or roll back
        the transaction.
        """

        connection = None

        try:
            connection = sqlite3.connect(
                str(self.db_path),
                timeout=30,
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 30000")

            yield connection

            connection.commit()

        except Exception:
            if connection is not None:
                connection.rollback()

            logger.exception("Database transaction failed.")
            raise

        finally:
            if connection is not None:
                connection.close()

    # --------------------------------------------------
    # 3. INITIALIZATION
    # --------------------------------------------------

    def initialize(self):
        """Create the database and required tables/indexes."""

        logger.info("TEST DB 1/4: Initializing database.")

        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

            with self.connect() as connection:
                connection.execute(CREATE_LEADS_TABLE)
                connection.execute(CREATE_DATE_INDEX)
                connection.execute(CREATE_SERVICE_INDEX)

            logger.info("TEST DB 1/4 PASSED: Database schema is ready.")
            return True

        except Exception:
            logger.exception("TEST DB 1/4 FAILED: Initialization failed.")
            return False

    # --------------------------------------------------
    # 4. POST KEY / DEDUPLICATION
    # --------------------------------------------------

    @staticmethod
    def make_post_key(lead):
        """
        Build a stable deduplication key.

        Priority:
        1. Reddit post ID.
        2. Canonical post URL.
        3. No key if neither is available.

        Records without a reliable identifier are skipped rather than
        accidentally treated as unique posts.
        """

        post_id = str(lead.get("post_id", "") or "").strip()
        post_url = str(lead.get("post_url", "") or "").strip()

        if post_id:
            return f"id:{post_id.lower()}"

        if post_url:
            return f"url:{post_url.rstrip('/').lower()}"

        return ""

    # --------------------------------------------------
    # 5. SAVE NEW LEADS
    # --------------------------------------------------

    def save_new_leads(self, leads):
        """
        Insert leads that have not been stored before.

        Returns a list containing only newly inserted records.
        A post that matches multiple services remains one database row.
        """

        logger.info("TEST DB 2/4: Saving qualified leads.")

        if not leads:
            logger.info("No qualified leads received for storage.")
            return []

        from datetime import datetime, timezone

        discovery_date = datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        )

        columns = [
            "post_key",
            "post_id",
            "post_url",
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
            "intent_evidence",
            "source_html",
            "discovery_date",
        ]

        placeholders = ", ".join("?" for _ in columns)

        insert_sql = f"""
            INSERT OR IGNORE INTO leads (
                {", ".join(columns)}
            )
            VALUES ({placeholders})
        """

        new_leads = []
        inserted_count = 0
        duplicate_count = 0
        invalid_count = 0

        try:
            with self.connect() as connection:
                for lead in leads:
                    if not isinstance(lead, dict):
                        invalid_count += 1
                        logger.warning(
                            "Skipping invalid lead record: expected a dict."
                        )
                        continue

                    post_key = self.make_post_key(lead)

                    if not post_key:
                        invalid_count += 1
                        logger.warning(
                            "Skipping lead without a post ID or URL: %r",
                            lead.get("post_title", ""),
                        )
                        continue

                    values = [
                        post_key,
                        str(lead.get("post_id", "") or ""),
                        str(lead.get("post_url", "") or ""),
                        str(lead.get("reddit_username", "") or ""),
                        str(lead.get("profile_url", "") or ""),
                        str(lead.get("post_title", "") or ""),
                        str(lead.get("post_text", "") or ""),
                        str(lead.get("service_needed", "") or ""),
                        str(lead.get("email", "") or ""),
                        str(lead.get("social_links", "") or ""),
                        str(lead.get("phone", "") or ""),
                        str(lead.get("google_docs_urls", "") or ""),
                        str(lead.get("subreddit", "") or ""),
                        str(lead.get("post_date", "") or ""),
                        str(lead.get("intent_evidence", "") or ""),
                        str(lead.get("source_html", "") or ""),
                        discovery_date,
                    ]

                    cursor = connection.execute(insert_sql, values)

                    if cursor.rowcount == 1:
                        inserted_count += 1
                        new_leads.append({
                            **lead,
                            "post_key": post_key,
                            "discovery_date": discovery_date,
                        })

                        logger.info(
                            "NEW LEAD SAVED: %s | %s",
                            post_key,
                            str(lead.get("post_title", ""))[:90],
                        )
                    else:
                        duplicate_count += 1
                        logger.info(
                            "DUPLICATE SKIPPED: %s",
                            post_key,
                        )

            logger.info(
                "TEST DB 2/4 PASSED: inserted=%d | duplicates=%d | "
                "invalid=%d",
                inserted_count,
                duplicate_count,
                invalid_count,
            )

            return new_leads

        except Exception:
            logger.exception("TEST DB 2/4 FAILED: Could not save leads.")
            raise

    # --------------------------------------------------
    # 6. QUERY STORED LEADS
    # --------------------------------------------------

    def get_leads(self, start_date=None, end_date=None, service=None):
        """
        Retrieve stored leads.

        Dates are filtered against original post_date, not discovery_date.
        The supplied date strings should use YYYY-MM-DD format.

        Rows with a missing or non-standard post date may not match a
        date range and should be reviewed separately.
        """

        logger.info("TEST DB 3/4: Querying stored leads.")

        conditions = []
        params = []

        if start_date:
            conditions.append("substr(post_date, 1, 10) >= ?")
            params.append(start_date)

        if end_date:
            conditions.append("substr(post_date, 1, 10) <= ?")
            params.append(end_date)

        if service:
            conditions.append("LOWER(service_needed) LIKE ?")
            params.append(f"%{service.lower()}%")

        sql = "SELECT * FROM leads"

        if conditions:
            sql += " WHERE " + " AND ".join(conditions)

        sql += " ORDER BY post_date DESC, id DESC"

        try:
            with self.connect() as connection:
                rows = connection.execute(sql, params).fetchall()

            results = [dict(row) for row in rows]

            logger.info(
                "TEST DB 3/4 PASSED: Retrieved %d records.",
                len(results),
            )

            return results

        except Exception:
            logger.exception("TEST DB 3/4 FAILED: Query failed.")
            raise

    # --------------------------------------------------
    # 7. DATABASE STATISTICS
    # --------------------------------------------------

    def get_stats(self):
        """Return basic database counts for terminal reporting."""

        try:
            with self.connect() as connection:
                total = connection.execute(
                    "SELECT COUNT(*) FROM leads"
                ).fetchone()[0]

                missing_date = connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM leads
                    WHERE post_date IS NULL OR TRIM(post_date) = ''
                    """
                ).fetchone()[0]

            stats = {
                "total_leads": total,
                "missing_post_date": missing_date,
                "database_path": str(self.db_path),
            }

            logger.info(
                "DATABASE STATS: total=%d | missing original dates=%d",
                total,
                missing_date,
            )

            logger.info("TEST DB 4/4 PASSED: Statistics query succeeded.")
            return stats

        except Exception:
            logger.exception("TEST DB 4/4 FAILED: Statistics query failed.")
            raise


# --------------------------------------------------
# 8. STANDALONE DIAGNOSTIC
# --------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    logger.info("=" * 55)
    logger.info("DATABASE DIAGNOSTIC STARTED")

    try:
        database = LeadDatabase()

        if not database.initialize():
            raise RuntimeError("Database initialization failed.")

        stats = database.get_stats()

        logger.info("Database ready: %s", stats["database_path"])
        logger.info("Existing lead records: %d", stats["total_leads"])
        logger.info("DIAGNOSTIC RESULT: PASSED")

    except Exception:
        logger.exception("DATABASE DIAGNOSTIC RESULT: FAILED")
        raise SystemExit(1)
