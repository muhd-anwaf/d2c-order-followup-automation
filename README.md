# D2C Order Follow-up Automation System

A local Streamlit application for d2c order follow up automation. It
imports order files, validates their contents, detects orders needing
attention, creates follow-up tasks, tracks ownership and status, and records
task changes in SQLite.

**Live app:** [D2C Order Follow-up Automation](https://d2c-order-followup-automation-cdfpckgnyxp6edzgnsf5a3.streamlit.app/)

## Contents

- [Features](#features)
- [Project structure](#project-structure)
- [Requirements](#requirements)
- [Clone the repository](#clone-the-repository)
- [Install and run](#install-and-run)
- [How to use the application](#how-to-use-the-application)
- [Order file format and validation](#order-file-format-and-validation)
- [Exception rules](#exception-rules)
- [Tasks, audit, dashboard, and reports](#tasks-audit-dashboard-and-reports)
- [Configuration](#configuration)
- [Sample data](#sample-data)
- [Tests](#tests)
- [Five-minute demonstration](#five-minute-demonstration)
- [Troubleshooting](#troubleshooting)
- [Limitations and future improvements](#limitations-and-future-improvements)

## Features

- Import CSV, `.xlsx`, and `.xls` order files.
- Restrict uploaded files to a maximum of 10 MB.
- Enforce a 100 MB SQLite database limit, including WAL/journal sidecars.
- Normalize common column-name variants, including `Order Value (INR)`.
- Validate required values, IDs, dates, payment types, and order amounts.
- Detect five exception types: Unconfirmed Order, Dispatch Delay, Shipment
  Delay, Failed Delivery, and Data Correction.
- Create one task per exception and use the order's assigned employee when
  creating a task.
- Reassign employees, set or clear task deadlines, and update task status.
- Show operational metrics, charts, and filters in a Streamlit dashboard.
- Export a daily CSV report with new, unresolved, overdue, high-priority, and
  employee-pending categories.
- Persist orders, exceptions, tasks, and task audit events in SQLite.

## Project structure

```text
project-root/
├── app.py
├── config.py
├── requirements.txt
├── README.md
├── .gitignore
├── data/
│   ├── generate_sample_orders.py
│   ├── sample_orders.csv
│   └── sample_orders.xlsx
├── src/
│   ├── database.py
│   ├── importer.py
│   ├── validator.py
│   ├── rule_engine.py
│   ├── task_service.py
│   ├── audit_service.py
│   └── report_service.py
└── tests/
    ├── conftest.py
    ├── test_importer.py
    ├── test_processing_orders.py
    ├── test_rules.py
    ├── test_sample_workflow.py
    ├── test_task_and_report.py
    └── test_task_deduplication.py
```

The database file, `order_followup.db`, is created in the project root when
the application starts. It is ignored by Git because it contains local
runtime data. The test suite redirects database access to temporary databases
and should not modify the application's database.

The sidebar displays total SQLite database usage against the 100 MB limit.
The size includes the database, WAL, shared-memory, and rollback-journal files
when present. A warning appears at 80 MB. Imports are estimated before writes,
constrained by SQLite's page limit, and checked again inside the import
transaction; an import that would exceed the limit is rolled back. Existing
data is never removed to make room. The 10 MB upload limit is separate and
measures the selected CSV/Excel file, not database growth.

## Requirements

- Python 3.11 or newer is recommended.
- Git.
- `pip`.
- Internet access when installing packages.
- Windows, macOS, or Linux.

The dependencies in `requirements.txt` are:

| Package | Purpose |
|---|---|
| Streamlit | Web application and dashboard |
| Pandas | CSV/Excel loading, validation, and data operations |
| OpenPyXL | `.xlsx` spreadsheet support |
| xlrd | Legacy `.xls` spreadsheet support |
| pytest | Automated tests |

## Clone the repository

Open a terminal and clone the GitHub repository:

```shell
git clone https://github.com/muhd-anwaf/d2c-order-followup-automation.git
cd d2c-order-followup-automation
```

Make sure you are in the cloned project directory containing `app.py` and
`requirements.txt` before continuing. If Git is not installed, install it
first, then reopen the terminal.

## Install and run

The following commands create an isolated Python environment, install the
project dependencies, and start the Streamlit app. Run them from the project
root after cloning (the directory containing `app.py`).

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m streamlit run app.py
```

If PowerShell blocks virtual-environment activation, either use a permitted
PowerShell execution policy or run the commands with the environment's
interpreter directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

### Windows Command Prompt

```bat
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m streamlit run app.py
```

### macOS/Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m streamlit run app.py
```

Streamlit prints a local address, usually `http://localhost:8501`. Open that
address in a browser. Keep the terminal running while using the application.
Stop the server with `Ctrl+C`.

## How to use the application

1. Start the app using the commands above.
2. In the sidebar, select a CSV or Excel file under **Upload CSV or Excel**.
   Files larger than 10 MB are rejected.
3. Click **Import Orders**. The app reports how many records it imported and
   displays row-level validation errors when present.
4. Set the **Dispatch delay threshold (hours)** if needed. It defaults to 24.
5. Enter the **Manager / audit actor** name. This value is recorded on new
   task and update audit entries; it is not an authenticated identity.
6. Click **Run Exception Detection**. The app evaluates stored orders,
   creates any new exceptions, and creates tasks for exceptions without tasks.
7. Use the dashboard filters, review high-priority cases, and assign/update
   tasks.
8. Set a deadline as `YYYY-MM-DD` or `YYYY-MM-DD HH:MM:SS`. Leave it blank to
   clear an existing deadline.
9. Review the audit trail and download the **Daily Exception Report CSV**.

Importing orders does not automatically run the rules. Run exception detection
after importing new data to create corresponding exceptions and tasks.

### Clear the database for a fresh upload

Use **Database Management** in the sidebar and click **Clear Database for
Fresh Upload**. The app displays a warning and requires **Confirm Clear
Database** before deleting imported orders, exceptions, tasks, and audit
history. Choose **Cancel** to leave all records unchanged. Clearing is
permanent, does not delete local upload files, and does not drop or recreate
database tables. After a successful clear, you can import a fresh CSV or Excel
file normally.

## Order file format and validation

The file must contain the following logical columns. Names are normalized:
for example, `Order Value (INR)` and `Order Value` both map to `order_value`.

| Logical field | Required value? | Example |
|---|---:|---|
| `order_id` | Yes | `ORD1001` |
| `order_date` | Yes, except a `processing` or `placed` row may be imported for correction | `2026-10-16 08:00:00` |
| `customer_name` | Yes | `Asha Nair` |
| `phone_number` | Yes | `9876543210` |
| `order_value` | Yes | `2499.00` |
| `payment_type` | Yes | `Prepaid` or `COD` |
| `order_status` | Yes | One of `processing`, `placed`, `cancelled`, `dispatched`, `delivered`, or `failed_delivery` |
| `dispatch_date` | No | `2026-10-16 12:00:00` |
| `expected_delivery_date` | Required for `dispatched` orders; otherwise optional | `2026-10-19` |
| `assigned_employee` | No | `Anu` |

Use an unambiguous ISO-style date or timestamp, such as `YYYY-MM-DD` or
`YYYY-MM-DD HH:MM:SS`. A timezone offset is accepted and converted to UTC
before storage. A date without a time is interpreted as midnight UTC. For
consistent elapsed-hour calculations, provide an order timestamp rather than
a date-only value.

Validation checks:

- Required columns and mandatory values.
- Duplicate order IDs within the same upload.
- IDs already present in the database.
- Invalid order, dispatch, or expected-delivery dates.
- Negative/non-finite or non-numeric order values.
- Payment values other than `prepaid` or `cod`.
- Upload files larger than 10 MB.

Duplicate IDs inside one upload are compared without regard to capitalization.
An order ID already stored in the database is rejected rather than updated;
the current import workflow is insert-only.

Statuses are trimmed and lowercased on import, so capitalization and
surrounding whitespace do not affect matching. Values outside the six statuses
listed above are rejected. For `processing` and `placed` orders, a missing or
invalid `order_date` is stored as missing and shown in the import error table
so the rule engine can create a Data Correction exception and follow-up task.
Dispatched orders must include a valid expected delivery date; otherwise the
row is rejected and reported as an import validation error. Other malformed
nonblank dates and records with other missing mandatory fields are rejected
from import. Blank optional dates are accepted; if a rule needs one of them,
the rule engine creates a Data Correction exception rather than evaluating
that business rule with incomplete data.

## Exception rules

Every created exception contains the order ID, exception type, reason,
priority, recommended action, and a stable key used to avoid duplicates.

| Exception type | Trigger | Default priority |
|---|---|---|
| **Unconfirmed Order** | Status is `processing` and elapsed time since `order_date` is strictly greater than 2 hours. | Medium |
| **Dispatch Delay** | Status is `placed`, there is no dispatch date, and elapsed time since `order_date` is strictly greater than the configured dispatch threshold (24 hours by default). | Medium |
| **Shipment Delay** | Status is `dispatched` and the expected delivery date is in the past. | Medium |
| **Failed Delivery** | Status is `failed_delivery`. | High |
| **Data Correction** | A date required to evaluate a relevant rule is missing or invalid, or an unsupported status is encountered in stored data. | Medium |

Any applicable exception for an order valued strictly above the currently
saved high-value threshold is raised to High priority. The default threshold
is ₹5,000; high value does not create a separate exception. Changing the
threshold does not change existing exceptions until **Recalculate Threshold**
is selected in the sidebar. Recalculation updates exception priority in place,
reverts priorities that no longer qualify to their configured default, and
records each change in the audit trail. It does not change task status, so
Open, In Progress, and Resolved tasks remain in their current lifecycle state.

Elapsed-time rules use a strict greater-than comparison. For `processing`,
1 hour 59 minutes and exactly 2 hours do not trigger an exception; 2 hours and
1 second does. For `placed`, exactly 24 hours does not trigger the default
dispatch exception. A dispatched order becomes overdue only after its expected
delivery timestamp; a date-only expected date is overdue starting the next
calendar day. Status comparison ignores capitalization and surrounding
whitespace. Once an order moves out of `processing`, the Unconfirmed Order
rule no longer applies.

The order schema has no separate confirmation timestamp. Consequently,
`order_date` is used as the elapsed-time reference for the `processing` and
`placed` rules; add a real confirmation timestamp before using this as a
production SLA. Cancelled and delivered orders do not trigger delay rules.

## Tasks, audit, dashboard, and reports

### Tasks

Each exception can have at most one task. New tasks start with `Open` status,
copy the recommended action, and use the employee on the order when one is
available. Tasks can be assigned or reassigned, moved among `Open`,
`In Progress`, and `Resolved`, and given a deadline. Invalid deadline strings
are rejected. A date-only deadline is considered overdue starting the next
calendar day; a timestamp deadline becomes overdue after its time has passed.
Resolving a task also sets the exception's `resolved_at` value.

### Duplicate prevention

- An order ID is unique in the `orders` table.
- An exception key (`order_id:exception_type`) is unique.
- Exception insertion uses `INSERT OR IGNORE` for repeat rule runs.
- `tasks.exception_id` is unique, and task creation selects only exceptions
  without a task.

These safeguards make repeated rule detection and task creation idempotent.
Re-uploading the same order ID is reported as an existing-order error and does
not update that order.

### Audit trail

The audit log records task creation, initial assignment when present,
assignment/reassignment, status changes, and deadline changes. Each event
includes order ID, task ID, action, old/new values where applicable, actor,
and timestamp. The actor is entered in the sidebar; the app does not provide
authentication.

### Dashboard

The dashboard includes:

- Total orders in the selected order-date range.
- Distinct orders requiring attention (orders with unresolved tasks).
- Open tasks.
- Overdue unresolved tasks.
- High-priority unresolved cases.
- Exception counts by category.
- Pending tasks grouped by employee, including unassigned work.

Filters are available for order-date range, exception type, employee, and
priority. The dashboard task table includes customer and order details,
exception reason, priority, assignee, action, deadline, and status.

### Daily CSV report

The download contains task rows tagged with one or more
`report_categories`:

- `New Exception`: exception created today (UTC).
- `Unresolved Exception`: task is not resolved.
- `Overdue Task`: unresolved task deadline has passed.
- `High Priority`: unresolved exception priority is High.
- `Employee-wise Pending Action`: unresolved task has an assigned employee.

A report row may have multiple categories. Resolved tasks are included only
when they are new exceptions for the current UTC date. The report is generated
from the stored database and is not a copy of the uploaded file.

## Configuration

Thresholds and default priorities are defined in `config.py`.

| Setting | Default | Description |
|---|---:|---|
| `UNCONFIRMED_LIMIT_HOURS` | 2 | Age after which a `processing` order is flagged. |
| `ORDER_STATUSES` | Six fixed statuses | Accepted order status values; inputs are normalized to lowercase. |
| `UNCONFIRMED_STATUSES` | `processing` | Statuses evaluated by the unconfirmed rule. |
| `DISPATCH_LIMIT_HOURS` | 24 | Default `placed`-order dispatch limit. |
| `HIGH_VALUE_THRESHOLD` | 5000 | Default order value in INR above which applicable exceptions are High priority; the saved dashboard setting overrides it. |
| `MAX_UPLOAD_SIZE_MB` | 10 | Maximum size of an individual uploaded file. |
| `MAX_DATABASE_SIZE_MB` | 100 | Maximum combined on-disk SQLite database and sidecar size. |
| `DEFAULT_PRIORITY` | Per exception type | Priority assigned to each exception type. |

The dashboard's **Dispatch delay threshold (hours)** control overrides the
configured default for the current rule-engine run. Set it to `12` to
demonstrate a 12-hour dispatch limit without editing code. The two-hour
unconfirmed limit is configured in `config.py`. The sidebar's **Business Rule
Settings** section saves the high-value threshold in the SQLite settings table.
Use **Recalculate Threshold** after saving to update priorities on existing
exceptions; normal exception detection uses the saved value for new exceptions.

## Sample data

`data/sample_orders.csv` and `data/sample_orders.xlsx` each contain 116 rows:

- 100 valid, unique orders.
- 5 duplicate-ID rows to exercise duplicate validation.
- 11 invalid rows to exercise validation errors: missing required values,
  missing/invalid expected-delivery dates for dispatched orders, an invalid
  order date, unsupported status and payment values, and a negative order
  value.
- Valid scenarios including delivered and `placed` orders, 15 `processing`
  orders, dispatch delays, overdue dispatched orders, failed delivery
  attempts, high-value orders, and missing expected-delivery dates.

Five of the `Processing` orders are generated with order timestamps about four
hours old. Five `placed` orders are generated about 18 hours old so the
dispatch threshold can be demonstrated at 12 hours versus 24 hours. These
timestamps are relative to the time the files were generated.

To regenerate both sample files from the project root:

```shell
python data/generate_sample_orders.py
```

This overwrites the two sample files. It does not change the application
database.

## Tests

Run the full test suite from the project root with the virtual environment
activated:

```shell
python -m pytest -q
```

The tests use a temporary SQLite database through `tests/conftest.py`. They
cover:

- CSV and Excel sample validation and imports.
- Required-field, duplicate-ID, invalid-date, and timezone-offset handling.
- `Processing` at 1:59, exactly 2:00, and 2:00:01, plus older orders.
- Status matching with capitalization and surrounding whitespace.
- Excluding other statuses from the unconfirmed rule.
- Data Correction behavior for missing or invalid `processing` order dates.
- Rule-engine/task idempotency and repeat-upload duplicate handling.
- Database size calculation including WAL/journal sidecars, capacity rejection,
  and transactional rollback for oversized imports.
- Task assignment, reassignment, status/deadline updates, and audit events.
- Report categories, empty report behavior, and a sample-data workflow.

## Five-minute demonstration

1. Optionally run `python data/generate_sample_orders.py` to refresh relative
   timestamps.
2. Start the app and upload `data/sample_orders.csv`. Show 100 imported rows
   and the 16 validation errors, including the dispatched order missing its
   expected delivery date.
3. Run exception detection with the default 24-hour dispatch threshold. Show
   the `Processing` exceptions and generated tasks.
4. Set the dispatch threshold to 12 hours and run detection again. Show new
   dispatch-delay exceptions and confirm repeated processing did not create
   duplicate tasks.
5. Filter to a task, set its deadline to yesterday, reassign it, and update
   its status. Review the overdue metric and audit trail.
6. Download and inspect the daily exception report. Upload the Excel sample
   in a clean database to show Excel support.

For a clean demonstration, use a separate copy of the project or back up the
database before replacing it. The database contains persistent local data;
do not remove it if its records need to be kept.

## Troubleshooting

### `streamlit` is not recognized

Run the application through the active interpreter:

```shell
python -m streamlit run app.py
```

### `ModuleNotFoundError` for a dependency

Activate the project environment and install the declared packages:

```shell
python -m pip install -r requirements.txt
```

### Excel import fails

Use `.xlsx` or `.xls` and install the packages from `requirements.txt`.
OpenPyXL reads `.xlsx`; xlrd is used for legacy `.xls` files. The uploader
shows an error if the spreadsheet cannot be read.

### An order does not create an exception

Importing only stores valid orders. Click **Run Exception Detection** after
import. Then verify the normalized status, order/dispatch/expected-delivery
dates, configured thresholds, and that the order is not delivered or in a
terminal status.

### Re-upload is rejected as a duplicate

The importer is insert-only and will not refresh an existing order. For a
demonstration, use a new order ID or a separate/clean database. Back up
important database contents before any reset.

## Limitations and future improvements

- Order date is a proxy for confirmation time; a dedicated `confirmed_at`
  field is needed for a reliable confirmation SLA.
- Existing order IDs cannot be updated on re-import. A controlled update or
  upsert workflow is needed to refresh changing order statuses.
- Commerce and courier systems may use additional status spellings; map
  incoming values to a canonical status vocabulary for production.
- Audit actor names are user-entered and are not authenticated.
- The app has no roles, scheduled rule processing, automated reminders,
  database migrations, or multi-user production hardening.
- SQLite is used for this local prototype; evaluate a managed database for
  concurrent production use.
- The time-savings figure should be measured in a pilot. For illustration
  only, if reviewing 100 orders manually takes 2 minutes per order (200
  minutes) and reviewing automated exceptions takes 20 minutes, the assumed
  net saving is 180 minutes (3 hours) per day. This is an estimate, not a
  measured result.

Courier APIs, WhatsApp integration, and automated messaging are intentionally
out of scope.
