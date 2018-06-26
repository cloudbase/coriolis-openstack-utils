# Copyright 2018 Cloudbase Solutions Srl
# All Rights Reserved.

from oslo_log import log as logging


LOG = logging.getLogger(__name__)


def list_security_groups(openstack_client, tenant_id, filters=None):
    if not filters:
        return openstack_client.neutron.list_security_groups(
            tenant_id=tenant_id, project_id=tenant_id)['security_groups']
    return openstack_client.neutron.list_security_groups(
        tenant_id=tenant_id, project_id=tenant_id,
        **filters)['security_groups']


def get_security_group(openstack_client, tenant_id, name):
    return openstack_client.neutron.find_resource(
        'security_group', name, project_id=tenant_id)


def create_security_group(openstack_client, tenant_id, body):
    body['tenant_id'] = tenant_id
    body['project_id'] = tenant_id
    post_body = {"security_group": body}
    secgroup_id = openstack_client.neutron.create_security_group(
        post_body)['security_group']['id']

    return secgroup_id


def get_destination_secgroup_rules_params(
        secgroup_id, source_rules, description=None):

    destination_rules = []
    for rule in source_rules:
        rule_body = {
            'direction': rule['direction'],
            'port_range_min': rule.get('port_range_min'),
            'port_range_max': rule.get('port_range_max'),
            'remote_ip_prefix': rule.get('remote_ip_prefix'),
            'ethertype': rule.get('ethertype'),
            'protocol': rule.get('protocol'),
            'security_group_id': secgroup_id,
            'description': description}

        rule_body = {k: v for k, v in rule_body.items() if v is not None}
        destination_rules.append(rule_body)

    return destination_rules


def add_rules_to_secgroup(secgroup_name, rules, openstack_client):
    for rule in rules:
        rule_body = {'security_group_rule': rule}
        LOG.info("Adding rule %s to Security Group %s "
                 % (rule, secgroup_name))
        openstack_client.neutron.create_security_group_rule(rule_body)


def check_rule_similarity(source_rule, destination_rule):
    conflict_keys = set()
    relevant_keys = set(['direction', 'ethertype', 'port_range_min',
                         'port_range_max', 'protocol', 'remote_ip_prefix'])
    for k in source_rule:
        if k in relevant_keys:
            if source_rule[k] == destination_rule.get(k):
                conflict_keys.add(k)
    relevant_source_keys = set(
        source_rule.keys()).intersection(relevant_keys)

    return len(relevant_source_keys) == len(conflict_keys)
