<<<<<<< HEAD
### visitor management system 

vms

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch frappe-bench-v161
bench install-app visitor_management
```

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/visitor_management
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade
### CI

This app can use GitHub Actions for CI. The following workflows are configured:

- CI: Installs this app and runs unit tests on every push to `develop` branch.
- Linters: Runs [Frappe Semgrep Rules](https://github.com/frappe/semgrep-rules) and [pip-audit](https://pypi.org/project/pip-audit/) on every pull request.


### License

mit
=======
# visitor-management-system
he Visitor Management System (VMS) is a digital solution designed to efficiently manage, monitor, and record visitor activities within an organization. It replaces manual register-based entry systems with a secure, automated, and real-time tracking system.
>>>>>>> 2963cf0a7eae4f035eb4cbecf08d8a646a244f4a
