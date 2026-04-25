# Copyright (c) 2026, Harthesh
# For license information, please see license.txt

import re
import frappe
import qrcode
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime, today, get_url, getdate, get_time, date_diff, cint
from io import BytesIO
from visitormanagement.visitor_management.lifecycle import (
    ensure_hospitality_request,
    normalize_visitor_pass,
)
from visitormanagement.visitor_management.doctype.hospitality_request.hospitality_request import (
    _get_hospitality_manager_emails,
)

PENDING_LANES_BY_VISITOR_TYPE = {
    "Contractor": ("Pending System Manager",),
    "Supplier": ("Pending System Manager",),
    "Customer": ("Pending Sales Manager",),
    "Candidate": ("Pending HR Manager",),
    "VIP": ("Pending HOD", "Pending CEO"),
}

ALL_PENDING_LANES = {
    "Pending System Manager",
    "Pending Visitor Manager",
    "Pending Sales Manager",
    "Pending HR Manager",
    "Pending HOD",
    "Pending CEO",
}

DEFAULT_DECLARED_ITEMS = [
    {"item_name": "Laptop",       "item_category": "Electronics", "quantity": 1},
    {"item_name": "Mobile Phone", "item_category": "Electronics", "quantity": 1},
    {"item_name": "ID Card",      "item_category": "Document / Sample / Gift / Perishable / Weapon / Other", "quantity": 1},
    {"item_name": "Bag",          "item_category": "Document / Sample / Gift / Perishable / Weapon / Other", "quantity": 1},
    {"item_name": "Water Bottle", "item_category": "Document / Sample / Gift / Perishable / Weapon / Other", "quantity": 1},
]

