import frappe
from frappe.utils import now_datetime, get_datetime, add_to_date


def check_overstays():
    """Every 30 min: alert if visitor is past expected_departure."""
    now = now_datetime()

    rows = frappe.db.sql("""
        SELECT name, visitor_name, host_employee, escort_employee, expected_departure
        FROM `tabVisitor Request`
        WHERE status='Checked-In'
        AND expected_departure < %(now)s
        AND actual_out_time IS NULL
    """, {'now': now}, as_dict=True)

    for v in rows:
        mins = int((now - get_datetime(v.expected_departure)).total_seconds() / 60)

        for emp in [v.host_employee, v.escort_employee]:
            if emp:
                user = frappe.db.get_value('Employee', emp, 'user_id')
                if user:
                    frappe.sendmail(
                        recipients=[user],
                        subject=f'VMS OVERSTAY: {v.visitor_name} ({mins} min overdue)',
                        message=f'{v.visitor_name} is {mins} minutes past departure.'
                    )


def expire_badges():
    """Every hour: mark badges expired."""
    now = now_datetime()

    rows = frappe.db.sql("""
        SELECT name, visitor_name
        FROM `tabVisitor Request`
        WHERE badge_status='Active'
        AND status='Checked-In'
        AND expected_departure < %(now)s
    """, {'now': now}, as_dict=True)

    for v in rows:
        frappe.db.set_value('Visitor Request', v.name, 'badge_status', 'Expired')


def escalate_pending_approvals():
    """Every 30 min: log SLA breaches."""
    now = now_datetime()

    rows = frappe.db.sql("""
        SELECT name, visitor_name, visitor_type, modified, workflow_state
        FROM `tabVisitor Request`
        WHERE docstatus=0
        AND workflow_state NOT IN ('Draft','Cancelled')
    """, as_dict=True)

    for v in rows:
        frappe.log_error(
            f'SLA Breach: {v.name} | State: {v.workflow_state}',
            'VMS SLA Breach'
        )