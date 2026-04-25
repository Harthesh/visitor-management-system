import frappe
from frappe.utils import getdate, now_datetime, nowdate


DIGEST_RECIPIENTS_BY_ROLE = [
	"Hospitality Manager",
	"Hospitality User",
	"Transport Coordinator",
	"Front Office Executive",
	"Factory Tour Coordinator",
	"Greeting Staff",
]


def _get_recipients():
	users = frappe.get_all(
		"Has Role",
		filters={
			"role": ("in", DIGEST_RECIPIENTS_BY_ROLE),
			"parenttype": "User",
		},
		fields=["parent"],
	)
	emails = set()
	for u in users:
		enabled, email = frappe.db.get_value(
			"User", u.parent, ["enabled", "email"]
		) or (0, None)
		if enabled and email:
			emails.add(email)
	return sorted(emails)


def _fetch_today_rows(today):
	return frappe.get_all(
		"Hospitality Request",
		filters={
			"status": ("not in", ("Cancelled", "Completed")),
		},
		or_filters=[
			["pickup_datetime", "between", [f"{today} 00:00:00", f"{today} 23:59:59"]],
			["drop_datetime", "between", [f"{today} 00:00:00", f"{today} 23:59:59"]],
			["check_in", "=", today],
			["tour_date", "=", today],
			["buggy_datetime", "between", [f"{today} 00:00:00", f"{today} 23:59:59"]],
			["greeting_delivery_time", "between", [f"{today} 00:00:00", f"{today} 23:59:59"]],
		],
		fields=[
			"name", "visitor_pass", "status",
			"cab_required", "cab_type", "pickup_location", "pickup_datetime",
			"drop_location", "drop_datetime", "driver_name",
			"hotel_required", "hotel_name", "check_in", "booking_reference",
			"factory_tour_required", "tour_date", "tour_start_time", "tour_guide",
			"buggy_required", "buggy_pickup_point", "buggy_datetime", "buggy_driver",
			"greeting_required", "greeting_type", "greeting_delivery_time", "greeting_assigned_to",
		],
	)


def _build_html(today, rows):
	cabs, hotels, tours, buggies, greetings = [], [], [], [], []
	for r in rows:
		if r.cab_required and (
			(r.pickup_datetime and getdate(r.pickup_datetime) == getdate(today))
			or (r.drop_datetime and getdate(r.drop_datetime) == getdate(today))
		):
			cabs.append(r)
		if r.hotel_required and r.check_in and getdate(r.check_in) == getdate(today):
			hotels.append(r)
		if r.factory_tour_required and r.tour_date and getdate(r.tour_date) == getdate(today):
			tours.append(r)
		if r.buggy_required and r.buggy_datetime and getdate(r.buggy_datetime) == getdate(today):
			buggies.append(r)
		if r.greeting_required and r.greeting_delivery_time and getdate(r.greeting_delivery_time) == getdate(today):
			greetings.append(r)

	def section(title, items, render_row):
		if not items:
			return f"<h3>{title} (0)</h3><p style='color:#829ab1'>None scheduled.</p>"
		html = [f"<h3>{title} ({len(items)})</h3><ul>"]
		for r in items:
			html.append(f"<li>{render_row(r)}</li>")
		html.append("</ul>")
		return "".join(html)

	parts = [
		f"<h2 style='color:#102a43'>Hospitality Schedule — {today}</h2>",
		section("🚗 Cabs", cabs, lambda r: (
			f"{r.pickup_datetime or r.drop_datetime} — {r.cab_type} — "
			f"{r.pickup_location or r.drop_location or '-'} "
			f"(Driver: {r.driver_name or 'Not assigned'}) "
			f"[{r.status or 'Pending'}] — {r.visitor_pass}"
		)),
		section("🏨 Hotel Check-ins", hotels, lambda r: (
			f"{r.hotel_name or '-'} — Ref: {r.booking_reference or '-'} "
			f"[{r.status or 'Pending'}] — {r.visitor_pass}"
		)),
		section("🏭 Factory Tours", tours, lambda r: (
			f"{r.tour_start_time or '-'} — Guide: {r.tour_guide or 'Not assigned'} "
			f"[{r.status or 'Pending'}] — {r.visitor_pass}"
		)),
		section("🛺 Buggy Requests", buggies, lambda r: (
			f"{r.buggy_datetime} — {r.buggy_pickup_point or '-'} — "
			f"Driver: {r.buggy_driver or 'Not assigned'} "
			f"[{r.status or 'Pending'}] — {r.visitor_pass}"
		)),
		section("🎁 Greetings", greetings, lambda r: (
			f"{r.greeting_delivery_time} — {r.greeting_type or '-'} — "
			f"Assigned: {r.greeting_assigned_to or 'Not assigned'} "
			f"[{r.status or 'Pending'}] — {r.visitor_pass}"
		)),
	]
	return "<div style='font-family:Arial,sans-serif;font-size:13px;color:#1f2933'>" + "".join(parts) + "</div>"


