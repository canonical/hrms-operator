# HRMS Terraform module

This folder contains a base [Terraform][Terraform] module for the hrms charm.

The module uses the [Terraform Juju provider][Terraform Juju provider] to model the charm
deployment onto any Kubernetes environment managed by [Juju][Juju].

## Module structure

- **product/main.tf** - Defines the Juju applications and integrations to deploy.
- **product/variables.tf** - Allows customization of the deployment and charm config.
- **product/outputs.tf** - Exposes deployed app names and relation endpoints.
- **product/versions.tf** - Defines Terraform and provider version constraints.

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

The module deploys `hrms`, `mariadb-k8s`, and `redis-k8s` and creates the required
integrations between them automatically. To add ingress, deploy Traefik and integrate
it with the exposed `ingress` endpoint:

```text
resource "juju_application" "traefik" {
  name       = "traefik-k8s"
  model_uuid = data.juju_model.my_model.uuid

  charm {
    name    = "traefik-k8s"
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
    name     = juju_application.traefik.name
    endpoint = "ingress"
  }
}
```

The complete list of available integrations can be found [in the Integrations tab][hrms-integrations].

[Terraform]: https://developer.hashicorp.com/terraform
[Terraform Juju provider]: https://registry.terraform.io/providers/juju/juju/latest
[Juju]: https://juju.is
[hrms-integrations]: https://charmhub.io/hrms/integrations
