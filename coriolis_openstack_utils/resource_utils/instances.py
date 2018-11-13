# Copyright 2018 Cloudbase Solutions Srl
# All Rights Reserved.
import math
import datetime

from oslo_log import log as logging
from neutronclient.common.exceptions import NotFound
from glanceclient.common.exceptions import NotFound as ImageNotFound
from oslo_utils import units

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
    instances_list = client.nova.servers.list(
        search_opts={'all_tenants': True})
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


def validate_transfer_options(
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
                 (destination_mapped_volume_types -
                  destination_volume_types))

    if not source_mapped_volume_types.issubset(source_volume_types):
        LOG.info("%s volume types don't exist on source." %
                 (source_mapped_volume_types -
                  source_volume_types))
    instance_volume_types = set(instance_info['attached_storage'])

    if not instance_volume_types.issubset(source_volume_types):
        LOG.info("%s volume types are not mapped." %
                 (instance_volume_types -
                  source_mapped_volume_types))


def _get_instance_assessment(source_client, instance):
    nova = source_client.nova
    glance = source_client.glance
    cinder = source_client.cinder

    assessment = {}
    assessment['storage'] = {}
    total_size_gb = 0
    if instance.image:
        # Taking in account that the source image might be deleted
        try:
            image = glance.images.get(instance.image.get('id'))
            image_size = math.ceil(image.size / units.Gi)
            total_size_gb += image_size
            image_info = {"size_bytes": image.size,
                          "source_image_name": image.name,
                          "os_type": image.get("os_type", "linux")}
            assessment["storage"]["image"] = image_info
        except ImageNotFound:
            pass

    volume_ids = [vol.id for vol in
                  nova.volumes.get_server_volumes(instance.id)]
    volumes = [cinder.volumes.find(id=vol_id) for vol_id in volume_ids]
    total_size_gb += sum([volume.size for volume in volumes])
    volumes_info = [{"volume_name": volume.name,
                     "volume_id": volume.id,
                     "size_bytes": units.Gi * volume.size}
                    for volume in volumes]
    assessment["storage"]["volumes"] = volumes_info

    instance_flavor = nova.flavors.get(instance.flavor['id'])
    total_size_gb += instance_flavor.disk
    flavor_info = {"flavor_name": instance_flavor.name,
                   "flavor_id": instance_flavor.id,
                   "flavor_vcpus": instance_flavor.vcpus,
                   "flavor_disk_size":
                   instance_flavor.disk * units.Gi}
    assessment["storage"]["flavor"] = flavor_info

    tenant_id = instance.tenant_id
    tenant_name = source_client.get_project_name(tenant_id)
    assessment["instance_name"] = instance.name
    assessment["instance_id"] = instance.id
    assessment["source_tenant_id"] = tenant_id
    assessment["source_tenant_name"] = tenant_name
    assessment["storage"]["total_size_gb"] = total_size_gb

    return assessment


def get_instances_assessment(source_client, instances_names):
    nova = source_client.nova
    instances = []
    for instance_el in nova.servers.list(search_opts={'all_tenants': True}):
        if instance_el.name in instances_names:
            instances.append(instance_el)
    found_instances = {instance.name for instance in instances}

    if (set(instances_names) - found_instances) != set():
        raise ValueError("Instances %s have not been found!" %
                         (set(instances_names) - found_instances))

    assessment_list = []
    for instance in instances:
        assessment = _get_instance_assessment(source_client, instance)
        assessment_list.append(assessment)

    return assessment_list


def get_migration_assessment(source_client, coriolis, migration_id):

    migration = coriolis.migrations.get(migration_id)

    creation_timestamp = migration.tasks[0].updated_at
    finish_timestamp = migration.tasks[-1].updated_at
    creation_date = datetime.datetime.strptime(
        creation_timestamp, '%Y-%m-%dT%H:%M:%S.%f')
    finish_date = datetime.datetime.strptime(
        finish_timestamp, '%Y-%m-%dT%H:%M:%S.%f')

    interval_date = finish_date - creation_date

    migration_instances = migration.instances
    assessment_list = get_instances_assessment(source_client,
                                               migration_instances)
    for assessment in assessment_list:
        assessment["migration"] = {}
        assessment["migration"]["migration_id"] = migration.id
        assessment["migration"]["migration_status"] = migration.status
        assessment["migration"]["migration_time"] = str(interval_date)
        previous_migration_ids = []
        for migr_thin in coriolis.migrations.list():
            migr = coriolis.migrations.get(migr_thin.id)
            prev_creation_timestamp = migr.tasks[0].updated_at
            prev_creation_date = datetime.datetime.strptime(
                prev_creation_timestamp, '%Y-%m-%dT%H:%M:%S.%f')

            if (assessment["instance_name"] in migr.instances and
                    prev_creation_date < creation_date):
                previous_migration_ids.append(migr.id)

        assessment["migration"]["previous_migrations"] = previous_migration_ids

    return assessment_list


def list_instances(openstack_client, filters={}):
    filters['all_tenants'] = True
    return openstack_client.nova.servers.list(search_opts=filters)


def get_instance_id(openstack_client, tenant_name, instance_name):
    project_id = openstack_client.get_project_id(tenant_name)
    filters = {'tenant_id': project_id, 'project_id': project_id,
               'name': instance_name}
    instances = list_instances(openstack_client, filters=filters)
    if not instances:
        raise Exception("Instance named '%s' in tenant named '%s' not "
                        "found" % (instance_name, tenant_name))
    if len(instances) > 1:
        raise Exception("Multiple instances named '%s' in tenant named '%s' "
                        "found" % (instance_name, tenant_name))
    return instances[0].id
