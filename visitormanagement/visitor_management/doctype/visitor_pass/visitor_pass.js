// Copyright (c) 2026, Harthesh and contributors
// For license information, please see license.txt

const DEFAULT_DECLARED_ITEMS = [
	{ item_name: "Laptop",       item_category: "Electronics", quantity: 1 },
	{ item_name: "Mobile Phone", item_category: "Electronics", quantity: 1 },
	{ item_name: "ID Card",      item_category: "Document / Sample / Gift / Perishable / Weapon / Other", quantity: 1 },
	{ item_name: "Bag",          item_category: "Document / Sample / Gift / Perishable / Weapon / Other", quantity: 1 },
	{ item_name: "Water Bottle", item_category: "Document / Sample / Gift / Perishable / Weapon / Other", quantity: 1 },
];

const ID_PROOF_RULES = {
	Aadhaar: {
		label: "Aadhaar",
		minLength: 12,
		maxLength: 12,
		ruleText: "Enter exactly 12 digits.",
		partialPattern: /^\d{0,12}$/,
		finalPattern: /^\d{12}$/,
		normalize(value) {
			return String(value || "").replace(/[\s-]/g, "");
		},
	},
	"PAN Card": {
		label: "PAN Card",
		minLength: 10,
		maxLength: 10,
		ruleText: "Enter 10 characters: 5 letters, 4 digits, 1 letter.",
		partialPattern: /^(?:[A-Za-z]{0,5}|[A-Za-z]{5}\d{0,4}|[A-Za-z]{5}\d{4}[A-Za-z]?)$/,
		finalPattern: /^[A-Z]{5}\d{4}[A-Z]$/,
		normalize(value) {
			return String(value || "").trim().toUpperCase();
		},
	},
	Passport: {
		label: "Passport",
		minLength: 6,
		maxLength: 12,
		ruleText: "Enter 6 to 12 alphanumeric characters.",
		partialPattern: /^[A-Za-z0-9]{0,12}$/,
		finalPattern: /^[A-Za-z0-9]{6,12}$/,
		normalize(value) {
			return String(value || "").trim().toUpperCase();
		},
	},
	"Driving License": {
		label: "Driving License",
		minLength: 10,
		maxLength: 16,
		ruleText: "Enter 10 to 16 characters using letters, digits, or hyphen.",
		partialPattern: /^[A-Za-z0-9-]{0,16}$/,
		finalPattern: /^[A-Z0-9-]{10,16}$/,
		normalize(value) {
			return String(value || "").replace(/\s/g, "").toUpperCase();
		},
	},
};

function get_id_proof_validation_state(idProofType, idProofNumber) {
	const rule = ID_PROOF_RULES[idProofType];
	if (!rule) {
		return { status: "neutral", isValid: true, isComplete: false, message: "" };
	}

	const normalized = rule.normalize(idProofNumber);
	if (!normalized) {
		return {
			status: "neutral",
			isValid: true,
			isComplete: false,
			message: `${rule.label}: ${rule.ruleText}`,
			maxLength: rule.maxLength,
		};
	}

	if (!rule.partialPattern.test(normalized)) {
		return {
			status: "invalid",
			isValid: false,
			isComplete: false,
			message: `${rule.label}: invalid character or format.`,
			maxLength: rule.maxLength,
		};
	}

	if (normalized.length > rule.maxLength) {
		return {
			status: "invalid",
			isValid: false,
			isComplete: false,
			message: `${rule.label}: maximum ${rule.maxLength} characters allowed.`,
			maxLength: rule.maxLength,
		};
	}

	if (rule.finalPattern.test(normalized)) {
		return {
			status: "valid",
			isValid: true,
			isComplete: true,
			message: `${rule.label}: format looks valid.`,
			maxLength: rule.maxLength,
		};
	}

	return {
		status: "pending",
		isValid: true,
		isComplete: false,
		message: `${rule.label}: ${rule.ruleText}`,
		maxLength: rule.maxLength,
	};
}

function get_id_proof_feedback_html(state) {
	if (!state.message) {
		return "";
	}

	const colorByStatus = {
		valid: "#15803d",
		invalid: "#b91c1c",
		pending: "#92400e",
		neutral: "#475569",
	};
	const color = colorByStatus[state.status] || colorByStatus.neutral;
	return `<span style="color: ${color};">${frappe.utils.escape_html(state.message)}</span>`;
}

