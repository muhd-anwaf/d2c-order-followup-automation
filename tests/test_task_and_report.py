import sqlite3
from datetime import datetime, timezone

import pandas as pd
import pytest

from src.database import get_connection
from src.report_service import build_daily_exception_report
from src.rule_engine import run_rule_engine
from src.task_service import create_tasks_for_exceptions, update_task


def _insert_exception(order_id="TASK-001", employee="Employee A"):
    with get_connection() as connection:
        connection.execute("""
            INSERT INTO orders (
                order_id, order_date, customer_name, phone_number,
                order_value, payment_type, order_status, assigned_employee
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            order_id, "2026-10-15 08:00:00", "Test Customer",
            "9876543210", 2000, "cod", "confirmed", employee,
        ))
        connection.execute("""
            INSERT INTO exceptions (
                exception_key, order_id, exception_type,
                reason, priority, recommended_action
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, (
            f"{order_id}:Dispatch Delay", order_id, "Dispatch Delay",
            "Dispatch is overdue", "High", "Contact warehouse",
        ))


def test_task_assignment_updates_status_and_persist_audit_events():
    _insert_exception()

    assert create_tasks_for_exceptions(performed_by="Manager One") == 1
    with get_connection() as connection:
        task = connection.execute(
            "SELECT * FROM tasks"
        ).fetchone()
        assert task["assigned_employee"] == "Employee A"
        assert task["status"] == "Open"
        task_id = task["id"]

    changes = update_task(
        task_id,
        performed_by="Manager Two",
        employee="Employee B",
        status="In Progress",
        deadline="2026-10-16 12:30:00",
    )
    assert changes == 3

    with get_connection() as connection:
        task = connection.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        events = connection.execute("""
            SELECT action, performed_by
            FROM audit_logs
            WHERE task_id = ?
            ORDER BY id
        """, (task_id,)).fetchall()
        assert task["assigned_employee"] == "Employee B"
        assert task["status"] == "In Progress"
        assert task["deadline"] == "2026-10-16 12:30:00"
        assert [event["action"] for event in events] == [
            "Task Created",
            "Task Assigned",
            "Task Reassigned",
            "Status Changed",
            "Deadline Changed",
        ]
        assert events[-1]["performed_by"] == "Manager Two"

    update_task(
        task_id,
        performed_by="Manager Two",
        status="Resolved",
    )
    with get_connection() as connection:
        resolved_at = connection.execute(
            "SELECT resolved_at FROM exceptions"
        ).fetchone()[0]
        assert resolved_at is not None


def test_rule_detection_and_task_creation_are_persistent_and_idempotent():
    with get_connection() as connection:
        connection.execute("""
            INSERT INTO orders (
                order_id, order_date, customer_name, phone_number,
                order_value, payment_type, order_status, assigned_employee
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "RULE-PERSIST", "2026-10-15 22:00:00", "Test Customer",
            "9876543210", 2000, "cod", "confirmed", "Employee A",
        ))

    now = datetime(2026, 10, 16, 15, 0, 0, tzinfo=timezone.utc)
    assert run_rule_engine(now=now, dispatch_limit_hours=24) == 0
    assert run_rule_engine(now=now, dispatch_limit_hours=12) == 1
    assert run_rule_engine(now=now, dispatch_limit_hours=12) == 0
    assert create_tasks_for_exceptions() == 1
    assert create_tasks_for_exceptions() == 0

    with get_connection() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM exceptions"
        ).fetchone()[0] == 1
        task = connection.execute(
            "SELECT assigned_employee, status FROM tasks"
        ).fetchone()
        assert task["assigned_employee"] == "Employee A"
        assert task["status"] == "Open"


def test_invalid_deadline_is_rejected_and_empty_deadline_clears_it():
    _insert_exception()
    create_tasks_for_exceptions()
    with get_connection() as connection:
        task_id = connection.execute(
            "SELECT id FROM tasks"
        ).fetchone()[0]

    with pytest.raises(ValueError, match="Deadline must use"):
        update_task(
            task_id,
            performed_by="Manager",
            deadline="tomorrow",
        )

    update_task(
        task_id,
        performed_by="Manager",
        deadline="2026-10-16 12:30:00",
    )
    update_task(task_id, performed_by="Manager", deadline="")
    with get_connection() as connection:
        assert connection.execute(
            "SELECT deadline FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()[0] is None


def test_daily_report_covers_all_required_categories():
    tasks = pd.DataFrame([
        {
            "id": 1,
            "order_id": "NEW-OVERDUE-HIGH",
            "status": "Open",
            "priority": "High",
            "assigned_employee": "Employee A",
            "deadline": "2026-10-15 10:00:00",
            "exception_created_at": "2026-10-16 09:00:00",
        },
        {
            "id": 2,
            "order_id": "UNRESOLVED",
            "status": "In Progress",
            "priority": "Medium",
            "assigned_employee": None,
            "deadline": None,
            "exception_created_at": "2026-10-15 09:00:00",
        },
        {
            "id": 3,
            "order_id": "RESOLVED",
            "status": "Resolved",
            "priority": "High",
            "assigned_employee": "Employee B",
            "deadline": "2026-10-15",
            "exception_created_at": "2026-10-16 08:00:00",
        },
    ])

    report = build_daily_exception_report(
        tasks,
        now=datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc),
    )
    first_categories = report.loc[
        report["id"] == 1, "report_categories"
    ].iloc[0]

    assert set(report["id"]) == {1, 2, 3}
    assert "New Exception" in first_categories
    assert "Unresolved Exception" in first_categories
    assert "Overdue Task" in first_categories
    assert "High Priority" in first_categories
    assert "Employee-wise Pending Action" in first_categories
    assert report.loc[report["id"] == 1, "is_overdue"].iloc[0]
    assert not report.loc[report["id"] == 2, "is_overdue"].iloc[0]


def test_daily_report_handles_empty_tasks():
    report = build_daily_exception_report(pd.DataFrame())

    assert report.empty
    assert "report_categories" in report


def test_database_context_closes_connection_and_rolls_back_failures():
    with get_connection() as connection:
        connection.execute("""
            INSERT INTO orders (order_id, order_status)
            VALUES ('ROLLBACK-TEST', 'confirmed')
        """)

    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        connection.execute("SELECT 1")

    with pytest.raises(RuntimeError, match="rollback"):
        with get_connection() as failed_connection:
            failed_connection.execute("""
                INSERT INTO orders (order_id, order_status)
                VALUES ('ROLLBACK-FAIL', 'confirmed')
            """)
            raise RuntimeError("rollback")

    with get_connection() as verification:
        assert verification.execute(
            "SELECT COUNT(*) FROM orders"
        ).fetchone()[0] == 1