def send_daily_hospitality_digest():
	today = nowdate()
	rows = _fetch_today_rows(today)
	if not rows:
		return

	recipients = _get_recipients()
	if not recipients:
		return

	frappe.sendmail(
		recipients=recipients,
		subject=f"Today's Hospitality Schedule — {today}",
		message=_build_html(today, rows),
		reference_doctype="Hospitality Request",
		now=False,
	)


# ---------------------------------------------------------------------------
# Daily unchecked-out digest  (Phase 4 — Item D)
# ---------------------------------------------------------------------------

_DIGEST_ROLES = ["Security Head", "Visitor Manager"]


def _get_digest_role_recipients():
	"""Return sorted list of enabled user emails holding Security Head or Visitor Manager."""
	users = frappe.get_all(
		"Has Role",
		filters={"role": ("in", _DIGEST_ROLES), "parenttype": "User"},
		fields=["parent"],
	)
	emails = set()
	for u in users:
		result = frappe.db.get_value("User", u.parent, ["enabled", "email"], as_dict=True)
		if result and result.enabled and result.email:
			emails.add(result.email)
	return sorted(emails)


def _get_host_emails_for_passes(passes):
	"""Return a de-duped set of host employee emails for the given passes.

	Each pass dict must contain a 'person_to_visit' field (Employee name).
	"""
	emails = set()
	seen_hosts = set()
	for p in passes:
		host = p.get("person_to_visit")
		if not host or host in seen_hosts:
			continue
		seen_hosts.add(host)
		employee = frappe.db.get_value(
			"Employee",
			host,
			["company_email", "personal_email", "user_id"],
			as_dict=True,
		)
		if not employee:
			continue
		email = employee.company_email or employee.personal_email or employee.user_id
		if email:
			emails.add(email)
	return emails


def _build_digest_html(today, passes):
	"""Build the HTML email body for the unchecked-out digest."""
	base_url = frappe.utils.get_url()
	rows_html = []
	for p in passes:
		pass_url = f"{base_url}/app/visitor-pass/{p.name}"
		rows_html.append(
			f"<tr>"
			f"<td style='padding:6px 10px;border:1px solid #ddd;'>{p.visitor_full_name or '-'}</td>"
			f"<td style='padding:6px 10px;border:1px solid #ddd;'>{p.visitor_type or '-'}</td>"
			f"<td style='padding:6px 10px;border:1px solid #ddd;'>{p.person_to_visit or '-'}</td>"
			f"<td style='padding:6px 10px;border:1px solid #ddd;'>{p.expected_checkout or '-'}</td>"
			f"<td style='padding:6px 10px;border:1px solid #ddd;'>{p.actual_checkin or '-'}</td>"
			f"<td style='padding:6px 10px;border:1px solid #ddd;'><a href='{pass_url}'>{p.name}</a></td>"
			f"</tr>"
		)
	header = (
		"<tr style='background:#f4f5f7;'>"
		"<th style='padding:6px 10px;border:1px solid #ddd;text-align:left;'>Visitor</th>"
		"<th style='padding:6px 10px;border:1px solid #ddd;text-align:left;'>Type</th>"
		"<th style='padding:6px 10px;border:1px solid #ddd;text-align:left;'>Host</th>"
		"<th style='padding:6px 10px;border:1px solid #ddd;text-align:left;'>Expected Checkout</th>"
		"<th style='padding:6px 10px;border:1px solid #ddd;text-align:left;'>Actual Check-In</th>"
		"<th style='padding:6px 10px;border:1px solid #ddd;text-align:left;'>Pass</th>"
		"</tr>"
	)
	return (
		"<div style='font-family:Arial,sans-serif;font-size:13px;color:#1f2933;'>"
		f"<h2 style='color:#c0392b;'>Visitors Not Checked Out — {today}</h2>"
		f"<p>{len(passes)} visitor(s) remain on premises as of end of day.</p>"
		"<table style='border-collapse:collapse;width:100%;'>"
		f"{header}"
		f"{''.join(rows_html)}"
		"</table>"
		"<p style='margin-top:16px;color:#64748b;font-size:12px;'>"
		"This digest is sent once per day at 20:00 site time. "
		"Please follow up with the listed hosts or security personnel."
		"</p>"
		"</div>"
	)


