# Copyright 2018 Cloudbase Solutions Srl
# All Rights Reserved.

from oslo_log import log as logging

from cliff import lister

from coriolis_openstack_utils import conf
from coriolis_openstack_utils.actions import network_actions
from coriolis_openstack_utils.cli import formatter
from coriolis_openstack_utils.resource_utils import networks

CONF = conf.CONF

LOG = logging.getLogger(__name__)


class NetworkMigrationFormatter(formatter.EntityFormatter):
    columns = (
        "Network Name",
        "Network ID",
        "Tenant ID",
        "Tenant Name")

    def _get_formatted_data(self, obj):
        data = (
            obj["destination_name"],
            obj["destination_id"],
            obj["dest_tenant_id"],
            obj["dest_tenant_name"])

        return data


class MigrateNetwork(lister.Lister):
    def get_parser(self, prog_name):
        parser = super(MigrateNetwork, self).get_parser(prog_name)
        src_network = parser.add_mutually_exclusive_group(required=True)
        src_network.add_argument(
            "--src-network-id", dest="src_network_id",
            default=False,
            help="The source network id of the source network.")
        src_network.add_argument(
            "--src-network-name", dest="src_network_name",
            default=False,
            help="The source network name of the source network.")
        dest_tenant = parser.add_mutually_exclusive_group(required=True)
        dest_tenant.add_argument(
            "--dest-tenant-id", dest="dest_tenant_id",
            default=False,
            help="The destination tenant id.")
        dest_tenant.add_argument(
            "--dest-tenant-name", dest="dest_tenant_name",
            default=False,
            help="The destination tenant name of the migrated network.")

        parser.add_argument(
            "--not-a-drill", dest="not_drill", action="store_true",
            default=False,
            help="If unset, tooling will only print the indented operations.")

        return parser

    def take_action(self, args):
        # instantiate all clients:
        source_client = conf.get_source_openstack_client()
        destination_client = conf.get_destination_openstack_client()

        if args.src_network_name:
            src_network_id = networks.get_network(
                source_client, args.src_network_name)['id']
        else:
            src_network_id = args.src_network_id

        if args.dest_tenant_name:
            dest_tenant_id = destination_client.get_project_id(
                args.dest_tenant_name)
        else:
            dest_tenant_id = args.dest_tenant_id

        network_creation_payload = {
            "src_network_id": src_network_id,
            "dest_tenant_id": dest_tenant_id}

        network_creation_action = network_actions.NetworkCreationAction(
            network_creation_payload,
            source_openstack_client=source_client,
            destination_openstack_client=destination_client)

        done = network_creation_action.check_already_done()
        if done["done"]:
            LOG.info(
                "Network Migration seemingly done with Network Id '%s' ."
                % done['result'])
            dest_network = networks.get_network(
                destination_client, done['result'])
            network = {
                'destination_name': dest_network['name'],
                'destination_id': done['result'],
                'dest_tenant_name': destination_client.get_project_name(
                    dest_tenant_id),
                'dest_tenant_id': dest_tenant_id}

        else:
            if args.not_drill:
                try:
                    network = network_creation_action.execute_operations()
                except (Exception, KeyboardInterrupt):
                    LOG.warn("Error occured while recreating network with id "
                             "'%s'. Rolling back all changes.", src_network_id)
                    network_creation_action.cleanup()
                    raise
            else:
                network_creation_action.print_operations()
                network = {
                    'destination_name': 'NOT DONE',
                    'destination_id': 'NOT DONE',
                    'dest_tenant_name': destination_client.get_project_name(
                        dest_tenant_id),
                    'dest_tenant_id': dest_tenant_id}

        return NetworkMigrationFormatter().list_objects([network])
