# Copyright (c) 2026, Harthesh and contributors
# For license information, please see license.txt

import re

import frappe
from frappe import _
from frappe.model.document import Document

from frappe.utils import cint, date_diff, get_datetime, getdate, nowdate


from visitormanagement.visitor_management.lifecycle import (
	populate_hospitality_request_from_pass,
	sync_hospitality_to_pass,
)


def _get_assigned_staff_email(employee_name):
	if not employee_name:
		return None

	employee = frappe.db.get_value(
		"Employee",
		employee_name,
		["company_email", "personal_email", "user_id", "employee_name"],
		as_dict=True,
	)
	if not employee:
		return None

	return employee.company_email or employee.personal_email or employee.user_id


def _get_employee_name_and_email(employee_id):
	"""Return (employee_name, email) tuple for an Employee link field value."""
	if not employee_id:
		return None, None
	emp = frappe.db.get_value(
		"Employee", employee_id,
		["employee_name", "company_email", "personal_email", "user_id"],
		as_dict=True,
	)
	if not emp:
		return None, None
	email = emp.company_email or emp.personal_email or emp.user_id
	return emp.employee_name, email


def _get_visitor_info(doc):
	"""Fetch visitor details from Visitor Pass for email content."""
	if not doc.visitor_pass:
		return {}
	vp = frappe.db.get_value(
		"Visitor Pass", doc.visitor_pass,
		["visitor_full_name", "visitor_type", "mobile_number",
		 "company__organisation", "person_to_visit", "visit_date"],
		as_dict=True,
	)
	return vp or {}


TYPE_COLORS = {
	"Contractor": "#e53e3e", "VIP": "#805ad5", "Customer": "#2b6cb0",
	"Supplier": "#c05621", "Candidate": "#2f855a",
}


def _visitor_info_bar_html(vp):
	"""Build the compact visitor info bar HTML matching the screenshot style."""
	if not vp:
		return ""
	badge_color = TYPE_COLORS.get(vp.get("visitor_type"), "#4a5568")
	return (
		'<div style="background:#1a202c;color:#fff;padding:10px 16px;border-radius:6px;'
		'margin-bottom:18px;font-family:Arial,sans-serif;font-size:13px;">'
		f'<span style="font-weight:700;font-size:14px;">{vp.get("visitor_full_name") or "-"}</span>'
		f'&nbsp;&nbsp;<span style="background:{badge_color};color:#fff;padding:2px 10px;'
		f'border-radius:4px;font-size:11px;font-weight:600;">{vp.get("visitor_type") or "-"}</span>'
		f'&nbsp;&nbsp;&#128222; {vp.get("mobile_number") or "-"}'
		f'&nbsp;&nbsp;&#127970; {vp.get("company__organisation") or "-"}'
		f'&nbsp;&nbsp;&#128100; Host: {vp.get("person_to_visit") or "-"}'
		f'&nbsp;&nbsp;&#128197; {vp.get("visit_date") or "-"}'
		'</div>'
	)


def _wrap_email_body(visitor_bar, title, content_html, doc_name):
	"""Wrap service-specific content with visitor bar header and footer."""
	return (
		'<div style="font-family:Arial,sans-serif;color:#1f2933;font-size:13px;line-height:1.6;">'
		f'{visitor_bar}'
		f'<h3 style="color:#102a43;margin:0 0 12px;">{title}</h3>'
		f'{content_html}'
		f'<hr style="border:none;border-top:1px solid #d9e2ec;margin-top:20px;">'
		f'<p style="color:#829ab1;font-size:11px;">Hospitality Request: {doc_name}</p>'
		'</div>'
	)


def _kv_table(rows):
	"""Build a simple key-value HTML table from a list of (label, value) tuples."""
	trs = ""
	for label, value in rows:
		trs += (
			f'<tr><td style="padding:5px 10px;border:1px solid #d9e2ec;background:#f0f4f8;'
			f'width:35%;font-weight:600;">{label}</td>'
			f'<td style="padding:5px 10px;border:1px solid #d9e2ec;">{value or "-"}</td></tr>'
		)
	return f'<table style="width:100%;border-collapse:collapse;margin-bottom:12px;">{trs}</table>'


