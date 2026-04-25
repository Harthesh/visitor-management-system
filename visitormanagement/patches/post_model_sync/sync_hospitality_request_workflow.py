"""
sync_hospitality_request_workflow — patch to bootstrap the Hospitality Request Approval workflow.

Fixture decision (Phase 3, 2026-04-22):
  The Hospitality Request Approval workflow is ALSO shipped as a fixture in
  visitormanagement/fixtures/workflow.json.  The fixture is the canonical
  source of truth for fresh installs (bench migrate syncs it automatically).

  This patch is kept active for two reasons:
    1. It ensures the Workflow State and Workflow Action Master records that
       the workflow references are present before the workflow row is created.
       Frappe's fixture loader does not auto-create those child records.
    2. It provides a safety net on benches where the fixtures key was not
       active at the time of first install.

  Idempotency: the patch now SKIPS creating/updating the Workflow record if
  it already exists (existence check on line `if frappe.db.exists(...)`).
  This prevents the patch from overwriting any admin customisations made
  through the UI after the initial install — those customisations are preserved
  on every subsequent `bench migrate`.

  If you need to RESET the workflow to the default definition, delete the
  Workflow record via the UI ("Hospitality Request Approval") and then run
  `bench --site <site> migrate` — the fixture will recreate it cleanly.
"""
import frappe


WORKFLOW_NAME = "Hospitality Request Approval"
DOCTYPE = "Hospitality Request"

STATES = [
	{"state": "Draft", "doc_status": "0", "allow_edit": "Host Employee"},
	{"state": "Pending Manager Approval", "doc_status": "0", "allow_edit": "Hospitality Manager"},
	{"state": "Approved", "doc_status": "0", "allow_edit": "Hospitality Manager"},
	{"state": "In Progress", "doc_status": "0", "allow_edit": "Hospitality Manager"},
	{"state": "Completed", "doc_status": "0", "allow_edit": "Hospitality Manager"},
	{"state": "Rejected", "doc_status": "0", "allow_edit": "Hospitality Manager"},
	{"state": "Cancelled", "doc_status": "0", "allow_edit": "Hospitality Manager"},
]

TRANSITIONS = [
	{"state": "Draft", "action": "Submit for Approval", "next_state": "Pending Manager Approval", "allowed": "Host Employee"},
	{"state": "Pending Manager Approval", "action": "Approve", "next_state": "Approved", "allowed": "Hospitality Manager"},
	{"state": "Pending Manager Approval", "action": "Reject", "next_state": "Rejected", "allowed": "Hospitality Manager"},
	{"state": "Approved", "action": "Start Work", "next_state": "In Progress", "allowed": "Hospitality Manager"},
	{"state": "In Progress", "action": "Complete", "next_state": "Completed", "allowed": "Hospitality Manager"},
	{"state": "Approved", "action": "Cancel", "next_state": "Cancelled", "allowed": "Hospitality Manager"},
	{"state": "In Progress", "action": "Cancel", "next_state": "Cancelled", "allowed": "Hospitality Manager"},
]


def _ensure_workflow_state(state_name):
	if frappe.db.exists("Workflow State", state_name):
		return
	frappe.get_doc({
		"doctype": "Workflow State",
		"workflow_state_name": state_name,
		"style": _style_for(state_name),
	}).insert(ignore_permissions=True)


def _style_for(state):
	mapping = {
		"Draft": "Primary",
		"Pending Manager Approval": "Warning",
		"Approved": "Success",
		"In Progress": "Inverse",
		"Completed": "Success",
		"Rejected": "Danger",
		"Cancelled": "Danger",
	}
	return mapping.get(state, "Primary")


def _ensure_workflow_action(action_name):
	if frappe.db.exists("Workflow Action Master", action_name):
		return
	frappe.get_doc({
		"doctype": "Workflow Action Master",
		"workflow_action_name": action_name,
	}).insert(ignore_permissions=True)


def _ensure_workflow_state_field():
	meta = frappe.get_meta(DOCTYPE)
	if meta.get_field("workflow_state"):
		return
	# Hospitality Request doesn't have workflow_state column; add custom field
	if frappe.db.exists("Custom Field", {"dt": DOCTYPE, "fieldname": "workflow_state"}):
		return
	frappe.get_doc({
		"doctype": "Custom Field",
		"dt": DOCTYPE,
		"fieldname": "workflow_state",
		"label": "Workflow State",
		"fieldtype": "Link",
		"options": "Workflow State",
		"read_only": 1,
		"insert_after": "status",
	}).insert(ignore_permissions=True)


def execute():
	# Always ensure the dependent Workflow State and Workflow Action Master
	# records exist — these are lightweight and safe to create idempotently.
	for state in STATES:
		_ensure_workflow_state(state["state"])
	for t in TRANSITIONS:
		_ensure_workflow_action(t["action"])

	_ensure_workflow_state_field()

	# Skip creating/updating the Workflow record if it already exists.
	# The fixture (workflow.json) is the canonical source for fresh installs.
	# Preserving an existing record avoids overwriting admin customisations.
	if frappe.db.exists("Workflow", WORKFLOW_NAME):
		return

	workflow = frappe.new_doc("Workflow")
	workflow.workflow_name = WORKFLOW_NAME
	workflow.document_type = DOCTYPE
	workflow.is_active = 1
	workflow.override_status = 0
	workflow.send_email_alert = 0
	workflow.workflow_state_field = "workflow_state"

	workflow.set("states", [])
	for st in STATES:
		workflow.append("states", {
			"state": st["state"],
			"doc_status": st["doc_status"],
			"allow_edit": st["allow_edit"],
			"update_field": "status" if st["state"] in ("Completed", "Cancelled") else None,
			"update_value": st["state"] if st["state"] in ("Completed", "Cancelled") else None,
		})

	workflow.set("transitions", [])
	for tr in TRANSITIONS:
		workflow.append("transitions", {
			"state": tr["state"],
			"action": tr["action"],
			"next_state": tr["next_state"],
			"allowed": tr["allowed"],
		})

	workflow.insert(ignore_permissions=True)
