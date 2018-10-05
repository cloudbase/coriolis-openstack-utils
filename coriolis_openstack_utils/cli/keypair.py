# Copyright 2018 Cloudbase Solutions Srl
# All Rights Reserved.

from oslo_log import log as logging

from cliff import lister

from coriolis_openstack_utils import conf
from coriolis_openstack_utils.actions import keypair_actions
from coriolis_openstack_utils.cli import formatter


LOG = logging.getLogger(__name__)


class KeypairMigrationFormatter(formatter.EntityFormatter):
    columns = (
        "Keypair Name",
        "Keypair Fingerprint",
        "User ID")

    def _get_formatted_data(self, obj):
        data = (
            obj["name"],
            obj["fingerprint"],
            obj["user_id"])

        return data


class MigrateKeypair(lister.Lister):
    def get_parser(self, prog_name):
        parser = super(MigrateKeypair, self).get_parser(prog_name)
        parser.add_argument(
            "--src-keypair-name",
            dest="src_keypair_name", required=True,
            help="The name of the keypair that is being migrated.")
        parser.add_argument(
            "--not-a-drill", dest="not_drill", action="store_true",
            default=False,
            help="If unset, tooling will only print the indented operations.")

        return parser

    def take_action(self, args):
        # instantiate all clients:
        source_client = conf.get_source_openstack_client()
        destination_client = conf.get_destination_openstack_client()

        keypair_creation_payload = {'src_keypair_name': args.src_keypair_name}
        keypair_creation_action = keypair_actions.KeypairCreationAction(
            keypair_creation_payload,
            source_openstack_client=source_client,
            destination_openstack_client=destination_client)

        done = keypair_creation_action.check_already_done()
        keypair = []
        if done["done"]:
            keypair = done["result"]
            LOG.info(
                "Keypair '%s' Migration seemingly done."
                % keypair['name'])
        else:
            if args.not_drill:
                try:
                    keypair = keypair_creation_action.execute_operations()
                except Exception as action_exception:
                    LOG.warn("Error occured while recreating keypair"
                             " \"%s\". Rolling back all changes",
                             args.src_keypair_name)
                    keypair_creation_action.cleanup()
                    raise action_exception
            else:
                keypair_creation_action.print_operations()
                keypair = {
                    'name': 'NOT DONE',
                    'fingerprint': 'NOT DONE',
                    'user_id': 'NOT DONE'}

        return KeypairMigrationFormatter().list_objects([keypair])