def _send_service_email(recipient_email, subject, visitor_bar, title, kv_rows, doc_name):
	"""Send an individual service assignment email."""
	if not recipient_email:
		return
	body = _wrap_email_body(visitor_bar, title, _kv_table(kv_rows), doc_name)
	frappe.sendmail(
		recipients=[recipient_email],
		subject=subject,
		message=body,
		reference_doctype="Hospitality Request",
		reference_name=doc_name,
		now=True,
	)


def _get_hospitality_manager_emails():
	"""Get email addresses of all users with Hospitality Manager role."""
	users = frappe.get_all(
		"Has Role",
		filters={"role": "Hospitality Manager", "parenttype": "User"},
		fields=["parent"],
	)
	emails = set()
	for u in users:
		enabled, email = frappe.db.get_value("User", u.parent, ["enabled", "email"]) or (0, None)
		if enabled and email:
			emails.add(email)
	return sorted(emails)


def _send_approval_emails(doc):
	"""On Approved: send individual emails to each service person + PDF summary to Manager."""
	vp = _get_visitor_info(doc)
	visitor_name = vp.get("visitor_full_name") or doc.visitor_pass
	visitor_bar = _visitor_info_bar_html(vp)
	sent_emails = set()

	# --- Cab / Transport ---
	if cint(doc.cab_required) and doc.cab_vendor:
		emp_name, email = _get_employee_name_and_email(doc.cab_vendor)
		if email and email not in sent_emails:
			rows = [
				("Cab Type", doc.cab_type),
				("Pickup Location", doc.pickup_location),
				("Pickup Time", doc.pickup_datetime),
				("Drop Location", doc.drop_location),
				("Drop Time", doc.drop_datetime),
				("Driver Name", doc.driver_name),
				("Driver Phone", doc.driver_phone),
				("Vehicle Number", doc.vehicle_number),
			]
			_send_service_email(
				email, f"Cab Assignment Approved: {visitor_name}",
				visitor_bar, "Cab / Transport Assignment", rows, doc.name,
			)
			sent_emails.add(email)

	# --- Hotel Booking ---
	if cint(doc.hotel_required) and doc.hotel_name:
		emp_name, email = _get_employee_name_and_email(doc.hotel_name)
		if email and email not in sent_emails:
			rows = [
				("Check-in", doc.check_in),
				("Check-out", doc.check_out),
				("Nights", doc.nights),
				("Room Type", doc.room_type),
				("No of Rooms", doc.no_of_rooms),
				("No of Guests", doc.no_of_guests),
				("Booking Reference", doc.booking_reference),
				("Hotel Cost", doc.hotel_cost),
			]
			_send_service_email(
				email, f"Hotel Booking Approved: {visitor_name}",
				visitor_bar, "Hotel Booking Assignment", rows, doc.name,
			)
			sent_emails.add(email)

	# --- Factory Tour ---
	if cint(doc.factory_tour_required) and doc.tour_guide:
		emp_name, email = _get_employee_name_and_email(doc.tour_guide)
		if email and email not in sent_emails:
			rows = [
				("Tour Date", doc.tour_date),
				("Start Time", doc.tour_start_time),
				("End Time", doc.tour_end_time),
				("Safety Briefing", "Required"),
				("PPE Issued", "Yes" if doc.ppe_issued else "No"),
				("NDA Signed", "Yes" if doc.nda_signed else "No"),
			]
			if doc.tour_areas:
				areas = ", ".join(a.area_name for a in doc.tour_areas if a.area_name)
				rows.append(("Tour Areas", areas))
			_send_service_email(
				email, f"Factory Tour Assignment Approved: {visitor_name}",
				visitor_bar, "Factory Tour Assignment", rows, doc.name,
			)
			sent_emails.add(email)

	# --- Buggy Vehicle ---
	if cint(doc.buggy_required) and doc.buggy_driver:
		emp_name, email = _get_employee_name_and_email(doc.buggy_driver)
		if email and email not in sent_emails:
			rows = [
				("Pickup Point", doc.buggy_pickup_point),
				("Drop Point", doc.buggy_drop_point),
				("Date & Time", doc.buggy_datetime),
				("Buggy Number", doc.buggy_number),
				("Passenger Count", doc.buggy_passenger_count),
			]
			_send_service_email(
				email, f"Buggy Assignment Approved: {visitor_name}",
				visitor_bar, "Buggy Vehicle Assignment", rows, doc.name,
			)
			sent_emails.add(email)

	# --- Greeting Arrangement ---
	if cint(doc.greeting_required) and doc.greeting_assigned_to:
		emp_name, email = _get_employee_name_and_email(doc.greeting_assigned_to)
		if email and email not in sent_emails:
			rows = [
				("Greeting Type", doc.greeting_type),
				("Delivery Time", doc.greeting_delivery_time),
				("Delivery Point", doc.greeting_delivery_point),
				("Greeting Cost", doc.greeting_cost),
			]
			_send_service_email(
				email, f"Greeting Assignment Approved: {visitor_name}",
				visitor_bar, "Greeting Arrangement Assignment", rows, doc.name,
			)
			sent_emails.add(email)

	# --- Meal / Conference ---
	if (cint(doc.meal_required) or doc.conference_room) and doc.assigned_staff:
		emp_name, email = _get_employee_name_and_email(doc.assigned_staff)
		if email and email not in sent_emails:
			rows = [
				("Meal Type", doc.meal_type),
				("Special Diet", doc.special_diet),
				("Meal Slots", getattr(doc, "assigned_meal_slots", None)),
				("Hospitality Type", getattr(doc, "hospitality_type", None)),
				("Conference Room", doc.conference_room),
				("Service Time", doc.service_time),
				("Snacks Required", "Yes" if doc.snacks_required else "No"),
				("Tea/Coffee Required", "Yes" if doc.tea_coffee_required else "No"),
			]
			_send_service_email(
				email, f"Meal/Conference Assignment Approved: {visitor_name}",
				visitor_bar, "Meal / Conference Assignment", rows, doc.name,
			)
			sent_emails.add(email)

	# --- Overall PDF to Hospitality Manager ---
	manager_emails = _get_hospitality_manager_emails()
	if manager_emails:
		pdf = frappe.attach_print(
			"Hospitality Request", doc.name,
			print_format="Visitor Itinerary",
			print_letterhead=True,
		)
		summary = _wrap_email_body(
			visitor_bar,
			f"Hospitality Request Approved: {doc.name}",
			"<p>All service assignments have been emailed to the respective staff. "
			"Please find the complete itinerary attached as PDF.</p>",
			doc.name,
		)
		frappe.sendmail(
			recipients=manager_emails,
			subject=f"Hospitality Approved (Summary): {visitor_name} - {doc.name}",
			message=summary,
			attachments=[pdf],
			reference_doctype="Hospitality Request",
			reference_name=doc.name,
			now=True,
		)


