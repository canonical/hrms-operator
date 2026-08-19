# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

run "setup_tests" {
  module {
    source = "./tests/setup"
  }

  variables {
    channel = "16/edge"
    # renovate: depName="hrms"
    revision = 3

    database = {
      # renovate: depName="mysql-k8s"
      revision = 423
    }

    redis = {
      # renovate: depName="redis-k8s"
      revision = 42
    }
  }

  assert {
    condition     = output.application == "hrms"
    error_message = "hrms application name did not match expected"
  }

  # TODO: Re-enable once a MySQL-compatible charm revision is published.
  # The terraform module now deploys mysql-k8s but the published charm
  # (16/edge rev 3) still expects MariaDB.
  # assert {
  #   condition     = output.status == "active"
  #   error_message = "hrms application status is not active"
  # }
}
