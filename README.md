# `hrms-operator`
<!-- Use this space for badges -->

Frappe HRMS is an open-source, modern HR and payroll application built on the Frappe Framework. This charm deploys Frappe HRMS on Kubernetes, integrating with database, Valkey, and ingress.

Like any Juju charm, this charm supports one-line deployment, configuration, integration, scaling, and more. For Charmed Frappe HRMS, this includes:
* Employee lifecycle management (hiring, transfers, exit)
* Leave and attendance management
* Expense claims and payroll processing
* Performance management
* Integration with database, message broker and ingress.

For information about the upstream software, see the official [Frappe HRMS documentation](https://docs.frappe.io/hr).

## Get started

### Prerequisites

* A Juju controller connected to a Kubernetes cluster.
* The following charms available: `mariadb-k8s`, `valkey`, and a K8s ingress charm. HRMS depends on `mariadb-k8s` and `valkey` charms to start successfully.

### Deploy

```bash
juju deploy hrms
juju integrate hrms mariadb-k8s
juju integrate hrms valkey
juju integrate hrms ingress-configurator
```

## Learn more

* [Frappe HRMS Documentation](https://docs.frappe.io/hr)
* [Frappe Framework](https://frappe.io/framework)
* [Contributing](CONTRIBUTING.md)
* [Matrix](https://matrix.to/#/#charmhub-platform:ubuntu.com)

## Project and community

* [Issues](https://github.com/canonical/hrms-operator/issues)
* [Contributing](CONTRIBUTING.md)
* [Matrix](https://matrix.to/#/#charmhub-platform:ubuntu.com)
* [Launchpad](https://launchpad.net/~canonical-is-devops)