def _get_all_service_emails(doc):
	"""Collect emails of all assigned service persons for this request."""
	fields = []
	if cint(doc.cab_required):
		fields.append(doc.cab_vendor)
	if cint(doc.hotel_required):
		fields.append(doc.hotel_name)
	if cint(doc.factory_tour_required):
		fields.append(doc.tour_guide)
	if cint(doc.buggy_required):
		fields.append(doc.buggy_driver)
	if cint(doc.greeting_required):
		fields.append(doc.greeting_assigned_to)
	if cint(doc.meal_required) or doc.conference_room:
		fields.append(doc.assigned_staff)

	emails = set()
	for emp_id in fields:
		_, email = _get_employee_name_and_email(emp_id)
		if email:
			emails.add(email)
	return sorted(emails)


def _send_workflow_status_email(doc, new_state):
	"""Notify service persons + managers on In Progress / Completed / Rejected."""
	vp = _get_visitor_info(doc)
	visitor_name = vp.get("visitor_full_name") or doc.visitor_pass
	visitor_bar = _visitor_info_bar_html(vp)

	STATUS_CONFIG = {
		"In Progress": {
			"subject": f"Hospitality In Progress: {visitor_name} - {doc.name}",
			"title": "Hospitality Arrangements - Work Started",
			"message": "The hospitality arrangements are now <b>In Progress</b>. "
			           "Please proceed with your assigned tasks.",
			"color": "#2b6cb0",
		},
		"Completed": {
			"subject": f"Hospitality Completed: {visitor_name} - {doc.name}",
			"title": "Hospitality Arrangements - Completed",
			"message": "All hospitality arrangements have been <b>Completed</b> successfully.",
			"color": "#2f855a",
		},
		"Rejected": {
			"subject": f"Hospitality Rejected: {visitor_name} - {doc.name}",
			"title": "Hospitality Request - Rejected",
			"message": "The hospitality request has been <b>Rejected</b> by the Hospitality Manager.",
			"color": "#e53e3e",
		},
	}

	cfg = STATUS_CONFIG.get(new_state)
	if not cfg:
		return

	status_badge = (
		f'<div style="padding:10px;margin-bottom:12px;background:#f7fafc;'
		f'border-left:4px solid {cfg["color"]};font-size:14px;">'
		f'<b>Status:</b> <span style="color:{cfg["color"]};font-weight:700;">{new_state}</span>'
		f'</div>'
	)
	content = status_badge + f'<p>{cfg["message"]}</p>'

	if doc.notes:
		content += f'<p style="color:#486581;"><b>Notes:</b> {frappe.utils.strip_html(doc.notes)}</p>'

	body = _wrap_email_body(visitor_bar, cfg["title"], content, doc.name)

	# Recipients: all service persons + Hospitality Manager
	recipients = set(_get_all_service_emails(doc))
	recipients.update(_get_hospitality_manager_emails())

	# For Rejected, also notify the Host Employee (the submitter)
	if new_state == "Rejected" and doc.visitor_pass:
		host_emp = frappe.db.get_value("Visitor Pass", doc.visitor_pass, "person_to_visit")
		if host_emp:
			_, host_email = _get_employee_name_and_email(host_emp)
			if host_email:
				recipients.add(host_email)

	if not recipients:
		return

	attachments = []
	if new_state == "Completed":
		attachments.append(frappe.attach_print(
			"Hospitality Request", doc.name,
			print_format="Visitor Itinerary",
			print_letterhead=True,
		))

	frappe.sendmail(
		recipients=sorted(recipients),
		subject=cfg["subject"],
		message=body,
		attachments=attachments or None,
		reference_doctype="Hospitality Request",
		reference_name=doc.name,
		now=True,
	)


