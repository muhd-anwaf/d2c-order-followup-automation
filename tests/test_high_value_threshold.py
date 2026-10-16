from datetime import datetime

import pytest

from config import HIGH_VALUE_THRESHOLD
from src.database import (
    get_connection,
    get_high_value_threshold,
    save_high_value_threshold,
)
from src.rule_engine import (
    evaluate_order,
    recalculate_high_value_priorities,
    run_rule_engine,
)
from src.task_service import create_tasks_for_exceptions, update_task


NOW = datetime(2026, 10, 16, 12, 0, 0)


def _insert_order(order_id, value, status="dispatched"):
    with get_connection() as connection:
        connection.execute("""
            INSERT INTO orders (
                order_id, order_date, customer_name, phone_number,
                order_value, payment_type, order_status, dispatch_date,
                expected_delivery_date, assigned_employee
            ) VALUES (?, '2026-10-14 08:00:00', 'Test Customer',
                      '9876543210', ?, 'cod', ?, '2026-10-14',
                      '2026-10-15', 'Employee A')
        """, (order_id, value, status))


def test_default_threshold_is_loaded_when_no_setting_exists():
    with get_connection() as connection:
        connection.execute(
            "DELETE FROM app_settings WHERE key = 'high_value_threshold'"
        )

    assert get_high_value_threshold() == float(HIGH_VALUE_THRESHOLD)


def test_custom_threshold_is_saved_and_loaded_from_database():
    assert save_high_value_threshold(7250.5) == 7250.5

    with get_connection() as connection:
        assert connection.execute(
            "SELECT value FROM app_settings "
            "WHERE key = 'high_value_threshold'"
        ).fetchone()[0] == 7250.5

    assert get_high_value_threshold() == 7250.5


def test_direct_order_evaluation_uses_the_saved_threshold():
    save_high_value_threshold(6000)
    _insert_order("DIRECT-THRESHOLD", 6000)
    with get_connection() as connection:
        order = dict(connection.execute(
            "SELECT * FROM orders WHERE order_id = 'DIRECT-THRESHOLD'"
        ).fetchone())

    shipment_exception = next(
        exception for exception in evaluate_order(order, now=NOW)
        if exception["exception_type"] == "Shipment Delay"
    )

    assert shipment_exception["priority"] == "Medium"


@pytest.mark.parametrize(
    ("order_value", "expected_priority"),
    [(5000, "Medium"), (5000.01, "High")],
)
def test_high_value_priority_uses_strictly_greater_than_saved_threshold(
    order_value, expected_priority
):
    _insert_order("THRESHOLD-ORDER", order_value)

    assert run_rule_engine(now=NOW) == 1

    with get_connection() as connection:
        exception = connection.execute(
            "SELECT priority FROM exceptions"
        ).fetchone()
    assert exception["priority"] == expected_priority


@pytest.mark.parametrize("task_status", ["In Progress", "Resolved"])
def test_recalculation_updates_priorities_without_duplicate_tasks_or_resetting_status(
    task_status,
):
    _insert_order("THRESHOLD-RECALC", 6000)
    assert run_rule_engine(now=NOW) == 1
    assert create_tasks_for_exceptions() == 1

    with get_connection() as connection:
        task_id = connection.execute(
            "SELECT id FROM tasks"
        ).fetchone()["id"]
    update_task(
        task_id,
        performed_by="Manager",
        status=task_status,
    )

    save_high_value_threshold(6000)
    assert recalculate_high_value_priorities("Manager") == 1
    assert run_rule_engine(now=NOW) == 0
    assert create_tasks_for_exceptions() == 0

    with get_connection() as connection:
        exception = connection.execute(
            "SELECT priority FROM exceptions"
        ).fetchone()
        task = connection.execute(
            "SELECT status FROM tasks"
        ).fetchone()
        counts = (
            connection.execute("SELECT COUNT(*) FROM exceptions").fetchone()[0],
            connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0],
        )
        priority_audit = connection.execute("""
            SELECT old_value, new_value, performed_by
            FROM audit_logs
            WHERE action = 'Exception Priority Changed'
        """).fetchone()

    assert exception["priority"] == "Medium"
    assert task["status"] == task_status
    assert counts == (1, 1)
    assert dict(priority_audit) == {
        "old_value": "High",
        "new_value": "Medium",
        "performed_by": "Manager",
    }

    save_high_value_threshold(5000)
    assert recalculate_high_value_priorities("Manager") == 1
    with get_connection() as connection:
        assert connection.execute(
            "SELECT priority FROM exceptions"
        ).fetchone()["priority"] == "High"
        assert connection.execute(
            "SELECT status FROM tasks"
        ).fetchone()["status"] == task_status
