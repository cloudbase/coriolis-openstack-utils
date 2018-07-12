# Copyright 2018 Cloudbase Solutions Srl
# All Rights Reserved.

""" Module defining tenant and access-related actions. """

import copy
import time

from oslo_log import log as logging

from coriolis_openstack_utils import conf
from coriolis_openstack_utils import openstack_client
from coriolis_openstack_utils.actions import base
from coriolis_openstack_utils.actions import coriolis_transfer_actions
from coriolis_openstack_utils.actions import network_actions
from coriolis_openstack_utils.actions import secgroup_actions
from coriolis_openstack_utils.resource_utils import instances
from coriolis_openstack_utils.resource_utils import networks
from coriolis_openstack_utils.resource_utils import routers
from coriolis_openstack_utils.resource_utils import security_groups
from coriolis_openstack_utils.resource_utils import users

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
            "original": self.payload["tenant_name"]}

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
            if self.payload["tenant_name"] == (
                    other_action.payload.get("tenant_name")):
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
        original_tenant_name = self.payload["tenant_name"]
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

    def cleanup(self):
        for action in self.subactions:
            action.cleanup()

        self._destination_openstack_client.delete_project_by_name(
            self.get_new_tenant_name())


class UserCreationAction(base.BaseAction):
    """ Action for managing the creation of a user. """

    action_type = base.ACTION_TYPE_CHECK_CREATE_USER

    @property
    def user_name_format(self):
        return CONF.destination.new_user_name_format

    def get_source_user_name(self):
        return users.get_user(
            self._source_openstack_client, self.payload['src_user_id']).name

    def get_new_user_name(self):
        return self.user_name_format % {
            "original": self.get_source_user_name()}

    def print_operations(self):
        super(UserCreationAction, self).print_operations()
        user_name = self.get_new_user_name()
        LOG.info(
            "Create new destination user named '%s' "
            % user_name)

    def equivalent_to(self, other_action):
        if other_action.action_type == self.action_type:
            if self.payload["src_user_id"] == (
                    other_action.payload.get("src_user_id")):
                return True

        return False

    def check_already_done(self):
        user_name = self.get_new_user_name()

        for user in users.list_users(self._destination_openstack_client,
                                     filters={'name': user_name}):
            if user.name == user_name:
                LOG.debug("User with name '%s' already exists. Skipping." % (
                    user_name))
                return {"done": True, "result": user.id}
        return {"done": False, "result": None}

    def execute_operations(self):
        super(UserCreationAction, self).print_operations()
        user_name = self.get_new_user_name()

        done = self.check_already_done()
        if done["done"]:
            LOG.info(
                "User named '%s' already exists.",
                user_name)
            return done["result"]

        LOG.info("Creating destination user with name '%s'" % user_name)
        src_body = users.get_body(
            self._source_openstack_client, self.payload['src_user_id'])
        src_body['name'] = user_name
        user_id = users.create_user(
            self._destination_openstack_client, src_body)
        LOG.info("Created user with id '%s'" % user_id)
        dest_admin_tenants = self.payload.get('admin_role_tenants', False)
        if not dest_admin_tenants:
            # if there are no explicit admin roles set, setting the ones
            # that were on the source projects, but with
            # the new_project_name_format
            src_tenant_names = users.get_user_admin_tenants(
                self._source_openstack_client, self.payload['src_user_id'])
            dest_admin_tenants = [CONF.destination.new_tenant_name_format %
                                  {'original': tenant_name} for
                                  tenant_name in src_tenant_names]
        users.add_admin_roles(
            self._destination_openstack_client, user_name, dest_admin_tenants)

        return {'id': user_id,
                'name': user_name,
                'tenants': dest_admin_tenants}

    def cleanup(self):
        user_list = users.list_users(
            self._destination_openstack_client,
            filters={'name': self.get_new_user_name()})
        user_list_length = len(user_list)
        if user_list_length == 1:
            self._destination_openstack_client.keystone.users.delete(
                user_list[0].id)
            LOG.info("Successfully deleted user '%s' on destination"
                     % self.get_new_user_name())


