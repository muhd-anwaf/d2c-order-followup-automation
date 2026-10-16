"""Streamlit dashboard for D2C order follow-up operations."""

from datetime import datetime, timezone
import sqlite3

import pandas as pd
import streamlit as st

from config import DISPATCH_LIMIT_HOURS
from src.database import get_connection, initialize_database
from src.importer import import_orders
from src.report_service import build_daily_exception_report
from src.rule_engine import run_rule_engine
from src.task_service import create_tasks_for_exceptions, update_task


st.set_page_config(
    page_title="D2C Order Follow-up",
    page_icon="📦",
    layout="wide",
)

initialize_database()

st.title("D2C Order Follow-up")
st.caption("Monitor exceptions, assign follow-ups, and track resolution.")

st.sidebar.header("Order Import")
uploaded_file = st.sidebar.file_uploader(
    "Upload CSV or Excel",
    type=["csv", "xlsx", "xls"],
)

if st.sidebar.button("Import Orders", type="primary"):
    if uploaded_file is None:
        st.sidebar.error("Select a file first.")
    else:
        try:
            result = import_orders(uploaded_file)
            st.session_state["import_result"] = result
            st.sidebar.success(f"Imported {result['imported']} orders.")
        except (OSError, ValueError, ImportError, sqlite3.Error) as exc:
            st.sidebar.error(f"Import failed: {exc}")

if "import_result" in st.session_state:
    result = st.session_state["import_result"]
    if result["errors"]:
        st.subheader("Import validation errors")
        st.dataframe(
            pd.DataFrame(result["errors"]),
            use_container_width=True,
        )

st.sidebar.header("Exception processing")
dispatch_limit_hours = st.sidebar.number_input(
    "Dispatch delay threshold (hours)",
    min_value=1,
    value=DISPATCH_LIMIT_HOURS,
    step=1,
)
performed_by = st.sidebar.text_input(
    "Manager / audit actor",
    value="Manager",
)

if st.sidebar.button("Run Exception Detection"):
    try:
        new_exceptions = run_rule_engine(
            dispatch_limit_hours=int(dispatch_limit_hours)
        )
        new_tasks = create_tasks_for_exceptions(performed_by=performed_by)
        st.sidebar.success(
            f"Created {new_exceptions} exceptions and {new_tasks} tasks."
        )
    except (sqlite3.Error, ValueError) as exc:
        st.sidebar.error(f"Processing failed: {exc}")

with get_connection() as connection:
    orders = pd.read_sql_query(
        "SELECT * FROM orders", connection
    )
    tasks = pd.read_sql_query("""
        SELECT t.*, e.order_id, e.exception_type, e.reason,
               e.priority, e.recommended_action,
               e.created_at AS exception_created_at,
               o.customer_name, o.phone_number, o.order_date
        FROM tasks t
        JOIN exceptions e ON e.id = t.exception_id
        JOIN orders o ON o.order_id = e.order_id
        ORDER BY
            CASE e.priority
                WHEN 'High' THEN 1
                WHEN 'Medium' THEN 2
                ELSE 3
            END,
            t.deadline
    """, connection)

st.sidebar.header("Filters")
today = datetime.now().date()
if orders.empty:
    minimum_order_date = maximum_order_date = today
else:
    parsed_order_dates = pd.to_datetime(
        orders["order_date"], errors="coerce"
    ).dropna()
    if parsed_order_dates.empty:
        minimum_order_date = maximum_order_date = today
    else:
        minimum_order_date = parsed_order_dates.min().date()
        maximum_order_date = parsed_order_dates.max().date()

date_range = st.sidebar.date_input(
    "Order date range",
    value=(minimum_order_date, maximum_order_date),
)

filtered = tasks.copy()
selected_types = []
selected_employees = []
selected_priorities = []
if not tasks.empty:
    exception_types = sorted(tasks["exception_type"].dropna().unique())
    employees = sorted(tasks["assigned_employee"].dropna().unique())
    employee_options = ["Unassigned", *employees]

    selected_types = st.sidebar.multiselect(
        "Exception type", exception_types
    )
    selected_employees = st.sidebar.multiselect(
        "Employee", employee_options
    )
    selected_priorities = st.sidebar.multiselect(
        "Priority", ["High", "Medium", "Low"]
    )

if isinstance(date_range, (tuple, list)) and len(date_range) == 2:
    start_date, end_date = date_range
else:
    start_date = end_date = date_range

order_dates = pd.to_datetime(filtered["order_date"], errors="coerce").dt.date
filtered = filtered.loc[
    order_dates.between(start_date, end_date, inclusive="both")
].copy()
if selected_types:
    filtered = filtered[filtered["exception_type"].isin(selected_types)]
