# Copyright 2018 Cloudbase Solutions Srl
# All Rights Reserved.

""" This module defines the base ABC for all `Action`s performed by the various
utility commands.
Each action should hold the self-contained logic for its pariticular resource
type (ex: recreating a secgroups, triggering Coriolis migrations, etc...), as
well as contain logic for checking if the action is already completed, and
logic for rolling back an action.
The various `Action` classes should be arranged into a logical tree of actions
and they should be excuted in a "leaf-first"-type traversal.
"""

import abc
from six import with_metaclass


ACTION_TYPE_BATCH_MIGRATE = "create_batch_migration"
ACTION_TYPE_CHECK_CREATE_SOURCE_ENDPOINT = "create_source_endpoint"
ACTION_TYPE_CHECK_CREATE_DESTINATION_ENDPOINT = "create_destination_endpoint"
ACTION_TYPE_CHECK_CREATE_TENANT = "create_tenant"
ACTION_TYPE_CHECK_CREATE_MIGRATION = "create_migration"
ACTION_TYPE_CHECK_CREATE_SECGROUP = "create_secgroup"


class BaseAction(object, with_metaclass(abc.ABCMeta)):
    """ The ABC for all `Action`s offered by the utilities. """

    @abc.abstractproperty
    def action_type(self):
        pass

    def __init__(self, openstack_client, coriolis_client, action_payload):
        """
        param action_client: type of client needed for the action
        param action_payload: dict(): payload (params) for the action
        """
        self._openstack_client = openstack_client
        self._coriolis_client = coriolis_client
        self.payload = action_payload
        self.subactions = []

    @abc.abstractmethod
    def equivalent_to(self, other_action):
        """ Returns True or False of equivalent to other actions.
        Subactions equivalency is considered implied.
        """
        pass

    @abc.abstractmethod
    def check_already_done(self):
        """ Returns dict of the form:
        {
            "done": True/False,    # whether the action needs doing
            "result": <res type>,  # whatever result would have come out
        }
        """
        pass

    def print_operations(self):
        """
        Prints all operations to be perfomed (including suboperations)
        """
        for action in self.subactions:
            action.print_operations()

    def execute_operations(self):
        """
        Executes the needed operations and returns some status info.
        """
        for action in self.subactions:
            action.execute_operations()
