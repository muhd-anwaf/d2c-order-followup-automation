from io import BytesIO

import pandas as pd
import pytest
import sqlite3

from src.database import clear_database, get_connection
from src.importer import import_orders


def _populate_database():
    with get_connection() as connection:
        connection.execute("""
            INSERT INTO orders (
                order_id, order_date, customer_name, phone_number,
                order_value, payment_type, order_status
            ) VALUES (
                'CLEAR-TEST', '2026-10-16 08:00:00', 'Test Customer',
                '9876543210', 2500, 'cod', 'processing'
            )
        """)
        connection.execute("""
            INSERT INTO exceptions (
                exception_key, order_id, exception_type, reason,
                priority, recommended_action
            ) VALUES (
                'CLEAR-TEST:Unconfirmed Order', 'CLEAR-TEST',
                'Unconfirmed Order', 'Test reason', 'Medium', 'Test action'
            )
        """)
        exception_id = connection.execute(
            "SELECT id FROM exceptions WHERE order_id = 'CLEAR-TEST'"
        ).fetchone()[0]
        connection.execute("""
            INSERT INTO tasks (
                exception_id, action_required, assigned_employee
            ) VALUES (?, 'Test action', 'Test Employee')
        """, (exception_id,))
        task_id = connection.execute(
            "SELECT id FROM tasks WHERE exception_id = ?", (exception_id,)
        ).fetchone()[0]
        connection.execute("""
            INSERT INTO audit_logs (
                order_id, task_id, action, performed_by
            ) VALUES ('CLEAR-TEST', ?, 'Task Created', 'Test Manager')
        """, (task_id,))


def _table_counts():
    with get_connection() as connection:
        return {
            table: connection.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
            for table in ("orders", "exceptions", "tasks", "audit_logs")
        }


def test_clear_database_removes_all_records_and_can_be_repeated():
    _populate_database()

    clear_database()

    assert _table_counts() == {
        "orders": 0,
        "exceptions": 0,
        "tasks": 0,
        "audit_logs": 0,
    }
    with get_connection() as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1

    clear_database()
    assert _table_counts() == {
        "orders": 0,
        "exceptions": 0,
        "tasks": 0,
        "audit_logs": 0,
    }


def test_clear_database_rolls_back_all_deletes_when_a_later_delete_fails():
    _populate_database()
    with get_connection() as connection:
        connection.execute("""
            CREATE TRIGGER reject_order_delete
            BEFORE DELETE ON orders
            BEGIN
                SELECT RAISE(ABORT, 'simulated delete failure');
            END
        """)

    with pytest.raises(sqlite3.IntegrityError, match="simulated delete failure"):
        clear_database()

    assert _table_counts() == {
        "orders": 1,
        "exceptions": 1,
        "tasks": 1,
        "audit_logs": 1,
    }


def test_fresh_upload_succeeds_after_database_clear():
    _populate_database()
    clear_database()
    frame = pd.DataFrame([{
        "Order ID": "FRESH-UPLOAD",
        "Order Date": "2026-10-16 08:00:00",
        "Customer Name": "Fresh Customer",
        "Phone Number": "9876543210",
        "Order Value": 1500,
        "Payment Type": "COD",
        "Order Status": "placed",
        "Dispatch Date": None,
        "Expected Delivery Date": None,
        "Assigned Employee": "Employee A",
    }])

    class NamedBytesIO(BytesIO):
        name = "fresh_orders.csv"

    upload = NamedBytesIO(frame.to_csv(index=False).encode("utf-8"))
    result = import_orders(upload)

    assert result["imported"] == 1
    assert result["errors"] == []
    assert _table_counts() == {
        "orders": 1,
        "exceptions": 0,
        "tasks": 0,
        "audit_logs": 0,
    }
