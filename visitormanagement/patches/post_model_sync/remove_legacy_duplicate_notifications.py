"""
Remove legacy Notification records that duplicate richer code-based email paths.

- VMS Host Alert:    duplicated the host check-in email already sent by
                     _notify_checkin() in security_log.py.  The Notification
                     was already disabled by sync_notification_delivery_configuration
                     but the DB record still exists.  Delete it so it cannot be
                     re-enabled accidentally.

- VMS Approval Email: duplicated the visitor approval email (without QR code)
                      already sent by _send_approval_email() in visitor_pass.py.
                      Also disabled by the earlier patch; delete permanently.

Bug guards addressed:
  B15 — prevents duplicate host email on check-in for existing sites.
  Duplicate visitor approval email — prevents visitor double-receive.

Idempotent: frappe.db.exists check means re-running this patch is safe.
"""

import frappe


_NOTIFICATIONS_TO_DELETE = [
    "VMS Host Alert",
    "VMS Approval Email",
]


def execute():
    for name in _NOTIFICATIONS_TO_DELETE:
        try:
            if frappe.db.exists("Notification", name):
                frappe.delete_doc(
                    "Notification",
                    name,
                    ignore_permissions=True,
                    force=True,
                )
                print(f"[remove_legacy_duplicate_notifications] Deleted Notification: {name}")
            else:
                print(f"[remove_legacy_duplicate_notifications] Notification not found (already removed or never installed): {name}")
        except Exception:
            frappe.log_error(
                frappe.get_traceback(),
                f"remove_legacy_duplicate_notifications: failed to delete Notification '{name}'",
            )
            print(f"[remove_legacy_duplicate_notifications] ERROR deleting '{name}' — see error log.")
