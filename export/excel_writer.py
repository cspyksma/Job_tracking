from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from export.excel_schema import APPLICATION_COLUMNS, EMAIL_LOG_COLUMNS


def _fmt_dt(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


def _existing_headers(path: Path, sheet_name: str, fallback: list[str]) -> list[str]:
    if not path.exists():
        return fallback
    wb = load_workbook(path)
    if sheet_name not in wb.sheetnames:
        return fallback
    ws = wb[sheet_name]
    headers = [c.value for c in ws[1] if c.value]
    return headers or fallback


def read_existing_application_overrides(path: str) -> dict[str, dict[str, Any]]:
    out_path = Path(path)
    if not out_path.exists():
        return {}
    wb = load_workbook(out_path)
    if "Applications" not in wb.sheetnames:
        return {}
    ws = wb["Applications"]
    header = [c.value for c in ws[1]]
    idx = {str(name): i for i, name in enumerate(header) if name}
    if "RecordID" not in idx:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        rid = row[idx["RecordID"]]
        if not rid:
            continue
        out[str(rid)] = {
            "Status": row[idx["Status"]] if "Status" in idx else "",
            "Notes": row[idx["Notes"]] if "Notes" in idx else "",
            "NextStep": row[idx["NextStep"]] if "NextStep" in idx else "",
            "UserLockStatus": int(row[idx["UserLockStatus"]] or 0) if "UserLockStatus" in idx else 0,
            "UserLockNotes": int(row[idx["UserLockNotes"]] or 0) if "UserLockNotes" in idx else 0,
            "UserLockNextStep": int(row[idx["UserLockNextStep"]] or 0) if "UserLockNextStep" in idx else 0,
        }
    return out


def _build_application_row(row: Any, headers: list[str], last_detected_type: str, tracking_category: str) -> list[Any]:
    values = {
        "RecordID": row["record_id"],
        "Company": row["company"],
        "Role": row["role"],
        "Location": row["location"],
        "ReqID / JobID": row["req_id"],
        "JobURL": row["job_url"],
        "Source": row["source"],
        "DateFirstSeen": _fmt_dt(row["date_first_seen"]),
        "DateApplied": _fmt_dt(row["date_applied"]),
        "Status": row["status"],
        "StatusDate": _fmt_dt(row["status_date"]),
        "LastEmailDate": _fmt_dt(row["last_email_date"]),
        "RecruiterName": row["recruiter_name"] if "recruiter_name" in row.keys() else "",
        "RecruiterEmail": row["recruiter_email"] if "recruiter_email" in row.keys() else "",
        "NextStep": row["next_step"],
        "FollowUpDue": _fmt_dt(row["follow_up_due"]),
        "Notes": row["notes"],
        "EmailThreadLink": row["email_thread_link"],
        "LastMessageID": row["last_message_id_header"],
        "Confidence": row["confidence"],
        "MatchedBy": row["matched_by"],
        "LastDetectedType": last_detected_type,
        "TrackingCategory": tracking_category,
        "UserLockStatus": row["user_lock_status"],
        "UserLockNotes": row["user_lock_notes"],
        "UserLockNextStep": row["user_lock_next_step"],
    }
    return [values.get(h, "") for h in headers]


def _add_status_data_validation(ws, status_col_idx: int, max_row: int) -> None:
    status_validation = DataValidation(
        type="list",
        formula1='"Opportunity,Applied,Interview,Offer,Rejected,Closed,NeedsReview"',
        allow_blank=False,
    )
    ws.add_data_validation(status_validation)
    col_letter = ws.cell(row=1, column=status_col_idx).column_letter
    status_validation.add(f"{col_letter}2:{col_letter}{max(2, max_row)}")


def _add_status_conditional_formatting(ws, status_col_idx: int, max_row: int) -> None:
    col_letter = ws.cell(row=1, column=status_col_idx).column_letter
    range_ref = f"A2:{ws.cell(1, ws.max_column).column_letter}{max(2, max_row)}"
    rules = [
        ('=$' + col_letter + '2="Interview"', PatternFill("solid", fgColor="C6EFCE")),
        ('=$' + col_letter + '2="Offer"', PatternFill("solid", fgColor="C6EFCE")),
        ('=$' + col_letter + '2="Rejected"', PatternFill("solid", fgColor="FFC7CE")),
        ('=$' + col_letter + '2="NeedsReview"', PatternFill("solid", fgColor="FFEB9C")),
    ]
    for formula, fill in rules:
        ws.conditional_formatting.add(range_ref, FormulaRule(formula=[formula], fill=fill))


def write_excel(
    path: str,
    applications: list[Any],
    email_events: list[Any],
    email_log_limit: int = 5000,
) -> None:
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    app_headers = _existing_headers(out_path, "Applications", APPLICATION_COLUMNS)
    email_headers = _existing_headers(out_path, "EmailLog", EMAIL_LOG_COLUMNS)

    wb = Workbook()
    ws = wb.active
    ws.title = "Applications"
    ws.append(app_headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)

    event_type_by_uid: dict[int, str] = {}
    event_type_by_message: dict[str, str] = {}
    for ev in email_events:
        event_type_by_uid[int(ev["uid"])] = ev["detected_type"]
        if ev["message_id_header"]:
            event_type_by_message[str(ev["message_id_header"])] = ev["detected_type"]

    for row in applications:
        last_type = event_type_by_uid.get(int(row["last_uid"] or 0), event_type_by_message.get(row["last_message_id_header"] or "", "Other"))
        if last_type == "Opportunity":
            tracking_category = "Opportunity Notification"
        elif last_type == "ApplicationConfirmation":
            tracking_category = "Application Confirmation"
        elif last_type in {"InterviewRequest", "Rejection", "Offer"}:
            tracking_category = "Application Update"
        else:
            tracking_category = "Needs Review"

        ws.append(_build_application_row(row, app_headers, last_type, tracking_category))
        row_idx = ws.max_row
        if "JobURL" in app_headers:
            c = app_headers.index("JobURL") + 1
            if row["job_url"]:
                ws.cell(row_idx, c).hyperlink = row["job_url"]
                ws.cell(row_idx, c).style = "Hyperlink"
        if "EmailThreadLink" in app_headers:
            c = app_headers.index("EmailThreadLink") + 1
            if row["email_thread_link"]:
                ws.cell(row_idx, c).hyperlink = row["email_thread_link"]
                ws.cell(row_idx, c).style = "Hyperlink"

    if "Status" in app_headers:
        status_col = app_headers.index("Status") + 1
        _add_status_data_validation(ws, status_col, ws.max_row)
        _add_status_conditional_formatting(ws, status_col, ws.max_row)

    for i in range(1, ws.max_column + 1):
        ws.column_dimensions[ws.cell(1, i).column_letter].width = 20

    log_ws = wb.create_sheet("EmailLog")
    log_ws.append(email_headers)
    for cell in log_ws[1]:
        cell.font = Font(bold=True)

    count = 0
    for ev in email_events:
        if count >= email_log_limit:
            break
        row = {
            "MessageID": ev["message_id_header"],
            "ThreadID": ev["thread_hint"],
            "ReceivedDate": _fmt_dt(ev["internal_date"]),
            "From": ev["from_email"],
            "Subject": ev["subject"],
            "DetectedType": ev["detected_type"],
            "LinkedRecordID": ev["linked_record_id"],
            "ExtractorNotes": ev["matched_by"],
            "RawSnippet": ev["snippet"],
        }
        log_ws.append([row.get(h, "") for h in email_headers])
        count += 1
    for i in range(1, log_ws.max_column + 1):
        log_ws.column_dimensions[log_ws.cell(1, i).column_letter].width = 26

    wb.save(path)
