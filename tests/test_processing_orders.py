from datetime import datetime, timedelta, timezone
from io import BytesIO

import pandas as pd
import pytest

from src.database import get_connection
from src.importer import import_orders
from src.rule_engine import evaluate_order, run_rule_engine
from src.task_service import create_tasks_for_exceptions


NOW = datetime(2026, 10, 16, 12, 0, 0, tzinfo=timezone.utc)


def _processing_order(**overrides):
    order = {
        "order_id": "PROCESSING-001",
        "order_date": "2026-10-16 10:00:00",
        "customer_name": "Test Customer",
        "phone_number": "9876543210",
        "order_value": 2500,
        "payment_type": "cod",
        "order_status": "Processing",
        "dispatch_date": None,
        "expected_delivery_date": None,
        "assigned_employee": "Employee A",
    }
    order.update(overrides)
    return order


@pytest.mark.parametrize(
    ("elapsed", "expected"),
    [
        (timedelta(hours=1, minutes=59), False),
        (timedelta(hours=2), False),
        (timedelta(hours=2, seconds=1), True),
        (timedelta(hours=5), True),
    ],
)
def test_processing_unconfirmed_threshold_is_strictly_greater_than_two_hours(
    elapsed, expected
):
    order_date = NOW - elapsed
    result = evaluate_order(
        _processing_order(order_date=order_date.strftime("%Y-%m-%d %H:%M:%S")),
        now=NOW,
    )

    unconfirmed = [
        item for item in result
        if item["exception_type"] == "Unconfirmed Order"
    ]
    assert bool(unconfirmed) is expected
    if unconfirmed:
        assert unconfirmed[0]["order_id"] == "PROCESSING-001"
        assert unconfirmed[0]["reason"]
        assert unconfirmed[0]["priority"]
        assert unconfirmed[0]["recommended_action"]


@pytest.mark.parametrize("status", ["Processing", " processing ", "PROCESSING"])
def test_processing_status_is_case_and_whitespace_insensitive(status):
    result = evaluate_order(
        _processing_order(
            order_status=status,
            order_date="2026-10-16 09:00:00",
        ),
        now=NOW,
    )

    assert any(
        item["exception_type"] == "Unconfirmed Order"
        for item in result
    )


@pytest.mark.parametrize("status", ["confirmed", "dispatched", "delivered"])
def test_other_status_does_not_create_unconfirmed_order_exception(status):
    result = evaluate_order(
        _processing_order(
            order_status=status,
            order_date="2026-10-16 08:00:00",
            dispatch_date=(
                "2026-10-16 08:30:00"
                if status in {"dispatched", "delivered"}
                else None
            ),
            expected_delivery_date="2026-10-20",
        ),
        now=NOW,
    )

    assert not any(
        item["exception_type"] == "Unconfirmed Order"
        for item in result
    )


@pytest.mark.parametrize("order_date", [None, "not-a-timestamp"])
def test_processing_with_missing_or_invalid_order_date_only_gets_data_correction(
    order_date,
):
    result = evaluate_order(
        _processing_order(order_date=order_date),
        now=NOW,
    )

    assert [item["exception_type"] for item in result] == ["Data Correction"]
    assert "order date" in result[0]["reason"].lower()
    assert result[0]["priority"]
    assert result[0]["recommended_action"]


class NamedBytesIO(BytesIO):
    def __init__(self, content, name="processing_orders.csv"):
        super().__init__(content)
        self.name = name


@pytest.mark.parametrize("bad_date", ["", "not-a-timestamp"])
def test_imported_processing_rows_with_bad_order_date_get_correction_task(bad_date):
    frame = pd.DataFrame([{
        "Order ID": f"PROCESSING-BAD-{bad_date or 'MISSING'}",
        "Order Date": bad_date,
        "Customer Name": "Test Customer",
        "Phone Number": "9876543210",
        "Order Value": 2500,
        "Payment Type": "COD",
        "Order Status": "  pRoCeSsInG  ",
        "Dispatch Date": None,
        "Expected Delivery Date": None,
        "Assigned Employee": "Employee A",
    }])
    uploaded_file = NamedBytesIO(frame.to_csv(index=False).encode("utf-8"))

    result = import_orders(uploaded_file)

    assert result["imported"] == 1
    assert len(result["errors"]) == 1
    assert run_rule_engine(now=NOW) == 1
    assert create_tasks_for_exceptions() == 1

    with get_connection() as connection:
        stored_order = connection.execute(
            "SELECT order_date, order_status FROM orders"
        ).fetchone()
        exception = connection.execute(
            "SELECT exception_type, reason, priority, recommended_action "
            "FROM exceptions"
        ).fetchone()
        task_count = connection.execute(
            "SELECT COUNT(*) FROM tasks"
        ).fetchone()[0]

    assert stored_order["order_date"] is None
    assert stored_order["order_status"] == "processing"
    assert exception["exception_type"] == "Data Correction"
    assert "order date" in exception["reason"].lower()
    assert exception["priority"]
    assert exception["recommended_action"]
    assert task_count == 1


def test_processing_exception_and_task_are_idempotent_across_runs_and_uploads():
    frame = pd.DataFrame([{
        "Order ID": "PROCESSING-DUP-001",
        "Order Date": "2026-10-16 09:00:00",
        "Customer Name": "Test Customer",
        "Phone Number": "9876543210",
        "Order Value": 2500,
        "Payment Type": "COD",
        "Order Status": "Processing",
        "Dispatch Date": None,
        "Expected Delivery Date": None,
        "Assigned Employee": "Employee A",
    }])
    csv_bytes = frame.to_csv(index=False).encode("utf-8")

    first_import = import_orders(NamedBytesIO(csv_bytes))
    second_import = import_orders(NamedBytesIO(csv_bytes))
    assert first_import["imported"] == 1
    assert second_import["imported"] == 0
    assert any(
        "already exists" in " ".join(error["errors"]).lower()
        for error in second_import["errors"]
    )

    assert run_rule_engine(now=NOW) == 1
    assert run_rule_engine(now=NOW) == 0
    assert create_tasks_for_exceptions() == 1
    assert create_tasks_for_exceptions() == 0

    with get_connection() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM exceptions"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM tasks"
        ).fetchone()[0] == 1