class WholeTenantCreationAction(TenantCreationAction):
    """  Action for managing the migration of a tenant and all the resources
    within it.
        action_payload must contain:
            'tenant_name'
            'instances': None: no instances will be migrated.
                         ['vm1','vm2']: instances named 'vm1' and 'vm2'
                                         will be migrated.
                         []: all instances will be migrated.
    """
    def __init__(
            self, action_payload, source_openstack_client=None,
            coriolis_client=None, destination_openstack_client=None,
            destination_env=None):
        super(WholeTenantCreationAction, self).__init__(
            action_payload, source_openstack_client=source_openstack_client,
            coriolis_client=coriolis_client,
            destination_openstack_client=destination_openstack_client)
        self._migration_prep_subactions = []

    def print_operations(self):
        super(WholeTenantCreationAction, self).print_operations()
        LOG.info("Create new destination tenant named '%s' "
                 "alongside its security_groups, networks and routers."
                 % self.get_new_tenant_name())

    def execute_operations(self):
        dest_tenant_id = super(
            WholeTenantCreationAction, self).execute_operations()
        src_tenant_id = self._destination_openstack_client.get_project_id(
            self.payload['tenant_name'])

        src_tenant_networks = [
            network['id'] for network in
            networks.list_networks(self._source_openstack_client,
                                   src_tenant_id)]

        for net_id in src_tenant_networks:
            network_migration_action = network_actions.NetworkCreationAction(
                {'src_network_id': net_id, 'dest_tenant_id': dest_tenant_id},
                source_openstack_client=self._source_openstack_client,
                destination_openstack_client=self._destination_openstack_client
                )
            self.subactions.append(network_migration_action)
        src_tenant_routers = [
            router['id'] for router in routers.list_routers(
                self._source_openstack_client, filters={
                    'project_id': src_tenant_id, 'tenant_id': src_tenant_id})]

        for router_id in src_tenant_routers:
            router_migration_action = network_actions.RouterCreationAction(
                {'src_router_id': router_id,
                 'dest_tenant_id': dest_tenant_id},
                source_openstack_client=self._source_openstack_client,
                destination_openstack_client=self._destination_openstack_client
                )
            self.subactions.append(router_migration_action)

        src_secgroup_names = [
            secgroup['name'] for secgroup in
            security_groups.list_security_groups(
                self._source_openstack_client, src_tenant_id)]

        for secgroup_name in src_secgroup_names:
            secgroup_action = secgroup_actions.SecurityGroupCreationAction(
                {'src_tenant_id': src_tenant_id,
                 'dest_tenant_id': dest_tenant_id,
                 'source_name': secgroup_name},
                source_openstack_client=self._source_openstack_client,
                destination_openstack_client=self._destination_openstack_client
                )
            self.subactions.append(secgroup_action)
        # if payload['instances'] is None, no VMs are migrated.
        instance_list = []
        if self.payload['instances'] == []:
            instance_list = [instance for instance in instances.list_instances(
                self._source_openstack_client,
                filters={'tenant_id': src_tenant_id})]
        elif self.payload['instances'] is not None:
            instance_list = [
                instance for instance in instances.list_instances(
                    self._source_openstack_client,
                    filters={'tenant_id': src_tenant_id})
                if instance.name in self.payload['instances']]
            found_instances = [instance.name for instance in instance_list]
            not_found_instances = (set(self.payload['instances']) -
                                   set(found_instances))
            if not_found_instances != set():
                raise Exception(
                    "Instances not found from list %s" % not_found_instances)

        for instance in instance_list:
            src_secgroups = [secgroup['name'] for secgroup in
                             getattr(instance, 'security_groups', [])]
            dest_secgroups = [CONF.destination.new_secgroup_name_format %
                              {'original': secgroup_name} for
                              secgroup_name in src_secgroups]

            dest_net_map = {src_net: (
                CONF.destination.new_network_name_format %
                {'original': src_net}) for src_net in
                            instance.networks.keys()}

            dest_target_migr_env = {'network_map': dest_net_map,
                                    'security_groups': dest_secgroups}
            instance_migration_action = (
                coriolis_transfer_actions.MigrationCreationAction(
                    {'instance_name': instance.name,
                     'instance_tenant_name':
                     self.payload['tenant_name']},
                    source_openstack_client=self._source_openstack_client,
                    destination_openstack_client=(
                        self._destination_openstack_client),
                    destination_env=dest_target_migr_env,
                    coriolis_client=self._coriolis_client))
            self.subactions.append(instance_migration_action)

        for migration_action in self.subactions:
            new_migration_subactions = []
            for action in migration_action.subactions:
                action_done = action.check_already_done()
                if action_done["done"]:
                    LOG.info("Action already done: ")
                    action.print_operations()
                    continue

                if not [existing
                        for existing in self._migration_prep_subactions
                        if action.equivalent_to(existing)]:
                    new_migration_subactions.append(action)
                    self._migration_prep_subactions.append(action)
                else:
                    LOG.info("Skipping action: ")
                    action.print_operations()
            # NOTE: we eliminate the unneeded action:
            migration_action.subactions = new_migration_subactions

        for action in self._migration_prep_subactions:
            action.execute_operations()

        for action in self.subactions:
            action.execute_operations()

        return {'name': self.get_new_tenant_name(),
                'id': dest_tenant_id}

    def cleanup(self):
        for action in self.subactions:
            action.cleanup()
        self._destination_openstack_client.delete_project_by_name(
            self.get_new_tenant_name())