class VisitorPass(Document):

    # Aliases used by notification templates and external references.
    # `visitor_name` is referenced by gate_security_alert.html and vms_prr_submitted notification.
    # `company` is referenced by gate_security_alert.html as {{ doc.company }}.
    @property
    def visitor_name(self):
        return self.visitor_full_name

    @property
    def company(self):
        return self.company__organisation

    def before_insert(self):
        self._populate_default_declared_items()

    def after_insert(self):
        self._auto_advance_on_webform_submit()
        self._fire_prr_submitted_notification()
        self._notify_invitation_creator_of_submission()

    def _populate_default_declared_items(self):
        if self.amended_from or self.visitor_items:
            return
        for item in DEFAULT_DECLARED_ITEMS:
            self.append("visitor_items", item)

    def validate(self):
        normalize_visitor_pass(self)
        self._align_workflow_lane_with_visitor_type()
        self._validate_schedule()
        self._validate_formats()
        self._validate_host_active()
        self._validate_duplicate_pass()
        self._validate_visit_duration()

    # ─────────────────────────────────────────────────────────
    # BUSINESS VALIDATIONS
    # ─────────────────────────────────────────────────────────
    def _validate_schedule(self):
        """Block past dates, enforce check-in < check-out, enforce future-date ceiling."""
        if not self.visit_date:
            return

        today_date = getdate(today())
        visit_date = getdate(self.visit_date)

        # Past date blocked — allow only if the pass is already checked-in/out (historical edits OK)
        if visit_date < today_date and self.status in (None, "", "Draft", "Approved"):
            if not (self.docstatus == 1 and self.status in ("Checked-In", "Checked-Out", "Cancelled")):
                frappe.throw(
                    _("Visit date {0} is in the past. Pick today or a future date.").format(self.visit_date),
                    title=_("Invalid Visit Date"),
                )

        # Future date ceiling — 90 days ahead max
        if date_diff(visit_date, today_date) > 90:
            frappe.throw(
                _("Visit date cannot be more than 90 days in the future."),
                title=_("Invalid Visit Date"),
            )

        # Check-in before check-out
        if self.expected_checkin and self.expected_checkout:
            if get_time(self.expected_checkin) >= get_time(self.expected_checkout):
                frappe.throw(
                    _("Expected Check-In ({0}) must be before Expected Check-Out ({1}).").format(
                        self.expected_checkin, self.expected_checkout
                    ),
                    title=_("Invalid Time Range"),
                )

    def _validate_formats(self):
        """Validate email, mobile number and ID proof number format per type."""
        if self.email_id:
            if not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", self.email_id):
                frappe.throw(
                    _("Email ID '{0}' is not a valid email address.").format(self.email_id),
                    title=_("Invalid Email"),
                )

        if self.mobile_number:
            raw = str(self.mobile_number).strip()
            digits = re.sub(r"\D", "", raw)
            if raw.startswith("+91") or digits.startswith("91") and len(digits) > 10:
                national = digits[2:] if digits.startswith("91") else digits
                if len(national) != 10 or not national.isdigit():
                    frappe.throw(
                        _("Indian mobile number must be exactly 10 digits after +91. Got: {0}").format(raw),
                        title=_("Invalid Mobile Number"),
                    )
                if national[0] not in "6789":
                    frappe.throw(
                        _("Indian mobile number must start with 6, 7, 8, or 9. Got: {0}").format(raw),
                        title=_("Invalid Mobile Number"),
                    )
            else:
                if len(digits) < 8 or len(digits) > 15:
                    frappe.throw(
                        _("Mobile number must be 8-15 digits (E.164). Got: {0}").format(raw),
                        title=_("Invalid Mobile Number"),
                    )

        if self.id_proof_type and self.id_proof_number:
            raw = str(self.id_proof_number).strip()
            # Strip non-alphanumeric for length/format check
            clean = re.sub(r"[\s\-]", "", raw)

            if self.id_proof_type == "Aadhaar":
                if not re.match(r"^\d{12}$", clean):
                    frappe.throw(
                        _("Aadhaar must be exactly 12 digits. Got: {0}").format(raw),
                        title=_("Invalid Aadhaar"),
                    )
            elif self.id_proof_type == "PAN Card":
                if not re.match(r"^[A-Z]{5}[0-9]{4}[A-Z]$", clean.upper()):
                    frappe.throw(
                        _("PAN Card format is 5 letters + 4 digits + 1 letter (e.g., ABCDE1234F). Got: {0}").format(raw),
                        title=_("Invalid PAN"),
                    )
            elif self.id_proof_type == "Passport":
                if not re.match(r"^[A-Z0-9]{6,12}$", clean.upper()):
                    frappe.throw(
                        _("Passport number should be 6-12 alphanumeric characters. Got: {0}").format(raw),
                        title=_("Invalid Passport"),
                    )
            elif self.id_proof_type == "Driving License":
                if not re.match(r"^[A-Z0-9\-]{10,16}$", clean.upper()):
                    frappe.throw(
                        _("Driving License should be 10-16 characters using letters, digits, or hyphen. Got: {0}").format(raw),
                        title=_("Invalid Driving License"),
                    )

    def _validate_host_active(self):
        """Host must be an Active employee."""
        if not self.person_to_visit:
            return
        status = frappe.db.get_value("Employee", self.person_to_visit, "status")
        if status != "Active":
            frappe.throw(
                _("Host {0} is not an Active employee (status: {1}). Cannot assign pass.").format(
                    self.person_to_visit, status or "Unknown"
                ),
                title=_("Invalid Host"),
            )

    def _validate_duplicate_pass(self):
        """Same visitor (by ID proof) cannot have multiple active passes on the same date."""
        if not self.id_proof_number or not self.visit_date:
            return
        existing = frappe.db.sql(
            """
            SELECT name FROM `tabVisitor Pass`
            WHERE id_proof_number = %(id)s
              AND visit_date = %(date)s
              AND name != %(self_name)s
              AND docstatus < 2
              AND status NOT IN ('Cancelled', 'Rejected')
            LIMIT 1
            """,
            {
                "id": self.id_proof_number,
                "date": self.visit_date,
                "self_name": self.name or "NEW",
            },
        )
        if existing:
            frappe.throw(
                _("A visitor pass ({0}) already exists for this ID Proof on {1}. Duplicate passes are not allowed.").format(
                    existing[0][0], self.visit_date
                ),
                title=_("Duplicate Pass"),
            )

    def _validate_visit_duration(self):
        """Enforce max visit duration from VMS Settings."""
        if not (self.expected_checkin and self.expected_checkout):
            return

        if self._is_host_approved_invitation_schedule():
            return

        settings = frappe.get_cached_doc("VMS Settings")
        max_hours = cint(getattr(settings, "max_visit_duration_hrs", 0))
        if not max_hours:
            return

        ci = get_time(self.expected_checkin)
        co = get_time(self.expected_checkout)
        duration_hours = (co.hour * 60 + co.minute - ci.hour * 60 - ci.minute) / 60
        if duration_hours > max_hours:
            frappe.throw(
                _("Visit duration ({0:.1f} hrs) exceeds the maximum allowed ({1} hrs). "
                  "Adjust the expected check-in/out times.").format(duration_hours, max_hours),
                title=_("Visit Too Long"),
            )

    def _is_host_approved_invitation_schedule(self):
        """Allow invitation-backed passes to retain the host-approved visit window."""
        if not self.visitor_invitation or not frappe.db.exists("Visitor Invitation", self.visitor_invitation):
            return False

        invitation = frappe.get_cached_doc("Visitor Invitation", self.visitor_invitation)
        return (
            str(self.visit_date or "") == str(invitation.visit_date or "")
            and str(self.expected_checkin or "") == str(invitation.expected_checkin or "")
            and str(self.expected_checkout or "") == str(invitation.expected_checkout or "")
            and (self.person_to_visit or "") == (invitation.host_employee or "")
        )

    # ─────────────────────────────────────────────────────────
    # AFTER INSERT — web form submission hooks
    # ─────────────────────────────────────────────────────────
    def _auto_advance_on_webform_submit(self):
        """Belt-and-suspenders workflow advance from Draft → correct Pending lane.

        Primary advance is handled by portal.py (_get_portal_submission_state).
        This method acts as a fallback in case the portal db_set hasn't committed
        yet or a future code path creates passes with visitor_invitation set but
        doesn't call portal.py.

        Guards (P2-1, P2-2, P2-3, P2-4, P2-5, P2-10):
        - Skip if visitor_invitation is empty → desk-created pass (P2-1).
        - Skip if workflow_state is already not Draft/blank (P2-10, P2-5).
        - Skip if docstatus != 0 (P2-5).
        - Skip if visitor_type is missing (log warning).
        """
        try:
            # P2-1: guard — only web form paths have visitor_invitation
            if not self.visitor_invitation:
                return

            # P2-10 / P2-5: skip if already advanced beyond Draft
            current_state = (self.workflow_state or "").strip()
            if current_state and current_state != "Draft":
                return

            # P2-5: skip if submitted
            if self.docstatus != 0:
                return

            if not self.visitor_type:
                frappe.log_error(
                    f"Visitor Pass {self.name}: visitor_type is empty — cannot auto-advance workflow.",
                    "Auto-Advance Warning",
                )
                return

            _WEBFORM_ADVANCE_MAP = {
                "Contractor": "Pending System Manager",
                "Supplier":   "Pending System Manager",
                "Candidate":  "Pending HR Manager",
                "Customer":   "Pending Sales Manager",
                "VIP":        "Pending HOD",
            }

            target = _WEBFORM_ADVANCE_MAP.get(self.visitor_type)
            if not target:
                frappe.log_error(
                    f"Visitor Pass {self.name}: visitor_type '{self.visitor_type}' not in advance map — skipping.",
                    "Auto-Advance Warning",
                )
                return

            # P2-2 / P2-4: use frappe.db.set_value — bypasses permission checks and
            # workflow engine entirely; does not re-trigger after_insert.
            frappe.db.set_value(
                "Visitor Pass", self.name, "workflow_state", target, update_modified=False
            )
            frappe.db.set_value(
                "Visitor Pass", self.name, "status", "Pending Approval", update_modified=False
            )

        except Exception:
            frappe.log_error(frappe.get_traceback(), "Auto-Advance Failed")

    def _fire_prr_submitted_notification(self):
        """Explicitly invoke the VMS PRR Submitted Notification document.

        The notification is wired to "Value Change" on workflow_state — it does
        not fire on after_insert or when db_set is called directly.  We enqueue
        the send so it runs after the transaction commits (P2-8, P2-9).
        """
        try:
            # P2-1: only web form paths carry visitor_invitation
            if not self.visitor_invitation:
                return

            # P2-8: notification fixture might be missing or disabled
            if not frappe.db.exists("Notification", "VMS PRR Submitted"):
                frappe.log_error(
                    f"Visitor Pass {self.name}: Notification 'VMS PRR Submitted' not found — skipping.",
                    "PRR Notification Skipped",
                )
                return

            frappe.enqueue(
                "visitormanagement.visitor_management.doctype.visitor_pass.visitor_pass._send_prr_submitted_notification",
                visitor_pass_name=self.name,
                queue="short",
                now=frappe.flags.in_test,
            )

        except Exception:
            frappe.log_error(frappe.get_traceback(), "PRR Notification Enqueue Failed")

    def _notify_invitation_creator_of_submission(self):
        """Email the invitation creator to confirm the visitor has submitted.

        Guards (P2-6, P2-7, P2-9):
        - Skip if visitor_invitation is not set (P2-1).
        - Skip if creator is blank, Administrator, or Guest (P2-7 defensive guard).
        - Wrapped in try/except (P2-9).
        """
        try:
            if not self.visitor_invitation:
                return

            inv = frappe.get_doc("Visitor Invitation", self.visitor_invitation)
            creator = (inv.created_by_user or "").strip()

            # P2-7: skip non-real users; in web form flow session.user IS Guest
            # so the == frappe.session.user check is also safe but mainly defensive
            if not creator or creator in ("Administrator", "Guest"):
                return
            if creator == frappe.session.user:
                return

            visitor_name = (self.visitor_full_name or "unnamed")
            visitor_type = (self.visitor_type or "-")
            visit_date = str(self.visit_date) if self.visit_date else "-"
            checkin = str(self.expected_checkin) if self.expected_checkin else "-"
            checkout = str(self.expected_checkout) if self.expected_checkout else "-"

            # Map visitor_type → responsible manager role for the body line
            _ROLE_MAP = {
                "Contractor": "System Manager",
                "Supplier":   "System Manager",
                "Candidate":  "HR Manager",
                "Customer":   "Sales Manager",
                "VIP":        "HOD",
            }
            manager_role = _ROLE_MAP.get(self.visitor_type, "the relevant approver")

            pass_url = f"{get_url()}/app/visitor-pass/{self.name}"

            subject = f"Visitor has submitted pre-registration — {visitor_name}"

            message_lines = [
                f"Dear {creator},",
                "",
                f"The visitor <b>{visitor_name}</b> has completed their pre-registration via the portal.",
                "",
                f"<b>Visitor Type :</b> {visitor_type}",
                f"<b>Visit Date   :</b> {visit_date}",
                f"<b>Check-In     :</b> {checkin}",
                f"<b>Check-Out    :</b> {checkout}",
                f"<b>Pass ID      :</b> <a href=\"{pass_url}\">{self.name}</a>",
                "",
                f"The pass is now pending review by <b>{manager_role}</b>.",
                "",
                "This is an automated notification — no action is required from you.",
            ]

            frappe.sendmail(
                recipients=[creator],
                subject=subject,
                message="<br>".join(message_lines),
                now=True,
            )

        except Exception:
            frappe.log_error(
                frappe.get_traceback(),
                f"Creator-Submission Notify Failed — {self.name}",
            )

    def _align_workflow_lane_with_visitor_type(self):
        if not self.visitor_type or not self.workflow_state:
            return

        if self.workflow_state not in ALL_PENDING_LANES:
            return

        allowed_lanes = PENDING_LANES_BY_VISITOR_TYPE.get(self.visitor_type)
        if not allowed_lanes:
            return

        if self.workflow_state in allowed_lanes:
            return

        self.workflow_state = allowed_lanes[0]

    # ─────────────────────────────────────────────────────────
    # BEFORE SAVE
    # ─────────────────────────────────────────────────────────
    def before_save(self):
        # Auto-fetch host department from Employee record
        if self.person_to_visit and not self.host_department:
            self.host_department = frappe.db.get_value(
                "Employee", self.person_to_visit, "department"
            )

        # Auto-set badge colour from VMS Settings (or defaults)
        if self.visitor_type:
            settings = frappe.get_cached_doc("VMS Settings")
            colour_field = f"badge_colour_{self.visitor_type.lower()}"
            colour = getattr(settings, colour_field, None)
            if not colour:
                colour = {"Contractor": "Orange", "Candidate": "Purple", "Customer": "Green",
                           "Supplier": "Teal", "VIP": "Gold"}.get(self.visitor_type, "Orange")
            self.badge_colour = colour

        # Sync item verification status from child table
        if self.visitor_items:
            total = len(self.visitor_items)
            # Match fieldname from Visitor Item DocType
            verified = sum(1 for i in self.visitor_items if i.verified_by_security)

            if verified == 0:
                self.item_verification_status = "Pending"
            elif verified < total:
                self.item_verification_status = "Partial"
            else:
                self.item_verification_status = "All Verified"
                self.all_items_verified = 1

    def on_update(self):
        if self.docstatus == 0 and self.status == "Draft":
            return
        ensure_hospitality_request(self)

    # ─────────────────────────────────────────────────────────
    # BEFORE SUBMIT
    # ─────────────────────────────────────────────────────────
    def before_submit(self):
        # 0️⃣ REQUIRED DOCUMENTS
        if not self.visitor_photo:
            frappe.throw(
                _("Visitor Photo is required before submitting the pass."),
                title=_("Missing Visitor Photo"),
            )
        if not self.id_proof_scan:
            frappe.throw(
                _("ID Proof Scan is required before submitting the pass."),
                title=_("Missing ID Proof Scan"),
            )

        # 1️⃣ BLACKLIST CHECK
        if self.id_proof_number:
            blacklist_name = frappe.db.exists(
                "Visitor Blacklist",
                {"id_proof_number": self.id_proof_number, "is_active": 1},
            )

            if blacklist_name:
                bl = frappe.get_doc("Visitor Blacklist", blacklist_name)
                frappe.throw(
                    f"<b>ACCESS DENIED</b><br>"
                    f"Visitor: {self.visitor_full_name}<br>"
                    f"Reason: {bl.reason}",
                    title="BLACKLISTED VISITOR",
                )

        # 2️⃣ Contractor Safety Check
        if self.visitor_type == "Contractor":
            if not getattr(self, "safety_induction_done", 0):
                frappe.throw(
                    _("Safety Induction must be completed before submitting a Contractor Visitor Pass. "
                      "Please check the Safety Induction field in the Contractor Details section."),
                    title=_("Safety Induction Required"),
                )

        # 3️⃣ VIP Approval Check
        if self.visitor_type == "VIP":
            if not getattr(self, "mdceo_notified", 0):
                frappe.throw(
                    _("MD/CEO must be notified before submitting a VIP Visitor Pass. "
                      "Please check the MD/CEO Notified field in the VIP Details section."),
                    title=_("VIP Notification Required"),
                )

    # ─────────────────────────────────────────────────────────
    # ON SUBMIT
    # ─────────────────────────────────────────────────────────
    def on_submit(self):
        # Record approval details
        self.db_set("approval_date", now_datetime())
        self.db_set("approved_by", frappe.session.user)
        self.db_set("status", "Approved")

        # Generate badge number for all approved visitors (non-VIP).
        # VIPs get badge at gate check-in (handled in security_log.py).
        # Only skip if badge disabled in settings or visitor_type not in badge_required_for.
        if self.visitor_type != "VIP":
            self.generate_badge_number(update_status=False)

        # Generate QR Code for the badge
        qr_file_url, qr_content = self._generate_qr_code()

        # Notify the visitor via email
        self._send_approval_email(qr_file_url, qr_content)

        # Notify Food Dept if a meal was requested
        if getattr(self, "meal_required", 0):
            self._notify_food_dept()

        # Phase 3 — Tweak 2: heads-up to Hospitality Manager when this pass
        # needs any hospitality service.  Differentiated from the later
        # "arrangements confirmed" mail by subject prefix "NEW … needs review".
        self._notify_hospitality_manager_heads_up()

    # ─────────────────────────────────────────────────────────
    # PHASE 3 — TWEAK 2: HOSPITALITY MANAGER HEADS-UP
    # ─────────────────────────────────────────────────────────
    def _notify_hospitality_manager_heads_up(self):
        """Send a heads-up email to Hospitality Managers when a Visitor Pass that
        needs hospitality services is approved.

        Guards:
        - Pass must be in workflow_state "Approved" (set by on_submit above via db_set).
        - At least one hospitality service must be required (hospitality_request link
          OR any of the individual service flags).
        - Wrapped in try/except — never raises; logs on failure.

        Idempotency note (Phase 3 known limitation): there is no database flag
        guarding against re-fire if a pass is re-submitted.  A dedicated Check
        field will be added in a follow-up phase to make this fully idempotent.
        Re-submitting an already-approved pass will send a duplicate heads-up.

        B13 guard: subject uses "NEW … needs review" prefix — clearly distinct
        from the later Hospitality Request approval mail subject
        "Hospitality Approved (Summary): …".
        """
        try:
            # Guard 1: workflow state must be Approved (set by on_submit)
            if (self.workflow_state or "").strip() != "Approved":
                return

            # Guard 2: must need at least one hospitality service
            hospitality_flags = (
                "cab_required", "hotel_required", "factory_tour_required",
                "buggy_required", "greeting_required", "meal_required",
            )
            needs_hospitality = bool(self.hospitality_request) or any(
                cint(getattr(self, flag, 0)) for flag in hospitality_flags
            )
            if not needs_hospitality:
                return

            manager_emails = _get_hospitality_manager_emails()
            if not manager_emails:
                return

            visitor_name = self.visitor_full_name or "Unknown Visitor"
            visitor_type = self.visitor_type or "-"
            visit_date = str(self.visit_date) if self.visit_date else "Not specified"
            host = self.person_to_visit or "-"

            hosp_req = self.hospitality_request or None
            hosp_link = ""
            if hosp_req:
                hosp_link = (
                    f'<br><b>Hospitality Request:</b> '
                    f'<a href="{get_url()}/app/hospitality-request/{hosp_req}">'
                    f'{hosp_req}</a>'
                )
            else:
                hosp_link = (
                    "<br><i>The Hospitality Request record will be created automatically "
                    "once the pass is saved — please check the Hospitality Request list.</i>"
                )

            # List which services are needed
            service_labels = {
                "cab_required": "Cab / Transport",
                "hotel_required": "Hotel Booking",
                "factory_tour_required": "Factory Tour",
                "buggy_required": "Buggy Vehicle",
                "greeting_required": "Greeting Arrangement",
                "meal_required": "Meal",
            }
            services_needed = [
                label for flag, label in service_labels.items()
                if cint(getattr(self, flag, 0))
            ]
            services_str = ", ".join(services_needed) if services_needed else "See hospitality request"

            subject = f"NEW hospitality request needs review — {visitor_name} ({visitor_type})"

            message_lines = [
                f"A Visitor Pass has been approved that requires hospitality arrangements.",
                "",
                f"<b>Visitor:</b> {visitor_name}",
                f"<b>Visitor Type:</b> {visitor_type}",
                f"<b>Visit Date:</b> {visit_date}",
                f"<b>Host:</b> {host}",
                f"<b>Services Required:</b> {services_str}",
                f"<b>Pass ID:</b> "
                f'<a href="{get_url()}/app/visitor-pass/{self.name}">{self.name}</a>',
                hosp_link,
                "",
                "Please review and fill in the hospitality arrangements at your earliest convenience.",
                "",
                "<i>This is an automated heads-up — no action is required from the visitor.</i>",
            ]

            frappe.sendmail(
                recipients=manager_emails,
                subject=subject,
                message="<br>".join(message_lines),
                reference_doctype="Visitor Pass",
                reference_name=self.name,
                now=True,
            )

        except Exception:
            frappe.log_error(
                frappe.get_traceback(),
                f"Hospitality Heads-Up Failed — {self.name}",
            )

    # ─────────────────────────────────────────────────────────
    # GENERATE BADGE NUMBER (Called by Security Log)
    # ─────────────────────────────────────────────────────────
    def generate_badge_number(self, update_status=True):
        """Generate a badge number if enabled in VMS Settings.

        `update_status=True` means this was called from the items-verification flow
        (Security Log) — move the pass to "Items Verified".
        `update_status=False` means called from on_submit — keep status as "Approved".
        """
        if self.badge_number:
            return

        # Check VMS Settings — is badge enabled for this visitor type?
        settings = frappe.get_cached_doc("VMS Settings")
        if not getattr(settings, "enable_badge", 1):
            return

        badge_types = (getattr(settings, "badge_required_for", "") or "").strip()
        if badge_types and self.visitor_type not in badge_types:
            return

        # Get prefix from settings or use defaults
        prefix_field = f"badge_prefix_{self.visitor_type.lower()}"
        p = getattr(settings, prefix_field, None) or {
            "Contractor": "CON",
            "Candidate": "CAN",
            "Customer": "CUS",
            "Supplier": "SUP",
            "VIP": "VIP",
        }.get(self.visitor_type, "VIS")

        count = frappe.db.count(
            "Visitor Pass",
            {"visitor_type": self.visitor_type, "visit_date": today()},
        )

        date_str = today().replace("-", "")
        badge_no = f"{p}-{date_str}-{str(count + 1).zfill(4)}"

        self.db_set("badge_number", badge_no)
        if update_status:
            self.db_set("status", "Items Verified")

        frappe.msgprint(
            _("Badge Number Generated: {0}").format(badge_no),
            alert=True,
            indicator="green",
        )

    # ─────────────────────────────────────────────────────────
    # PRIVATE: GENERATE QR CODE
    # ─────────────────────────────────────────────────────────
    def _generate_qr_code(self):
        # Match keys used in visitor_gate.py (scan_qr_checkin)
        qr_data = (
            f"PASS:{self.name}"
            f"|VISITOR:{self.visitor_full_name}"
            f"|VISIT_DATE:{self.visit_date}"
            f"|ID_NO:{self.id_proof_number}"
            f"|HOST:{self.person_to_visit}"
        )

        qr_img = qrcode.make(qr_data)
        buffer = BytesIO()
        qr_img.save(buffer, format="PNG")
        qr_content = buffer.getvalue()

        # Cleanup existing QR files for this record
        frappe.db.delete("File", {
            "attached_to_doctype": "Visitor Pass",
            "attached_to_name": self.name,
            "attached_to_field": "qr_code_image"
        })

        file_doc = frappe.get_doc({
            "doctype": "File",
            "file_name": f"QR_{self.name}.png",
            "attached_to_doctype": "Visitor Pass",
            "attached_to_name": self.name,
            "attached_to_field": "qr_code_image",
            "content": qr_content,
            "is_private": 0,
        })

        file_doc.insert(ignore_permissions=True)
        self.db_set("qr_code_image", file_doc.file_url)
        return file_doc.file_url, qr_content

    # ─────────────────────────────────────────────────────────
    # PRIVATE: SEND EMAIL
    # ─────────────────────────────────────────────────────────
    def _send_approval_email(self, qr_file_url, qr_content=None):
        if not self.email_id:
            return

        items_text = ""
        if self.visitor_items:
            items_text = "<br><b>Items Declared:</b><ul>"
            for item in self.visitor_items:
                qty = getattr(item, 'quantity', 1)
                items_text += f"<li>{item.item_name} (Qty: {qty})</li>"
            items_text += "</ul>"

        attachments = []
        inline_images = []
        
        # Use a constant CID for the QR code
        qr_cid = "qr_pass_code"

        if qr_content:
            # Add as attachment fallback
            attachments.append({
                "fname": f"QR_{self.name}.png",
                "fcontent": qr_content
            })
            # Add as inline image for email clients supporting CID
            inline_images.append({
                "fname": f"QR_{self.name}.png",
                "fcontent": qr_content,
                "cid": qr_cid
            })

        frappe.sendmail(
            recipients=[self.email_id],
            subject=f"Visit APPROVED — {self.name}",
            message=(
                f"Dear {self.visitor_full_name},<br><br>"
                f"Your visit request has been approved.<br>"
                f"Please present the QR code below at the security gate:<br><br>"
                f"<img src='cid:{qr_cid}' width='200' style='border: 1px solid #ddd; padding: 10px;' alt='QR Code'><br><br>"
                f"<i>(If the image above is not visible, please use the attached QR code)</i><br><br>"
                f"<b>Visit Details:</b><br>"
                f"Pass ID: {self.name}<br>"
                f"Host: {self.person_to_visit}<br>"
                f"Date: {self.visit_date}<br>"
                f"{items_text}"
            ),
            attachments=attachments,
            inline_images=inline_images
        )

    # ─────────────────────────────────────────────────────────
    # PRIVATE: NOTIFY FOOD DEPT
    # ─────────────────────────────────────────────────────────
    def _notify_food_dept(self):
        food_email = frappe.db.get_single_value("VMS Settings", "food_dept_email")
        if food_email:
            frappe.sendmail(
                recipients=[food_email],
                subject=f"Meal Required: {self.visitor_full_name}",
                message=f"Meal Type: {self.meal_type}<br>Visitor Pass: {self.name}",
            )