function apply_id_proof_validation_to_desk_form(frm) {
	const field = frm.get_field("id_proof_number");
	if (!field) {
		return { status: "neutral", isValid: true, isComplete: false, message: "" };
	}

	const state = get_id_proof_validation_state(frm.doc.id_proof_type, frm.doc.id_proof_number);
	frm.set_df_property("id_proof_number", "description", get_id_proof_feedback_html(state));

	const maxLength = state.maxLength || "";
	if (field.$input) {
		field.$input.attr("maxlength", maxLength);
		field.$input.css("border-color", state.status === "invalid" ? "#dc2626" : "");
	}

	return state;
}

function get_mobile_validation_state(raw) {
	if (!raw) {
		return { status: "neutral", isValid: true, message: "Enter a mobile number." };
	}
	const digits = String(raw).replace(/\D/g, "");
	const isIndia = String(raw).trim().startsWith("+91") || (digits.startsWith("91") && digits.length > 10);
	if (isIndia) {
		const national = digits.startsWith("91") ? digits.slice(2) : digits;
		if (national.length !== 10) {
			return { status: "invalid", isValid: false, message: `India: need exactly 10 digits after +91. Got ${national.length}.` };
		}
		if (!"6789".includes(national[0])) {
			return { status: "invalid", isValid: false, message: "India: mobile must start with 6, 7, 8, or 9." };
		}
		return { status: "valid", isValid: true, message: "India: format looks valid." };
	}
	if (digits.length < 8) {
		return { status: "pending", isValid: true, message: `Enter 8-15 digits. Got ${digits.length}.` };
	}
	if (digits.length > 15) {
		return { status: "invalid", isValid: false, message: "Number too long (max 15 digits)." };
	}
	return { status: "valid", isValid: true, message: "Format looks valid." };
}

function apply_mobile_validation_to_desk_form(frm) {
	const field = frm.get_field("mobile_number");
	if (!field) return;
	const state = get_mobile_validation_state(frm.doc.mobile_number);
	frm.set_df_property("mobile_number", "description", get_id_proof_feedback_html(state));
	if (field.$input) {
		field.$input.css("border-color", state.status === "invalid" ? "#dc2626" : "");
	}
}

function prefill_default_declared_items(frm) {
	if (!frm.is_new() || frm.doc.amended_from) return;
	if ((frm.doc.visitor_items || []).length) return;
	DEFAULT_DECLARED_ITEMS.forEach((item) => {
		const row = frm.add_child("visitor_items");
		Object.assign(row, item);
	});
	frm.refresh_field("visitor_items");
}

