.. meta::
   :description: Reference documentation for all relation endpoints supported by the HRMS charm.

.. _reference_relation_endpoints:

Relation endpoints
==================

Observability
-------------

* **metrics-endpoint** (provides, interface ``prometheus_scrape``): Exposes the
  HRMS Prometheus scrape job and alert rules to Prometheus.
* **logging** (requires, interface ``loki_push_api``): Forwards workload logs to
  Loki using Pebble log forwarding.
* **grafana-dashboard** (provides, interface ``grafana_dashboard``): Ships the
  HRMS Grafana dashboard.

Example integrate commands:

.. code-block:: bash

   juju integrate hrms:metrics-endpoint prometheus:metrics-endpoint
   juju integrate hrms:logging loki:logging
   juju integrate hrms:grafana-dashboard grafana:grafana-dashboard
