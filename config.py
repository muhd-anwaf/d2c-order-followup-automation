"""Application configuration."""

UNCONFIRMED_LIMIT_HOURS = 2
UNCONFIRMED_STATUSES = {"processing"}
ORDER_STATUSES = {
    "processing",
    "placed",
    "cancelled",
    "dispatched",
    "delivered",
    "failed_delivery",
}
DISPATCH_LIMIT_HOURS = 24
HIGH_VALUE_THRESHOLD = 5000
MAX_UPLOAD_SIZE_MB = 10

DEFAULT_PRIORITY = {
    "Unconfirmed Order": "Medium",
    "Dispatch Delay": "Medium",
    "Shipment Delay": "Medium",
    "Failed Delivery": "High",
    "Data Correction": "Medium",
}
