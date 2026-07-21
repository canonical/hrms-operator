.. meta::
   :description: View the changelog for the __charm_name__ charm, including all versions and changes.

.. _changelog:

Changelog
=========

All notable changes to this project will be documented in this file.

The format is based on `Keep a Changelog <https://keepachangelog.com/en/1.1.0/>`_.

Each revision is versioned by the date of the revision.

2026-07-21
----------

Added
~~~~~

- Support for the ``upgrade-charm`` hook. The charm now runs ``bench migrate``
  on upgrade to apply pending database schema changes and data patches.

2026-07-16
----------

Changed
~~~~~~~

- Updated the tutorial with a basic Frappe HRMS deployment walkthrough.

2026-07-15
----------

Changed
~~~~~~~

- Updated publish workflow track to 16/edge.

Added
~~~~~

- Terraform module to deploy Frappe HRMS with MariaDB and Redis.

