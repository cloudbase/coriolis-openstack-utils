# Copyright 2018 Cloudbase Solutions Srl
# All Rights Reserved.

""" Module defining tenant and access-related actions. """

import copy
import time

from oslo_log import log as logging

from coriolis_openstack_utils import conf
from coriolis_openstack_utils import openstack_client
from coriolis_openstack_utils.actions import base

CONF = conf.CONF
LOG = logging.getLogger(__name__)


class TenantCreationAction(base.BaseAction):
    """ Action for managing the creation of a tenant. """

    action_type = base.ACTION_TYPE_CHECK_CREATE_TENANT
    NEW_PROJECT_DESCRIPTION = (
        "Created by the Coriolis OpenStack utilities for source tenant '%s'.")

    @property
    def tenant_name_format(self):
        return CONF.destination.new_tenant_name_format

    def get_new_tenant_name(self):
        return self.tenant_name_format % {
            "original": self.payload["instance_tenant_name"]}

    def _update_tenant_quotas(self):
        """ Updates all tenant quotas necessary for the migration.

        Updates quotas are:
            - neutron/security_group -- set to -1 (unlimited)
            - cinder/volumes -- set to -1 (unlimited)
            - nova/instances -- set to -1 (unlimited)
        """
        tenant_name = self.get_new_tenant_name()
        tenant_id = self._destination_openstack_client.get_project_id(
            tenant_name)

        # update Neutron quotas:
        neutron_quotas = CONF.destination.new_tenant_neutron_quotas
        updated_neutron_quotas = {
            k: int(neutron_quotas[k]) for k in neutron_quotas}
        LOG.info(
            "Adding Neutron quotas for tenant '%s': %s",
            tenant_name, updated_neutron_quotas)
        self._destination_openstack_client.neutron.update_quota(
            tenant_id, body={"quota": updated_neutron_quotas})

        # update Cinder quotas:
        cinder_quotas = CONF.destination.new_tenant_cinder_quotas
        updated_cinder_quotas = {
            k: int(cinder_quotas[k]) for k in cinder_quotas}
        LOG.info(
            "Adding Cinder quotas for tenant '%s': %s",
            tenant_name, updated_cinder_quotas)
        self._destination_openstack_client.cinder.quotas.update(
            tenant_id, **updated_cinder_quotas)

        # update Nova quotas:
        nova_quotas = CONF.destination.new_tenant_nova_quotas
        updated_nova_quotas = {
            k: int(nova_quotas[k]) for k in nova_quotas}
        LOG.info(
            "Adding Nova quotas for tenant '%s': %s",
            tenant_name, updated_nova_quotas)
        self._destination_openstack_client.nova.quotas.update(
            tenant_id, **updated_nova_quotas)

    def _allow_secgroup_traffic(self):
        tenant_name = self.get_new_tenant_name()
        tenant_id = self._destination_openstack_client.get_project_id(
            tenant_name)

        # NOTE: in order to see the new secgroup we must use the
        # right tenant name:
        new_connection_info = copy.deepcopy(
            self._destination_openstack_client.connection_info)
        new_connection_info["project_name"] = tenant_name
        new_client = openstack_client.OpenStackClient(new_connection_info)

        # NOTE: secgroup may not have been created yet, wait for it:
        LOG.info(
            "Waiting for tenant '%s' default security group creation.",
            tenant_name)
        while True:
            secgroups = new_client.neutron.list_security_groups()[
                "security_groups"]
            secgroups = [s for s in secgroups if s["tenant_id"] == tenant_id]
            if len(secgroups) > 1:
                raise Exception(
                    "Multiple 'default' secgroups found in destination tenant "
                    "'%s'. Please delete all but one, or rerun without the "
                    "tenant security group option." % tenant_name)

            if not secgroups:
                time.sleep(4)
            else:
                break

        # NOTE: the 'default' secgroup should always be there:
        secgroup = secgroups[0]
        generic_allow_rule = {
            "security_group_id": secgroup["id"],
            # NOTE: egress traffic is allowed by default:
            "direction": "ingress",
            # NOTE: intentionally not setting 'port_range_{min,max}'
            "remote_ip_prefix": "0.0.0.0/0"}

        protocols = CONF.destination.new_tenant_allowed_protocols
        for protocol in protocols:
            rule = copy.deepcopy(generic_allow_rule)
            rule["protocol"] = protocol

            LOG.info(
                "Adding rule to allow '%s' traffic in new tenant '%s'",
                protocol, tenant_name)
            new_client.neutron.create_security_group_rule({
                "security_group_rule": rule})

    def equivalent_to(self, other_action):
        if other_action.action_type == self.action_type:
            if self.payload["instance_tenant_name"] == (
                    other_action.payload.get("instance_tenant_name")):
                return True

        return False

    def print_operations(self):
        super(TenantCreationAction, self).print_operations()
        tenant_name = self.get_new_tenant_name()
        LOG.info(
            "Create new destination tenant named '%s' "
            "and set appropriate usage quotas. " % (
                tenant_name))

    def check_already_done(self):
        tenant_name = self.get_new_tenant_name()

        for tenant in self._destination_openstack_client.list_project_names():
            if tenant == tenant_name:
                LOG.debug("Tenant with name '%s' already exists. Skipping." % (
                    tenant_name))
                return {"done": True, "result": tenant_name}
        return {"done": False, "result": None}

    def execute_operations(self):
        super(TenantCreationAction, self).print_operations()
        original_tenant_name = self.payload["instance_tenant_name"]
        tenant_name = self.get_new_tenant_name()

        done = self.check_already_done()
        if done["done"]:
            LOG.info(
                "Tenant named '%s' already exists, updating quotas.",
                tenant_name)
            self._update_tenant_quotas()
            return done["result"]

        description = self.NEW_PROJECT_DESCRIPTION % original_tenant_name
        LOG.info("Creating destination tenant with name '%s'" % tenant_name)
        new_project_id = self._destination_openstack_client.create_project(
            tenant_name, description)

        LOG.info(
            "Waiting for creation of destination tenant '%s'.", tenant_name)
        # NOTE: depending on the destination OpenStack setup, the above tenant
        # might not be immediately visible, so we must wait for it:
        self._destination_openstack_client.wait_for_project_creation(
            tenant_name)

        # add user roles:
        LOG.info("Adding admin user(s) to new tenant '%s'", tenant_name)
        users = [self._destination_openstack_client.connection_info[
            "username"]]
        users.extend(
            CONF.destination.new_tenant_admin_users)
        for user in users:
            self._destination_openstack_client.add_admin_role_to_project(
                tenant_name, user,
                admin_role_name=CONF.destination.admin_role_name)

        # update quotas:
        self._update_tenant_quotas()

        # open default secgroup:
        if CONF.destination.new_tenant_open_default_secgroup:
            self._allow_secgroup_traffic()

        return new_project_id
