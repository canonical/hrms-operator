<!--
Avoid using this README file for information that is maintained or published elsewhere, e.g.:

* metadata.yaml > published on Charmhub
* documentation > published on (or linked to from) Charmhub
* detailed contribution guide > documentation or CONTRIBUTING.md

Use links instead.
-->
# Frappe HRMS Operator
<!-- Use this space for badges -->

Frappe HRMS is an open-source, modern HR and payroll application built on the Frappe Framework. This charm deploys Frappe HRMS on Kubernetes, integrating with database, Redis, and ingress.

Like any Juju charm, this charm supports one-line deployment, configuration, integration, scaling, and more. For Charmed Frappe HRMS, this includes:
* Employee lifecycle management (hiring, transfers, exit)
* Leave and attendance management
* Expense claims and payroll processing
* Performance management
* Integration with MariaDB (via data-platform-libs), Redis, and ingress

For information about how to deploy, integrate, and manage this charm, see the Official [Frappe HRMS Documentation](https://docs.frappe.io/hr).

## Get started

### Prerequisites

* A Juju controller connected to a Kubernetes cluster
* The following charms available: `mariadb-k8s`, `redis-k8s`, and a K8s ingress charm

### Deploy

```bash
juju deploy hrms
juju integrate hrms mariadb-k8s
juju integrate hrms redis-k8s
juju integrate hrms traefik-k8s
```

## Integrations

| Relation | Interface | Role | Description |
|----------|-----------|------|-------------|
| `mysql` | `mysql_client` | requires | MariaDB database (via data-platform-libs) |
| `redis` | `redis` | requires | Redis for caching, queues, and Socket.IO |
| `ingress` | `ingress` | requires | Ingress for external access |

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
