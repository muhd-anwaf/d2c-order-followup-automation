
from src.database import get_connection


def log_action(
    order_id,
    action,
    performed_by,
    task_id=None,
    old_value=None,
    new_value=None,
):
    with get_connection() as connection:
        connection.execute("""
            INSERT INTO audit_logs (
                order_id, task_id, action,
                old_value, new_value, performed_by
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, (
            order_id,
            task_id,
            action,
            old_value,
            new_value,
            performed_by,
        ))
