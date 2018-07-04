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


class SubnetMigrationFormatter(formatter.EntityFormatter):
    columns = (
        "Subnet Name",
        "Subnet ID",
        "Network ID",
        "Network Name")

    def _get_formatted_data(self, obj):
        data = (
            obj["destination_name"],
            obj["destination_id"],
            obj["dest_network_id"],
            obj["dest_network_name"])

        return data


class MigrateSubnet(lister.Lister):
    def get_parser(self, prog_name):
        parser = super(MigrateSubnet, self).get_parser(prog_name)
        source_group = parser.add_mutually_exclusive_group(required=True)
        source_group.add_argument(
            "--src-network-id", dest="src_network_id",
            default=False,
            help="The source network id of the source subnet.")
        source_group.add_argument(
            "--src-network-name", dest="src_network_name",
            default=False,
            help="The destination network id where the subnet is located")
        parser.add_argument(
            "--not-a-drill", dest="not_drill", action="store_true",
            default=False,
            help="If unset, tooling will only print the indented operations.")
        parser.add_argument("subnet_name", metavar="SUBNET_NAME")

        return parser

    def take_action(self, args):
        # instantiate all clients:
        source_client = conf.get_source_openstack_client()
        destination_client = conf.get_destination_openstack_client()

        if args.src_network_id:
            src_network_id = args.src_network_id
            src_network_name = networks.get_network(
                source_client, args.src_network_id)['name']
        elif args.src_network_name:
            src_network_id = networks.get_network(
                source_client, args.src_network_name)['id']
            src_network_name = args.src_network_name

        dest_network_name = CONF.destination.new_network_name_format % {
            "original": src_network_name}
        dest_network_id = networks.get_network(
            destination_client, dest_network_name)['id']

        subnet_creation_payload = {
            "source_name": args.subnet_name,
            "src_network_id": src_network_id,
            "dest_network_id": dest_network_id}

        subnet_creation_action = network_actions.SubnetCreationAction(
            subnet_creation_payload, source_openstack_client=source_client,
            destination_openstack_client=destination_client)

        done = subnet_creation_action.check_already_done()
        subnet = []
        if done["done"]:
            LOG.info(
                "Subnet Migration seemingly done.")
            subnet = {
                'destination_name': (
                    subnet_creation_action.get_new_subnet_name()),
                'destination_id': done['result'],
                'dest_network_id': dest_network_id,
                'dest_network_name': dest_network_name}

        else:
            if args.not_drill:
                subnet = subnet_creation_action.execute_operations()
            else:
                subnet_creation_action.print_operations()
                subnet = {
                    'destination_name': 'NOT DONE',
                    'destination_id': 'NOT DONE',
                    'dest_network_id': dest_network_id,
                    'dest_network_name': dest_network_name}

        return SubnetMigrationFormatter().list_objects([subnet])
