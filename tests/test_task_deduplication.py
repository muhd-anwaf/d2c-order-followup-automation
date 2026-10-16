"""Tests for follow-up task deduplication."""

from src.database import get_connection, initialize_database
from src.task_service import create_tasks_for_exceptions


def test_task_creation_is_idempotent():
    initialize_database()

    with get_connection() as connection:
        connection.execute("""
            INSERT OR IGNORE INTO orders (
                order_id, order_date, customer_name, phone_number,
                order_value, payment_type, order_status
            ) VALUES (
                'TASKTEST01', '2026-10-16 08:00:00',
                'Test Customer', '9876543210', 2000,
                'cod', 'unconfirmed'
            )
        """)

        connection.execute("""
            INSERT OR IGNORE INTO exceptions (
                exception_key, order_id, exception_type,
                reason, priority, recommended_action
            ) VALUES (
                'TASKTEST01:Unconfirmed Order', 'TASKTEST01',
                'Unconfirmed Order', 'Test reason',
                'Medium', 'Contact customer'
            )
        """)

    first = create_tasks_for_exceptions()
    second = create_tasks_for_exceptions()

    with get_connection() as connection:
        count = connection.execute("""
            SELECT COUNT(*) FROM tasks
            WHERE exception_id = (
                SELECT id FROM exceptions
                WHERE exception_key = 'TASKTEST01:Unconfirmed Order'
            )
        """).fetchone()[0]

    assert first == 1
    assert second == 0
    assert count == 1
