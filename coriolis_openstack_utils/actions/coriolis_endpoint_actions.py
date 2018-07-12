# Copyright 2018 Cloudbase Solutions Srl
# All Rights Reserved.

""" Module defining Coriolis Endpoint-related actions. """

import copy

from oslo_log import log as logging

from coriolis_openstack_utils import conf
from coriolis_openstack_utils import utils
from coriolis_openstack_utils.actions import base

CONF = conf.CONF
LOG = logging.getLogger(__name__)

ENDPOINT_TYPE_SOURCE = "source"
ENDPOINT_TYPE_DESTINATION = "destination"

ENDPOINT_TYPE_OPENSTACK = "openstack"
DEFAULT_REGION_NAME = "NoRegion"
DEFAULT_ENDPOINT_DESCRIPTION = "Created by the Coriolis OpenStack utils."


class SourceEndpointCreationAction(base.BaseAction):
    """
    NOTE: should be instantiated with the OpenStackClient for source/dest.
    """
    SOURCE_TENANT_NAME_FORMAT = "%(original)s"

    action_type = base.ACTION_TYPE_CHECK_CREATE_SOURCE_ENDPOINT

    @property
    def endpoint_type(self):
        return ENDPOINT_TYPE_SOURCE

    @property
    def tenant_name_format(self):
        return self.SOURCE_TENANT_NAME_FORMAT

    @property
    def endpoint_name_format(self):
        return CONF.source.endpoint_name_format

    @property
    def connection_info(self):
        return self._source_openstack_client.connection_info

    def get_tenant_name(self):
        return self.tenant_name_format % {
            "original": self.payload["instance_tenant_name"]}

    def get_endpoint_name(self):
        connection_info = self.connection_info
        return self.endpoint_name_format % {
            "region": connection_info.get(
                "region_name", DEFAULT_REGION_NAME),
            "tenant": self.get_tenant_name(),
            "user": connection_info["username"]}

    def equivalent_to(self, other_action):
        if other_action.action_type == self.action_type:
            # NOTE: we only really need to check the tenant name, as
            # connection info should be the same, and the same action
            # type scoping won't lead to source endpoints overriding
            # destination endpoints or vice-versa.
            if (self.payload["instance_tenant_name"] ==
                    other_action.payload["instance_tenant_name"]):
                return True

        return False

    def print_operations(self):
        super(SourceEndpointCreationAction, self).print_operations()
        tenant_name = self.get_tenant_name()
        connection_info = self.connection_info
        host_auth_url = connection_info["auth_url"]
        endpoint_name = self.get_endpoint_name()

        LOG.info(
            "Create %s endpoint named '%s' for tenant '%s' with "
            "connection info for host '%s'." % (
                self.endpoint_type, endpoint_name,
                tenant_name, host_auth_url))

    def check_already_done(self):
        super(SourceEndpointCreationAction, self).execute_operations()
        connection_info = copy.deepcopy(self.connection_info)
        # override the con info with the right one:
        tenant_name = self.get_tenant_name()
        connection_info["project_name"] = tenant_name

        endpoint_name = self.get_endpoint_name()
        existing_endpoint = None
        done = {"done": False, "result": None}
        endpoint_name = None
        for endpoint in self._coriolis_client.endpoints.list():
            existing_connection_info = endpoint.connection_info.to_dict()
            conn_infos_equal = utils.check_dict_equals(
                connection_info, existing_connection_info)
            if endpoint.name == endpoint_name:
                if not conn_infos_equal:
                    raise Exception(
                        "Found existing %s endpoint named '%s' (ID '%s') with "
                        "conn info '%s' (expecting conn info '%s')" % (
                            self.endpoint_type, endpoint_name, endpoint.id,
                            existing_connection_info, connection_info))

                LOG.debug("Found existing %s endpoint named '%s'",
                          self.endpoint_type, endpoint_name)
                existing_endpoint = endpoint
                break
            elif conn_infos_equal:
                LOG.debug(
                    "Found existing %s endpoint with conn info '%s': ID '%s'",
                    self.endpoint_type, connection_info, endpoint.id)
                existing_endpoint = endpoint
                break

        if existing_endpoint:
            done = {"done": True, "result": existing_endpoint.id}

        return done

    def execute_operations(self):
        done = self.check_already_done()
        if done["done"]:
            return done["result"]

        connection_info = copy.deepcopy(self.connection_info)
        tenant_name = self.get_tenant_name()
        connection_info["project_name"] = tenant_name

        endpoint_name = self.get_endpoint_name()

        LOG.info("Creating new endpoint named '%s'", endpoint_name)
        endpoint = self._coriolis_client.endpoints.create(
            endpoint_name, ENDPOINT_TYPE_OPENSTACK,
            connection_info, DEFAULT_ENDPOINT_DESCRIPTION)

        return endpoint.id

    def cleanup(self):
        endpoint_name = self.get_endpoint_name()

        connection_info = copy.deepcopy(self.connection_info)
        similar_endpoints = []
        for endpoint in self._coriolis_client.endpoints.list():
            existing_connection_info = endpoint.connection_info.to_dict()
            conn_infos_equal = utils.check_dict_equals(
                connection_info, existing_connection_info)
            if endpoint.name == endpoint_name:
                if conn_infos_equal:
                    similar_endpoints.append(endpoint.id)

        endpoints_length = len(similar_endpoints)
        if not similar_endpoints:
            LOG.info("Cannot delete endpoint '%s' with connection_info '%s',"
                     "not found.")
        if endpoints_length == 1:
            self._coriolis_client.endpoints.delete(similar_endpoints[0].id)
        elif endpoints_length > 1:
            LOG.warn("Multiple endpoints with name '%s' and "
                     "connection_info '%s' found, skipping deletion."
                     % (endpoint_name, connection_info))


class DestinationEndpointCreationAction(SourceEndpointCreationAction):

    action_type = base.ACTION_TYPE_CHECK_CREATE_DESTINATION_ENDPOINT

    @property
    def endpoint_type(self):
        return ENDPOINT_TYPE_DESTINATION

    @property
    def tenant_name_format(self):
        return CONF.destination.new_tenant_name_format

    @property
    def endpoint_name_format(self):
        return CONF.destination.endpoint_name_format

    @property
    def connection_info(self):
        return self._destination_openstack_client.connection_info
