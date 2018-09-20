# Copyright 2018 Cloudbase Solutions Srl
# All Rights Reserved.

from oslo_log import log as logging

from cliff import lister

from coriolis_openstack_utils.actions import coriolis_transfer_actions
from coriolis_openstack_utils.actions import flavor_actions
from coriolis_openstack_utils import conf
from coriolis_openstack_utils.cli import formatter


LOG = logging.getLogger(__name__)


class MigrationFormatter(formatter.EntityFormatter):
    columns = (
        "Instance Name",
        "Migration ID",
        "Status",
        "Origin Endpoint ID",
        "Destination Endpoint ID",
        "Destination Environment",
        "New")

    def _get_formatted_data(self, obj):
        data = (
            obj["instance_name"],
            obj["transfer_id"],
            obj["status"],
            obj["origin_endpoint_id"],
            obj["destination_endpoint_id"],
            obj["destination_environment"],
            obj["new"])

        return data


class CreateMigrations(lister.Lister):
    def get_parser(self, prog_name):
        parser = super(CreateMigrations, self).get_parser(prog_name)
        parser.add_argument(
            "--batch-name", dest="batch_name",
            default="MigrationBatch",
            help="Human-readable name/id for the batch.")
        parser.add_argument(
            "--not-a-drill", dest="not_drill", action="store_true",
            default=False,
            help="If unset, tooling will only print the indented operations.")
        parser.add_argument(
            "--replicate-flavors", dest="replicate_flavors",
            action="store_true", default=False,
            help="If set, all source flavors will be recreated on "
                 "destination.")

        parser.add_argument(
            "instances", metavar="INSTANCE_NAME", nargs="+")
        return parser

    def take_action(self, args):
        # instantiate all clients:
        coriolis = conf.get_coriolis_client()
        source_client = conf.get_source_openstack_client()
        destination_client = conf.get_destination_openstack_client()
        dest_env = conf.get_destination_openstack_environment()

        source_vms = args.instances
        batch_name = args.batch_name
        migration_payload = {
            "instances": source_vms,
            "batch_name": batch_name}
        batch_migration_action = (
            coriolis_transfer_actions.BatchMigrationAction(
                migration_payload, source_openstack_client=source_client,
                destination_openstack_client=destination_client,
                coriolis_client=coriolis, destination_env=dest_env))

        migrations = []
        done = batch_migration_action.check_already_done()
        if done["done"]:
            LOG.info(
                "Batch seemingly done. (a migration for each VM in the "
                "batch which has equivalent endpoint details was found)")
        else:
            if args.not_drill:
                try:
                    migrations = batch_migration_action.execute_operations()
                except Exception as action_migration:
                    LOG.warn("Error occured while creating migrations for "
                             "instances '%s'. Rolling back all changes",
                             source_vms)
                    batch_migration_action.cleanup()
                    raise action_migration
            else:
                batch_migration_action.print_operations()

        if args.replicate_flavors:
            for flavor in source_client.nova.flavors.list(is_public=None):
                flavor_migration_action = (
                        flavor_actions.FlavorCreationAction(
                            {'src_flavor_id': flavor.id},
                            source_openstack_client=source_client,
                            destination_openstack_client=destination_client,
                            coriolis_client=coriolis))
                try:
                    if args.not_drill:
                        flavor_migration_action.execute_operations()
                    else:
                        flavor_migration_action.print_operations()
                except Exception as action_exception:
                    LOG.warn("Error occured while recreating flavor "
                             "'%s'. Rolling back all changes", flavor.id)
                    flavor_migration_action.cleanup()
                    raise action_exception

        return MigrationFormatter().list_objects(migrations)
