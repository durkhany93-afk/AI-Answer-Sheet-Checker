
import sqlite3
import json
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "grading.db")


def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def add_column(c, table, column, definition):
    existing = [
        row["name"]
        for row in c.execute(f"PRAGMA table_info({table})").fetchall()
    ]

    if column not in existing:
        c.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
        )


def init_db():
    with conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS exams(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            questions TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS submissions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_id INTEGER NOT NULL,
            student_name TEXT NOT NULL,
            image_path TEXT,
            extracted_text TEXT,
            result TEXT,
            total REAL,
            max_total REAL,
            status TEXT DEFAULT 'graded',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS rechecks(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            submission_id INTEGER NOT NULL,
            reason TEXT,
            old_total REAL,
            new_total REAL,
            result TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # Add new columns safely
        add_column(c, "submissions", "ai_result", "TEXT")
        add_column(c, "submissions", "teacher_total", "REAL")
        add_column(c, "rechecks", "action_type",
                   "TEXT NOT NULL DEFAULT 'ai_recheck'")
        add_column(c, "rechecks", "old_result", "TEXT")
        add_column(c, "rechecks", "teacher_id", "TEXT")

        # Preserve existing AI results
        c.execute("""
            UPDATE submissions
            SET ai_result = result
            WHERE ai_result IS NULL
        """)

        # Preserve existing teacher marks
        c.execute("""
            UPDATE submissions
            SET teacher_total = total
            WHERE status = 'teacher_override'
              AND teacher_total IS NULL
        """)


def row(r):
    d = dict(r)

    for k in ("questions", "result", "ai_result", "old_result"):
        if k in d and d[k]:
            d[k] = json.loads(d[k])

    return d
