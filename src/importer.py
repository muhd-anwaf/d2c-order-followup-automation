
import sqlite3
import zipfile

import pandas as pd

from config import MAX_DATABASE_SIZE_BYTES, MAX_UPLOAD_SIZE_MB
from src.database import (
    DatabaseSizeLimitError,
    ensure_database_capacity,
    get_connection,
    verify_database_capacity,
)
from src.validator import validate_dataframe


def _uploaded_file_size(uploaded_file):
    size = getattr(uploaded_file, "size", None)
    if size is not None:
        return int(size)

    current_position = uploaded_file.tell()
    uploaded_file.seek(0, 2)
    size = uploaded_file.tell()
    uploaded_file.seek(current_position)
    return size


def _estimate_database_growth(records):
    # Row payload plus SQLite page/index/record overhead; final sizing is also
    # checked against SQLite's page count and on-disk files in the transaction.
    return sum(
        8192 + sum(
            len(str(value).encode("utf-8"))
            for value in record.values()
            if value is not None
        )
        for record in records
    )


def import_orders(uploaded_file):
    filename = uploaded_file.name.lower()

    if _uploaded_file_size(uploaded_file) > MAX_UPLOAD_SIZE_MB * 1024 * 1024:
        return {
            "imported": 0,
            "errors": [{
                "row": None,
                "order_id": None,
                "errors": [
                    f"File exceeds the {MAX_UPLOAD_SIZE_MB} MB upload limit"
                ],
            }],
        }

    if not filename.endswith((".csv", ".xlsx", ".xls")):
        return {
            "imported": 0,
            "errors": [{
                "row": None,
                "order_id": None,
                "errors": ["Only CSV and Excel files are supported"],
            }],
        }

    try:
        if filename.endswith(".csv"):
            df = pd.read_csv(uploaded_file)
        else:
            df = pd.read_excel(uploaded_file)
    except (
        pd.errors.ParserError,
        pd.errors.EmptyDataError,
        UnicodeDecodeError,
        ValueError,
        OSError,
        ImportError,
        zipfile.BadZipFile,
    ) as exc:
        return {
            "imported": 0,
            "errors": [{
                "row": None,
                "order_id": None,
                "errors": [f"Could not read uploaded file: {exc}"],
            }],
        }

    records, errors = validate_dataframe(df)
    imported = 0

    try:
        with get_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            new_records = []
            for record in records:
                existing = connection.execute(
                    "SELECT 1 FROM orders WHERE order_id = ?",
                    (record["order_id"],),
                ).fetchone()

                if existing:
                    errors.append({
                        "row": None,
                        "order_id": record["order_id"],
                        "errors": ["Order ID already exists in database"],
                    })
                    continue
                new_records.append(record)

            if new_records:
                ensure_database_capacity(
                    connection,
                    estimated_growth_bytes=_estimate_database_growth(
                        new_records
                    ),
                    limit_bytes=MAX_DATABASE_SIZE_BYTES,
                )

            for record in new_records:
                connection.execute("""
                    INSERT INTO orders (
                        order_id, order_date, customer_name,
                        phone_number, order_value, payment_type,
                        order_status, dispatch_date,
                        expected_delivery_date, assigned_employee
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    record["order_id"],
                    record["order_date"],
                    record["customer_name"],
                    record["phone_number"],
                    record["order_value"],
                    record["payment_type"],
                    record["order_status"],
                    record["dispatch_date"],
                    record["expected_delivery_date"],
                    record["assigned_employee"],
                ))

                imported += 1

            if new_records:
                verify_database_capacity(
                    connection,
                    limit_bytes=MAX_DATABASE_SIZE_BYTES,
                )
    except DatabaseSizeLimitError:
        raise DatabaseSizeLimitError(
            "Could not upload data: the database size limit of 100 MB "
            "would be exceeded. Clear existing data or upload a smaller "
            "dataset."
        ) from None
    except sqlite3.OperationalError as exc:
        if "full" in str(exc).lower():
            raise DatabaseSizeLimitError(
                "Could not upload data: the database size limit of 100 MB "
                "would be exceeded. Clear existing data or upload a smaller "
                "dataset."
            ) from exc
        raise

    return {
        "imported": imported,
        "errors": errors,
    }
