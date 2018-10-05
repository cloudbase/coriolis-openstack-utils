# Copyright 2018 Cloudbase Solutions Srl
# All Rights Reserved.

""" Module defining OpenStack keypair-related actions. """
import novaclient.exceptions
import keystoneauth1.exceptions.http

from oslo_log import log as logging

from coriolis_openstack_utils import conf
from coriolis_openstack_utils.actions import base
from coriolis_openstack_utils.resource_utils import users

CONF = conf.CONF
LOG = logging.getLogger(__name__)


class KeypairCreationAction(base.BaseAction):
    """ Action for creating keypairs on the destination.
    param action_payload: dict(): payload (params) for the action
    must contain 'src_keypair_name'
                 'src_user_id' - (optional) if nonexistent, will fetch source
                                 keypair based on current user

    """

    action_type = base.ACTION_TYPE_CHECK_CREATE_KEYPAIR
    NEW_SECGROUP_DESCRIPTION = (
        "Created by the Coriolis OpenStack utilities for source security group"
        " '%s'.")

    @property
    def keypair_name_format(self):
        return CONF.destination.new_keypair_name_format

    def get_source_keypair(self):
        src_nova = self._source_openstack_client.nova
        src_keypair_name = self.payload['src_keypair_name']
        src_user_id = self.payload.get('src_user_id', None)

        if float(src_nova.api_version.get_string()) >= 2.10:
            src_keypair = src_nova.keypairs.get(
                src_keypair_name, user_id=src_user_id)
        else:
            src_keypair = src_nova.keypairs.get(src_keypair_name)

        return src_keypair

    def get_destination_keypair(self, src_keypair):
        dest_nova = self._destination_openstack_client.nova
        dest_keypair_name = self.get_new_keypair_name()
        src_user_id = self.payload.get('src_user_id', src_keypair.user_id)
        if src_user_id is None or float(
                dest_nova.api_version.get_string()) < 2.10:
            dest_keypair = dest_nova.keypairs.get(dest_keypair_name)
        else:
            src_user = users.get_user(self._source_openstack_client,
                                      src_user_id)
            dest_user_name = CONF.destination.new_user_name_format % {
                'original': src_user.name}
            try:
                dest_keystone = self._destination_openstack_client.keystone
                dest_user = dest_keystone.users.find(name=dest_user_name)
                dest_keypair = dest_nova.keypairs.get(
                    dest_keypair_name, user_id=dest_user.id)
            except keystoneauth1.exceptions.http.NotFound:
                dest_keypair = dest_nova.keypairs.get(dest_keypair_name)
        return dest_keypair

    def check_already_done(self):
        src_keypair = self.get_source_keypair()
        dest_keypair = None
        try:
            dest_keypair = self.get_destination_keypair(src_keypair)
        except novaclient.exceptions.NotFound:
            return {"done": False, "result": None}

        if src_keypair.public_key == dest_keypair.public_key:
                return {"done": True,
                        "result": dest_keypair.to_dict()}
        else:
            raise Exception(
                "Found destination keypair \"%s\" with different public "
                "key than source keypair \"%s\" !" % (
                    self.get_new_keypair_name(), src_keypair.id))

        return {"done": False, "result": None}

    def equivalent_to(self, other_action):
        if other_action.action_type == self.action_type:
            if self.payload['src_keypair_name'] == (
                    other_action.payload.get('src_keypair_name')):
                return True
        return False

    def print_operations(self):
        super(KeypairCreationAction, self).print_operations()
        keypair_name = self.get_new_keypair_name()
        LOG.info(
            "Create new destination keypair named '%s' with source's "
            "public key." % (keypair_name))

    def get_new_keypair_name(self):
        return self.keypair_name_format % {
            "original": self.payload["src_keypair_name"]}

    def create_keypair_body(self, description):
        return {"name": self.get_new_keypair_name(),
                "tenant_id": self.payload['dest_tenant_id'],
                "description": description}

    def execute_operations(self):
        super(KeypairCreationAction, self).print_operations()
        dest_keypair_name = self.get_new_keypair_name()

        dest_nova = self._destination_openstack_client.nova

        done = self.check_already_done()
        if done["done"]:
            LOG.info(
                "Keypair named '%s' already exists.",
                dest_keypair_name)
            return done["result"]

        src_keypair = self.get_source_keypair()
        src_user_id = src_keypair.user_id
        src_public_keypair = src_keypair.public_key

        src_user = users.get_user(self._source_openstack_client, src_user_id)
        src_user_name = src_user.name
        dest_user_name = (CONF.destination.new_user_name_format %
                          {'original': src_user_name})
        dest_keypair_kwargs = {'public_key': src_public_keypair}
        if float(dest_nova.api_version.get_string()) >= 2.10:
            try:
                dest_keystone = self._destination_openstack_client.keystone
                dest_user = dest_keystone.users.find(name=dest_user_name)
                user_id = dest_user.id
                dest_keypair_kwargs['user_id'] = user_id
            except keystoneauth1.exceptions.http.NotFound:
                pass

        LOG.info("Creating destination keypair with name '%s' and kwargs"
                 "\"%s\" " % (dest_keypair_name, dest_keypair_kwargs))
        dest_keypair = dest_nova.keypairs.create(
            dest_keypair_name, **dest_keypair_kwargs)
        return dest_keypair.to_dict()

    def cleanup(self):
        src_keypair = self.get_source_keypair()
        dest_keypair = None
        try:
            dest_keypair = self.get_destination_keypair(src_keypair)
        except novaclient.exceptions.NotFound:
            pass
        dest_nova = self._destination_openstack_client.nova
        if dest_keypair is not None and float(
                dest_nova.api_verison.get_string()) > 2.10:
            dest_nova.keypairs(dest_keypair.name, user_id=dest_keypair.user_id)
        else:
            dest_keypair.delete()
