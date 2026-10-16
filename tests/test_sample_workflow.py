from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

import pandas as pd

from src.database import get_connection
from src.importer import import_orders
from src.report_service import build_daily_exception_report
from src.rule_engine import run_rule_engine
from src.task_service import create_tasks_for_exceptions, update_task


class NamedBytesIO(BytesIO):
    def __init__(self, content, name):
        super().__init__(content)
        self.name = name


def test_sample_orders_complete_import_detection_task_and_report_workflow():
    sample = (
        Path(__file__).resolve().parents[1]
        / "data"
        / "sample_orders.csv"
    )
    upload = NamedBytesIO(sample.read_bytes(), sample.name)
    import_result = import_orders(upload)

    assert import_result["imported"] == 100
    assert len(import_result["errors"]) == 10
    repeated_upload = NamedBytesIO(sample.read_bytes(), sample.name)
    repeated_import = import_orders(repeated_upload)
    assert repeated_import["imported"] == 0
    assert len(repeated_import["errors"]) == 110

    now = datetime.now(timezone.utc)
    default_threshold_count = run_rule_engine(
        now=now, dispatch_limit_hours=24
    )
    assert default_threshold_count == 65
    assert run_rule_engine(now=now, dispatch_limit_hours=24) == 0
    assert run_rule_engine(now=now, dispatch_limit_hours=12) == 5
    assert create_tasks_for_exceptions() == 70
    assert create_tasks_for_exceptions() == 0

    with get_connection() as connection:
        first_task_id = connection.execute(
            "SELECT id FROM tasks ORDER BY id LIMIT 1"
        ).fetchone()[0]
    overdue_deadline = (
        now.date() - timedelta(days=1)
    ).strftime("%Y-%m-%d") + " 12:00:00"
    update_task(
        first_task_id,
        performed_by="Demo Manager",
        deadline=overdue_deadline,
    )

    with get_connection() as connection:
        tasks = connection.execute("""
            SELECT t.id, t.status, e.priority, t.assigned_employee,
                   t.deadline, e.created_at AS exception_created_at,
                   e.exception_type
            FROM tasks t
            JOIN exceptions e ON e.id = t.exception_id
        """).fetchall()
        assert connection.execute(
            "SELECT COUNT(*) FROM orders"
        ).fetchone()[0] == 100

    report = build_daily_exception_report(
        pd.DataFrame([dict(task) for task in tasks]),
        now=now,
    )
    categories = ";".join(report["report_categories"])
    for required_category in (
        "New Exception",
        "Unresolved Exception",
        "Overdue Task",
        "High Priority",
        "Employee-wise Pending Action",
    ):
        assert required_category in categories
