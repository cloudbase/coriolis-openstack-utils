from oslo_log import log as logging

from coriolis_openstack_utils import conf
from coriolis_openstack_utils.resource_utils import subnets
from coriolis_openstack_utils.resource_utils import networks

CONF = conf.CONF
LOG = logging.getLogger(__name__)


def get_router(openstack_client, name_or_id):
    return openstack_client.neutron.find_resource('router', name_or_id)


def list_routers(openstack_client, filters):
    return openstack_client.neutron.list_routers(**filters)['routers']


def check_router_similarity(source_client, src_router, destination_client,
                            dest_router):
    relevant_keys = {'admin_state_up', 'external_gateway_info',
                     'distributed', 'ha'}
    conflicting_keys = set()

    router_network_mapping = CONF.destination.external_network_name_map
    src_router = {k: v for k, v in src_router.items() if v is not None}
    dest_router = {k: v for k, v in dest_router.items() if v is not None}
    for k in src_router:
        if k in relevant_keys:
            if k == 'external_gateway_info':
                src_snat = src_router[k].get('enable_snat', False)
                dest_snat = dest_router.get(k, {}).get('enable_snat', False)
                src_network_id = src_router[k]['network_id']
                dest_network_id = dest_router.get(
                    k, {}).get('network_id', True)
                if src_snat == dest_snat:
                    src_net_name = networks.get_network(
                        source_client, src_network_id)['name']
                    dest_net_name = networks.get_network(
                        destination_client, dest_network_id)['name']
                    if (router_network_mapping.get(
                            src_net_name, src_net_name) == dest_net_name):
                        conflicting_keys.add(k)
            elif src_router[k] == dest_router.get(k):
                conflicting_keys.add(k)

    src_relevant_keys = set(src_router.keys()).intersection(relevant_keys)
    return conflicting_keys == src_relevant_keys


def get_migration_info(source_client, name_or_id):
    router = get_router(source_client, name_or_id)
    relevant_keys = {'admin_state_up', 'distributed', 'ha',
                     'availability_zone_hints'}

    body = {k: v for k, v in router.items() if k in relevant_keys}
    body['availability_zone_hints'] += router['availability_zones']
    # eliminate any possible duplicates
    body['availability_zone_hints'] = list(
        set(body['availability_zone_hints']))
    ext_gateway_info = router['external_gateway_info']

    src_ext_subnet_ids = set()
    for fixed_ip in ext_gateway_info['external_fixed_ips']:
        src_ext_subnet_ids.add(fixed_ip['subnet_id'])
    ext_networks_ids = [subnets.get_subnet(source_client, subnet_id)[
        'network_id'] for subnet_id in src_ext_subnet_ids]
    ext_network_names = [networks.get_network(source_client, network_id)[
        'name'] for network_id in ext_networks_ids]

    # mapped with new_subnet_name_format and new_network_name_format
    src_subnet_ids = set()
    for port in source_client.neutron.list_ports(
            device_id=router['id'])['ports']:
        for fixed_ip in port['fixed_ips']:
            src_subnet_ids.add(fixed_ip['subnet_id'])

    src_subnet_ids = src_subnet_ids - src_ext_subnet_ids

    src_subnets = [subnets.get_subnet(source_client, subnet_id)
                   for subnet_id in src_subnet_ids]

    # adding both network name and subnet name the chance of a collision on
    # destination is greatly reduced
    src_subnets = [{'subnet_name': subnet['name'],
                    'network_name': networks.get_network(
                        source_client, subnet['network_id'])['name']}
                   for subnet in src_subnets]

    return {'source_name': router['name'],
            'migration_body': body,
            'src_ext_net_names': ext_network_names,
            'src_subnets': src_subnets}


def create_router(destination_client, migr_info):
    body = migr_info['migration_body']
    src_router_name = migr_info['source_name']
    new_format = CONF.destination.new_router_name_format
    body['name'] = new_format % {
        "original": src_router_name}
    router_id = destination_client.neutron.create_router(
        {'router': body})['router']['id']

    src_ext_net_names = migr_info['src_ext_net_names']
    src_subnets = migr_info['src_subnets']

    external_network_map = CONF.destination.external_network_name_map
    dest_ext_net_names = [external_network_map.get(net_name, net_name)
                          for net_name in src_ext_net_names]

    dest_ext_net_ids = [networks.get_network(
        destination_client, net_name)['id'] for net_name in dest_ext_net_names]
    for net_id in dest_ext_net_ids:
        LOG.info(
            "Adding external network %s gateway to router %s"
            % (net_id, router_id))
        destination_client.neutron.add_gateway_router(
            router_id, {'network_id': net_id})

    new_net_name_format = CONF.destination.new_network_name_format
    new_subnet_name_format = CONF.destination.new_subnet_name_format

    # TODO more efficient way to determine destination subnets?
    for subnet in src_subnets:
        dest_net_name = new_net_name_format % {
            "original": subnet['network_name']}
        dest_net_id = networks.get_network(
            destination_client, dest_net_name)['id']

        dest_subnet_name = new_subnet_name_format % {
            "original": subnet['subnet_name']}

        dest_subnet_id = subnets.list_subnets(
            destination_client, filters={'network_id': dest_net_id,
                                         'name': dest_subnet_name})[0]['id']
        LOG.info("Adding interface for subnet '%s' to router '%s' "
                 % (dest_subnet_name, body['name']))
        destination_client.neutron.add_interface_router(
            router_id, dest_subnet_id)

    return router_id


def delete_router(openstack_client, name):
    routers = list_routers(
        openstack_client, filters={'name': name})
    routers_length = len(routers)
    if routers_length == 1:
        openstack_client.neutron.delete_router(routers[0]['id'])
    elif routers_length > 1:
        LOG.info("Unable to delete router named '%s'. "
                 "Multiple routers found." % name)
    elif routers_length == 0:
        LOG.info("Unable to delete router named '%s'."
                 "No router found." % name)
