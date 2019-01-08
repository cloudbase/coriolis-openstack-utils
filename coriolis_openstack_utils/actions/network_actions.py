# Copyright 2018 Cloudbase Solutions Srl
# All Rights Reserved.

""" Module defining OpenStack security-group-related actions. """

from oslo_log import log as logging

from coriolis_openstack_utils import conf
from coriolis_openstack_utils.actions import base
from coriolis_openstack_utils.resource_utils import networks, subnets, routers

CONF = conf.CONF
LOG = logging.getLogger(__name__)


class SubnetCreationAction(base.BaseAction):
    """ Action class for replicating subnets into existing networks.
    param action_payload: dict(): payload (params) for the action
    must contain 'src_network_id',
                 'dest_network_id',
                 'source_name'
    """

    action_type = base.ACTION_TYPE_CHECK_CREATE_SUBNET
    NEW_SUBNET_DESCRIPTION = (
        "Created by the Coriolis OpenStack utilities for source subnet '%s'.")

    @property
    def subnet_name_format(self):
        return CONF.destination.new_subnet_name_format

    def check_already_done(self):
        src_tenant_id = self.get_source_tenant_id()
        src_subnet_name = self.payload['source_name']

        dest_network_id = self.payload['dest_network_id']
        dest_subnet_name = self.get_new_subnet_name()

        conflicting = subnets.list_subnets(
            self._destination_openstack_client,
            filters={'network_id': dest_network_id, 'name': dest_subnet_name})

        src_subnet = subnets.get_body(
            self._source_openstack_client, src_tenant_id, src_subnet_name)

        for subnet in conflicting:
            if subnets.check_subnet_similarity(subnet, src_subnet):
                LOG.info("Found destination subnet '%s' with same information "
                         "as source subnet '%s'."
                         % (dest_subnet_name, src_subnet_name))
                return {"done": True, "result": subnet['id']}

        if len(conflicting) == 1:
            raise Exception("Found destination subnet with "
                            "with name '%s' but different attributes!"
                            % dest_subnet_name)
        elif conflicting:
            raise Exception("Found multiple destination subnets with "
                            "with name '%s'! Aborting subnet "
                            "migration." % dest_subnet_name)

        return {"done": False, "result": None}

    def equivalent_to(self, other_action):
        if other_action.action_type == self.action_type:
            if self.payload['source_name'] == (
                    other_action.payload.get('source_name')):

                src_network_id = self.payload['src_network_id']
                src_other_network_id = (
                    other_action.payload.get('src_network_id'))

                if src_network_id == src_other_network_id:
                    dest_network_id = self.payload['dest_network_id']
                    dest_other_network_id = other_action.payload.get(
                        'dest_network_id')

                    return dest_network_id == dest_other_network_id
        return False

    def print_operations(self):
        super(SubnetCreationAction, self).print_operations()
        subnet_name = self.get_new_subnet_name()
        LOG.info(
            "Create new destination subnet named '%s'." % subnet_name)

    def get_new_subnet_name(self):
        return self.subnet_name_format % {
            "original": self.payload["source_name"]}

    def get_source_tenant_id(self):
        src_subnet_list = subnets.list_subnets(
            self._source_openstack_client,
            filters={'network_id': self.payload['src_network_id'],
                     'name': self.payload['source_name']})

        if not src_subnet_list:
            raise Exception("Source Subnet '%s' in network '%s' not found!"
                            % (self.payload['source_name'],
                               self.payload['src_network_id']))

        src_subnet = src_subnet_list[0]

        return (src_subnet.get('tenant_id') or
                src_subnet.get('project_id'))

    def get_destination_tenant_id(self):
        dest_network = networks.get_network(
            self._destination_openstack_client,
            self.payload['dest_network_id'])

        return (dest_network.get('tenant_id') or
                dest_network.get('project_id'))

    def create_subnet_body(self, description):
        src_subnet_name = self.payload['source_name']
        src_tenant_id = self.get_source_tenant_id()
        dest_tenant_id = self.get_destination_tenant_id()
        dest_subnet_name = self.get_new_subnet_name()
        dest_network_id = self.payload['dest_network_id']
        src_body = subnets.get_body(
            self._source_openstack_client, src_tenant_id, src_subnet_name)
        body = {'name': dest_subnet_name,
                'tenant_id': dest_tenant_id,
                'project_id': dest_tenant_id,
                'description': description,
                'network_id': dest_network_id}

        for k in src_body:
            if k not in body:
                body[k] = src_body[k]

        return body

    def execute_operations(self):
        super(SubnetCreationAction, self).print_operations()
        dest_subnet_name = self.get_new_subnet_name()
        dest_network_id = self.payload['dest_network_id']
        done = self.check_already_done()
        if done["done"]:
            LOG.info(
                "Subnet named '%s' already exists.",
                dest_subnet_name)
            return done["result"]

        LOG.info("Creating destination Subnet with name '%s'" %
                 dest_subnet_name)
        description = (self.NEW_SUBNET_DESCRIPTION %
                       self.payload['source_name'])
        body = self.create_subnet_body(description)
        dest_subnet_id = subnets.create_subnet(
            self._destination_openstack_client, body)
        dest_network_name = networks.get_network(
            self._destination_openstack_client, dest_network_id)['name']
        dest_subnet = {
            'destination_name': dest_subnet_name,
            'destination_id': dest_subnet_id,
            'dest_network_id': dest_network_id,
            'dest_network_name': dest_network_name}

        return dest_subnet

    def cleanup(self):
        subnets.delete_subnet(
            self._destination_openstack_client,
            self.payload['dest_network_id'], self.get_new_subnet_name())


