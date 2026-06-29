<!--
Avoid using this README file for information that is maintained or published elsewhere, e.g.:

* metadata.yaml > published on Charmhub
* documentation > published on (or linked to from) Charmhub
* detailed contribution guide > documentation or CONTRIBUTING.md

Use links instead.
-->
# Frappe HRMS Operator
<!-- Use this space for badges -->

Frappe HRMS is an open-source, modern HR and payroll application built on the Frappe Framework. This charm deploys Frappe HRMS on Kubernetes, integrating with PostgreSQL, Redis, and Traefik ingress.

Like any Juju charm, this charm supports one-line deployment, configuration, integration, scaling, and more. For Charmed Frappe HRMS, this includes:
* Employee lifecycle management (onboarding, transfers, exit)
* Leave and attendance management
* Expense claims and payroll processing
* Performance management
* Integration with PostgreSQL (via data-platform-libs), Redis, and Traefik ingress

For information about how to deploy, integrate, and manage this charm, see the Official [Frappe HRMS Documentation](https://docs.frappe.io/hr).

## Get started

### Prerequisites

* A Juju controller connected to a Kubernetes cluster
* The following charms available: `postgresql-k8s`, `redis-k8s`, `traefik-k8s`

### Deploy

```bash
juju deploy frappe-hrms --resource frappe-hrms-image=ghcr.io/canonical/frappe-hrms:latest
juju config frappe-hrms site-name=hrms.example.com admin-password=<password>
juju integrate frappe-hrms postgresql-k8s
juju integrate frappe-hrms redis-k8s
juju integrate frappe-hrms traefik-k8s
```

### Basic operations

**Change nginx proxy timeout:**

```bash
juju config frappe-hrms proxy-read-timeout=300
```

**Change the maximum upload size:**

```bash
juju config frappe-hrms client-max-body-size=100m
```

## Integrations

| Relation | Interface | Role | Description |
|----------|-----------|------|-------------|
| `postgresql` | `postgresql_client` | requires | PostgreSQL database (via data-platform-libs) |
| `redis` | `redis` | requires | Redis for caching, queues, and Socket.IO |
| `ingress` | `ingress` | requires | Traefik ingress for external access |

## Learn more

* [Frappe HRMS Documentation](https://docs.frappe.io/hr)
* [Frappe Framework](https://frappeframework.com)
* [Issues](https://github.com/canonical/hrms-operator/issues)
* [Contributing](CONTRIBUTING.md)
* [Matrix](https://matrix.to/#/#charmhub-platform:ubuntu.com)

## Project and community

* [Issues](https://github.com/canonical/hrms-operator/issues)
* [Contributing](CONTRIBUTING.md)
* [Matrix](https://matrix.to/#/#charmhub-platform:ubuntu.com)
* [Launchpad](https://launchpad.net/~canonical-is-devops)

