

from datetime import datetime, timedelta, timezone

from src.database import get_connection
from config import (
    UNCONFIRMED_LIMIT_HOURS,
    DISPATCH_LIMIT_HOURS,
    HIGH_VALUE_THRESHOLD,
    DEFAULT_PRIORITY,
    UNCONFIRMED_STATUSES,
    ORDER_STATUSES,
)


DELIVERED_STATUSES = {"delivered"}
TERMINAL_STATUSES = {"cancelled"}


def parse_date(value):
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def is_undelivered(status):
    normalized_status = str(status or "").strip().lower()
    return normalized_status not in DELIVERED_STATUSES | TERMINAL_STATUSES


def is_date_past(value, now):
    date_value = parse_date(value)

    if date_value is None:
        return False

    # Date-only values represent a calendar day.
    if date_value.time() == datetime.min.time():
        return date_value.date() < now.date()

    return date_value < now


def evaluate_order(
    order,
    now=None,
    dispatch_limit_hours=DISPATCH_LIMIT_HOURS,
):
    """Return all applicable exceptions for one order."""
    if dispatch_limit_hours <= 0:
        raise ValueError("dispatch_limit_hours must be greater than zero")

    now = parse_date(now or datetime.now(timezone.utc))
    if now is None:
        raise ValueError("now must be a valid datetime")
    exceptions = []

    order_id = order["order_id"]
    status = str(order["order_status"] or "").strip().lower()
    order_date = parse_date(order["order_date"])
    dispatch_date = parse_date(order["dispatch_date"])
    expected_date = parse_date(order["expected_delivery_date"])

    try:
        order_value = float(order["order_value"])
    except (ValueError, TypeError):
        order_value = None

    def add_exception(exception_type, reason, action):
        existing = next(
            (
                item for item in exceptions
                if item["exception_type"] == exception_type
            ),
            None,
        )
        if existing is not None:
            if reason not in existing["reason"]:
                existing["reason"] += f" {reason}"
            if action not in existing["recommended_action"]:
                existing["recommended_action"] += f" {action}"
            return

        exceptions.append(
            {
                "exception_key": f"{order_id}:{exception_type}",
                "order_id": order_id,
                "exception_type": exception_type,
                "reason": reason,
                "priority": (
                    "High"
                    if order_value is not None
                    and order_value > HIGH_VALUE_THRESHOLD
                    else DEFAULT_PRIORITY[exception_type]
                ),
                "recommended_action": action,
            }
        )

    # Rule 1: Unconfirmed orders
    if status in UNCONFIRMED_STATUSES:
        if order_date is None:
            add_exception(
                "Data Correction",
                "Order date is missing or invalid; confirmation delay "
                "cannot be calculated.",
                "Correct the order date and rerun the rule engine.",
            )
        elif now - order_date > timedelta(
            hours=UNCONFIRMED_LIMIT_HOURS
        ):
            add_exception(
                "Unconfirmed Order",
                f"Order has remained unconfirmed for more than "
                f"{UNCONFIRMED_LIMIT_HOURS} hours.",
                "Contact the customer and confirm the order.",
            )

    # Rule 2: Placed but not dispatched
    if status == "placed" and dispatch_date is None:
        if order_date is None:
            add_exception(
                "Data Correction",
                "Order date is missing or invalid; placed-order delay "
                "cannot be calculated.",
                "Correct the order date and rerun the rule engine.",
            )
        elif now - order_date > timedelta(hours=dispatch_limit_hours):
            add_exception(
                "Dispatch Delay",
                f"Placed order has not been dispatched within "
                f"{dispatch_limit_hours} hours.",
                "Contact the warehouse and arrange dispatch.",
            )

    # Rule 3: Dispatched but overdue
    if status == "dispatched":
        if expected_date is None:
            add_exception(
                "Data Correction",
                "Expected delivery date is missing or invalid.",
                "Correct the expected delivery date.",
            )
        elif is_date_past(order["expected_delivery_date"], now):
            add_exception(
                "Shipment Delay",
                "Expected delivery date has passed and the order "
                "is not delivered.",
                "Contact the courier and obtain a delivery update.",
            )

    # Rule 4: Failed delivery attempt
    if status == "failed_delivery":
        add_exception(
            "Failed Delivery",
            "The shipment has a failed delivery attempt.",
            "Contact the customer and arrange another delivery attempt.",
        )

    if status not in ORDER_STATUSES:
        add_exception(
            "Data Correction",
            f"Order status '{status}' is not a supported order status.",
            "Correct the order status to a supported value and rerun "
            "the rule engine.",
        )

    return exceptions


def run_rule_engine(now=None, dispatch_limit_hours=DISPATCH_LIMIT_HOURS):
    """Evaluate stored orders and persist new exceptions."""
    with get_connection() as connection:
        orders = connection.execute(
            "SELECT * FROM orders"
        ).fetchall()

        created = 0

        for order in orders:
            for exception in evaluate_order(
                dict(order),
                now,
                dispatch_limit_hours=dispatch_limit_hours,
            ):
                cursor = connection.execute("""
                    INSERT OR IGNORE INTO exceptions (
                        exception_key,
                        order_id,
                        exception_type,
                        reason,
                        priority,
                        recommended_action
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    exception["exception_key"],
                    exception["order_id"],
                    exception["exception_type"],
                    exception["reason"],
                    exception["priority"],
                    exception["recommended_action"],
                ))

                created += cursor.rowcount

    return created
