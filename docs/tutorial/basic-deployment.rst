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


To be able to work inside the Multipass VM, log in with the following command:

.. code-block:: bash

    multipass shell charm-tutorial-vm 

.. note::

    If you're working locally, you don't need to do this step.

This tutorial requires the following software to be installed on your working station
(either locally or in the Multipass VM):

* Juju 3.6+
* Canonical Kubernetes 1.32+

Use `Concierge <https://github.com/canonical/concierge>`_ to set up Juju,
and Canonical Kubernetes:

.. code-block:: shell

   VM_IP=$(hostname -I | awk '{print $1}')
   sudo snap install --classic concierge
   cat << EOF > concierge.yaml
   providers:
     k8s:
       enable: true
       bootstrap: true
       bootstrap-constraints:
         root-disk: "5G"
       features:
         load-balancer:
           l2-mode: "true"
           cidrs: "$VM_IP/28"
         local-storage: {}
         network: {}
         ingress:

   host:
     snaps:
       aws-cli:
   EOF
   sudo concierge prepare -c concierge.yaml

Once the command succeeds, you have a working environment with Juju, and
Kubernetes working. You can confirm this by running ``juju controllers``, which
should return the controller:

.. code-block:: text

   Controller      Model    User   Access     Cloud/Region         Models  Nodes    HA  Version
   concierge-k8s   testing  admin  superuser  k8s                       2      1     -  3.6.24

If Concierge did not perform the bootstrap, run:

.. code-block::

    juju bootstrap k8s tutorial-controller

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
the charm, and save the returned secret ID (For production use, replace the 
example password with a stronger value before creating the secret):

.. code-block:: bash

    SECRET_ID=$(juju add-secret hrms-admin password='ChangeMe123!')
    echo "$SECRET_ID"

The output is a Juju secret URI such as ``secret:9m4e2mr0ui3e8a215n4g``. You will
use it during deployment and then grant the application access to it.

Deploy the charm
----------------

Deploy the required backing services first, then deploy the Frappe HRMS charm:

.. code-block:: bash

    juju deploy mysql-k8s --channel latest/edge --trust
    juju deploy redis-k8s --channel latest/edge --trust
    juju deploy self-signed-certificates --channel 1/stable --trust
    juju deploy gateway-api-integrator --channel 1/stable \
        --config gateway-class=cilium --trust
    juju deploy ingress-configurator --channel latest/stable \
        --config hostname=hrms.internal --trust
    juju deploy hrms --channel 16/edge --trust --config admin-password-secret=$SECRET_ID

MySQL provides the database, Redis provides caching, and the Gateway API
components expose the application via an external HTTPS endpoint. MySQL and
Redis are mandatory dependencies for successful deployment of HRMS, while the
Gateway API components are optional but recommended for production deployments.

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
    juju integrate hrms:database mysql-k8s:database
    juju integrate hrms:redis redis-k8s:redis
    juju integrate hrms:ingress ingress-configurator:ingress

The first bootstrap can take several minutes while the charm creates the
``frappe-hrms`` site and installs the ``erpnext`` and ``hrms`` applications.


Run ``juju status`` to check the current status of the deployment.
The output should be similar to the following:

.. code-block:: text

    Model          Controller     Cloud/Region  Version  SLA          Timestamp
    hrms-tutorial  concierge-k8s  k8s           3.6.25   unsupported  16:12:49Z

    App                       Version  Status  Scale  Charm                     Channel        Rev  Address         Exposed  Message
    gateway-api-integrator             active      1  gateway-api-integrator    1/stable       165  10.152.183.112  no       Gateway addresses: 10.114.45.113
    hrms                               active      1  hrms                      16/edge          3  10.152.183.163  no       
    ingress-configurator               active      1  ingress-configurator      latest/stable   95  10.152.183.201  no       Ready
    mysql-k8s                        active      1  mysql-k8s               latest/edge      8  10.152.183.24   no       Ready - serving 1 database(s)
    redis-k8s                 7.2.5    active      1  redis-k8s                 latest/edge     42  10.152.183.227  no       
    self-signed-certificates           active      1  self-signed-certificates  1/stable       586  10.152.183.101  no       

    Unit                         Workload  Agent  Address     Ports  Message
    gateway-api-integrator/0*    active    idle   10.1.0.117         Gateway addresses: 10.114.45.113
    hrms/0*                      active    idle   10.1.0.170         
    ingress-configurator/0*      active    idle   10.1.0.183         Ready
    mysql-k8s/0*               active    idle   10.1.0.44          Ready - serving 1 database(s)
    redis-k8s/0*                 active    idle   10.1.0.96          
    self-signed-certificates/0*  active    idle   10.1.0.91 


Your revision numbers and IP addresses will differ, but the deployment is finished
when all applications show ``active``.

Verify ingress and open the login page
--------------------------------------

Get the Gateway API address:

.. code-block:: bash

   GATEWAY_IP=$(juju status --format json | jq -r '.applications."gateway-api-integrator"."application-status".message | capture("Gateway addresses: (?<ip>[0-9.]+)").ip')
   echo "$GATEWAY_IP"

Verify that the ingress endpoint returns HTTP 200:

.. code-block:: bash

    curl -k --resolve "hrms.internal:443:$GATEWAY_IP" -o /dev/null -w '%{http_code}\n' https://hrms.internal/

The command should print:

.. code-block:: text

    200

To view the website, add ``hrms.internal`` to ``/etc/hosts``:

.. code-block:: bash

    echo "$GATEWAY_IP hrms.internal" | sudo tee -a /etc/hosts

.. note::

    If you are using Multipass, add this entry to the host machine's
    ``/etc/hosts`` file, not the VM's ``/etc/hosts`` file.

Finally, open the ingress URL in your browser:

.. code-block:: text

    https://hrms.internal/

Because this tutorial uses ``self-signed-certificates``, your browser may warn
that the certificate is not trusted. Accept the warning for this local test
environment and confirm that the Frappe HRMS login page loads.

Clean up the environment
------------------------

Congratulations! You deployed Frappe HRMS with its required 
dependencies and verified that the login page is reachable.

To remove the tutorial model, run:

.. code-block:: bash

    juju destroy-model hrms-tutorial --destroy-storage

After you finish the tutorial, remove the ``hrms.internal`` entry from
``/etc/hosts`` if you added one.

.. code-block:: bash

    sudo sed -i '/hrms\.internal/d' /etc/hosts

You can clean up your environment by following this guide:
`Tear down your test environment <https://documentation.ubuntu.com/juju/3.6/howto/manage-your-juju-deployment/tear-down-your-juju-deployment-local-testing-and-development/>`_

Next steps
----------

You achieved a basic deployment of the charm. If you want to go farther,
continue with these resources:

- Learn more about the available :ref:`relation endpoints <reference_relation_endpoints>`.
- Review the upstream `Frappe HRMS documentation <https://docs.frappe.io/hr>`_.
