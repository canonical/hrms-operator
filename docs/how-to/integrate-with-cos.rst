.. meta::
   :description: How to integrate the HRMS charm with the Canonical Observability Stack (COS).

.. _how_to_integrate_with_cos:

How to integrate with COS
=========================

The HRMS charm integrates with the
`Canonical Observability Stack <https://documentation.ubuntu.com/observability/track-3.0/>`_
(COS) to export metrics, forward logs, and provide Grafana dashboards. It exposes
three relation endpoints:

- ``metrics-endpoint`` (interface ``prometheus_scrape``)
- ``logging`` (interface ``loki_push_api``)
- ``grafana-dashboard`` (interface ``grafana_dashboard``)

Recommended: integrate through the OpenTelemetry Collector
----------------------------------------------------------

The recommended approach, especially for cross-model deployments, is to relate
HRMS to the
`OpenTelemetry Collector <https://documentation.ubuntu.com/observability/track-3.0/explanation/architecture/telemetry-flow/>`_
(``opentelemetry-collector-k8s``), which aggregates the telemetry and forwards it
to the COS backends. This decouples HRMS from the individual backends and is the
supported pattern for sending telemetry across models.

Relate HRMS to the collector:

.. code-block:: bash

   juju integrate hrms:metrics-endpoint opentelemetry-collector:metrics-endpoint
   juju integrate hrms:logging opentelemetry-collector:receive-loki-logs
   juju integrate hrms:grafana-dashboard opentelemetry-collector:grafana-dashboards-consumer

The collector then forwards the telemetry to the COS backends (typically deployed
in the COS model):

.. code-block:: bash

   juju integrate opentelemetry-collector:send-remote-write prometheus:receive-remote-write
   juju integrate opentelemetry-collector:send-loki-logs loki:logging
   juju integrate opentelemetry-collector:grafana-dashboards-provider grafana:grafana-dashboard

Alternative: integrate directly (single-model)
----------------------------------------------

For simple, single-model setups you can relate HRMS directly to the COS
components instead of using the collector:

.. code-block:: bash

   juju integrate hrms:metrics-endpoint prometheus:metrics-endpoint
   juju integrate hrms:logging loki:logging
   juju integrate hrms:grafana-dashboard grafana:grafana-dashboard

Result
------

After the relations settle, HRMS metrics are scraped by Prometheus, workload
logs are forwarded to Loki via Pebble log forwarding, and the
"Frappe HRMS Operator" dashboard appears in Grafana. Bundled Prometheus and
Loki alert rules are published automatically over the same relations.
