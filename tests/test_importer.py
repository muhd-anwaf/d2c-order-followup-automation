"""Tests for order importing and validation."""

from io import BytesIO
from pathlib import Path

import pandas as pd

from src.database import get_connection
from src.importer import import_orders
from src.validator import validate_dataframe


class NamedBytesIO(BytesIO):
    def __init__(self, content, name):
        super().__init__(content)
        self.name = name


def test_valid_order():
    df = pd.DataFrame([{
        "Order ID": "ORD001",
        "Order Date": "2026-10-15",
        "Customer Name": "Test Customer",
        "Phone Number": "9876543210",
        "Order Value": 2500,
        "Payment Type": "COD",
        "Order Status": "placed",
        "Dispatch Date": None,
        "Expected Delivery Date": "2026-10-20",
        "Assigned Employee": "Employee A",
    }])

    records, errors = validate_dataframe(df)

    assert len(records) == 1
    assert errors == []


def test_duplicate_ids():
    df = pd.DataFrame([
        {
            "order_id": "ORD001",
            "order_date": "2026-10-15",
            "customer_name": "Customer A",
            "phone_number": "9876543210",
            "order_value": 1000,
            "payment_type": "prepaid",
            "order_status": "placed",
            "dispatch_date": None,
            "expected_delivery_date": None,
            "assigned_employee": "Employee A",
        },
        {
            "order_id": "ORD001",
            "order_date": "2026-10-15",
            "customer_name": "Customer B",
            "phone_number": "9876543211",
            "order_value": 1500,
            "payment_type": "cod",
            "order_status": "placed",
            "dispatch_date": None,
            "expected_delivery_date": None,
            "assigned_employee": "Employee B",
        },
    ])

    records, errors = validate_dataframe(df)

    assert len(records) == 1
    assert len(errors) == 1
    assert "Duplicate order ID" in errors[0]["errors"][0]


def test_fixed_order_status_enum_is_normalized_and_enforced():
    df = pd.DataFrame([
        {
            "Order ID": "ORD-STATUS-OK",
            "Order Date": "2026-10-16 08:00:00",
            "Customer Name": "Customer A",
            "Phone Number": "9876543210",
            "Order Value": 1000,
            "Payment Type": "COD",
            "Order Status": "  FaIlEd_DeLiVeRy ",
            "Dispatch Date": None,
            "Expected Delivery Date": None,
            "Assigned Employee": "Employee A",
        },
        {
            "Order ID": "ORD-STATUS-INVALID",
            "Order Date": "2026-10-16 08:00:00",
            "Customer Name": "Customer B",
            "Phone Number": "9876543211",
            "Order Value": 1000,
            "Payment Type": "COD",
            "Order Status": "in transit",
            "Dispatch Date": None,
            "Expected Delivery Date": None,
            "Assigned Employee": "Employee B",
        },
    ])

    records, errors = validate_dataframe(df)

    assert len(records) == 1
    assert records[0]["order_status"] == "failed_delivery"
    assert len(errors) == 1
    assert "Order status must be one of" in errors[0]["errors"][0]


def test_csv_and_excel_sample_files_have_expected_valid_and_invalid_rows():
    project_root = Path(__file__).resolve().parents[1]
    csv_path = project_root / "data" / "sample_orders.csv"
    excel_path = project_root / "data" / "sample_orders.xlsx"

    for path in (csv_path, excel_path):
        df = pd.read_csv(path) if path.suffix == ".csv" else pd.read_excel(path)
        records, errors = validate_dataframe(df)

        assert len(df) == 110
        assert len(records) == 100
        assert len(errors) == 10
        assert sum(
            "Duplicate order ID in uploaded file" in " ".join(error["errors"])
            for error in errors
        ) == 5
        assert sum(
            any(message.startswith("Missing mandatory field:")
                for message in error["errors"])
            for error in errors
        ) == 5


def test_import_orders_persists_valid_sample_rows_and_reports_rejections():
    project_root = Path(__file__).resolve().parents[1]
    csv_content = (project_root / "data" / "sample_orders.csv").read_bytes()
    upload = NamedBytesIO(csv_content, "sample_orders.csv")

    result = import_orders(upload)

    assert result["imported"] == 100
    assert len(result["errors"]) == 10
    with get_connection() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM orders"
        ).fetchone()[0] == 100


def test_excel_import_persists_valid_sample_rows():
    project_root = Path(__file__).resolve().parents[1]
    excel_content = (
        project_root / "data" / "sample_orders.xlsx"
    ).read_bytes()
    upload = NamedBytesIO(excel_content, "sample_orders.xlsx")

    result = import_orders(upload)

    assert result["imported"] == 100
    assert len(result["errors"]) == 10
    with get_connection() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM orders"
        ).fetchone()[0] == 100


def test_invalid_dates_are_rejected_and_timezone_offsets_normalized():
    df = pd.DataFrame([
        {
            "Order ID": "ORD-TZ",
            "Order Date": "2026-10-16T10:00:00+05:30",
            "Customer Name": "Customer",
            "Phone Number": "9876543210",
            "Order Value": 1000,
            "Payment Type": "COD",
            "Order Status": "placed",
            "Dispatch Date": None,
            "Expected Delivery Date": "2026-10-17",
            "Assigned Employee": "Employee A",
        },
        {
            "Order ID": "ORD-BAD-DATE",
            "Order Date": "not-a-date",
            "Customer Name": "Customer",
            "Phone Number": "9876543210",
            "Order Value": 1000,
            "Payment Type": "COD",
            "Order Status": "placed",
            "Dispatch Date": None,
            "Expected Delivery Date": "2026-10-17",
            "Assigned Employee": "Employee A",
        },
    ])

    records, errors = validate_dataframe(df)

    assert len(records) == 2
    assert records[0]["order_date"] == "2026-10-16 04:30:00"
    assert records[1]["order_date"] is None
    assert len(errors) == 1
    assert "Invalid date: order_date" in errors[0]["errors"]
