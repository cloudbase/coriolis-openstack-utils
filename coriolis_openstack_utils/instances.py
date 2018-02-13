# Copyright 2018 Cloudbase Solutions Srl
# All Rights Reserved.

from oslo_log import log as logging
from neutronclient.common.exceptions import NotFound

LOG = logging.getLogger(__name__)


def find_source_instances_by_name(client, instance_names):
    """ List all instances from source and return dicts of the form:
    {
        "instance_name": "",
        "instance_id": "",
        "instance_tenant_name": "",
        "instance_tenant_id"
        # TODO:
        "fixed IP addresses": ["ip1", "ip2"],
        "attached_networks": ["net1", "net2", ...],
        "attached_storage": ["cindervoltype1", "cindervoltype2", ...]
    }
    """
    instances_list = client.nova.servers.list(search_opts={'all_tenants': 1})
    instance_info_list = []
    for instance in instances_list:
        if instance.name in instance_names:
            instance_info = {}
            instance_info['instance_name'] = instance.name
            instance_info['instance_id'] = instance.id
            instance_info['instance_tenant_id'] = instance.tenant_id
            instance_info['instance_tenant_name'] = client.get_project_name(
                instance_info['instance_tenant_id'])

            attached_volumes_ids = [
                el.id for el in
                client.nova.volumes.get_server_volumes(instance.id)]

            attached_volume_types = [
                client.cinder.volumes.find(id=vol_id).volume_type
                for vol_id in attached_volumes_ids]

            instance_info['attached_storage'] = list(
                set(attached_volume_types))

            ips = set()
            for iface in instance.interface_list():
                ips |= set([ip['ip_address'] for ip in iface.fixed_ips])

            instance_info['fixed_ips'] = list(ips)

            # Do we care only about the fixed ips networks?
            net_names = [
                n for n, v in instance.networks.items() if set(v) & ips]
            instance_info['attached_networks'] = net_names

            instance_info_list.append(instance_info)

    return instance_info_list


def validate_migration_options(
        source_client, destination_client, instance_info, target_env):
    """
    Raise error if: unmapped network, inexistent destination network,
    unmapped storage, inexistent destination storage
    # TODO: check if all IPs available on destination.

    param source_client: utils.OpenStackClient: client for source
    param destination_client: utils.OpenStackClient: client for destination
    param instance_info: dict: output from `find_source_instances_by_name`
    target_env: dict: with "network_map" and "storage_map"
    """

    destination_mapped_networks = set(target_env['network_map'].values())
    for network in destination_mapped_networks:
        try:
            destination_client.neutron.find_resource('network', network)
        except Exception:
            ValueError("Invalid destination network %s" % network)

    source_mapped_networks = set(target_env['network_map'].keys())
    for network in source_mapped_networks:
        try:
            source_client.neutron.find_resource('network', network)
        except NotFound:
            ValueError("Invalid source network %s" % network)

    instance_networks = set(instance_info['attached_networks'])
    if not instance_networks.issubset(source_mapped_networks):
        raise ValueError("%s instance networks are not mapped." % (
            instance_networks - source_mapped_networks))
    for network in instance_networks:
        dest_net = target_env['network_map'][network]
        try:
            destination_client.neutron.find_resource('network', dest_net)
        except NotFound:
            raise ValueError("Inexistent destination network %s" % dest_net)

    source_volume_types = set([
        el.name for el in source_client.cinder.volume_types.findall()])
    destination_volume_types = set([
        el.name for el in destination_client.cinder.volume_types.findall()])

    storage_map = target_env.get("storage_map", {})
    destination_mapped_volume_types = set(storage_map.values())
    source_mapped_volume_types = set(storage_map.keys())

    if not destination_mapped_volume_types.issubset(destination_volume_types):
        LOG.info("%s volume types don't exist on destination." %
                 destination_mapped_volume_types -
                 destination_volume_types)

    if not source_mapped_volume_types.issubset(source_volume_types):
        LOG.info("%s volume types don't exist on source." %
                 source_mapped_volume_types -
                 source_volume_types)
    instance_volume_types = set(instance_info['attached_storage'])

    if not instance_volume_types.issubset(source_volume_types):
        LOG.info("%s volume types are not mapped." %
                 instance_volume_types -
                 source_mapped_volume_types)