frappe.ui.form.on("Visitor Pass", {
	refresh(frm) {
		frm.dashboard?.clear_headline();
		ensure_customer_crm_defaults(frm);
		setup_supplier_pass_query(frm);
		apply_visitor_pass_ui(frm);
		add_action_buttons(frm);
		add_hospitality_buttons(frm);
		prefill_default_declared_items(frm);
		apply_id_proof_validation_to_desk_form(frm);
		apply_mobile_validation_to_desk_form(frm);
	},

	visitor_type(frm) {
		apply_visitor_type_defaults(frm, true);
		ensure_customer_crm_defaults(frm);
		setup_supplier_pass_query(frm);
		apply_visitor_pass_ui(frm);
	},

	factory_tour_required(frm) {
		if (frm.doc.factory_tour_required) {
			if (!frm.doc.buggy_required) {
				frm.set_value("buggy_required", 1);
			}
		} else if (frm.doc.buggy_required) {
			frm.set_value("buggy_required", 0);
		}
	},

	crm_reference_type(frm) {
		if (frm.doc.crm_lead_opportunity) {
			frm.set_value("crm_lead_opportunity", "");
		}
	},

	crm_lead_opportunity(frm) {
		fetch_customer_crm_details(frm);
	},

	supplier_link(frm) {
		if (frm.doc.supplier_link) {
			frappe.call({
				method: 'frappe.client.get',
				args: { doctype: 'Supplier', name: frm.doc.supplier_link },
				callback: function(r) {
					if (r.message) {
						frm.set_value('visitor_full_name', r.message.supplier_name);
						frm.set_value('mobile_number', r.message.mobile_no || '');
						frm.set_value('email_id', r.message.email_id || '');
						frm.set_value('company__organisation', r.message.supplier_name);
					}
				}
			});
		}
	},

	contractor_link(frm) {
		if (frm.doc.contractor_link) {
			frappe.call({
				method: 'frappe.client.get',
				args: { doctype: 'Supplier', name: frm.doc.contractor_link },
				callback: function(r) {
					if (r.message) {
						frm.set_value('visitor_full_name', r.message.supplier_name);
						frm.set_value('mobile_number', r.message.mobile_no || '');
						frm.set_value('email_id', r.message.email_id || '');
						frm.set_value('company__organisation', r.message.supplier_name);
					}
				}
			});
		}
	},

	job_applicant_link(frm) {
		if (frm.doc.job_applicant_link) {
			frappe.call({
				method: 'frappe.client.get',
				args: { doctype: 'Job Applicant', name: frm.doc.job_applicant_link },
				callback: function(r) {
					if (r.message) {
						frm.set_value('visitor_full_name', r.message.applicant_name);
						frm.set_value('mobile_number', r.message.phone_number || '');
						frm.set_value('email_id', r.message.email_id || '');
						frm.set_value('company__organisation', r.message.company_name || '');
					}
				}
			});
		}
	},

	mobile_number(frm) {
		apply_mobile_validation_to_desk_form(frm);
		lookup_existing_visitor_match(frm, "mobile_number");
	},

	id_proof_number(frm) {
		const state = apply_id_proof_validation_to_desk_form(frm);
		if (!state.isValid || !state.isComplete) {
			return;
		}
		lookup_existing_visitor_match(frm, "id_proof_number");
	},

	id_proof_type(frm) {
		apply_id_proof_validation_to_desk_form(frm);
	},

	supplier_visit_mode(frm) {
		apply_visitor_pass_ui(frm);
	},

	entry_type(frm) {
		if (frm.doc.entry_type === "New") {
			frm.set_value("existing_visitor_pass", "");
			frm.set_value("visitor_full_name", "");
			frm.set_value("mobile_number", "");
			frm.set_value("email_id", "");
			frm.set_value("company__organisation", "");
			frm.set_value("id_proof_type", "");
			frm.set_value("id_proof_number", "");
			// Clear type-specific links
			if (frm.doc.visitor_type === "Supplier") {
				frm.set_value("supplier_link", "");
			} else if (frm.doc.visitor_type === "Customer") {
				frm.set_value("crm_reference_type", "");
				frm.set_value("crm_lead_opportunity", "");
			} else if (frm.doc.visitor_type === "Contractor") {
				frm.set_value("contractor_link", "");
				frm.set_value("work_order_ref", "");
			} else if (frm.doc.visitor_type === "Candidate") {
				frm.set_value("job_applicant_link", "");
			}
		}

		apply_visitor_pass_ui(frm);
	},

	existing_visitor_pass(frm) {
		if (!frm.doc.existing_visitor_pass) {
			apply_visitor_pass_ui(frm);
			return;
		}

		frappe.call({
			method:
				"visitormanagement.visitor_management.doctype.visitor_pass.visitor_pass.get_existing_visitor_pass_details",
			args: {
				visitor_pass: frm.doc.existing_visitor_pass,
				visitor_type: frm.doc.visitor_type,
			},
			callback: ({ message }) => {
				if (!message) {
					return;
				}
				apply_existing_pass_data(frm, message);
				apply_visitor_pass_ui(frm);
			},
		});
	},

	meeting_outcome(frm) {
		apply_visitor_pass_ui(frm);
	},

	meal_required(frm) {
		apply_visitor_pass_ui(frm);
	},

	refreshments_required(frm) {
		apply_visitor_pass_ui(frm);
	},

	visit_date(frm) {
		refresh_hospitality_plan(frm);
	},

	expected_checkin(frm) {
		refresh_hospitality_plan(frm);
	},

	expected_checkout(frm) {
		refresh_hospitality_plan(frm);
	},

	interpreter_required(frm) {
		apply_visitor_pass_ui(frm);
	},

	multi_day_pass(frm) {
		apply_visitor_pass_ui(frm);
	},

	status(frm) {
		apply_visitor_pass_ui(frm);
	},

	workflow_state(frm) {
		apply_visitor_pass_ui(frm);
	},
});

function apply_visitor_pass_ui(frm) {
	apply_visitor_pass_field_rules(frm);
}

