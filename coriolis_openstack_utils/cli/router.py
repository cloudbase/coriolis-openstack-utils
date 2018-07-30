# Copyright 2018 Cloudbase Solutions Srl
# All Rights Reserved.

from oslo_log import log as logging

from cliff import lister

from coriolis_openstack_utils import conf
from coriolis_openstack_utils.actions import network_actions
from coriolis_openstack_utils.cli import formatter
from coriolis_openstack_utils.resource_utils import routers


LOG = logging.getLogger(__name__)


class RouterMigrationFormatter(formatter.EntityFormatter):
    columns = (
        "Router Name",
        "Router ID",
        "Tenant ID")

    def _get_formatted_data(self, obj):
        data = (
            obj["name"],
            obj["id"],
            obj["tenant_id"])

        return data


class MigrateRouter(lister.Lister):
    def get_parser(self, prog_name):
        parser = super(MigrateRouter, self).get_parser(prog_name)
        source_group = parser.add_mutually_exclusive_group(required=True)
        source_group.add_argument(
            "--src-router-id",
            dest="src_router_id",
            help="The id of the router that is being migrated.")
        source_group.add_argument(
            "--src-router-name", dest="src_router_name",
            help="The name of the router that is being "
                 "migrated.")
        parser.add_argument(
            "--not-a-drill", dest="not_drill", action="store_true",
            default=False,
            help="If unset, tooling will only print the indented operations.")

        return parser

    def take_action(self, args):
        # instantiate all clients:
        source_client = conf.get_source_openstack_client()
        destination_client = conf.get_destination_openstack_client()

        if args.src_router_name:
            src_router_id = routers.get_router(
                source_client, args.src_router_name)['id']
        else:
            src_router_id = args.src_router_id

        router_creation_payload = {
            'src_router_id': src_router_id}

        router_creation_action = network_actions.RouterCreationAction(
            router_creation_payload,
            source_openstack_client=source_client,
            destination_openstack_client=destination_client)

        done = router_creation_action.check_already_done()
        router = None
        if done["done"]:
            router = routers.get_router(destination_client, done['result'])
            LOG.info(
                "Router '%s' Migration seemingly done."
                % router['name'])
        else:
            if args.not_drill:
                router = router_creation_action.execute_operations()
            else:
                router_creation_action.print_operations()
                router = {
                    'name': 'NOT DONE',
                    'id': 'NOT DONE',
                    'tenant_id': 'NOT DONE'}

        return RouterMigrationFormatter().list_objects([router])