class NetworkCreationAction(base.BaseAction):
    """ Action class for replicating Neutron networks.
    param action_payload: dict(): payload (params) for the action
    must contain 'src_network_id'
                 'dest_tenant_id'
    """
    action_type = base.ACTION_TYPE_CHECK_CREATE_NETWORK
    NEW_NETWORK_DESCRIPTION = (
        "Created by the Coriolis OpenStack utilities for source network '%s'.")

    @property
    def network_name_format(self):
        return CONF.destination.new_network_name_format

    def check_already_done(self):
        src_network = networks.get_network(
            self._source_openstack_client, self.payload['src_network_id'])

        dest_network_name = self.get_new_network_name()
        conflicting = networks.list_networks(
            self._destination_openstack_client, self.payload['dest_tenant_id'],
            filters={'name': dest_network_name})

        for dest_network in conflicting:
            if networks.check_network_similarity(
                    src_network, dest_network,
                    self._source_openstack_client,
                    self._destination_openstack_client):
                LOG.info("Found destination network '%s' with same "
                         "information and subnets as source network '%s'."
                         % (dest_network_name, src_network['name']))
                return {"done": True, "result": dest_network['id']}

        if len(conflicting) == 1:
            raise Exception("Found destination network with "
                            "with name '%s' but different attributes!"
                            % dest_network_name)
        elif conflicting:
            raise Exception("Found multiple destination networks with "
                            "with name '%s'! Aborting subnet "
                            "migration." % dest_network_name)

        return {"done": False, "result": None}

    def equivalent_to(self, other_action):
        if other_action.action_type == self.action_type:
            if (self.payload['src_network_id'] == (
                    other_action.payload.get('src_network_id'))):
                if (self.payload.get('dest_tenant_id') == (
                        other_action.payload.get('dest_tenant_id'))):
                    return True
        return False

    def print_operations(self):
        super(NetworkCreationAction, self).print_operations()
        network_name = self.get_new_network_name()
        LOG.info(
            "Create new destination network named '%s'." % network_name)

    def get_source_network_name(self):
        return networks.get_network(
            self._source_openstack_client,
            self.payload['src_network_id'])['name']

    def get_new_network_name(self):
        return self.network_name_format % {
            "original": self.get_source_network_name()}

    def execute_operations(self):
        super(NetworkCreationAction, self).print_operations()
        done = self.check_already_done()
        dest_network_name = self.get_new_network_name()
        if done["done"]:
            LOG.info(
                "Network named '%s' already exists.",
                dest_network_name)
            return done["result"]

        LOG.info("Creating destination Network with name '%s'" %
                 dest_network_name)

        description = (
            self.NEW_NETWORK_DESCRIPTION % self.get_source_network_name())

        body = networks.create_network_body(
            self._source_openstack_client, self.payload['src_network_id'],
            self.payload['dest_tenant_id'],
            self.get_new_network_name(), description)

        dest_network_id = networks.create_network(
            self._destination_openstack_client, body)

        src_subnet_ids = networks.get_network(
            self._source_openstack_client,
            self.payload['src_network_id'])['subnets']

        src_subnet_names = [
            subnets.get_subnet(
                self._source_openstack_client, subnet_id)['name']
            for subnet_id in src_subnet_ids]

        for name in src_subnet_names:
            subnet_migration_payload = {
                'source_name': name,
                'src_network_id': self.payload['src_network_id'],
                'dest_network_id': dest_network_id}
            subnet_migration_action = SubnetCreationAction(
                subnet_migration_payload,
                source_openstack_client=self._source_openstack_client,
                destination_openstack_client=(
                    self._destination_openstack_client))
            self.subactions.append(subnet_migration_action)
            subnet_migration_action.execute_operations()

        dest_network = {
            'destination_name': dest_network_name,
            'destination_id': dest_network_id,
            'dest_tenant_name':
                self._destination_openstack_client.connection_info[
                    'project_name'],
            'dest_tenant_id': self.payload['dest_tenant_id']}

        return dest_network

    def cleanup(self):
        networks.delete_network(
            self._destination_openstack_client,
            self.payload['dest_tenant_id'], self.get_new_network_name())


