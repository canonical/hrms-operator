.. meta::
   :description: Reference documentation for all Juju events observed by the HRMS charm.

.. _reference_juju_events:

Juju events
===========

For this charm, the following Juju events are observed:

Observability
-------------

The charm observes the relation events for its Canonical Observability Stack
integrations. These events are handled by the COS charm library providers
(``MetricsEndpointProvider``, ``GrafanaDashboardProvider``, and
``LogForwarder``) rather than by the charm's ``_reconcile`` handler:

* ``metrics-endpoint-relation-*``: Publishes the Prometheus scrape job and
  alert rules when a Prometheus charm relates over ``metrics-endpoint``.
* ``grafana-dashboard-relation-*``: Publishes the bundled Grafana dashboard
  when a Grafana charm relates over ``grafana-dashboard``.
* ``logging-relation-*``: Configures Pebble log forwarding to Loki and
  publishes Loki alert rules when a Loki charm relates over ``logging``.

.. seealso::

   See more in the Juju docs:
   `Hook <https://canonical.com/juju/docs/juju-cli/latest/reference/hook/>`_
