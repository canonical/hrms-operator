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
      revision = 8
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

  assert {
    condition     = output.status == "active"
    error_message = "hrms application status is not active"
  }
}
