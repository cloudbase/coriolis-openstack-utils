# Copyright 2018 Cloudbase Solutions Srl
# All Rights Reserved.

from oslo_log import log as logging

LOG = logging.getLogger(__name__)


def get_subnet(openstack_client, subnet_id):
    return openstack_client.neutron.find_resource_by_id('subnet', subnet_id)


def list_subnets(openstack_client, filters={}):
    return openstack_client.neutron.list_subnets(
        **filters)['subnets']


def get_body(openstack_client, src_tenant_id, source_name):
    src_subnet = list_subnets(
        openstack_client,
        filters={'tenant_id': src_tenant_id, 'name': source_name})[0]
    body = {
        'ipv6_ra_mode': src_subnet.get('ipv6_ra_mode'),
        'dns_nameservers': src_subnet.get('dns_nameservers'),
        'ipv6_address_mode': src_subnet.get('ipv6_address_mode'),
        'ip_version': src_subnet.get('ip_version'),
        'host_routes': src_subnet.get('host_routes'),
        'gateway_ip': src_subnet.get('gateway_ip'),
        'allocation_pools': src_subnet.get('allocation_pools'),
        'service_types': src_subnet.get('service_types'),
        'enable_dhcp': src_subnet.get('enable_dhcp'),
        'cidr': src_subnet.get('cidr')}
    body = {k: v for k, v in body.items() if v is not None}

    return body


def create_subnet(openstack_client, body):
    subnet_id = openstack_client.neutron.create_subnet(
        {'subnet': body})['subnet']['id']

    return subnet_id


def check_subnet_similarity(src_subnet, dest_subnet):
    relevant_keys = set(['enable_dhcp', 'dns_nameservers', 'allocation_pools',
                         'host_routes', 'ip_version', 'gateway_ip',
                         'cidr', 'prefixlen', 'ipv6_address_mode',
                         'ipv6_ra_mode', 'service_types'])

    conflict_keys = set()
    src_service_types = set(src_subnet.get('service_types'))
    dest_service_types = set(dest_subnet.get('service_types'))
    if src_service_types == dest_service_types:
        conflict_keys.add('service_types')

    for k in src_subnet:
        if k in relevant_keys:
            if src_subnet[k] == dest_subnet.get(k):
                conflict_keys.add(k)
    src_relevant_keys = set(src_subnet.keys()).intersection(relevant_keys)

    return len(src_relevant_keys) == len(conflict_keys)


def delete_subnet(openstack_client, network_id, name):
    src_subnets = list_subnets(
        openstack_client, filters={'network_id': network_id, 'name': name})
    len_src_subnets = len(src_subnets)
    if len_src_subnets == 1:
        openstack_client.neutron.delete_subnet(src_subnets[0]['id'])
    elif len_src_subnets == 0:
        LOG.info("Deleting subnet with name '%s' in network '%s' "
                 "failed.Subnet not found." % (name, network_id))
    elif len_src_subnets > 1:
        LOG.info("Deleting subnet with name '%s' in network '%s' "
                 "failed. Multiple subnets found." % (name, network_id))
