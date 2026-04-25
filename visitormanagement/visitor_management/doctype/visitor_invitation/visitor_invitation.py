# Copyright (c) 2026, Harthesh and contributors
# For license information, please see license.txt

import secrets

import re
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, get_datetime, get_time, get_url, now_datetime, getdate, today, date_diff

from visitormanagement.visitor_management.lifecycle import derive_hospitality_meal_plan


INVITATION_EXPIRY_DAYS = 7


def _coerce_datetime(value):
	if not value:
		return None

	return get_datetime(value)


def build_invitation_link(token):
	return get_url(f"/visitor-pre-registration-form/new?token={token}")


def get_valid_invitation_by_token(token):
	token = (token or "").strip()
	if not token:
		return None

	name = frappe.db.get_value("Visitor Invitation", {"invitation_token": token}, "name")
	if not name:
		return None

	doc = frappe.get_doc("Visitor Invitation", name)
	if doc.invitation_status in {"Submitted", "Expired"}:
		return None

	expires_on = _coerce_datetime(doc.invitation_expires_on)
	if expires_on and expires_on < now_datetime():
		doc.db_set("invitation_status", "Expired", update_modified=False)
		return None

	return doc


def _format_time_for_web_form(value):
	if not value:
		return ""

	return get_time(value).strftime("%H:%M:%S")


def _format_datetime_for_web_form(value):
	if not value:
		return ""

	return get_datetime(value).strftime("%Y-%m-%d %H:%M:%S")


@frappe.whitelist(allow_guest=True)
def get_web_form_context(token):
	invitation = get_valid_invitation_by_token(token)
	if not invitation:
		return {
			"valid": False,
			"message": "This invitation link is invalid, expired, or already used.",
		}

	if invitation.invitation_status == "Sent":
		invitation.db_set(
			{
				"invitation_status": "Opened",
				"link_opened_on": now_datetime(),
			},
			update_modified=False,
		)

	meal_plan = derive_hospitality_meal_plan(invitation)
	existing_pass = None
	if invitation.visitor_pass and frappe.db.exists("Visitor Pass", invitation.visitor_pass):
		existing_pass = frappe.get_doc("Visitor Pass", invitation.visitor_pass)

	values = {
		"entry_type": "New",
		"visitor_invitation": invitation.name,
		"visitor_type": invitation.visitor_type,
		"email_id": invitation.visitor_email,
		"mobile_number": invitation.get("visitor_mobile") or "",
		"visitor_full_name": invitation.get("visitor_full_name") or "",
		"visit_date": str(invitation.visit_date) if invitation.visit_date else "",
		"expected_checkin": _format_time_for_web_form(invitation.expected_checkin),
		"expected_checkout": _format_time_for_web_form(invitation.expected_checkout),
		"person_to_visit": invitation.host_employee,
		"purpose_of_visit": invitation.purpose_of_visit,
		"meal_required": invitation.meal_required,
		"meal_type": meal_plan["meal_type"] if invitation.meal_required else "",
		"assigned_meal_slots": meal_plan["assigned_meal_slots"] if invitation.meal_required else "",
		"hospitality_type": meal_plan["hospitality_type"] if invitation.meal_required else "",
		"service_time": _format_datetime_for_web_form(meal_plan["service_time"]) if invitation.meal_required else "",
		"refreshments_required": invitation.refreshments_required,
		"position_applied": invitation.get("position_applied") or "",
		"candidate_interview_type": invitation.get("candidate_interview_type") or "",
	}

	if existing_pass:
		values.update(
			{
				"visitor_full_name": existing_pass.visitor_full_name,
				"mobile_number": existing_pass.mobile_number,
				"company__organisation": existing_pass.company__organisation,
				"supplier_link": existing_pass.supplier_link,
				"supplier_visit_mode": existing_pass.supplier_visit_mode,
				"purchase_order": existing_pass.purchase_order,
				"delivery_note": existing_pass.delivery_note,
				"goods_description": existing_pass.goods_description,
				"visit_category": existing_pass.visit_category,
				"products_discussed": existing_pass.products_discussed,
				"meeting_outcome": existing_pass.meeting_outcome,
				"followup_date": str(existing_pass.followup_date) if existing_pass.followup_date else "",
				"contractor_link": existing_pass.contractor_link,
				"work_order_ref": existing_pass.work_order_ref,
				"safety_induction_done": existing_pass.safety_induction_done,
				"contractor_nda_signed": existing_pass.contractor_nda_signed,
				"ppe_provided": existing_pass.ppe_provided,
				"tools_list": existing_pass.tools_list,
				"multi_day_pass": existing_pass.multi_day_pass,
				"pass_valid_until": str(existing_pass.pass_valid_until) if existing_pass.pass_valid_until else "",
				"job_applicant_link": existing_pass.job_applicant_link,
				"position_applied": existing_pass.position_applied,
				"candidate_interview_type": existing_pass.candidate_interview_type,
				"interview_panel": existing_pass.interview_panel,
				"vip_category": existing_pass.vip_category,
				"priority_lane": existing_pass.priority_lane,
				"mdceo_notified": existing_pass.mdceo_notified,
				"interpreter_required": existing_pass.interpreter_required,
				"interpreter_language": existing_pass.interpreter_language,
				"protocol_notes": existing_pass.protocol_notes,
				"meal_required": existing_pass.meal_required,
				"meal_type": existing_pass.meal_type or values.get("meal_type"),
				"assigned_meal_slots": existing_pass.assigned_meal_slots or values.get("assigned_meal_slots"),
				"hospitality_type": existing_pass.hospitality_type or values.get("hospitality_type"),
				"special_diet": existing_pass.special_diet,
				"service_time": _format_datetime_for_web_form(existing_pass.service_time)
				if existing_pass.service_time
				else values.get("service_time"),
				"refreshments_required": existing_pass.refreshments_required,
				"items_carried": existing_pass.items_carried,
				"visitor_items": [
					{
						"item_code": row.item_code,
						"item_name": row.item_name,
						"item_category": row.item_category,
						"quantity": row.quantity,
						"unit_of_measure": row.unit_of_measure,
						"description": row.description,
						"is_new_item": row.is_new_item,
						"serial_number": row.serial_number,
						"estimated_value": row.estimated_value,
					}
					for row in (existing_pass.get("visitor_items") or [])
				],
			}
		)

	return {
		"valid": True,
		"invitation": invitation.name,
		"values": values,
	}


