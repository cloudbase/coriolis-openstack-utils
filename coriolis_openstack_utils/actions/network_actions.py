# Copyright 2018 Cloudbase Solutions Srl
# All Rights Reserved.

""" Module defining OpenStack security-group-related actions. """

from oslo_log import log as logging

from coriolis_openstack_utils import conf
from coriolis_openstack_utils.actions import base
from coriolis_openstack_utils.resource_utils import networks, subnets

CONF = conf.CONF
LOG = logging.getLogger(__name__)


class SubnetCreationAction(base.BaseAction):
    action_type = base.ACTION_TYPE_CHECK_CREATE_SUBNET
    NEW_SUBNET_DESCRIPTION = (
        "Created by the Coriolis OpenStack utilities for source subnet '%s'.")

    def __init__(self, source_client, destination_client, action_payload):
        """
        param action_payload: dict(): payload (params) for the action
        must contain 'src_network_id',
                     'dest_network_id',
                     'source_name'
        """
        # NOTE no openstack_client or coriolis_client

        super(SubnetCreationAction, self).__init__(
            None, None, action_payload)
        self._source_client = source_client
        self._destination_client = destination_client

    @property
    def subnet_name_format(self):
        return CONF.destination.new_subnet_name_format

    def check_already_done(self):
        src_tenant_id = self.get_source_tenant_id()
        src_subnet_name = self.payload['source_name']

        dest_network_id = self.payload['dest_network_id']
        dest_subnet_name = self.get_new_subnet_name()

        conflicting = subnets.list_subnets(
            self._destination_client, dest_network_id, dest_subnet_name)

        src_subnet = subnets.get_body(
            self._source_client, src_tenant_id, src_subnet_name)

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
            self._source_client, self.payload['src_network_id'],
            self.payload['source_name'])

        if not src_subnet_list:
            raise Exception("Source Subnet '%s' in network '%s' not found!"
                            % (self.payload['source_name'],
                               self.payload['src_network_id']))

        src_subnet = src_subnet_list[0]

        return (src_subnet.get('tenant_id') or
                src_subnet.get('project_id'))

    def get_destination_tenant_id(self):
        dest_network = networks.get_network(
            self._destination_client, self.payload['dest_network_id'])

        return (dest_network.get('tenant_id') or
                dest_network.get('project_id'))

    def create_subnet_body(self, description):
        src_subnet_name = self.payload['source_name']
        src_tenant_id = self.get_source_tenant_id()
        dest_tenant_id = self.get_destination_tenant_id()
        dest_subnet_name = self.get_new_subnet_name()
        dest_network_id = self.payload['dest_network_id']
        src_body = subnets.get_body(
            self._source_client, src_tenant_id, src_subnet_name)
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
            self._destination_client, body)
        dest_network_name = networks.get_network(
            self._destination_client, dest_network_id)['name']
        dest_subnet = {
            'destination_name': dest_subnet_name,
            'destination_id': dest_subnet_id,
            'dest_network_id': dest_network_id,
            'dest_network_name': dest_network_name}

        return dest_subnet


class NetworkCreationAction(base.BaseAction):
    action_type = base.ACTION_TYPE_CHECK_CREATE_NETWORK
    NEW_NETWORK_DESCRIPTION = (
        "Created by the Coriolis OpenStack utilities for source network '%s'.")

    def __init__(self, source_client, destination_client, action_payload):
        """
        param action_payload: dict(): payload (params) for the action
        must contain 'src_network_id'
                     'dest_tenant_id'
        """
        # NOTE no openstack_client or coriolis_client

        super(NetworkCreationAction, self).__init__(
            None, None, action_payload)
        self._source_client = source_client
        self._destination_client = destination_client

    @property
    def network_name_format(self):
        return CONF.destination.new_network_name_format

    def check_already_done(self):
        src_network = networks.get_network(
            self._source_client, self.payload['src_network_id'])

        dest_network_name = self.get_new_network_name()
        conflicting = networks.list_networks(
            self._destination_client, self.payload['dest_tenant_id'],
            filters={'name': dest_network_name})

        for dest_network in conflicting:
            if networks.check_network_similarity(
                    src_network, dest_network,
                    self._source_client, self._destination_client):
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
            if (self.payload['src_network_id']
                    == other_action.payload.get('src_network_id')):
                if (self.payload.get('dest_tenant_id')
                        == other_action.payload.get('dest_tenant_id')):
                    return True
        return False

    def print_operations(self):
        super(NetworkCreationAction, self).print_operations()
        network_name = self.get_new_network_name()
        LOG.info(
            "Create new destination network named '%s'." % network_name)

    def get_source_network_name(self):
        return networks.get_network(
            self._source_client, self.payload['src_network_id'])['name']

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
            self._source_client, self.payload['src_network_id'],
            self.payload['dest_tenant_id'], self.get_new_network_name(),
            description)

        dest_network_id = networks.create_network(
            self._destination_client, body)

        src_subnet_ids = networks.get_network(
            self._source_client, self.payload['src_network_id'])['subnets']

        src_subnet_names = [
            subnets.get_subnet(self._source_client, subnet_id)['name']
            for subnet_id in src_subnet_ids]

        for name in src_subnet_names:
            subnet_migration_payload = {
                'source_name': name,
                'src_network_id': self.payload['src_network_id'],
                'dest_network_id': dest_network_id}
            subnet_migration_action = SubnetCreationAction(
                self._source_client, self._destination_client,
                subnet_migration_payload)
            self.subactions.append(subnet_migration_action)
            subnet_migration_action.execute_operations()

        dest_network = {
            'destination_name': dest_network_name,
            'destination_id': dest_network_id,
            'dest_tenant_name':
                self._destination_client.connection_info['project_name'],
            'dest_tenant_id': self.payload['dest_tenant_id']}

        return dest_network