function ensure_customer_crm_defaults(frm) {
	if (frm.doc.visitor_type === "Customer" && frm.doc.entry_type === "New" && !frm.doc.crm_reference_type) {
		frm.set_value("crm_reference_type", "Lead");
		return;
	}

	if (frm.doc.visitor_type !== "Customer" || frm.doc.entry_type !== "New") {
		if (frm.doc.crm_reference_type || frm.doc.crm_lead_opportunity) {
			frm.set_value({
				crm_reference_type: "",
				crm_lead_opportunity: "",
			});
		}
	}
}

function apply_visitor_type_defaults(frm, force = false) {
	const updates = {};
	if (frm.doc.visitor_type === "VIP") {
		if (!frm.doc.priority_lane) {
			updates.priority_lane = 1;
		}
		if (frm.doc.interpreter_required && !frm.doc.interpreter_language) {
			updates.interpreter_language = "English";
		}
	}

	if (Object.keys(updates).length) {
		frm.set_value(updates);
	}
}

function fetch_customer_crm_details(frm) {
	if (frm.doc.visitor_type !== "Customer" || !frm.doc.crm_reference_type || !frm.doc.crm_lead_opportunity) {
		return;
	}

	let doctype = frm.doc.crm_reference_type;
	if (doctype === "Customer") {
		doctype = "Customer";
	}

	frappe.call({
		method: "frappe.client.get",
		args: { doctype: doctype, name: frm.doc.crm_lead_opportunity },
		callback: ({ message }) => {
			if (!message) {
				return;
			}

			let visitor_full_name = "";
			let mobile_number = "";
			let email_id = "";
			let company__organisation = "";
			let sales_executive = "";

			if (frm.doc.crm_reference_type === "Lead") {
				visitor_full_name = message.lead_name || "";
				mobile_number = message.mobile_no || "";
				email_id = message.email_id || "";
				company__organisation = message.company_name || "";
				sales_executive = message.lead_owner || "";
			} else if (frm.doc.crm_reference_type === "Opportunity") {
				visitor_full_name = message.contact_display || message.customer_name || "";
				mobile_number = message.contact_mobile || "";
				email_id = message.contact_email || "";
				company__organisation = message.customer_name || "";
				sales_executive = message.opportunity_owner || "";
			} else if (frm.doc.crm_reference_type === "Customer") {
				visitor_full_name = message.customer_name || "";
				mobile_number = message.mobile_no || "";
				email_id = message.email_id || "";
				company__organisation = message.customer_name || "";
				// Sales executive might need to be fetched differently
			}

			frm.set_value({
				visitor_full_name: visitor_full_name,
				mobile_number: mobile_number,
				email_id: email_id,
				company__organisation: company__organisation,
				sales_executive: sales_executive,
			});

			if (message.owner_user && !message.sales_executive) {
				frappe.show_alert(
					{
						message: __(
							"CRM owner {0} has no linked Employee, so Sales Executive was not auto-filled.",
							[message.owner_user]
						),
						indicator: "orange",
					},
					7
				);
			}
		},
	});
}