class VisitorInvitation(Document):
	def validate(self):
		if not self.created_by_user:
			self.created_by_user = frappe.session.user

		if not self.invitation_status:
			self.invitation_status = "Draft"

		self._validate_visit_date()
		self._validate_email()
		self._validate_time_range()
		self._validate_host_active()

		if not self.invitation_expires_on and self.visit_date:
			self.invitation_expires_on = get_datetime(f"{self.visit_date} 23:59:59")

		self.invitation_expires_on = _coerce_datetime(self.invitation_expires_on)

		if self.invitation_expires_on and self.invitation_expires_on < now_datetime():
			frappe.throw(_("Invitation Expiry must be a future date and time."))

		self._apply_hospitality_defaults()

		# Generate token and portal URL eagerly so they are available in after_insert
		# and in any downstream code that reads these fields before send_invitation() runs.
		self._ensure_token()

	def _ensure_token(self):
		"""Generate invitation_token and portal_submission_url if they are not yet set.

		Called from validate() so the values are persisted on first save.
		send_invitation() will reuse an existing token (idempotent resend creates a new token
		intentionally, as a fresh link).
		"""
		if not self.invitation_token:
			self.invitation_token = secrets.token_urlsafe(24)
		if not self.portal_submission_url:
			self.portal_submission_url = build_invitation_link(self.invitation_token)

	def after_insert(self):
		self._auto_send_on_create()
		self._notify_creator_of_invitation()

	def _auto_send_on_create(self):
		"""Send the visitor invitation email automatically when a new record is created.

		Guards (all wrapped in try/except so a mail failure never aborts the save):
		- Skip if already Sent (idempotency — B1).
		- Skip if visitor_email is blank (B2).
		- Skip if no outgoing email account is configured (B4).
		"""
		try:
			if self.invitation_status == "Sent":
				return

			if not self.visitor_email:
				frappe.log_error(
					f"Visitor Invitation {self.name}: visitor_email is blank — skipping auto-send.",
					"Auto-Send Skipped",
				)
				return

			if not frappe.db.exists(
				"Email Account", {"default_outgoing": 1, "enable_outgoing": 1}
			):
				frappe.log_error(
					f"Visitor Invitation {self.name}: no default outgoing email account configured — skipping auto-send.",
					"Auto-Send Skipped",
				)
				return

			self.send_invitation()

		except Exception:
			frappe.log_error(frappe.get_traceback(), f"Visitor Invitation {self.name}: auto-send failed")

	def _notify_creator_of_invitation(self):
		"""Send a confirmation email to the person who created the invitation (created_by_user).

		Guards:
		- Skip if created_by_user is blank, Administrator, or Guest (B3).
		- Wrapped in try/except so failure never aborts the save (B6).
		"""
		try:
			creator = (self.created_by_user or "").strip()
			if not creator or creator in ("Administrator", "Guest"):
				return

			visitor_name = (
				self.get("visitor_full_name") or self.visitor_email or "-"
			)
			visit_date = str(self.visit_date) if self.visit_date else "-"
			checkin = str(self.expected_checkin) if self.expected_checkin else "-"
			checkout = str(self.expected_checkout) if self.expected_checkout else "-"
			visitor_type = self.visitor_type or "-"
			host = self.host_employee or "-"
			purpose = self.purpose_of_visit or "-"
			portal_url = self.portal_submission_url or build_invitation_link(self.invitation_token) if self.invitation_token else "-"

			subject = f"Visitor invitation sent to {visitor_name}"

			message_lines = [
				f"Dear {creator},",
				"",
				"A visitor pre-registration invitation has been sent automatically.",
				"",
				f"Visitor Name/Email : {visitor_name}",
				f"Visitor Type       : {visitor_type}",
				f"Visit Date         : {visit_date}",
				f"Expected Check-In  : {checkin}",
				f"Expected Check-Out : {checkout}",
				f"Host               : {host}",
				f"Purpose            : {purpose}",
				"",
				"Portal Link (share manually if needed):",
				f'<a href="{portal_url}">{portal_url}</a>',
				"",
				"This is an automated confirmation — no action is required from you.",
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
				f"Visitor Invitation {self.name}: creator notification failed",
			)

	def _validate_visit_date(self):
		if not self.visit_date:
			return
		today_date = getdate(today())
		visit_date = getdate(self.visit_date)
		if visit_date < today_date:
			frappe.throw(
				_("Visit date {0} is in the past. Cannot send an invitation for a past date.").format(self.visit_date),
				title=_("Invalid Visit Date"),
			)
		if date_diff(visit_date, today_date) > 90:
			frappe.throw(
				_("Visit date cannot be more than 90 days in the future."),
				title=_("Invalid Visit Date"),
			)

	def _validate_email(self):
		if self.visitor_email and not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", self.visitor_email):
			frappe.throw(
				_("Visitor Email '{0}' is not a valid email address.").format(self.visitor_email),
				title=_("Invalid Email"),
			)

	def _validate_time_range(self):
		if self.expected_checkin and self.expected_checkout:
			if get_time(self.expected_checkin) >= get_time(self.expected_checkout):
				frappe.throw(
					_("Expected Check-In must be before Expected Check-Out."),
					title=_("Invalid Time Range"),
				)

	def _validate_host_active(self):
		if not self.host_employee:
			return
		status = frappe.db.get_value("Employee", self.host_employee, "status")
		if status != "Active":
			frappe.throw(
				_("Host employee {0} is not Active (status: {1}).").format(self.host_employee, status or "Unknown"),
				title=_("Invalid Host"),
			)

	def _apply_hospitality_defaults(self):
		self.meal_required = frappe.utils.cint(self.meal_required)
		self.refreshments_required = frappe.utils.cint(self.refreshments_required)

		meal_plan = derive_hospitality_meal_plan(self)
		self.meal_type = meal_plan["meal_type"] if self.meal_required else None
		self.assigned_meal_slots = meal_plan["assigned_meal_slots"] if self.meal_required else None
		self.hospitality_type = meal_plan["hospitality_type"] if self.meal_required else None

	@frappe.whitelist()
	def send_invitation(self):
		if self.is_new():
			frappe.throw("Save the Visitor Invitation before sending the invitation mail.")

		if not self.visitor_email:
			frappe.throw("Visitor Email is required before sending invitation.")

		# Reuse the existing token if one was already generated in validate() / _ensure_token().
		# On a manual "Resend" the caller intentionally wants a fresh link — generate a new token
		# only when the status is already "Sent" or beyond (resend scenario).
		already_sent = self.invitation_status in ("Sent", "Opened", "Saved", "Submitted")
		if already_sent or not self.invitation_token:
			token = secrets.token_urlsafe(24)
		else:
			token = self.invitation_token

		sent_on = now_datetime()
		expires_on = _coerce_datetime(self.invitation_expires_on) or add_days(
			sent_on, INVITATION_EXPIRY_DAYS
		)

		if expires_on < sent_on:
			frappe.throw("Invitation Expiry must be later than the send time.")

		link = build_invitation_link(token)

		self.db_set(
			{
				"invitation_token": token,
				"invitation_sent_on": sent_on,
				"invitation_expires_on": expires_on,
				"portal_submission_url": link,
				"invitation_status": "Sent",
			}
		)

		message = [
			"Dear Visitor,",
			"",
			"You have received a visitor pre-registration invitation from our company.",
			f"Visitor Type: {self.visitor_type or '-'}",
			f"Host: {self.host_employee or '-'}",
			f"Visit Date: {self.visit_date or '-'}",
			f"Expected Check-In: {self.expected_checkin or '-'}",
			f"Expected Check-Out: {self.expected_checkout or '-'}",
			f"Purpose: {self.purpose_of_visit or '-'}",
			f"Meal Required: {'Yes' if self.meal_required else 'No'}",
			f"Meal Type: {self.meal_type or '-'}",
			f"Refreshments Required: {'Yes' if self.refreshments_required else 'No'}",
			"",
			"Please use the secure link below to fill your information before arrival:",
			f"<a href=\"{link}\">{link}</a>",
			"",
			f"This invitation expires on {expires_on}.",
		]
		frappe.sendmail(
			recipients=[self.visitor_email],
			subject="Visitor Pre-Registration Invitation",
			message="<br>".join(message),
			now=True,
		)
		return link