def _send_prr_submitted_notification(visitor_pass_name):
    """Background worker: load the fresh Visitor Pass and send the VMS PRR Submitted notification.

    Called via frappe.enqueue from _fire_prr_submitted_notification so the
    transaction has committed before we read the workflow_state.
    """
    try:
        if not frappe.db.exists("Notification", "VMS PRR Submitted"):
            return
        notif = frappe.get_doc("Notification", "VMS PRR Submitted")
        if not notif.enabled:
            return
        doc = frappe.get_doc("Visitor Pass", visitor_pass_name)
        notif.send(doc)
    except Exception:
        frappe.log_error(frappe.get_traceback(), f"PRR Notification Send Failed — {visitor_pass_name}")


@frappe.whitelist()
def search_existing_by_phone(phone):
    if not phone:
        return []
    visitors = frappe.db.sql("""
        SELECT name, visitor_full_name, visitor_type
        FROM `tabVisitor Pass`
        WHERE mobile_number = %s
        ORDER BY creation DESC
        LIMIT 10
    """, (phone,), as_dict=True)
    return visitors

@frappe.whitelist()
def search_existing_by_id(id_number):
    if not id_number:
        return []
    visitors = frappe.db.sql("""
        SELECT name, visitor_full_name, visitor_type
        FROM `tabVisitor Pass`
        WHERE id_proof_number = %s
        ORDER BY creation DESC
        LIMIT 10
    """, (id_number,), as_dict=True)
    return visitors


