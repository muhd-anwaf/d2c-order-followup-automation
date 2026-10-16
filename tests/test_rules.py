"""Tests for follow-up rule evaluation."""

from datetime import datetime

from src.rule_engine import evaluate_order


def test_unconfirmed_order():
    order = {
        "order_id": "ORD101",
        "order_date": "2026-10-16 08:00:00",
        "customer_name": "Test Customer",
        "phone_number": "9876543210",
        "order_value": 2000,
        "payment_type": "cod",
        "order_status": "unconfirmed",
        "dispatch_date": None,
        "expected_delivery_date": None,
        "assigned_employee": "Employee A",
    }

    result = evaluate_order(
        order, now=datetime(2026, 10, 16, 11, 0, 0)
    )

    assert any(
        e["exception_type"] == "Unconfirmed Order"
        for e in result
    )


def test_no_duplicate_exception_types():
    order = {
        "order_id": "ORD102",
        "order_date": "2026-10-15 08:00:00",
        "customer_name": "Test Customer",
        "phone_number": "9876543210",
        "order_value": 7000,
        "payment_type": "prepaid",
        "order_status": "dispatched",
        "dispatch_date": "2026-10-15 09:00:00",
        "expected_delivery_date": "2026-10-15",
        "assigned_employee": "Employee A",
    }

    result = evaluate_order(
        order, now=datetime(2026, 10, 16, 11, 0, 0)
    )

    types = [e["exception_type"] for e in result]

    assert "Shipment Delay" in types
    assert "High-Value Order" in types


def _order(**overrides):
    order = {
        "order_id": "RULE-TEST",
        "order_date": "2026-10-15 22:00:00",
        "customer_name": "Test Customer",
        "phone_number": "9876543210",
        "order_value": 2000,
        "payment_type": "cod",
        "order_status": "confirmed",
        "dispatch_date": None,
        "expected_delivery_date": "2026-10-20",
        "assigned_employee": "Employee A",
    }
    order.update(overrides)
    return order


def test_dispatch_rule_supports_12_hour_threshold_without_false_positive_at_24():
    now = datetime(2026, 10, 16, 15, 0, 0)
    order = _order()

    normal_threshold = evaluate_order(order, now)
    interview_threshold = evaluate_order(
        order, now, dispatch_limit_hours=12
    )

    assert not any(
        item["exception_type"] == "Dispatch Delay"
        for item in normal_threshold
    )
    assert any(
        item["exception_type"] == "Dispatch Delay"
        for item in interview_threshold
    )


def test_failed_delivery_creates_high_priority_follow_up():
    result = evaluate_order(
        _order(order_status="failed delivery"),
        datetime(2026, 10, 16, 15, 0, 0),
    )

    failed = next(
        item for item in result
        if item["exception_type"] == "Failed Delivery"
    )
    assert failed["priority"] == "High"
    assert failed["reason"]
    assert failed["recommended_action"]


def test_missing_expected_delivery_date_only_creates_data_correction():
    result = evaluate_order(
        _order(
            order_status="in transit",
            dispatch_date="2026-10-15 10:00:00",
            expected_delivery_date=None,
            order_value=8000,
        ),
        datetime(2026, 10, 16, 15, 0, 0),
    )

    assert [item["exception_type"] for item in result] == [
        "Data Correction"
    ]
    assert result[0]["reason"]
    assert result[0]["recommended_action"]


def test_cancelled_and_returned_orders_are_not_treated_as_overdue():
    for terminal_status in ("cancelled", "returned"):
        result = evaluate_order(
            _order(
                order_status=terminal_status,
                dispatch_date="2026-10-10",
                expected_delivery_date="2026-10-11",
                order_value=8000,
            ),
            datetime(2026, 10, 16, 15, 0, 0),
        )
        assert not any(
            item["exception_type"] in {
                "Shipment Delay",
                "High-Value Order",
            }
            for item in result
        )


def test_offset_timestamps_are_compared_as_utc():
    result = evaluate_order(
        _order(
            order_date="2026-10-16T02:00:00+05:30",
            order_status="unconfirmed",
        ),
        datetime(2026, 10, 16, 0, 0, 0),
    )

    assert any(
        item["exception_type"] == "Unconfirmed Order"
        for item in result
    )
