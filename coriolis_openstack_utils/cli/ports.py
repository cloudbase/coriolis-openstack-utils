# Copyright 2018 Cloudbase Solutions Srl
# All Rights Reserved.

from oslo_log import log as logging

from cliff import lister

from coriolis_openstack_utils import conf
from coriolis_openstack_utils.actions import network_actions
from coriolis_openstack_utils.cli import formatter
from coriolis_openstack_utils.resource_utils import users
from novaclient import client as nova_client


LOG = logging.getLogger(__name__)


class PortMigrationFormatter(formatter.EntityFormatter):
    columns = (
        "Port Name",
        "Port ID")

    def _get_formatted_data(self, obj):
        data = (
            obj["name"],
            obj["id"])

        return data


class MigratePort(lister.Lister):
    def get_parser(self, prog_name):
        parser = super(MigratePort, self).get_parser(prog_name)
        parser.add_argument(
            "--src-port-id", dest="src_port_id", required=True)
        parser.add_argument(
            "--dest-network-id", dest="dest_network_id", required=True)
        parser.add_argument(
            "--not-a-drill", dest="not_drill", action="store_true",
            default=False,
            help="If unset, tooling will only print the indented operations.")

        return parser

    def take_action(self, args):
        # instantiate all clients:
        source_client = conf.get_source_openstack_client()
        destination_client = conf.get_destination_openstack_client()

        src_port_id = args.src_port_id
        dest_network_id = args.dest_network_id

        port_creation_payload = {
            'src_port_id': src_port_id, 'dest_network_id': dest_network_id}

        port_creation_action = network_actions.PortCreationAction(
            port_creation_payload,
            source_openstack_client=source_client,
            destination_openstack_client=destination_client)

        done = port_creation_action.check_already_done()
        port = []
        if done["done"]:
            port = done["result"]
            LOG.info(
                "port with info '%s' Migration seemingly done."
                % port)

        else:
            if args.not_drill:
                try:
                    port = port_creation_action.execute_operations()
                except Exception as action_exception:
                    LOG.warn("Error occured while recreating port with id"
                             " '%s'. Rolling back all changes", src_port_id)
                    port_creation_action.cleanup()
                    raise action_exception
            else:
                port_creation_action.print_operations()
                port = {
                    'name': 'NOT DONE',
                    'id': 'NOT DONE'}

        return PortMigrationFormatter().list_objects([port])
