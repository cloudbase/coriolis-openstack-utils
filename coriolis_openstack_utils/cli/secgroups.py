# Copyright 2018 Cloudbase Solutions Srl
# All Rights Reserved.

from oslo_log import log as logging

from cliff import lister

from coriolis_openstack_utils import conf
from coriolis_openstack_utils.actions import secgroup_actions
from coriolis_openstack_utils.cli import formatter
from coriolis_openstack_utils.resource_utils import security_groups


LOG = logging.getLogger(__name__)


class SecurityMigrationFormatter(formatter.EntityFormatter):
    columns = (
        "Security Group Name",
        "Security Group ID",
        "Tenant ID",
        "Tenant Name")

    def _get_formatted_data(self, obj):
        data = (
            obj["destination_name"],
            obj["destination_id"],
            obj["dest_tenant_id"],
            obj["dest_tenant_name"])

        return data


class MigrateSecurityGroup(lister.Lister):
    def get_parser(self, prog_name):
        parser = super(MigrateSecurityGroup, self).get_parser(prog_name)
        source_group = parser.add_mutually_exclusive_group(required=True)
        source_group.add_argument(
            "--source-tenant-id",
            dest="src_tenant_id",
            help="The tenant id of the security group that is being migrated.")
        source_group.add_argument(
            "--source-tenant-name", dest="src_tenant_name",
            help="The tenant name of the security group that is being "
                 "migrated.")
        destination_group = parser.add_mutually_exclusive_group(required=True)
        destination_group.add_argument(
            "--destination-tenant-id",
            dest="dest_tenant_id",
            help="The tenant id of the security group that is being migrated.")
        destination_group.add_argument(
            "--destination-tenant-name", dest="dest_tenant_name",
            help="The tenant name of the security group that is being "
                 "migrated.")
        parser.add_argument(
            "--not-a-drill", dest="not_drill", action="store_true",
            default=False,
            help="If unset, tooling will only print the indented operations.")
        parser.add_argument("secgroup_name", metavar="SECURITY_GROUP")

        return parser

    def take_action(self, args):
        # instantiate all clients:
        source_client = conf.get_source_openstack_client()
        destination_client = conf.get_destination_openstack_client()

        if args.src_tenant_id:
            src_tenant_id = args.src_tenant_id
        elif args.src_tenant_name:
            src_tenant_id = source_client.get_project_id(
                args.src_tenant_name)
        if args.dest_tenant_id:
            dest_tenant_id = args.dest_tenant_id
        elif args.dest_tenant_name:
            dest_tenant_id = destination_client.get_project_id(
                args.dest_tenant_name)

        secgroup_creation_payload = {
            "source_name": args.secgroup_name,
            "src_tenant_id": src_tenant_id,
            "dest_tenant_id": dest_tenant_id}

        secgroup_creation_action = (
            secgroup_actions.SecurityGroupCreationAction(
                secgroup_creation_payload,
                source_openstack_client=source_client,
                destination_openstack_client=destination_client))

        done = secgroup_creation_action.check_already_done()
        secgroup = []
        if done["done"]:
            LOG.info(
                "Security Group %s Creation seemingly done."
                % args.secgroup_name)
            secgroup = {
                'destination_name': done["result"],
                'destination_id': security_groups.get_security_group(
                    destination_client, dest_tenant_id, done["result"])['id'],
                'dest_tenant_id': dest_tenant_id,
                'dest_tenant_name': destination_client.get_project_name(
                    dest_tenant_id)}
        else:
            if args.not_drill:
                secgroup = secgroup_creation_action.execute_operations()
            else:
                secgroup_creation_action.print_operations()
                secgroup = {
                    'destination_name': 'NOT DONE',
                    'destination_id': 'NOT DONE',
                    'dest_tenant_id': dest_tenant_id,
                    'dest_tenant_name': destination_client.get_project_name(
                        dest_tenant_id)}

        return SecurityMigrationFormatter().list_objects([secgroup])