function apply_visitor_pass_field_rules(frm) {
	const is_supplier_existing = frm.doc.visitor_type === "Supplier" && frm.doc.entry_type === "Existing";
	const is_existing = ['Supplier','Customer','Contractor','Candidate'].includes(frm.doc.visitor_type) && frm.doc.entry_type === "Existing";
	const is_supplier_delivery =
		frm.doc.visitor_type === "Supplier" && frm.doc.supplier_visit_mode === "Delivery";
	const is_supplier_business =
		frm.doc.visitor_type === "Supplier" &&
		!!frm.doc.supplier_visit_mode &&
		frm.doc.supplier_visit_mode !== "Delivery";
	const is_follow_up = frm.doc.visitor_type === "Customer" && frm.doc.meeting_outcome === "Follow-Up Needed";
	const needs_interpreter = frm.doc.visitor_type === "VIP" && !!frm.doc.interpreter_required;
	const is_multi_day_contractor = frm.doc.visitor_type === "Contractor" && !!frm.doc.multi_day_pass;
	const has_contractor_nda = frm.doc.visitor_type === "Contractor" && !!frm.doc.contractor_nda_signed;
	const has_ppe_proof = frm.doc.visitor_type === "Contractor" && !!frm.doc.ppe_provided;
	const hospitality_requested =
		!!frm.doc.meal_required || !!frm.doc.refreshments_required || !!frm.doc.conference_room;
	const hospitality_recorded = hospitality_requested || !!frm.doc.hospitality_request;

	[
		"status",
		"workflow_state",
		"approval_date",
		"approved_by",
		"badge_number",
		"qr_code_image",
		"gate_verified_photo",
		"gate_verified_on",
		"gate_verified_by",
		"host_department",
		"item_verification_status",
		"items_verified",
		"all_items_verified",
		"actual_checkin",
		"actual_checkout",
		"no_show",
		"current_location",
		"last_health_screening",
		"health_screening_status",
		"hospitality_request",
	].forEach((fieldname) => frm.set_df_property(fieldname, "read_only", 1));

	frm.set_df_property("items_verification_status", "hidden", 1);
	frm.toggle_display("existing_visitor_pass", is_existing);
	frm.toggle_reqd("existing_visitor_pass", is_existing);
	frm.toggle_display("supplier_link", frm.doc.visitor_type === "Supplier" && frm.doc.entry_type === "New");
	frm.toggle_display("crm_reference_type", frm.doc.visitor_type === "Customer" && frm.doc.entry_type === "New");
	frm.toggle_display("crm_lead_opportunity", frm.doc.visitor_type === "Customer" && frm.doc.entry_type === "New");
	frm.toggle_display("contractor_link", frm.doc.visitor_type === "Contractor" && frm.doc.entry_type === "New");
	frm.toggle_display("work_order_ref", frm.doc.visitor_type === "Contractor" && frm.doc.entry_type === "New");
	frm.toggle_display("job_applicant_link", frm.doc.visitor_type === "Candidate" && frm.doc.entry_type === "New");
	frm.toggle_display(
		[
			"purchase_order",
			"delivery_note",
			"goods_received_by",
			"driver_id_number",
			"dock_bay_assigned",
			"store_officer",
			"goods_description",
		],
		is_supplier_delivery
	);
	frm.toggle_display(
		[
			"meeting_subject",
			"meeting_start_time",
			"meeting_end_time",
			"meeting_room",
			"attendees",
			"refreshments_required",
			"refreshment_notes",
			"presentation_material",
			"nda_required",
			"documents_shared",
		],
		is_supplier_business
	);
	frm.toggle_reqd("purchase_order", is_supplier_delivery);
	frm.toggle_reqd("meeting_subject", is_supplier_business);

	frm.toggle_display("followup_date", is_follow_up);
	frm.toggle_reqd("followup_date", is_follow_up);

	frm.toggle_display("interpreter_language", needs_interpreter);
	frm.toggle_reqd("interpreter_language", needs_interpreter);

	frm.toggle_display("pass_valid_until", is_multi_day_contractor);
	frm.toggle_reqd("pass_valid_until", is_multi_day_contractor);
	frm.toggle_display("contractor_nda_document", has_contractor_nda);
	frm.toggle_reqd("contractor_nda_document", has_contractor_nda);
	frm.toggle_display("ppe_provided_document", has_ppe_proof);
	frm.toggle_reqd("ppe_provided_document", has_ppe_proof);

	[
		"meal_type",
		"assigned_meal_slots",
		"hospitality_type",
		"number_of_people",
		"special_diet",
		"food_dept_staff_assigned",
		"food_status",
		"hospitality_request",
	].forEach((fieldname) => frm.toggle_display(fieldname, hospitality_recorded));

	frm.toggle_display(["conference_room", "service_time"], true);
	frm.toggle_display(["rest_area", "hospitality_notes"], hospitality_recorded);
}

function refresh_hospitality_plan(frm) {
	if (!frm.doc.visit_date || !frm.doc.expected_checkin || !frm.doc.expected_checkout) {
		frm.set_value({
			meal_required: 0,
			meal_type: "",
			assigned_meal_slots: "",
			hospitality_type: "",
			service_time: null,
		});
		apply_visitor_pass_ui(frm);
		return;
	}

	frappe.call({
		method: "visitormanagement.visitor_management.lifecycle.get_hospitality_meal_plan",
		args: {
			visit_date: frm.doc.visit_date,
			expected_checkin: frm.doc.expected_checkin,
			expected_checkout: frm.doc.expected_checkout,
		},
		callback: ({ message }) => {
			if (!message) {
				return;
			}

			frm.set_value({
				meal_required: message.meal_required || 0,
				meal_type: message.meal_type || "",
				assigned_meal_slots: message.assigned_meal_slots || "",
				hospitality_type: message.hospitality_type || "",
				service_time: message.service_time || null,
			});
			apply_visitor_pass_ui(frm);
		},
	});
}

