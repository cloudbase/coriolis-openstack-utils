# Copyright 2018 Cloudbase Solutions Srl
# All Rights Reserved.

""" Module defining OpenStack flavor related actions. """

from oslo_log import log as logging

from coriolis_openstack_utils import conf
from coriolis_openstack_utils.actions import base

import novaclient.exceptions
import keystoneauth1.exceptions.http

CONF = conf.CONF
LOG = logging.getLogger(__name__)


class FlavorCreationAction(base.BaseAction):
    """ Action for creating flavors on the destination.
    param action_payload: dict(): payload (params) for the action
    must contain 'src_flavor_id'
    """

    action_type = base.ACTION_TYPE_CHECK_CREATE_FLAVOR
    NEW_FLAVOR_DESCRIPTION = (
        "Created by the Coriolis OpenStack utilities for source flavor"
        " '%s'.")

    @property
    def flavor_name_format(self):
        return CONF.destination.new_flavor_name_format

    def check_same_flavor(self, src_flavor, dest_flavor):
        relevant_keys = ['ram', 'disk', 'vcpus', 'rxtx_factor']
        dest_flavor_info = {k: v for k, v in dest_flavor.items()
                            if k in relevant_keys}
        src_flavor_info = {k: v for k, v in src_flavor.items()
                           if k in relevant_keys}

        if (src_flavor_info == dest_flavor_info and
                dest_flavor['name'] == self.get_new_flavor_name()):
            return True

        return False

    def check_already_done(self):
        dest_flavor_name = self.get_new_flavor_name()

        src_flavor_id = self.payload['src_flavor_id']
        src_flavor = self._source_openstack_client.nova.flavors.get(
            src_flavor_id)

        dest_flavor_name = self.get_new_flavor_name()
        dest_flavor = None
        try:
            dest_flavor = self._destination_openstack_client.nova.flavors.find(
                name=dest_flavor_name, is_public=None)
            if self.check_same_flavor(src_flavor.to_dict(),
                                      dest_flavor.to_dict()):
                return {"done": True, "result": dest_flavor.to_dict()}
            else:
                raise Exception("Found destination flavor named \"%s\", but "
                                "with different properties than source flavor "
                                "\"%s\" !" %
                                (dest_flavor_name, src_flavor_id))

        except novaclient.exceptions.NotFound:
            return {"done": False, "result": None}

    def equivalent_to(self, other_action):
        if other_action.action_type == self.action_type:
            if self.payload['src_flavor_id'] == (
                    other_action.payload.get('src_flavor_id')):
                return True
        return False

    def print_operations(self):
        super(FlavorCreationAction, self).print_operations()
        dest_flavor_name = self.get_new_flavor_name()
        LOG.info(
            "Create new destination flavor named \"%s\" with sources' "
            "properties." % (dest_flavor_name))

    def get_new_flavor_name(self):
        return self.flavor_name_format % {
            "original": self._source_openstack_client.nova.flavors.get(
                self.payload['src_flavor_id']).name}

    def create_flavor_body(self):
        src_flavor = self._source_openstack_client.nova.flavors.get(
            self.payload['src_flavor_id'])
        relevant_keys = ['ram', 'disk', 'vcpus', 'swap', 'rxtx_factor']
        src_flavor_info = src_flavor.to_dict()
        body = {k: v for k, v in src_flavor_info.items()
                if k in relevant_keys}
        dest_nova = self._destination_openstack_client.nova

        if float(dest_nova.api_version.get_string()) >= 2.55:
            body['description'] = (self.NEW_FLAVOR_DESCRIPTION %
                                   self.payload['src_flavor_id'])

        body['ephemeral'] = src_flavor_info.get('OS-FLV-EXT-DATA:ephemeral')
        body['is_public'] = src_flavor_info.get('os-flavor-access:is_public')
        if body['swap'] != '':
            body['swap'] = int(body['swap'])
        else:
            body.pop('swap', None)

        body['name'] = self.get_new_flavor_name()
        return body

    def add_tenant_access_to_flavor(self, dest_flavor_id):
        access_list = self._source_openstack_client.nova.flavor_access.list(
            flavor=self.payload['src_flavor_id'])
        src_tenant_ids = [access.tenant_id for access in access_list]
        src_tenant_names = []
        for tenant_id in src_tenant_ids:
            try:
                tenant_name = self._source_openstack_client.get_project_name(
                    tenant_id)
                src_tenant_names.append(tenant_name)
            except keystoneauth1.exceptions.http.Forbidden:
                LOG.warn("Cannot fetch source tenant \"%s\"'s name for "
                         "destination mapping. " % tenant_id)
            except keystoneauth1.exceptions.http.NotFound:
                LOG.warn("Cannot find source tenant \"%s\" for destination "
                         "mapping. ")
        dest_tenant_names = [CONF.destination.new_tenant_name_format %
                             {'original': tenant_name} for tenant_name in
                             src_tenant_names]
        flavor_access = self._destination_openstack_client.nova.flavor_access
        for tenant_name in dest_tenant_names:
            try:
                tenant_id = self._destination_openstack_client.get_project_id(
                        tenant_name)
                flavor_access.add_tenant_access(dest_flavor_id, tenant_id)
                LOG.info("Adding access for tenant \"%s\" to flavor \"%s\""
                         % (tenant_id, dest_flavor_id))
            except keystoneauth1.exceptions.http.Forbidden:
                LOG.warn("Cannot fetch id of destination tenant named \"%s\" "
                         "due to lack of priviledges of current user. "
                         "No flavor access will be added to this tenant. "
                         % tenant_name)
            except keystoneauth1.exceptions.http.NotFound:
                LOG.warn("Cannot find destination tenant named \"%s\". "
                         "No flavor access will be added to this tenant. ")

    def execute_operations(self):
        super(FlavorCreationAction, self).print_operations()
        dest_flavor_name = self.get_new_flavor_name()
        done = self.check_already_done()
        if done["done"]:
            LOG.info(
                "Flavor named '%s' already exists.",
                dest_flavor_name)
            return done["result"]

        LOG.info("Creating destination flavor with name '%s'" %
                 dest_flavor_name)
        body = self.create_flavor_body()
        dest_nova = self._destination_openstack_client.nova
        dest_flavor = dest_nova.flavors.create(**body)
        if not dest_flavor.is_public:
            self.add_tenant_access_to_flavor(dest_flavor)

        return dest_flavor.to_dict()

    def cleanup(self):
        dest_flavor = self._destination_openstack_client.nova.flavors.find(
            name=self.get_new_flavor_name(), is_public=None)
        self._destination_openstack_client.nova.flavors.delete(dest_flavor)