def _send_hospitality_assignment_mail(doc):
	email = _get_assigned_staff_email(doc.assigned_staff)
	if not email:
		return

	visitor_name = frappe.db.get_value("Visitor Pass", doc.visitor_pass, "visitor_full_name") or doc.visitor_pass
	subject = f"Hospitality Confirmed: {visitor_name}"
	lines = [
		f"Hospitality Request: {doc.name}",
		f"Visitor Pass: {doc.visitor_pass}",
		f"Visitor: {visitor_name}",
		f"Meal Required: {'Yes' if doc.meal_required else 'No'}",
		f"Meal Type: {doc.meal_type or '-'}",
		f"Meal Slots: {getattr(doc, 'assigned_meal_slots', None) or '-'}",
		f"Hospitality Type: {getattr(doc, 'hospitality_type', None) or '-'}",
		f"Special Diet: {getattr(doc, 'special_diet', None) or '-'}",
		f"Conference Room: {doc.conference_room or '-'}",
		f"Service Time: {doc.service_time or '-'}",
	]
	if doc.notes:
		lines.extend(["", f"Notes: {frappe.utils.strip_html(doc.notes)}"])

	frappe.sendmail(
		recipients=[email],
		subject=subject,
		message="<br>".join(lines),
		now=True,
	)


