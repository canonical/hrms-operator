# HRMS Terraform module

This folder contains a base [Terraform][Terraform] module for the hrms charm.

The module uses the [Terraform Juju provider][Terraform Juju provider] to model the charm
deployment onto any Kubernetes environment managed by [Juju][Juju].

## Module structure

- **product/main.tf** - Defines the Juju applications to deploy and the integrations.
- **product/variables.tf** - Allows customization of the deployment and charm config.
- **product/outputs.tf** - Exposes deployed app names and relation endpoints.
- **product/versions.tf** - Defines Terraform provider version.

## Using hrms base module in higher level modules

If you want to use `hrms` base module as part of your Terraform module, import it
like shown below:

```text
data "juju_model" "my_model" {
  name = var.model
}

module "hrms" {
  source = "git::https://github.com/canonical/hrms-operator//terraform/product"

  model_uuid = data.juju_model.my_model.uuid
  # (Customize configuration variables here if needed)
}
```

Create integrations, for instance:

```text
resource "juju_application" "ingress_configurator" {
  name       = "ingress-configurator"
  model_uuid = data.juju_model.my_model.uuid

  charm {
    name    = "ingress-configurator"
    channel = "latest/stable"
  }
}

resource "juju_integration" "hrms-ingress" {
  model_uuid = data.juju_model.my_model.uuid

  application {
    name     = module.hrms.app_name
    endpoint = module.hrms.endpoints.requires.ingress
  }

  application {
    name     = juju_application.ingress_configurator.name
    endpoint = "ingress"
  }
}
```

The complete list of available integrations can be found [in the Integrations tab][hrms-integrations].

[Terraform]: https://developer.hashicorp.com/terraform
[Terraform Juju provider]: https://registry.terraform.io/providers/juju/juju/latest
[Juju]: https://juju.is
[hrms-integrations]: https://charmhub.io/hrms/integrations
