# Copyright 2018 Cloudbase Solutions Srl
# All Rights Reserved.

from oslo_log import log as logging

from cliff import lister

from coriolis_openstack_utils import conf
from coriolis_openstack_utils.actions import tenant_actions
from coriolis_openstack_utils.cli import formatter
from coriolis_openstack_utils.resource_utils import users


LOG = logging.getLogger(__name__)


class UserMigrationFormatter(formatter.EntityFormatter):
    columns = (
        "User Name",
        "User ID",
        "Admin Role Tenants")

    def _get_formatted_data(self, obj):
        data = (
            obj["name"],
            obj["id"],
            obj["tenants"])

        return data


class MigrateUser(lister.Lister):
    def get_parser(self, prog_name):
        parser = super(MigrateUser, self).get_parser(prog_name)
        source_group = parser.add_mutually_exclusive_group(required=True)
        source_group.add_argument(
            "--src-user-id",
            dest="src_user_id",
            help="The id of the user that is being migrated.")
        source_group.add_argument(
            "--src-user-name", dest="src_user_name",
            help="The name of the user that is being "
                 "migrated.")
        parser.add_argument(
            "--not-a-drill", dest="not_drill", action="store_true",
            default=False,
            help="If unset, tooling will only print the indented operations.")
        parser.add_argument(
            "--admin-role-tenant", dest="admin_role_tenants", nargs="+",
            default=False,
            help="If unset, tooling will add admin tenant role from migrated "
                 "tenants on source to which the user originally had the "
                 "admin role.")

        return parser

    def take_action(self, args):
        # instantiate all clients:
        source_client = conf.get_source_openstack_client()
        destination_client = conf.get_destination_openstack_client()

        src_user_id = None
        if args.src_user_name:
            user_list = users.list_users(
                source_client, filters={'name': args.src_user_name})
            if len(user_list) == 1:
                src_user_id = user_list[0].id
            elif len(user_list) > 1:
                raise Exception(
                    "Multiple users with name '%s' found! Please rename "
                    "source user or use --src-user-id parameter."
                    % args.src_user_name)
            elif not user_list:
                raise Exception(
                    "No users with name '%s' found!" % args.src_user_name)
        else:
            src_user_id = args.src_user_id

        user_creation_payload = {'src_user_id': src_user_id}

        if args.admin_role_tenants:
            user_creation_payload[
                'admin_role_tenants'] = args.admin_role_tenants

        user_creation_action = tenant_actions.UserCreationAction(
            user_creation_payload,
            source_openstack_client=source_client,
            destination_openstack_client=destination_client)

        done = user_creation_action.check_already_done()
        user = []
        if done["done"]:
            user = users.get_user(destination_client, done['result']).to_dict()
            user['tenants'] = users.get_user_admin_tenants(
                destination_client, user['id'])
            LOG.info(
                "User '%s' Migration seemingly done."
                % user['name'])
        else:
            if args.not_drill:
                try:
                    user = user_creation_action.execute_operations()
                except Exception as action_exception:
                    LOG.warn("Error occured while recreating user with id"
                             " '%s'. Rolling back all changes", src_user_id)
                    user_creation_action.cleanup()
                    raise action_exception
            else:
                user_creation_action.print_operations()
                user = {
                    'name': 'NOT DONE',
                    'id': 'NOT DONE',
                    'tenants': 'NOT DONE'}

        return UserMigrationFormatter().list_objects([user])