if selected_employees:
    assigned = filtered["assigned_employee"].fillna("").astype(str).str.strip()
    employee_filter = pd.Series(False, index=filtered.index)
    if "Unassigned" in selected_employees:
        employee_filter |= assigned.eq("")
    selected_named_employees = [
        employee for employee in selected_employees
        if employee != "Unassigned"
    ]
    if selected_named_employees:
        employee_filter |= assigned.isin(selected_named_employees)
    filtered = filtered[employee_filter]
if selected_priorities:
    filtered = filtered[filtered["priority"].isin(selected_priorities)]

filtered_orders = orders.copy()
if not orders.empty:
    parsed_order_dates = pd.to_datetime(
        filtered_orders["order_date"], errors="coerce"
    ).dt.date
    filtered_orders = filtered_orders.loc[
        parsed_order_dates.between(
            start_date, end_date, inclusive="both"
        )
    ]

now = datetime.now(timezone.utc)
report = build_daily_exception_report(tasks, now=now)
overdue_ids = set(report.loc[report["is_overdue"], "id"])
attention = filtered[filtered["status"] != "Resolved"]
open_tasks = filtered[filtered["status"] == "Open"]
overdue_tasks = filtered[filtered["id"].isin(overdue_ids)]
high_priority = filtered[
    (filtered["priority"] == "High")
    & (filtered["status"] != "Resolved")
]

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Orders", len(filtered_orders))
col2.metric("Orders Requiring Attention", attention["order_id"].nunique())
col3.metric("Open Tasks", len(open_tasks))
col4.metric("Overdue Tasks", len(overdue_tasks))

left, right = st.columns(2)
with left:
    st.subheader("Exceptions by Category")
    if not filtered.empty:
        st.bar_chart(filtered["exception_type"].value_counts())
    else:
        st.info("No exceptions match the selected filters.")

with right:
    st.subheader("Employee-wise Pending Tasks")
    pending = attention.copy()
    if not pending.empty:
        pending["assigned_employee"] = (
            pending["assigned_employee"].fillna("Unassigned")
        )
        pending = pending[pending["assigned_employee"].astype(str).str.strip().ne("")]
        st.bar_chart(pending["assigned_employee"].value_counts())
    else:
        st.info("No pending tasks match the selected filters.")

st.subheader("High-priority cases")
st.dataframe(high_priority, use_container_width=True)

st.subheader("Task Management")
if filtered.empty:
    st.info("No tasks match the selected filters.")
else:
    st.dataframe(
        filtered[
            [
                "id", "order_id", "customer_name", "phone_number",
                "exception_type", "reason", "priority",
                "assigned_employee", "action_required", "deadline", "status",
            ]
        ],
        use_container_width=True,
    )

    selected_task = st.selectbox("Select task ID", filtered["id"].tolist())
    selected_task_id = (
        selected_task
        if selected_task is not None
        else filtered["id"].iloc[0]
    )
    selected_row = filtered[filtered["id"] == selected_task_id].iloc[0]

    with st.form("update_task_form"):
        st.write(
            f"Order: {selected_row['order_id']} | "
            f"Customer: {selected_row['customer_name']} | "
            f"Phone: {selected_row['phone_number']}"
        )
        employee = st.text_input(
            "Assigned employee",
            value=(
                str(selected_row["assigned_employee"])
                if pd.notna(selected_row["assigned_employee"])
                else ""
            ),
        )
        status = st.selectbox(
            "Task status",
            ["Open", "In Progress", "Resolved"],
            index=["Open", "In Progress", "Resolved"].index(
                selected_row["status"]
            ),
        )
        deadline = st.text_input(
            "Deadline (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)",
            value=(
                str(selected_row["deadline"])
                if pd.notna(selected_row["deadline"])
                else ""
            ),
            help="Leave blank to remove a deadline.",
        )
        submitted = st.form_submit_button("Save Task Changes")

    if submitted:
        try:
            update_task(
                task_id=selected_task_id,
                performed_by=performed_by,
                employee=employee,
                status=status,
                deadline=deadline,
            )
            st.success("Task updated.")
            st.rerun()
        except ValueError as exc:
            st.error(f"Could not update task: {exc}")

st.subheader("Audit Trail")
with get_connection() as connection:
    audit = pd.read_sql_query("""
        SELECT order_id, task_id, action,
               old_value, new_value, performed_by, timestamp
        FROM audit_logs
        ORDER BY id DESC
        LIMIT 200
    """, connection)
st.dataframe(audit, use_container_width=True)

st.subheader("Daily Exception Report")
st.download_button(
    "Download Daily Exception Report CSV",
    data=report.to_csv(index=False).encode("utf-8"),
    file_name="daily_exception_report.csv",
    mime="text/csv",
    disabled=report.empty,
)
