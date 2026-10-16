
from contextlib import contextmanager
import math
import sqlite3
from pathlib import Path

from config import HIGH_VALUE_THRESHOLD

DB_PATH = Path(__file__).resolve().parent.parent / "order_followup.db"


@contextmanager
def get_connection():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database():
    with get_connection() as connection:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT NOT NULL UNIQUE,
                order_date TEXT,
                customer_name TEXT,
                phone_number TEXT,
                order_value REAL,
                payment_type TEXT,
                order_status TEXT,
                dispatch_date TEXT,
                expected_delivery_date TEXT,
                assigned_employee TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS exceptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                exception_key TEXT NOT NULL UNIQUE,
                order_id TEXT NOT NULL,
                exception_type TEXT NOT NULL,
                reason TEXT NOT NULL,
                priority TEXT NOT NULL
                    CHECK (priority IN ('High', 'Medium', 'Low')),
                recommended_action TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                resolved_at TEXT,
                FOREIGN KEY (order_id) REFERENCES orders(order_id)
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                exception_id INTEGER NOT NULL UNIQUE,
                assigned_employee TEXT,
                action_required TEXT NOT NULL,
                deadline TEXT,
                status TEXT NOT NULL DEFAULT 'Open'
                    CHECK (status IN (
                        'Open', 'In Progress', 'Resolved'
                    )),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (exception_id) REFERENCES exceptions(id)
            );

            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT NOT NULL,
                task_id INTEGER,
                action TEXT NOT NULL,
                old_value TEXT,
                new_value TEXT,
                performed_by TEXT NOT NULL,
                timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (task_id) REFERENCES tasks(id)
            );

            CREATE INDEX IF NOT EXISTS idx_tasks_status
                ON tasks(status);

            CREATE INDEX IF NOT EXISTS idx_tasks_employee
                ON tasks(assigned_employee);

            CREATE INDEX IF NOT EXISTS idx_exceptions_type
                ON exceptions(exception_type);

            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value REAL NOT NULL CHECK (value > 0)
            );
        """)
        connection.execute(
            "INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)",
            ("high_value_threshold", HIGH_VALUE_THRESHOLD),
        )


def get_high_value_threshold():
    """Return the persisted high-value threshold, falling back to config."""
    with get_connection() as connection:
        row = connection.execute(
            "SELECT value FROM app_settings WHERE key = ?",
            ("high_value_threshold",),
        ).fetchone()

    return float(row["value"]) if row else float(HIGH_VALUE_THRESHOLD)


def save_high_value_threshold(threshold):
    """Persist a positive, finite high-value threshold."""
    try:
        normalized_threshold = float(threshold)
    except (TypeError, ValueError) as exc:
        raise ValueError("Threshold must be a positive amount") from exc

    if not math.isfinite(normalized_threshold) or normalized_threshold <= 0:
        raise ValueError("Threshold must be a positive amount")

    with get_connection() as connection:
        connection.execute("""
            INSERT INTO app_settings (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """, ("high_value_threshold", normalized_threshold))

    return normalized_threshold


def clear_database():
    """Delete all application records in one foreign-key-safe transaction."""
    with get_connection() as connection:
        for table in ("audit_logs", "tasks", "exceptions", "orders"):
            connection.execute(f"DELETE FROM {table}")


if __name__ == "__main__":
    initialize_database()
    print(f"Database initialized: {DB_PATH}")
