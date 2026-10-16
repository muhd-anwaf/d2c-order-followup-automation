from datetime import datetime, timezone

from src.database import get_connection


def _normalize_deadline(value):
    if value is None:
        return None

    value = value.strip()
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(
            "Deadline must use YYYY-MM-DD or YYYY-MM-DD HH:MM:SS"
        ) from exc

    has_time = "T" in value or " " in value
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)

    if has_time:
        return parsed.strftime("%Y-%m-%d %H:%M:%S")
    return parsed.strftime("%Y-%m-%d")


def create_tasks_for_exceptions(performed_by="System"):
    """Create one task for each exception that has no task."""
    if not performed_by or not performed_by.strip():
        raise ValueError("performed_by is required")

    created = 0

    with get_connection() as connection:
        exceptions = connection.execute("""
            SELECT e.*, o.assigned_employee
            FROM exceptions e
            JOIN orders o ON o.order_id = e.order_id
            LEFT JOIN tasks t ON t.exception_id = e.id
            WHERE t.id IS NULL
        """).fetchall()

        for exception in exceptions:
            cursor = connection.execute("""
                INSERT INTO tasks (
                    exception_id,
                    assigned_employee,
                    action_required,
                    deadline,
                    status
                ) VALUES (?, ?, ?, ?, 'Open')
            """, (
                exception["id"],
                exception["assigned_employee"],
                exception["recommended_action"],
                None,
            ))

            task_id = cursor.lastrowid

            connection.execute("""
                INSERT INTO audit_logs (
                    order_id, task_id, action,
                    old_value, new_value, performed_by
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (
                exception["order_id"],
                task_id,
                "Task Created",
                None,
                "Open",
                performed_by,
            ))
            if exception["assigned_employee"]:
                connection.execute("""
                    INSERT INTO audit_logs (
                        order_id, task_id, action,
                        old_value, new_value, performed_by
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    exception["order_id"],
                    task_id,
                    "Task Assigned",
                    None,
                    exception["assigned_employee"],
                    performed_by,
                ))

            created += 1

    return created


def update_task(task_id, performed_by, employee=None,
                status=None, deadline=None):
    """Update task fields and audit every change."""
    allowed_statuses = {"Open", "In Progress", "Resolved"}
    if not performed_by or not performed_by.strip():
        raise ValueError("performed_by is required")

    normalized_deadline = _normalize_deadline(deadline)
    normalized_employee = (
        (employee.strip() or None) if employee is not None else None
    )

    with get_connection() as connection:
        task = connection.execute("""
            SELECT t.*, e.order_id
            FROM tasks t
            JOIN exceptions e ON e.id = t.exception_id
            WHERE t.id = ?
        """, (task_id,)).fetchone()

        if task is None:
            raise ValueError(f"Task {task_id} does not exist")

        changes = []

        if employee is not None:
            old_employee = task["assigned_employee"]

            if normalized_employee != old_employee:
                action = (
                    "Task Reassigned"
                    if old_employee
                    else "Task Assigned"
                )
                changes.append((
                    "assigned_employee", normalized_employee,
                    action, old_employee, normalized_employee
                ))

        if status is not None:
            if status not in allowed_statuses:
                raise ValueError("Invalid task status")

            if status != task["status"]:
                changes.append((
                    "status", status, "Status Changed",
                    task["status"], status
                ))

        if deadline is not None and normalized_deadline != task["deadline"]:
            changes.append((
                "deadline", normalized_deadline, "Deadline Changed",
                task["deadline"], normalized_deadline
            ))

        for field, value, action, old_value, new_value in changes:
            connection.execute(
                f"UPDATE tasks SET {field} = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (value, task_id),
            )

            connection.execute("""
                INSERT INTO audit_logs (
                    order_id, task_id, action,
                    old_value, new_value, performed_by
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (
                task["order_id"],
                task_id,
                action,
                str(old_value) if old_value is not None else None,
                str(new_value) if new_value is not None else None,
                performed_by,
            ))

            if field == "status":
                connection.execute(
                    """
                    UPDATE exceptions
                    SET resolved_at = CASE
                        WHEN ? = 'Resolved' THEN CURRENT_TIMESTAMP
                        ELSE NULL
                    END
                    WHERE id = ?
                    """,
                    (value, task["exception_id"]),
                )

    return len(changes)