def send_unchecked_out_digest():
	"""Send a daily digest of visitors who have not yet checked out.

	Scheduled at 20:00 site time via hooks.py cron entry.

	Recipients:
	  - All users holding 'Security Head' role.
	  - All users holding 'Visitor Manager' role.
	  - Host employee of each unchecked-out pass (de-duplicated).

	Idempotency (B16 guard):
	  Uses frappe.cache().set_value() with a 24-hour TTL as a sentinel.
	  Cache is Redis-backed in production; if Redis is unavailable the key
	  check will raise, which we catch and log.  This is preferred over a
	  new DocType (zero schema impact) and simpler than a Communication
	  sentinel (no DB write on every invocation).  The cache key is:
	    vms:unchecked_out_sent:<YYYY-MM-DD>

	Bug guards addressed:
	  B16 — digest fires at most once per calendar day.
	  B17 — now_datetime() / getdate() use site timezone, not server stdlib.
	  B18 — early return if no unchecked-out visitors found.
	  B19 — if Security Head has 0 users, those slots are simply omitted;
	         the digest still fires to Visitor Manager + hosts.
	"""
	try:
		today = getdate(now_datetime())
		today_str = str(today)

		# B16 — idempotency: skip if already sent today
		cache_key = f"vms:unchecked_out_sent:{today_str}"
		if frappe.cache().get_value(cache_key):
			frappe.logger().info(
				f"[send_unchecked_out_digest] Already sent for {today_str}; skipping."
			)
			return

		# B18 — query passes still checked-in as of today
		passes = frappe.get_all(
			"Visitor Pass",
			filters={"status": "Checked-In", "visit_date": ["<=", today_str]},
			fields=[
				"name",
				"visitor_full_name",
				"visitor_type",
				"person_to_visit",
				"expected_checkout",
				"actual_checkin",
			],
			order_by="visit_date asc, visitor_full_name asc",
		)

		if not passes:
			# B18 — do not send empty digest
			frappe.logger().info(
				f"[send_unchecked_out_digest] No unchecked-out visitors for {today_str}; not sending."
			)
			# Still mark as sent so we don't re-query unnecessarily later in the day
			frappe.cache().set_value(cache_key, 1, expires_in_sec=86400)
			return

		# Build recipient list
		role_recipients = _get_digest_role_recipients()
		host_emails = _get_host_emails_for_passes(passes)
		all_recipients = sorted(set(role_recipients) | host_emails)

		if not all_recipients:
			# No one to send to — log and return (B19: no Security Head/Visitor Manager users)
			frappe.logger().warning(
				f"[send_unchecked_out_digest] No recipients found (no Security Head / "
				f"Visitor Manager users, no host emails). Skipping for {today_str}."
			)
			return

		subject = f"[VMS] {len(passes)} visitor(s) not checked out — {today_str}"
		message = _build_digest_html(today_str, passes)

		frappe.sendmail(
			recipients=all_recipients,
			subject=subject,
			message=message,
			now=False,
		)

		# Mark sent in cache — 24 h TTL ensures idempotency for the rest of today
		frappe.cache().set_value(cache_key, 1, expires_in_sec=86400)

		frappe.logger().info(
			f"[send_unchecked_out_digest] Sent to {len(all_recipients)} recipient(s) "
			f"for {len(passes)} pass(es) on {today_str}."
		)

	except Exception:
		# Never raise from a scheduler task — log and exit silently
		frappe.log_error(
			frappe.get_traceback(),
			"send_unchecked_out_digest: unexpected error",
		)
