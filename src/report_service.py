"""Daily exception report generation."""

from datetime import datetime, timezone

import pandas as pd


def _as_utc_naive(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def build_daily_exception_report(tasks, now=None):
    """Return task rows tagged with each applicable daily-report category."""
    report = tasks.copy()
    if report.empty:
        report["is_new_exception"] = pd.Series(dtype=bool)
        report["is_unresolved"] = pd.Series(dtype=bool)
        report["is_overdue"] = pd.Series(dtype=bool)
        report["report_categories"] = pd.Series(dtype=str)
        return report

    now = _as_utc_naive(now or datetime.now(timezone.utc))
    if now is None:
        raise ValueError("now must be a valid datetime")

    status = report["status"].fillna("").astype(str)
    unresolved = status.ne("Resolved")

    created_values = report.get(
        "exception_created_at",
        pd.Series(index=report.index, dtype=object),
    )
    created_at = pd.to_datetime(
        created_values, errors="coerce", utc=True
    )
    new_exception = created_at.dt.date.eq(now.date())

    deadline_values = report.get(
        "deadline",
        pd.Series(index=report.index, dtype=object),
    )
    deadlines = deadline_values.map(_as_utc_naive)

    def deadline_is_overdue(deadline):
        if deadline is None or pd.isna(deadline):
            return False
        if deadline.time() == datetime.min.time():
            return deadline.date() < now.date()
        return deadline < now

    overdue = deadlines.map(deadline_is_overdue) & unresolved
    high_priority = (
        report["priority"].fillna("").astype(str).eq("High")
        & unresolved
    )
    assigned_pending = (
        report["assigned_employee"].notna()
        & report["assigned_employee"].astype(str).str.strip().ne("")
        & unresolved
    )

    report["is_new_exception"] = new_exception
    report["is_unresolved"] = unresolved
    report["is_overdue"] = overdue

    categories = []
    for is_new, is_open, is_late, is_high, has_owner in zip(
        new_exception,
        unresolved,
        overdue,
        high_priority,
        assigned_pending,
    ):
        labels = []
        if is_new:
            labels.append("New Exception")
        if is_open:
            labels.append("Unresolved Exception")
        if is_late:
            labels.append("Overdue Task")
        if is_high:
            labels.append("High Priority")
        if has_owner:
            labels.append("Employee-wise Pending Action")
        categories.append("; ".join(labels))

    report["report_categories"] = categories
    return report.loc[report["report_categories"].ne("")].copy()
