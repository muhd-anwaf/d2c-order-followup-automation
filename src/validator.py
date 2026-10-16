
import math

import pandas as pd

from config import UNCONFIRMED_STATUSES

REQUIRED_COLUMNS = [
    "order_id",
    "order_date",
    "customer_name",
    "phone_number",
    "order_value",
    "payment_type",
    "order_status",
    "dispatch_date",
    "expected_delivery_date",
    "assigned_employee",
]

MANDATORY_FIELDS = [
    "order_id",
    "order_date",
    "customer_name",
    "phone_number",
    "order_value",
    "payment_type",
    "order_status",
]

DATE_FIELDS = [
    "order_date",
    "dispatch_date",
    "expected_delivery_date",
]


def normalize_columns(df):
    """Normalize column names and common variations."""
    df = df.copy()
    df.columns = (
        df.columns.astype(str)
        .str.strip()
        .str.lower()
        .str.replace(r"[^a-z0-9]+", "_", regex=True)
        .str.strip("_")
    )

    aliases = {
        "orderid": "order_id",
        "customer": "customer_name",
        "customer_phone": "phone_number",
        "phone": "phone_number",
        "value": "order_value",
        "order_value_inr": "order_value",
        "ordervalueinr": "order_value",
        "payment": "payment_type",
        "status": "order_status",
        "dispatch": "dispatch_date",
        "expected_delivery": "expected_delivery_date",
        "employee": "assigned_employee",
    }

    df = df.rename(columns=aliases)
    duplicated_columns = df.columns[df.columns.duplicated()].tolist()
    if duplicated_columns:
        raise ValueError(
            "Multiple columns map to the same field: "
            + ", ".join(sorted(set(duplicated_columns)))
        )
    return df


def validate_dataframe(df):
    try:
        df = normalize_columns(df)
    except ValueError as exc:
        return [], [{
            "row": None,
            "order_id": None,
            "errors": [str(exc)],
        }]

    missing_columns = [
        column for column in REQUIRED_COLUMNS
        if column not in df.columns
    ]

    if missing_columns:
        return [], [{
            "row": None,
            "order_id": None,
            "errors": [
                f"Missing columns: {', '.join(missing_columns)}"
            ],
        }]

    valid_records = []
    errors = []
    seen_ids = set()

    for index, row in df.iterrows():
        record = row.to_dict()
        row_errors = []

        order_id = record.get("order_id")
        order_id = (
            str(order_id).strip()
            if pd.notna(order_id) else ""
        )
        record["order_id"] = order_id
        status_value = record.get("order_status")
        normalized_status = (
            str(status_value).strip().lower()
            if pd.notna(status_value)
            else ""
        )

        for field in MANDATORY_FIELDS:
            if (
                field == "order_date"
                and normalized_status in UNCONFIRMED_STATUSES
            ):
                continue
            value = record.get(field)

            if pd.isna(value) or str(value).strip() == "":
                row_errors.append(f"Missing mandatory field: {field}")

        if order_id:
            normalized_id = order_id.casefold()
            if normalized_id in seen_ids:
                row_errors.append("Duplicate order ID in uploaded file")
            seen_ids.add(normalized_id)

        for field in DATE_FIELDS:
            value = record.get(field)

            if pd.isna(value) or str(value).strip() == "":
                record[field] = None
                if (
                    field == "order_date"
                    and normalized_status in UNCONFIRMED_STATUSES
                ):
                    row_errors.append(
                        "Missing mandatory field: order_date"
                    )
                continue

            try:
                parsed_date = pd.to_datetime(
                    value, errors="raise", utc=True
                )
                record[field] = parsed_date.strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            except (ValueError, TypeError, OverflowError):
                record[field] = None
                row_errors.append(f"Invalid date: {field}")

        try:
            value = record.get("order_value")
            if pd.isna(value) or str(value).strip() == "":
                pass
            else:
                record["order_value"] = float(value)
                if not math.isfinite(record["order_value"]):
                    row_errors.append("Order value must be finite")
                elif record["order_value"] < 0:
                    row_errors.append("Order value cannot be negative")
        except (ValueError, TypeError):
            row_errors.append("Invalid order value")

        payment = record.get("payment_type")
        if pd.notna(payment):
            payment = str(payment).strip().lower()
            if payment not in ("prepaid", "cod"):
                row_errors.append(
                    "Payment type must be prepaid or COD"
                )
            record["payment_type"] = payment

        status = record.get("order_status")
        if pd.notna(status):
            record["order_status"] = str(status).strip().lower()

        for field in [
            "customer_name", "phone_number", "assigned_employee"
        ]:
            value = record.get(field)
            record[field] = (
                str(value).strip()
                if pd.notna(value) and str(value).strip()
                else None
            )

        if row_errors:
            errors.append({
                "row": int(index) + 2,
                "order_id": order_id or None,
                "errors": row_errors,
            })
            date_correction_only = set(row_errors).issubset({
                "Missing mandatory field: order_date",
                "Invalid date: order_date",
            })
            if (
                normalized_status in UNCONFIRMED_STATUSES
                and date_correction_only
            ):
                valid_records.append(record)
        else:
            valid_records.append(record)

    return valid_records, errors
