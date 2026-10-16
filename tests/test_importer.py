"""Tests for order importing and validation."""

from io import BytesIO
from pathlib import Path

import pandas as pd

from config import MAX_UPLOAD_SIZE_MB
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


def test_import_rejects_files_larger_than_10_mb_without_importing():
    upload = NamedBytesIO(
        b"Order ID\n" + b"x" * (MAX_UPLOAD_SIZE_MB * 1024 * 1024),
        "oversized.csv",
    )

    result = import_orders(upload)

    assert result["imported"] == 0
    assert result["errors"] == [{
        "row": None,
        "order_id": None,
        "errors": ["File exceeds the 10 MB upload limit"],
    }]
    with get_connection() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM orders"
        ).fetchone()[0] == 0


def test_import_accepts_file_exactly_at_size_limit():
    csv_content = (
        b"Order ID,Order Date,Customer Name,Phone Number,Order Value,"
        b"Payment Type,Order Status,Dispatch Date,"
        b"Expected Delivery Date,Assigned Employee\n"
        b"ORD-EXACT-LIMIT,2026-10-16 08:00:00,Customer,9876543210,1000,"
        b"COD,placed,,,Employee A\n"
    )
    csv_content += b"\n" * (
        MAX_UPLOAD_SIZE_MB * 1024 * 1024 - len(csv_content)
    )
    upload = NamedBytesIO(csv_content, "exact-limit.csv")

    result = import_orders(upload)

    assert result["imported"] == 1
    assert not any(
        "upload limit" in " ".join(error["errors"])
        for error in result["errors"]
    )


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


def test_dispatched_order_requires_expected_delivery_date():
    df = pd.DataFrame([{
        "Order ID": "ORD-DISPATCHED-NO-ETA",
        "Order Date": "2026-10-16 08:00:00",
        "Customer Name": "Customer",
        "Phone Number": "9876543210",
        "Order Value": 1000,
        "Payment Type": "COD",
        "Order Status": " dispatched ",
        "Dispatch Date": "2026-10-16 09:00:00",
        "Expected Delivery Date": None,
        "Assigned Employee": "Employee A",
    }])

    records, errors = validate_dataframe(df)

    assert records == []
    assert len(errors) == 1
    assert "Missing mandatory field: expected_delivery_date" in errors[0][
        "errors"
    ]


def test_import_rejects_dispatched_order_without_expected_delivery_date():
    df = pd.DataFrame([{
        "Order ID": "ORD-DISPATCHED-NO-ETA",
        "Order Date": "2026-10-16 08:00:00",
        "Customer Name": "Customer",
        "Phone Number": "9876543210",
        "Order Value": 1000,
        "Payment Type": "COD",
        "Order Status": "dispatched",
        "Dispatch Date": "2026-10-16 09:00:00",
        "Expected Delivery Date": "",
        "Assigned Employee": "Employee A",
    }])
    upload = NamedBytesIO(
        df.to_csv(index=False).encode("utf-8"),
        "dispatched_missing_eta.csv",
    )

    result = import_orders(upload)

    assert result["imported"] == 0
    assert len(result["errors"]) == 1
    assert "Missing mandatory field: expected_delivery_date" in result[
        "errors"
    ][0]["errors"]
    with get_connection() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM orders"
        ).fetchone()[0] == 0


def test_csv_and_excel_sample_files_have_expected_valid_and_invalid_rows():
    project_root = Path(__file__).resolve().parents[1]
    csv_path = project_root / "data" / "sample_orders.csv"
    excel_path = project_root / "data" / "sample_orders.xlsx"

    for path in (csv_path, excel_path):
        df = pd.read_csv(path) if path.suffix == ".csv" else pd.read_excel(path)
        records, errors = validate_dataframe(df)

        assert len(df) == 116
        assert df.loc[
            df["Order ID"] != "ORD-INVALID-BAD-ORDER-DATE",
            "Order Date",
        ].astype(str).str.fullmatch(
            r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}"
        ).all()
        assert len(records) == 100
        assert len(errors) == 16
        assert sum(
            "Duplicate order ID in uploaded file" in " ".join(error["errors"])
            for error in errors
        ) == 5
        assert sum(
            any(message.startswith("Missing mandatory field:")
                for message in error["errors"])
            for error in errors
        ) == 6
        dispatched_without_eta = [
            error for error in errors
            if error["order_id"] == "ORD-INVALID-DISPATCH-NO-ETA"
        ]
        assert len(dispatched_without_eta) == 1
        assert (
            "Missing mandatory field: expected_delivery_date"
            in dispatched_without_eta[0]["errors"]
        )
        assert any(
            error["order_id"] == "ORD-INVALID-DISPATCH-BAD-ETA"
            and "Invalid date: expected_delivery_date" in error["errors"]
            for error in errors
        )
        for invalid_order_id in (
            "ORD-INVALID-BAD-ORDER-DATE",
            "ORD-INVALID-STATUS",
            "ORD-INVALID-PAYMENT",
            "ORD-INVALID-NEGATIVE-VALUE",
        ):
            assert any(
                error["order_id"] == invalid_order_id
                for error in errors
            )


def test_import_orders_persists_valid_sample_rows_and_reports_rejections():
    project_root = Path(__file__).resolve().parents[1]
    csv_content = (project_root / "data" / "sample_orders.csv").read_bytes()
    upload = NamedBytesIO(csv_content, "sample_orders.csv")

    result = import_orders(upload)

    assert result["imported"] == 100
    assert len(result["errors"]) == 16
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
    assert len(result["errors"]) == 16
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