function add_action_buttons(frm) {
	// "Actions" group removed — "Open Hospitality" is already available
	// under the "Hospitality" group (see add_hospitality_buttons).
	return;
}

function setup_supplier_pass_query(frm) {
	if (!['Supplier','Customer','Contractor','Candidate'].includes(frm.doc.visitor_type)) return;

	frm.set_query("existing_visitor_pass", () => ({
		filters: {
			visitor_type: frm.doc.visitor_type,
		},
	}));
}

function show_web_submissions_dialog(frm) {
	frappe.call({
		method: 'frappe.client.get_list',
		args: {
			doctype: 'Visitor Pass',
			filters: [
				['workflow_state', 'in', ['Pending System Manager', 'Pending Visitor Manager', 'Pending Sales Manager', 'Pending HR Manager', 'Pending HOD', 'Pending CEO', 'Draft']]
			],
			fields: ['name', 'visitor_full_name', 'visitor_type', 'mobile_number', 'email_id', 'visit_date']
		},
		callback: function(r) {
			if (r.message && r.message.length > 0) {
				let dialog = new frappe.ui.Dialog({
					title: __('Pending Web Submissions'),
					fields: [
						{
							fieldtype: 'HTML',
							fieldname: 'submissions',
							options: generate_submissions_html(r.message, frm)
						}
					],
					size: 'large'
				});
				dialog.show();
			} else {
				frappe.msgprint(__('No pending web visitor pass submissions found.'));
			}
		}
	});
}

function generate_submissions_html(submissions, frm) {
	let html = '<div class="row">';
	submissions.forEach(sub => {
		html += `
			<div class="col-md-6 mb-3">
				<div class="card">
					<div class="card-body">
						<h5 class="card-title">${sub.visitor_full_name} (${sub.visitor_type})</h5>
						<p class="card-text">
							Phone: ${sub.mobile_number}<br>
							Email: ${sub.email_id}<br>
							Date: ${sub.visit_date}
						</p>
						<button class="btn btn-primary btn-sm" onclick="select_submission('${sub.name}', '${frm.doc.name}')">Select & Auto-Fetch</button>
					</div>
				</div>
			</div>
		`;
	});
	html += '</div>';
	return html;
}

window.select_submission = function(submission_name, frm_name) {
	frappe.call({
		method: 'frappe.client.get',
		args: { doctype: 'Visitor Pass', name: submission_name },
		callback: function(r) {
			if (r.message) {
				let data = r.message;
				// Set values in Visitor Pass
				frappe.set_route('Form', 'Visitor Pass', frm_name);
				setTimeout(() => {
					let frm = cur_frm;
					frm.set_value('visitor_type', data.visitor_type);
					frm.set_value('visitor_full_name', data.visitor_full_name);
					frm.set_value('mobile_number', data.mobile_number);
					frm.set_value('email_id', data.email_id);
					frm.set_value('company__organisation', data.company__organisation);
					frm.set_value('visit_date', data.visit_date);
					frm.set_value('expected_checkin', data.expected_checkin);
					frm.set_value('expected_checkout', data.expected_checkout);
					frm.set_value('purpose_of_visit', resolve_purpose_of_visit(data));
					frm.set_value('person_to_visit', data.person_to_visit);
					frm.set_value('id_proof_type', data.id_proof_type);
					frm.set_value('id_proof_number', data.id_proof_number);
					frm.set_value('id_proof_scan', data.id_proof_scan);
					frm.set_value('visitor_photo', data.visitor_photo);
					frm.save();
				}, 500);
			}
		}
	});
};

function resolve_purpose_of_visit(data) {
	const explicit = (data.purpose_of_visit || "").trim();
	if (explicit) {
		return explicit;
	}

	if (data.visitor_type === "Supplier") {
		if ((data.supplier_visit_mode || "") === "Delivery") {
			return __("Supplier Delivery");
		}
		return __("Supplier Meeting");
	}
	if (data.visitor_type === "Customer") {
		return __("Customer Meeting");
	}
	if (data.visitor_type === "Contractor") {
		return __("Contract Work Visit");
	}
	if (data.visitor_type === "Candidate") {
		return __("Interview Visit");
	}
	if (data.visitor_type === "VIP") {
		return __("VIP Visit");
	}
	return "";
}

