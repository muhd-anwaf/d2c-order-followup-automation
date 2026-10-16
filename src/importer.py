
import zipfile

import pandas as pd

from src.database import get_connection
from src.validator import validate_dataframe


def import_orders(uploaded_file):
    filename = uploaded_file.name.lower()

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