def _normalized_digits(value):
    return "".join(ch for ch in (value or "") if ch.isdigit())


@frappe.whitelist()
def get_existing_visitor_matches(visitor_type=None, id_proof_number=None, mobile_number=None, exclude_name=None):
    id_proof_number = (id_proof_number or "").strip()
    mobile_number = (mobile_number or "").strip()
    exclude_name = (exclude_name or "").strip()
    visitor_type = (visitor_type or "").strip()

    if not id_proof_number and not mobile_number:
        return {"best_match": None, "matches": []}

    matches = []
    seen = set()

    def _push(rows):
        for row in rows:
            if row.name in seen:
                continue
            seen.add(row.name)
            matches.append(row)

    type_filter = "AND visitor_type = %(visitor_type)s" if visitor_type else ""
    exclude_filter = "AND name != %(exclude_name)s" if exclude_name else ""
    params = {
        "visitor_type": visitor_type,
        "exclude_name": exclude_name,
        "id_proof_number": id_proof_number,
    }

    if id_proof_number:
        by_id = frappe.db.sql(
            f"""
            SELECT name, visitor_full_name, visitor_type, mobile_number, id_proof_number
            FROM `tabVisitor Pass`
            WHERE id_proof_number = %(id_proof_number)s
              {type_filter}
              {exclude_filter}
            ORDER BY modified DESC
            LIMIT 10
            """,
            params,
            as_dict=True,
        )
        _push(by_id)

    if mobile_number and len(matches) < 10:
        phone_digits = _normalized_digits(mobile_number)
        by_phone = frappe.db.sql(
            f"""
            SELECT name, visitor_full_name, visitor_type, mobile_number, id_proof_number
            FROM `tabVisitor Pass`
            WHERE ifnull(mobile_number, '') != ''
              {type_filter}
              {exclude_filter}
            ORDER BY modified DESC
            LIMIT 100
            """,
            {
                "visitor_type": visitor_type,
                "exclude_name": exclude_name,
            },
            as_dict=True,
        )

        for row in by_phone:
            if row.name in seen:
                continue
            if not phone_digits:
                continue
            if _normalized_digits(row.mobile_number) == phone_digits:
                _push([row])
            if len(matches) >= 10:
                break

    return {"best_match": matches[0] if matches else None, "matches": matches}