function apply_existing_pass_data(frm, data) {
	const fields = [
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
		"supplier_visit_mode",
		"supplier_link",
		"purchase_order",
		"delivery_note",
		"goods_description",
		"meeting_subject",
		"meeting_start_time",
		"meeting_end_time",
		"meeting_room",
		"attendees",
		"refreshments_required",
		"refreshment_notes",
		"presentation_material",
		"nda_required",
		"documents_shared",
		"crm_reference_type",
		"crm_lead_opportunity",
		"visit_category",
		"sales_executive",
		"products_discussed",
		"meeting_outcome",
		"followup_date",
		"meeting_minutes",
		"contractor_link",
		"work_order_ref",
		"safety_induction_done",
		"contractor_nda_signed",
		"contractor_nda_document",
		"ppe_provided",
		"ppe_provided_document",
		"work_area_zone",
		"tools_list",
		"multi_day_pass",
		"pass_valid_until",
		"job_applicant_link",
		"position_applied",
		"candidate_interview_type",
		"interview_panel",
		"interview_room",
	];

	const updates = {};
	fields.forEach((fieldname) => {
		if (Object.prototype.hasOwnProperty.call(data, fieldname)) {
			updates[fieldname] = data[fieldname];
		}
	});
	frm.set_value(updates);
}

function lookup_existing_visitor_match(frm, trigger_field) {
	if (!frm.doc.visitor_type || !["Supplier", "Customer", "Contractor", "Candidate"].includes(frm.doc.visitor_type)) {
		return;
	}
	if (!frm.doc.mobile_number && !frm.doc.id_proof_number) {
		return;
	}

	frappe.call({
		method: "visitormanagement.visitor_management.doctype.visitor_pass.visitor_pass.get_existing_visitor_matches",
		args: {
			visitor_type: frm.doc.visitor_type,
			id_proof_number: frm.doc.id_proof_number,
			mobile_number: frm.doc.mobile_number,
			exclude_name: frm.doc.name,
		},
		callback: ({ message }) => {
			if (!message || !message.best_match) {
				return;
			}

			const best = message.best_match;
			const signature = `${best.name}:${trigger_field}:${frm.doc.id_proof_number || ""}:${frm.doc.mobile_number || ""}`;
			if (frm.__last_existing_prompt_signature === signature) {
				return;
			}
			frm.__last_existing_prompt_signature = signature;

			const prompt = __(
				"Existing {0} record found: {1} ({2}). Do you want to load this data?",
				[best.visitor_type, best.name, best.visitor_full_name]
			);

			frappe.confirm(prompt, () => {
				if (frm.doc.entry_type !== "Existing") {
					frm.set_value("entry_type", "Existing");
				}
				frm.set_value("existing_visitor_pass", best.name);
			});
		},
	});
}

function add_hospitality_buttons(frm) {
	if (frm.is_new()) return;

	if (frm.doc.hospitality_request) {
		frm.add_custom_button(
			__("View Itinerary"),
			() => {
				const url = `/printview?doctype=${encodeURIComponent("Hospitality Request")}`
					+ `&name=${encodeURIComponent(frm.doc.hospitality_request)}`
					+ `&format=${encodeURIComponent("Visitor Itinerary")}`
					+ `&no_letterhead=0`;
				window.open(url, "_blank");
			},
			__("Hospitality")
		);

		frm.add_custom_button(
			__("Open Hospitality Request"),
			() => {
				frappe.set_route("Form", "Hospitality Request", frm.doc.hospitality_request);
			},
			__("Hospitality")
		);
	} else {
		const any_arrangement = (
			frm.doc.cab_required
			|| frm.doc.hotel_required
			|| frm.doc.factory_tour_required
			|| frm.doc.buggy_required
			|| frm.doc.greeting_required
			|| frm.doc.meal_required
			|| frm.doc.conference_room
		);
		if (any_arrangement) {
			frm.add_custom_button(
				__("Create Hospitality Request"),
				() => {
					frappe.new_doc("Hospitality Request", {
						visitor_pass: frm.doc.name,
					});
				},
				__("Hospitality")
			);
		}
	}
}
