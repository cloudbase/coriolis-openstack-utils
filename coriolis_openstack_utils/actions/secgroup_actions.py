# Copyright 2018 Cloudbase Solutions Srl
# All Rights Reserved.

""" Module defining OpenStack security-group-related actions. """

from oslo_log import log as logging

from coriolis_openstack_utils import conf
from coriolis_openstack_utils.actions import base
from coriolis_openstack_utils.resource_utils import security_groups

CONF = conf.CONF
LOG = logging.getLogger(__name__)


class SecurityGroupCreationAction(base.BaseAction):
    """ Action for creating security groups on the destination.
    param action_payload: dict(): payload (params) for the action
    must contain 'src_tenant_id'
                 'dest_tenant_id'
                 'source_name'
    """

    action_type = base.ACTION_TYPE_CHECK_CREATE_SECGROUP
    NEW_SECGROUP_DESCRIPTION = (
        "Created by the Coriolis OpenStack utilities for source security group"
        " '%s'.")

    @property
    def secgroup_name_format(self):
        return CONF.destination.new_secgroup_name_format

    def check_rules_added(self, src_rules, dest_rules):
        conflicts = []
        for src_rule in src_rules:
            for dest_rule in dest_rules:
                if security_groups.check_rule_similarity(
                        src_rule, dest_rule):
                    conflicts.append(src_rule)
                    break
        return len(src_rules) == len(conflicts)

    def check_already_done(self):
        dest_tenant_id = self.payload['dest_tenant_id']
        dest_secgroup_name = self.get_new_secgroup_name()

        src_tenant_id = self.payload['src_tenant_id']
        src_secgroup_name = self.payload['source_name']

        dest_secgroups = security_groups.list_security_groups(
            self._destination_openstack_client,
            dest_tenant_id,
            filters={'name': dest_secgroup_name})

        src_rules = security_groups.get_security_group(
            self._source_openstack_client, tenant_id=src_tenant_id,
            name=src_secgroup_name)['security_group_rules']

        found_secgroup_id = None
        for secgroup in dest_secgroups:
            dest_rules = secgroup['security_group_rules']
            if self.check_rules_added(src_rules, dest_rules):
                LOG.info("Found destination Security Group "
                         "with name %s and %s's rules."
                         % (dest_secgroup_name, src_secgroup_name))
                found_secgroup_id = secgroup['id']
                break

        if found_secgroup_id:
            return {"done": True,
                    "result": found_secgroup_id}
        elif dest_secgroups:
            raise Exception("Found Security Groups %s in tenant %s with "
                            "different rules than source %s in tenant %s!" %
                            (dest_secgroup_name, dest_tenant_id,
                             src_secgroup_name, src_tenant_id))

        return {"done": False, "result": None}

    def equivalent_to(self, other_action):
        if other_action.action_type == self.action_type:
            if self.payload['source_name'] == (
                    other_action.payload.get('source_name')):
                src_tenant_id = self.payload['src_tenant_id']
                src_other_tenant_id = (
                    other_action.payload.get('src_tenant_id'))

                dest_tenant_id = self.payload['dest_tenant_id']
                dest_other_tenant_id = (
                    other_action.payload.get('dest_tenant_id'))
                if (src_tenant_id == src_other_tenant_id and
                        dest_tenant_id == dest_other_tenant_id):
                    return True
        return False

    def print_operations(self):
        super(SecurityGroupCreationAction, self).print_operations()
        secgroup_name = self.get_new_secgroup_name()
        LOG.info(
            "Create new destination secgroup named '%s' with source's "
            "security rules." % (secgroup_name))

    def get_new_secgroup_name(self):
        return self.secgroup_name_format % {
            "original": self.payload["source_name"]}

    def create_secgroup_body(self, description):
        return {"name": self.get_new_secgroup_name(),
                "tenant_id": self.payload['dest_tenant_id'],
                "description": description}

    def execute_operations(self):
        super(SecurityGroupCreationAction, self).print_operations()
        dest_secgroup_name = self.get_new_secgroup_name()
        dest_tenant_id = self.payload['dest_tenant_id']
        done = self.check_already_done()
        if done["done"]:
            LOG.info(
                "Security Group named '%s' already exists.",
                dest_secgroup_name)
            return done["result"]

        LOG.info("Creating destination security group with name '%s'" %
                 dest_secgroup_name)

        description = (self.NEW_SECGROUP_DESCRIPTION %
                       self.payload['source_name'])

        body = self.create_secgroup_body(description)
        dest_secgroup_id = security_groups.create_security_group(
            self._destination_openstack_client, dest_tenant_id, body)

        LOG.info("Adding source %s rules to destination security group '%s'" %
                 (self.payload['source_name'], dest_secgroup_name))

        src_secgroup_name = self.payload.get('source_name')
        src_tenant_id = self.payload['src_tenant_id']

        source_secgroup_list = security_groups.list_security_groups(
            self._source_openstack_client, src_tenant_id,
            filters={'name': src_secgroup_name})

        if not source_secgroup_list:
            raise Exception("Source security group named %s in tenant %s "
                            "not found! " % (src_secgroup_name, src_tenant_id))
        elif len(source_secgroup_list) > 1:
            raise Exception("Multiple secgroups named %s on source in "
                            "tenant %s " % (src_secgroup_name, src_tenant_id))
        else:
            source_secgroup = source_secgroup_list[0]

        src_rules = source_secgroup['security_group_rules']
        new_dest_rules = (
            security_groups.get_destination_secgroup_rules_params(
                dest_secgroup_id, src_rules))

        prev_dest_rules = security_groups.get_security_group(
            self._destination_openstack_client, dest_tenant_id,
            dest_secgroup_name)['security_group_rules']

        # Removing conflicting rules
        dest_rules = []
        for new_rule in new_dest_rules:
            if new_rule not in dest_rules:
                skip_rule = False
                for prev_rule in prev_dest_rules:
                    if security_groups.check_rule_similarity(
                            new_rule, prev_rule):
                        skip_rule = True
                if not skip_rule:
                    dest_rules.append(new_rule)
                else:
                    LOG.debug("Skip adding already existing rule from "
                              "source %s" % new_rule)

        security_groups.add_rules_to_secgroup(
            dest_secgroup_name, dest_rules, self._destination_openstack_client)

        dest_secgroup = {
            'destination_name': dest_secgroup_name,
            'destination_id': dest_secgroup_id,
            'dest_tenant_id': dest_tenant_id,
            'dest_tenant_name':
                self._destination_openstack_client.get_project_name(
                    dest_tenant_id)}

        return dest_secgroup

    def cleanup(self):
        security_groups.delete_secgroup(
            self._destination_openstack_client,
            self.payload['dest_tenant_id'], self.get_new_secgroup_name())