class RouterCreationAction(base.BaseAction):
    """ Action class for replicating Neutron routers.
    param action_payload: dict(): payload (params) for the action
    must contain 'src_router_id'
                 'dest_tenant_id'
                 'copy_routes' (default: False)
    """

    action_type = base.ACTION_TYPE_CHECK_CREATE_ROUTER
    NEW_ROUTER_DESCRIPTION_FORMAT = (
        "Created by the Coriolis OpenStack utilities for source router '%s'.")

    def check_already_done(self):
        src_router = routers.get_router(
            self._source_openstack_client, self.payload['src_router_id'])
        dest_router_name = self.get_new_router_name()
        conflicting = routers.list_routers(
            self._destination_openstack_client, {'name': dest_router_name})
        for dest_router in conflicting:
            if routers.check_router_similarity(
                    self._source_openstack_client, src_router,
                    self._destination_openstack_client, dest_router):

                LOG.info("Found destination router '%s' with same "
                         "information as source router '%s'."
                         % (dest_router_name, src_router['name']))
                return {"done": True, "result": dest_router['id']}

        if len(conflicting) == 1:
            raise Exception("Found destination router with "
                            "with name '%s' but different attributes!"
                            % dest_router_name)
        elif conflicting:
            raise Exception("Found multiple destination networks with "
                            "with name '%s'! Aborting router "
                            "migration." % dest_router_name)

        return {"done": False, "result": None}

    def equivalent_to(self, other_action):
        if other_action.action_type == self.action_type:
            if self.payload['src_router_id'] == (
                    other_action.payload.get('src_router_id')):
                return True
        return False

    def print_operations(self):
        super(RouterCreationAction, self).print_operations()
        router_name = self.get_new_router_name()
        LOG.info(
            "Create new destination router named '%s'." % router_name)

    def get_source_router_name(self):
        return routers.get_router(
            self._source_openstack_client,
            self.payload['src_router_id'])['name']

    def get_new_router_name(self):
        return CONF.destination.new_router_name_format % {
            "original": self.get_source_router_name()}

    def execute_operations(self):
        super(RouterCreationAction, self).print_operations()
        done = self.check_already_done()
        dest_router_name = self.get_new_router_name()
        if done["done"]:
            LOG.info(
                "Router named '%s' already exists.",
                dest_router_name)
            return done["result"]

        LOG.info("Creating destination Router with name '%s'" %
                 dest_router_name)

        migr_info = routers.get_migration_info(
            self._source_openstack_client, self.payload['src_router_id'])
        description = (
            self.NEW_ROUTER_DESCRIPTION_FORMAT % self.get_source_router_name())

        migr_info['migration_body']['description'] = description
        migr_info['migration_body']['project_id'] = self.payload[
            'dest_tenant_id']
        migr_info['migration_body']['tenant_id'] = self.payload[
            'dest_tenant_id']
        router_id = routers.create_router(
            self._destination_openstack_client, migr_info)

        if self.payload.get('copy_routes') or CONF.destination.copy_routes:
            src_routes = routers.get_source_routes(
                self._source_openstack_client, self.payload['src_router_id'])
            LOG.info(
                "Adding routes '%s' to router '%s'" % (src_routes, router_id))
            routers.add_routes_to_dest(
                self._destination_openstack_client, src_routes, router_id)

        router = routers.get_router(
            self._destination_openstack_client, router_id)

        return router

    def cleanup(self):
        routers.delete_router(
            self._destination_openstack_client, self.get_new_router_name())
