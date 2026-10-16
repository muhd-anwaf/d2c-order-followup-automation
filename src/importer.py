
import zipfile

import pandas as pd

from config import MAX_UPLOAD_SIZE_MB
from src.database import get_connection
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

    with get_connection() as connection:
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

    return {
        "imported": imported,
        "errors": errors,
    }
