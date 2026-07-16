.. meta::
    :description: A step-by-step tutorial for deploying the Frappe HRMS charm for the first time.

.. _tutorial_basic_deployment:

Deploy the Frappe HRMS charm for the first time
===============================================

This tutorial walks through a minimal Frappe HRMS deployment on a K8s-backed
Juju controller. You will create the Juju secret required by the charm, deploy
Frappe HRMS with its dependencies, and verify that the site finishes bootstrapping 
and serves the login page.

What you'll do
--------------

1. Create an administrator password secret for Frappe HRMS.
2. Deploy the Frappe HRMS charm and its dependencies.
3. Integrate the charm with its database, cache, and ingress dependencies.
4. Verify that the published ingress URL serves the HRMS login page.
5. Clean up the model.

What you'll need
----------------

.. vale Canonical.013-Spell-out-numbers-below-10 = NO

.. SPREAD SKIP

You will need a working station, e.g., a laptop, with AMD64 architecture. Your working station
should have at least 4 CPU cores, 8 GB of RAM, and 50 GB of disk space.

.. tip::

    You can use Multipass to create an isolated environment by running:

    .. code-block::

        multipass launch 24.04 --name charm-tutorial-vm --cpus 4 --memory 8G --disk 50G


This tutorial requires the following software to be installed on your working station
(either locally or in the Multipass VM):

- Juju
- K8s

Use `Concierge <https://github.com/canonical/concierge>`_ to set up Juju and K8s:

.. code-block::

    sudo snap install --classic concierge
    sudo concierge prepare -p k8s

This first command installs Concierge, and the second command uses Concierge to install
and configure Juju and Kubernetes.

For this tutorial, Juju must be bootstrapped to a controller backed by K8s.
Concierge should complete this step for you, and you can verify it by running
``juju controllers``.

If Concierge did not perform the bootstrap, run:

.. code-block::

    juju bootstrap k8s tutorial-controller


To be able to work inside the Multipass VM, log in with the following command:

.. code-block:: bash

    multipass shell charm-tutorial-vm 

.. note::

    If you're working locally, you don't need to do this step.

.. SPREAD SKIP END

Set up the environment
----------------------

To manage resources effectively and to separate this tutorial's workload from
your usual work, create a new model in the K8s controller using the following command:

.. code-block:: bash

    juju add-model hrms-tutorial

Create the admin password secret
--------------------------------

The charm reads the initial Frappe HRMS administrator password from the
``admin-password-secret`` configuration option. Create the secret before deploying
the charm, and save the returned secret ID:

.. code-block:: bash

    SECRET_ID=$(juju add-secret hrms-admin password='ChangeMe123!')
    echo "$SECRET_ID"

The output is a Juju secret URI such as ``secret:9m4e2mr0ui3e8a215n4g``. You will
use it during deployment and then grant the application access to it.

Deploy the charm
----------------

Deploy the required backing services first, then deploy the Frappe HRMS charm:

.. code-block:: bash

    juju deploy mariadb-k8s --channel latest/edge --trust
    juju deploy redis-k8s --channel latest/edge --trust
    juju deploy self-signed-certificates --channel 1/stable --trust
    juju deploy gateway-api-integrator --channel 1/stable \
        --config gateway-class=cilium --trust
    juju deploy ingress-configurator --channel latest/edge \
        --config hostname=hrms.internal --trust
    juju deploy hrms --channel 16/edge --trust --config admin-password-secret=$SECRET_ID

Grant the charm access to the secret:

.. code-block:: bash

    juju grant-secret $SECRET_ID hrms

Deploy and integrate dependencies
---------------------------------

Now integrate the ingress components and then integrate Frappe HRMS with its
dependencies:

.. code-block:: bash

    juju integrate gateway-api-integrator:certificates self-signed-certificates:certificates
    juju integrate gateway-api-integrator:gateway-route ingress-configurator
    juju integrate hrms:database mariadb-k8s:database
    juju integrate hrms:redis redis-k8s:redis
    juju integrate hrms:ingress ingress-configurator:ingress

