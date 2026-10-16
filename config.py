"""Application configuration."""

UNCONFIRMED_LIMIT_HOURS = 2
UNCONFIRMED_STATUSES = {
    "unconfirmed",
    "pending confirmation",
    "processing",
}
DISPATCH_LIMIT_HOURS = 24
HIGH_VALUE_THRESHOLD = 5000

DEFAULT_PRIORITY = {
    "Unconfirmed Order": "Medium",
    "Dispatch Delay": "High",
    "Shipment Delay": "High",
    "Failed Delivery": "High",
    "High-Value Order": "High",
    "Data Correction": "Medium",
}
