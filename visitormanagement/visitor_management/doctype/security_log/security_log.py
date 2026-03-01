# Copyright (c) 2026, Harthesh and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class SecurityLog(Document):
	pass
import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class SecurityLog(Document):

    def before_save(self):

        # Fetch Visitor Pass once
        vp = None
        if self.visitor_pass:
            vp = frappe.get_doc('Visitor Pass', self.visitor_pass)

        # 1. Auto-fetch visitor info
        if vp and not self.visitor_name:
            self.badge_number = vp.badge_number
            self.visitor_name = vp.visitor_name

        # 2. Auto-assign gate
        if vp and not self.gate_name:
            gate_rules = {
                'VIP': 'VIP Entrance',
                'Supplier': 'Loading Dock',
                'Contractor': 'Back Gate',
                'Candidate': 'Main Gate',
                'Customer': 'Main Gate',
            }
            self.gate_name = gate_rules.get(vp.visitor_type, 'Main Gate')
            self.gate_auto_assigned = 1

        # 3. Auto-stamp datetime
        now = now_datetime()
        if self.event_type == 'Check-In' and not self.checkin_datetime:
            self.checkin_datetime = now
        elif self.event_type == 'Check-Out' and not self.checkout_datetime:
            self.checkout_datetime = now

        # 4. Auto-set security officer
        if not self.security_officer:
            emp = frappe.db.get_value(
                'Employee',
                {'user_id': frappe.session.user},
                'name'
            )
            if emp:
                self.security_officer = emp

        # 5. Populate item table ONLY on new Check-In
        if (
            self.is_new()
            and self.event_type == 'Check-In'
            and vp
            and not self.security_item_verify
        ):
            for vi in (vp.visitor_items or []):
                self.append('security_item_verify', {
                    'visitor_item_row': vi.name,
                    'item_name': vi.item_name,
                    'item_category': vi.item_category,
                    'qty_declared': vi.qty,
                    'uom': vi.uom,
                    'serial_number': vi.serial_number,
                    'qty_found': vi.qty,
                    'item_verified': 0,
                })

        # 6. Detect discrepancy
        for row in (self.security_item_verify or []):
            if row.qty_found is not None and row.qty_declared is not None:
                row.discrepancy = 1 if row.qty_found != row.qty_declared else 0

        # 7. Check if all items confirmed
        if self.security_item_verify:
            all_ok = all(r.item_verified for r in self.security_item_verify)
            self.all_items_confirmed = 1 if all_ok else 0
        else:
            self.all_items_confirmed = 1

    # --------------------------------------------------

    def after_insert(self):
        if not self.visitor_pass:
            return

        if self.event_type == 'Check-In':
            self._sync_item_verification()

        elif self.event_type == 'Check-Out':
            frappe.db.set_value(
                'Visitor Pass',
                self.visitor_pass,
                'status',
                'Checked-Out'
            )

    # --------------------------------------------------

    def on_update(self):
        if self.event_type == 'Check-In' and self.visitor_pass:
            self._sync_item_verification()

    # --------------------------------------------------

    def _sync_item_verification(self):

        vp = frappe.get_doc('Visitor Pass', self.visitor_pass)

        total_items = len(self.security_item_verify or [])
        verified_count = sum(
            1 for r in (self.security_item_verify or [])
            if r.item_verified
        )

        if total_items == 0 or verified_count == total_items:
            new_status = 'All Verified'
            items_verified_flag = 1
        elif verified_count > 0:
            new_status = 'Partial'
            items_verified_flag = 0
        else:
            new_status = 'Pending'
            items_verified_flag = 0

        # Update Visitor Item rows
        for row in (self.security_item_verify or []):
            if row.visitor_item_row:
                frappe.db.set_value(
                    'Visitor Item',
                    row.visitor_item_row,
                    {
                        'is_verified': row.item_verified,
                        'verification_remarks': row.security_remarks,
                    }
                )

        # Update Visitor Pass
        frappe.db.set_value(
            'Visitor Pass',
            self.visitor_pass,
            {
                'item_verification_status': new_status,
                'items_verified': items_verified_flag,
            }
        )

        # Generate badge only if fully verified
        if items_verified_flag and not vp.badge_number:
            vp.reload()
            vp.generate_badge_number()
            frappe.msgprint(
                f'All items verified! Badge issued: {vp.badge_number}',
                alert=True,
                indicator='green'
            )