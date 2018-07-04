# Copyright 2018 Cloudbase Solutions Srl
# All Rights Reserved.

from oslo_log import log as logging

from cliff import lister

from coriolis_openstack_utils.actions import coriolis_transfer_actions
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
            obj["migration_id"],
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
            "--dont-recreate-tenants",
            dest="dont_recreate_tenants", default=False, action="store_true",
            help="Whether or not to use existing tenants on the destination, "
                 "or attempt to create a new corrresponding one for each "
                 "source tenant.")
        parser.add_argument(
            "--batch-name", dest="batch_name",
            default="MigrationBatch",
            help="Human-readable name/id for the batch.")
        parser.add_argument(
            "--not-a-drill", dest="not_drill", action="store_true",
            default=False,
            help="If unset, tooling will only print the indented operations.")
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
            "batch_name": batch_name,
            "create_tenants": not args.dont_recreate_tenants}
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
                migrations = batch_migration_action.execute_operations()
            else:
                batch_migration_action.print_operations()

        return MigrationFormatter().list_objects(migrations)