class HospitalityRequest(Document):
	def autoname(self):
		visitor_name = None
		visit_date = None
		if self.visitor_pass:
			visitor_name, visit_date = frappe.db.get_value(
				"Visitor Pass", self.visitor_pass, ["visitor_full_name", "visit_date"]
			) or (None, None)

		letters = re.sub(r"[^A-Za-z]", "", visitor_name or "").upper()[:3] or "XXX"
		letters = letters.ljust(3, "X")
		date_part = getdate(visit_date or nowdate()).strftime("%d%m%y")

		base = f"HOSP-{letters}-{date_part}"
		candidate = base
		suffix = 2
		while frappe.db.exists("Hospitality Request", candidate):
			candidate = f"{base}-{suffix}"
			suffix += 1
		self.name = candidate

	def validate(self):
		if not self.status:
			self.status = "Pending"
		if self.visitor_pass:
			populate_hospitality_request_from_pass(self)
		self._compute_hotel_nights()
		self._validate_cab_timing()
		self._validate_tour_safety()
		self._validate_buggy_conflict()
		self._validate_seating_capacity()
		self._validate_hotel_in_visit_window()

	def _validate_seating_capacity(self):
		# Only validate if seating_capacity was explicitly set to 0 or negative
		if self.conference_room and self.seating_capacity and int(self.seating_capacity) < 0:
			frappe.throw(
				_("Seating Capacity cannot be negative."),
				title=_("Invalid Seating"),
			)

	def _validate_hotel_in_visit_window(self):
		"""Hotel check-in/out should fall within (or very close to) the visit window."""
		if not (self.hotel_required and self.check_in and self.visitor_pass):
			return

		vp = frappe.db.get_value(
			"Visitor Pass", self.visitor_pass,
			["visit_date", "pass_valid_until"],
			as_dict=True,
		) or {}
		visit_date = vp.get("visit_date")
		valid_until = vp.get("pass_valid_until") or visit_date

		if visit_date and getdate(self.check_in) < getdate(visit_date):
			# Allow arriving up to 1 day earlier (for late evening/next-day meetings)
			if date_diff(visit_date, self.check_in) > 1:
				frappe.throw(
					_("Hotel check-in ({0}) is before the visit date ({1}).").format(
						self.check_in, visit_date
					),
					title=_("Invalid Hotel Dates"),
				)

		if self.check_out and valid_until:
			if getdate(self.check_out) > getdate(valid_until):
				# Allow departing up to 1 day after
				if date_diff(self.check_out, valid_until) > 1:
					frappe.throw(
						_("Hotel check-out ({0}) is after the visit ends ({1}).").format(
							self.check_out, valid_until
						),
						title=_("Invalid Hotel Dates"),
					)

	def _compute_hotel_nights(self):
		if self.hotel_required and self.check_in and self.check_out:
			nights = date_diff(self.check_out, self.check_in)
			if nights < 1:
				frappe.throw("Hotel check-out must be after check-in")
			self.nights = nights
		else:
			self.nights = 0

	def _validate_cab_timing(self):
		if not self.cab_required:
			return
		if self.cab_type in ("Pickup", "Both") and not self.pickup_datetime:
			frappe.throw("Pickup datetime required when cab type includes Pickup")
		if self.cab_type in ("Drop", "Both") and not self.drop_datetime:
			frappe.throw("Drop datetime required when cab type includes Drop")
		if self.pickup_datetime and self.drop_datetime:
			if get_datetime(self.drop_datetime) < get_datetime(self.pickup_datetime):
				frappe.throw("Drop datetime cannot be before pickup datetime")

	def _validate_tour_safety(self):
		if not self.factory_tour_required:
			return
		if self.tour_start_time and self.tour_end_time:
			if self.tour_end_time <= self.tour_start_time:
				frappe.throw("Tour end time must be after start time")

	def _validate_buggy_conflict(self):
		if not (self.buggy_required and self.buggy_number and self.buggy_datetime):
			return
		conflict = frappe.db.exists(
			"Hospitality Request",
			{
				"name": ("!=", self.name),
				"buggy_required": 1,
				"buggy_number": self.buggy_number,
				"buggy_datetime": self.buggy_datetime,
				"status": ("not in", ("Cancelled", "Completed")),
			},
		)
		if conflict:
			frappe.throw(f"Buggy {self.buggy_number} already booked at {self.buggy_datetime} ({conflict})")

	def on_update(self):
		sync_hospitality_to_pass(self)
		previous = self.get_doc_before_save()

		# --- Workflow state change emails ---
		prev_wf = getattr(previous, "workflow_state", None) if previous else None
		curr_wf = getattr(self, "workflow_state", None)
		if curr_wf and curr_wf != prev_wf:
			if curr_wf == "Approved":
				_send_approval_emails(self)
			elif curr_wf in ("In Progress", "Completed", "Rejected"):
				_send_workflow_status_email(self, curr_wf)

		# --- Legacy: Confirmed status email (non-workflow path) ---
		status_changed_to_confirmed = self.status == "Confirmed" and (
			not previous or previous.status != "Confirmed"
		)
		assigned_staff_changed = (
			self.status == "Confirmed"
			and self.assigned_staff
			and previous
			and previous.assigned_staff != self.assigned_staff
		)
		if status_changed_to_confirmed or assigned_staff_changed:
			_send_hospitality_assignment_mail(self)
