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
        "order_status": "processing",
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
    assert result[0]["priority"] == "High"


def _order(**overrides):
    order = {
        "order_id": "RULE-TEST",
        "order_date": "2026-10-15 22:00:00",
        "customer_name": "Test Customer",
        "phone_number": "9876543210",
        "order_value": 2000,
        "payment_type": "cod",
        "order_status": "placed",
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
        _order(order_status="failed_delivery"),
        datetime(2026, 10, 16, 15, 0, 0),
    )

    failed = next(
        item for item in result
        if item["exception_type"] == "Failed Delivery"
    )
    assert failed["priority"] == "High"
    assert failed["reason"]
    assert failed["recommended_action"]


def test_placed_order_uses_strict_24_hour_dispatch_threshold_and_medium_priority():
    now = datetime(2026, 10, 16, 12, 0, 0)

    exactly_24_hours = evaluate_order(
        _order(
            order_status=" PLACED ",
            order_date="2026-10-15 12:00:00",
        ),
        now,
    )
    older_than_24_hours = evaluate_order(
        _order(
            order_status="placed",
            order_date="2026-10-15 11:59:59",
        ),
        now,
    )

    assert not any(
        item["exception_type"] == "Dispatch Delay"
        for item in exactly_24_hours
    )
    dispatch_exception = next(
        item for item in older_than_24_hours
        if item["exception_type"] == "Dispatch Delay"
    )
    assert dispatch_exception["priority"] == "Medium"
    assert dispatch_exception["reason"]
    assert dispatch_exception["recommended_action"]


def test_dispatched_overdue_order_gets_medium_shipment_priority():
    result = evaluate_order(
        _order(
            order_status="dispatched",
            dispatch_date="2026-10-14 10:00:00",
            expected_delivery_date="2026-10-15 10:00:00",
        ),
        datetime(2026, 10, 16, 12, 0, 0),
    )

    shipment = next(
        item for item in result
        if item["exception_type"] == "Shipment Delay"
    )
    assert shipment["priority"] == "Medium"
    assert shipment["reason"]
    assert shipment["recommended_action"]


def test_dispatched_order_is_overdue_only_after_expected_delivery_timestamp():
    order = _order(
        order_status="dispatched",
        dispatch_date="2026-10-15 10:00:00",
        expected_delivery_date="2026-10-16 12:00:00",
    )

    at_expected_time = evaluate_order(
        order, datetime(2026, 10, 16, 12, 0, 0)
    )
    after_expected_time = evaluate_order(
        order, datetime(2026, 10, 16, 12, 0, 1)
    )

    assert not any(
        item["exception_type"] == "Shipment Delay"
        for item in at_expected_time
    )
    assert any(
        item["exception_type"] == "Shipment Delay"
        for item in after_expected_time
    )


def test_high_value_orders_raise_applicable_exception_priority_only():
    low_value_result = evaluate_order(
        _order(
            order_status="processing",
            order_date="2026-10-16 08:00:00",
            order_value=5000,
        ),
        datetime(2026, 10, 16, 12, 0, 0),
    )
    high_value_result = evaluate_order(
        _order(
            order_status="processing",
            order_date="2026-10-16 08:00:00",
            order_value=5000.01,
        ),
        datetime(2026, 10, 16, 12, 0, 0),
    )

    assert low_value_result[0]["priority"] == "Medium"
    assert high_value_result[0]["exception_type"] == "Unconfirmed Order"
    assert high_value_result[0]["priority"] == "High"
    assert len(high_value_result) == 1


def test_missing_expected_delivery_date_only_creates_data_correction():
    result = evaluate_order(
        _order(
            order_status="dispatched",
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
    for terminal_status in ("cancelled", "delivered"):
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
            }
            for item in result
        )


def test_offset_timestamps_are_compared_as_utc():
    result = evaluate_order(
        _order(
            order_date="2026-10-16T02:00:00+05:30",
            order_status="processing",
        ),
        datetime(2026, 10, 16, 0, 0, 0),
    )

    assert any(
        item["exception_type"] == "Unconfirmed Order"
        for item in result
    )