@frappe.whitelist()
def get_existing_visitor_pass_details(visitor_pass, visitor_type=None):
    if not visitor_pass:
        frappe.throw("Visitor Pass is required.")

    doc = frappe.get_doc("Visitor Pass", visitor_pass)
    if visitor_type and doc.visitor_type != visitor_type:
        frappe.throw("Selected record type does not match current Visitor Type.")

    common_fields = [
        "name",
        "visitor_type",
        "visitor_full_name",
        "mobile_number",
        "email_id",
        "company__organisation",
        "id_proof_type",
        "id_proof_number",
        "id_proof_scan",
        "visitor_photo",
        "purpose_of_visit",
        "person_to_visit",
        "host_department",
        "visit_date",
        "expected_checkin",
        "expected_checkout",
    ]

    type_fields = {
        "Supplier": [
            "supplier_visit_mode",
            "supplier_link",
            "purchase_order",
            "delivery_note",
            "goods_description",
            "meeting_subject",
            "nda_required",
            "documents_shared",
        ],
        "Customer": [
            "crm_reference_type",
            "crm_lead_opportunity",
            "visit_category",
            "sales_executive",
            "products_discussed",
            "meeting_outcome",
            "followup_date",
            "meeting_minutes",
        ],
        "Contractor": [
            "contractor_link",
            "work_order_ref",
            "safety_induction_done",
            "contractor_nda_signed",
            "contractor_nda_document",
            "ppe_provided",
            "ppe_provided_document",
            "tools_list",
            "multi_day_pass",
            "pass_valid_until",
        ],
        "Candidate": [
            "job_applicant_link",
            "position_applied",
            "candidate_interview_type",
            "interview_panel",
        ],
    }

    fields = common_fields + type_fields.get(doc.visitor_type, [])
    return {field: doc.get(field) for field in fields}


@frappe.whitelist()
def sync_badge_number(visitor_pass):
    """Generate badge number for a visitor pass if not already set."""
    vp = frappe.get_doc("Visitor Pass", visitor_pass)
    if vp.badge_number:
        return vp.badge_number

    vp.generate_badge_number()
    vp.reload()
    return vp.badge_number
