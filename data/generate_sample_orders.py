"""Regenerate the demonstration order files with dates relative to today."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd


def main():
    generated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    base_date = generated_at.date()
    rows = []

    def add_order(
        order_id: str,
        category: str,
        status: str,
        *,
        order_offset: int = 0,
        dispatch_offset: int | None = None,
        delivery_offset: int | None = 5,
        value: int = 2500,
        assigned: str = "Asha Nair",
    ) -> None:
        order_day = base_date + timedelta(days=order_offset)
        dispatch_day = (
            base_date + timedelta(days=dispatch_offset)
            if dispatch_offset is not None
            else None
        )
        delivery_day = (
            base_date + timedelta(days=delivery_offset)
            if delivery_offset is not None
            else None
        )

        if category == "borderline_dispatch":
            order_date = (
                generated_at - timedelta(hours=18)
            ).strftime("%Y-%m-%d %H:%M:%S")
        elif category == "unconfirmed":
            order_date = (
                generated_at - timedelta(hours=4)
            ).strftime("%Y-%m-%d %H:%M:%S")
        elif category == "dispatch_delay":
            order_date = f"{order_day.isoformat()} 08:00:00"
        else:
            order_date = f"{order_day.isoformat()} 08:00:00"

        rows.append({
            "Order ID": order_id,
            "Order Date": order_date,
            "Customer Name": f"Customer {order_id}",
            "Phone Number": f"+91 90000{len(rows):05d}",
            "Order Value (INR)": value,
            "Payment Type": "Prepaid" if len(rows) % 2 else "COD",
            "Order Status": status,
            "Dispatch Date": (
                dispatch_day.isoformat() if dispatch_day else None
            ),
            "Expected Delivery Date": (
                delivery_day.isoformat() if delivery_day else None
            ),
            "Assigned Employee": assigned,
        })

    for index in range(1, 16):
        add_order(
            f"ORD-NORM-D-{index:03}",
            "normal",
            "delivered",
            order_offset=-2,
            dispatch_offset=-1,
            delivery_offset=0,
            assigned="Asha Nair",
        )
    for index in range(1, 16):
        add_order(
            f"ORD-NORM-C-{index:03}",
            "normal",
            "placed",
            dispatch_offset=0,
            assigned="Ravi Kumar",
        )
    for index in range(1, 16):
        add_order(
            f"ORD-UNCONF-{index:03}",
            "unconfirmed",
            "Processing",
            delivery_offset=3,
            assigned="Asha Nair",
        )
    for index in range(1, 6):
        add_order(
            f"ORD-DISP-B-{index:03}",
            "borderline_dispatch",
            "placed",
            assigned="Meera Das",
        )
    for index in range(6, 16):
        add_order(
            f"ORD-DISP-{index:03}",
            "dispatch_delay",
            "placed",
            order_offset=-2,
            assigned="Meera Das",
        )
    for index in range(1, 16):
        add_order(
            f"ORD-SHIP-{index:03}",
            "overdue_shipment",
            "dispatched",
            order_offset=-4,
            dispatch_offset=-3,
            delivery_offset=-1,
            assigned="Asha Nair",
        )
    for index in range(1, 11):
        add_order(
            f"ORD-FAIL-{index:03}",
            "failed_delivery",
            "failed_delivery",
            order_offset=-2,
            dispatch_offset=-1,
            delivery_offset=2,
            assigned="Ravi Kumar",
        )
    for index in range(1, 11):
        add_order(
            f"ORD-HIGH-{index:03}",
            "high_value",
            "dispatched",
            order_offset=-4,
            dispatch_offset=-3,
            delivery_offset=-1,
            value=6500 + index * 100,
            assigned="Meera Das",
        )
    for index in range(1, 6):
        add_order(
            f"ORD-DATA-{index:03}",
            "data_correction",
            "dispatched",
            order_offset=-2,
            dispatch_offset=-1,
            delivery_offset=None,
            assigned="Ravi Kumar",
        )

    if len(rows) != 100:
        raise RuntimeError(f"Expected 100 valid records, generated {len(rows)}")

    rows.extend(dict(row) for row in rows[:5])
    missing_fields = (
        "Customer Name",
        "Phone Number",
        "Order Value (INR)",
        "Payment Type",
        "Order Status",
    )
    for index, missing_field in enumerate(missing_fields, 1):
        incomplete = dict(rows[20 + index])
        incomplete["Order ID"] = f"ORD-INVALID-{index:03}"
        incomplete[missing_field] = None
        rows.append(incomplete)

    output_dir = Path(__file__).resolve().parent
    frame = pd.DataFrame(rows)
    frame.to_csv(output_dir / "sample_orders.csv", index=False)
    frame.to_excel(output_dir / "sample_orders.xlsx", index=False)
    print(
        "Generated sample_orders.csv and sample_orders.xlsx: "
        "100 valid unique orders, 5 duplicate rows, 5 incomplete rows."
    )


if __name__ == "__main__":
    main()