The first bootstrap can take several minutes while the charm creates the
``frappe-hrms`` site and installs the ``erpnext`` and ``hrms`` applications.


Run ``juju status`` to check the current status of the deployment.
The output should be similar to the following:

.. code-block:: text

    Model          Controller           Cloud/Region        Version  SLA          Timestamp
    hrms-tutorial  tutorial-controller  <k8s-cloud>/localhost  3.x      unsupported  10:00:00Z

    App                       Version  Status  Scale  Charm                    Channel      Rev  Address      Exposed  Message
    gateway-api-integrator             active      1  gateway-api-integrator   1/stable     XX  10.152.0.13  no
    hrms                               active      1  hrms                     16/edge      XX  10.152.0.10  no
    ingress-configurator               active      1  ingress-configurator     latest/edge  XX  10.152.0.14  no
    mariadb-k8s                        active      1  mariadb-k8s              latest/edge  XX  10.152.0.11  no
    redis-k8s                          active      1  redis-k8s                latest/edge  XX  10.152.0.12  no
    self-signed-certificates           active      1  self-signed-certificates 1/stable     XX  10.152.0.15  no

    Unit                         Workload  Agent  Address     Ports  Message
    gateway-api-integrator/0     active    idle   10.1.0.13
    hrms/0                       active    idle   10.1.0.10
    ingress-configurator/0       active    idle   10.1.0.14
    mariadb-k8s/0                active    idle   10.1.0.11
    redis-k8s/0                  active    idle   10.1.0.12
    self-signed-certificates/0   active    idle   10.1.0.15


Your revision numbers and IP addresses will differ, but the deployment is finished
when all applications show ``active``.

Verify ingress and open the login page
--------------------------------------

First, retrieve the proxied endpoint from ``ingress-configurator``:

.. code-block:: bash

    INGRESS_URL=$(juju run ingress-configurator/leader get-proxied-endpoints --format json | jq -r '.results.endpoints | fromjson | .[0]')
    echo "$INGRESS_URL"

Next, get the Gateway API address:

.. code-block:: bash

    GATEWAY_IP=$(juju status --format json | jq -r '.applications."gateway-api-integrator".units."gateway-api-integrator/0"."public-address"')

Verify that the ingress endpoint returns HTTP 200:

.. code-block:: bash

    curl -k --resolve "hrms.internal:443:$GATEWAY_IP" -o /dev/null -w '%{http_code}\n' "$INGRESS_URL"

The command should print:

.. code-block:: text

    200

Finally, open the ingress URL in your browser:

.. code-block:: text

    https://hrms.internal/

If your workstation does not already resolve ``hrms.internal``, add it to
``/etc/hosts`` first:

.. code-block:: bash

    echo "$GATEWAY_IP hrms.internal" | sudo tee -a /etc/hosts

Because this tutorial uses ``self-signed-certificates``, your browser may warn
that the certificate is not trusted. Accept the warning for this local test
environment and confirm that the Frappe HRMS login page loads.

If the deployment stays in a waiting or maintenance state for longer than expected,
inspect the charm logs with:

.. code-block:: bash

    juju debug-log --include unit-hrms-0 --level INFO --tail

Clean up the environment
------------------------

Congratulations! You deployed Frappe HRMS with its required 
dependencies and verified that the login page is reachable.

To remove the tutorial model, run:

.. code-block:: bash

    juju destroy-model hrms-tutorial --destroy-storage --no-prompt

You can clean up your environment by following this guide:
`Tear down your test environment <https://documentation.ubuntu.com/juju/3.6/howto/manage-your-juju-deployment/tear-down-your-juju-deployment-local-testing-and-development/>`_

Next steps
----------

You achieved a basic deployment of the charm. If you want to go farther,
continue with these resources:

- Learn more about the available :ref:`relation endpoints <reference_relation_endpoints>`.
- Review the upstream `Frappe HRMS documentation <https://docs.frappe.io/hr>`_.
