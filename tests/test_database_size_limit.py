import sqlite3
from io import BytesIO

import pandas as pd

import src.database as database
import src.importer as importer
from src.database import get_connection


class NamedBytesIO(BytesIO):
    def __init__(self, content, name="size_test.csv"):
        super().__init__(content)
        self.name = name


def _csv_upload(order_ids):
    frame = pd.DataFrame([
        {
            "Order ID": order_id,
            "Order Date": "2026-10-16 08:00:00",
            "Customer Name": f"Customer {order_id}",
            "Phone Number": "9876543210",
            "Order Value": 1000,
            "Payment Type": "COD",
            "Order Status": "placed",
            "Dispatch Date": None,
            "Expected Delivery Date": None,
            "Assigned Employee": "Employee A",
        }
        for order_id in order_ids
    ])
    return NamedBytesIO(frame.to_csv(index=False).encode("utf-8"))


def test_database_size_calculation_includes_sqlite_sidecar_files(
    tmp_path, monkeypatch
):
    path = tmp_path / "size_count.sqlite"
    monkeypatch.setattr(database, "DB_PATH", path)
    path.write_bytes(b"database")
    (tmp_path / "size_count.sqlite-wal").write_bytes(b"wal-file")
    (tmp_path / "size_count.sqlite-shm").write_bytes(b"shared-memory")
    (tmp_path / "size_count.sqlite-journal").write_bytes(b"journal")

    assert database.database_size_bytes() == (
        len(b"database")
        + len(b"wal-file")
        + len(b"shared-memory")
        + len(b"journal")
    )


def test_import_is_rejected_when_database_is_at_configured_limit(monkeypatch):
    monkeypatch.setattr(
        importer,
        "MAX_DATABASE_SIZE_BYTES",
        database.database_size_bytes(),
    )

    try:
        importer.import_orders(_csv_upload(["AT-LIMIT"]))
    except database.DatabaseSizeLimitError as exc:
        assert str(exc) == (
            "Could not upload data: the database size limit of 100 MB "
            "would be exceeded. Clear existing data or upload a smaller "
            "dataset."
        )
    else:
        raise AssertionError("Expected database size limit rejection")

    with get_connection() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM orders"
        ).fetchone()[0] == 0


def test_oversized_batch_is_rejected_without_partial_inserts(monkeypatch):
    current_size = database.database_size_bytes()
    monkeypatch.setattr(
        importer,
        "MAX_DATABASE_SIZE_BYTES",
        current_size + 13000,
    )

    try:
        importer.import_orders(_csv_upload(["BATCH-ONE", "BATCH-TWO"]))
    except database.DatabaseSizeLimitError:
        pass
    else:
        raise AssertionError("Expected oversized batch to be rejected")

    with get_connection() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM orders"
        ).fetchone()[0] == 0


def test_capacity_failure_after_inserts_rolls_back_the_import(monkeypatch):
    def reject_after_write(connection, limit_bytes=None):
        raise database.DatabaseSizeLimitError

    monkeypatch.setattr(
        importer,
        "verify_database_capacity",
        reject_after_write,
    )

    try:
        importer.import_orders(_csv_upload(["ROLLBACK-SIZE-TEST"]))
    except database.DatabaseSizeLimitError:
        pass
    else:
        raise AssertionError("Expected database size limit rejection")

    with get_connection() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM orders"
        ).fetchone()[0] == 0


def test_small_import_succeeds_when_database_has_capacity(monkeypatch):
    current_size = database.database_size_bytes()
    monkeypatch.setattr(
        importer,
        "MAX_DATABASE_SIZE_BYTES",
        current_size + 1024 * 1024,
    )

    result = importer.import_orders(_csv_upload(["SMALL-IMPORT"]))

    assert result["imported"] == 1
    with get_connection() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM orders"
        ).fetchone()[0] == 1


def test_database_size_calculation_counts_real_wal_storage():
    connection = sqlite3.connect(database.DB_PATH)
    try:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute(
            "INSERT INTO orders (order_id, order_status) "
            "VALUES ('WAL-SIZE-TEST', 'placed')"
        )
        connection.commit()
        wal_path = database.Path(f"{database.DB_PATH}-wal")
        assert wal_path.exists()
        measured_size = database.database_size_bytes()
        assert measured_size >= wal_path.stat().st_size
        assert measured_size == sum(
            path.stat().st_size
            for path in (
                database.DB_PATH,
                database.Path(f"{database.DB_PATH}-wal"),
                database.Path(f"{database.DB_PATH}-shm"),
                database.Path(f"{database.DB_PATH}-journal"),
            )
            if path.exists()
        )
    finally:
        connection.close()
