# Copyright 2018 Cloudbase Solutions Srl
# All Rights Reserved.

from oslo_log import log as logging

from cliff import lister

from coriolis_openstack_utils import conf
from coriolis_openstack_utils.actions import flavor_actions
from coriolis_openstack_utils.cli import formatter


LOG = logging.getLogger(__name__)


class FlavorMigrationFormatter(formatter.EntityFormatter):
    columns = (
        "Flavor Name",
        "Flavor ID",
        "Flavor VCPUS",
        "Flavor Disk",
        "Flavor RAM")

    def _get_formatted_data(self, obj):
        data = (
            obj["name"],
            obj["id"],
            obj["vcpus"],
            obj["disk"],
            obj["ram"])

        return data


class MigrateFlavor(lister.Lister):
    def get_parser(self, prog_name):
        parser = super(MigrateFlavor, self).get_parser(prog_name)
        source_group = parser.add_mutually_exclusive_group(required=True)
        source_group.add_argument(
            "--src-flavor-id",
            dest="src_flavor_id",
            help="The id of the flavor that is being replicated.")
        source_group.add_argument(
            "--src-flavor-name", dest="src_flavor_name",
            help="The name of the flavor that is being "
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

        src_flavor_id = None
        if args.src_flavor_id:
            src_flavor_id = args.src_flavor_id
        else:
            src_flavor_id = source_client.nova.flavors.find(
                is_public=None, name=args.src_flavor_name)

        flavor_creation_payload = {
                'src_flavor_id': src_flavor_id}

        flavor_creation_action = flavor_actions.FlavorCreationAction(
            flavor_creation_payload,
            source_openstack_client=source_client,
            destination_openstack_client=destination_client)

        done = flavor_creation_action.check_already_done()
        flavor = None
        if done["done"]:
            flavor = done["result"]
            LOG.info(
                "Flavor '%s' Migration seemingly done."
                % flavor['name'])
        else:
            if args.not_drill:
                try:
                    flavor = flavor_creation_action.execute_operations()
                except (Exception, KeyboardInterrupt):
                    LOG.warn("Error occured while recreating flavor "
                             "'%s'. Rolling back all changes", src_flavor_id)
                    flavor_creation_action.cleanup()
                    raise
            else:
                flavor_creation_action.print_operations()
                flavor = {
                    'name': 'NOT DONE',
                    'id': 'NOT DONE',
                    'vcpus': 'NOT DONE',
                    'ram': 'NOT DONE',
                    'disk': 'NOT DONE'}

        return FlavorMigrationFormatter().list_objects([flavor])
