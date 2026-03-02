// Copyright (c) 2026, Harthesh and contributors
// For license information, please see license.txt

// frappe.ui.form.on("Security Log", {
// 	refresh(frm) {

// 	},
// });
frappe.ui.form.on('Security Log', {
    qr_code_value: function(frm) {
        if (frm.doc.qr_code_value) {
            frm.set_value('visitor_pass', frm.doc.qr_code_value);
        }
    }
});