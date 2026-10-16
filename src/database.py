
from contextlib import contextmanager
import sqlite3
from pathlib import Path

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
        """)


if __name__ == "__main__":
    initialize_database()
    print(f"Database initialized: {DB_PATH}")
