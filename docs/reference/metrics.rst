.. meta::
   :description: Reference documentation for the alerting and monitoring metrics provided by the HRMS charm.

.. _reference_metrics:

Metrics
=======

HRMS exposes Prometheus metrics from a ``statsd_exporter`` process that runs
inside the ``frappe-hrms`` container and listens on port ``9102`` at ``/metrics``.
The gunicorn ``backend`` service is configured with ``--statsd-host`` so its
request statistics (prefixed ``frappe_hrms``) are converted to Prometheus
metrics by the exporter.

Key metrics:

* **gunicorn_requests_total**: Total number of HTTP requests handled by the
  gunicorn backend.
* **gunicorn_request_status_total**: HTTP responses broken down by status code
  (label ``status``).
* **gunicorn_request_duration_seconds**: Request processing duration.
* **gunicorn_workers**: Number of active gunicorn workers.

These metrics are scraped over the ``metrics-endpoint`` relation
(interface ``prometheus_scrape``).
