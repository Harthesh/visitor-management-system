# -------------------
# FIXTURES
# -------------------
app_name = "visitormanagement"
app_title = "Visitor Management"
app_publisher = "Harthesh"
app_description = "Visitor Management System"
app_email = "harthesh@example.com"
app_license = "MIT"
fixtures = [
    {
        "doctype": "Workflow",
        "filters": [
            ["name", "in", [
                "CRITICAL RISK RISK",
                "HIGH RISK RISK",
                "MEDIUM RISK RISK",
                "LOW RISK RISK"
            ]]
        ]
    },
    {
        "doctype": "Workflow State",
        "filters": [
            ["workflow", "in", [
                "CRITICAL RISK RISK",
                "HIGH RISK RISK",
                "MEDIUM RISK RISK",
                "LOW RISK RISK"
            ]]
        ]
    },
    {
        "doctype": "Workflow Transition",
        "filters": [
            ["parent", "in", [
                "CRITICAL RISK RISK",
                "HIGH RISK RISK",
                "MEDIUM RISK RISK",
                "LOW RISK RISK"
            ]]
        ]
    }
]


# -------------------
# SCHEDULER EVENTS
# -------------------

scheduler_events = {
    "cron": {
        "*/30 * * * *": [
            "visitor_management.tasks.check_overstays",
            "visitor_management.tasks.escalate_pending_approvals",
        ],
        "0 * * * *": [
            "visitor_management.tasks.expire_badges",
        ],
    }
}
