.. meta::
   :description: How to integrate the HRMS charm with the Canonical Observability Stack (COS).

.. _how_to_integrate_with_cos:

How to integrate with COS
=========================

The HRMS charm integrates with the `Canonical Observability Stack
https://documentation.ubuntu.com/observability/track-3.0/`_ (COS) to export
metrics, forward logs, and provide Grafana dashboards.

Prerequisites
-------------

A COS deployment providing Prometheus, Loki, and Grafana (for example,
``cos-lite``) reachable from the model where HRMS is deployed (typically via a
cross-model offer).

Integrate
---------

.. code-block:: bash

   juju integrate hrms:metrics-endpoint prometheus:metrics-endpoint
   juju integrate hrms:logging loki:logging
   juju integrate hrms:grafana-dashboard grafana:grafana-dashboard

After the relations settle, HRMS metrics are scraped by Prometheus, workload
logs are forwarded to Loki via Pebble log forwarding, and the
"Frappe HRMS Operator" dashboard appears in Grafana. Bundled Prometheus and
Loki alert rules are published automatically over the same relations.
