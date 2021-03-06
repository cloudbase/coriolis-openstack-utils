# Copyright 2018 Cloudbase Solutions Srl
# All Rights Reserved.

from oslo_log import log as logging

from cliff import lister

from coriolis_openstack_utils import conf
from coriolis_openstack_utils.actions import tenant_actions
from coriolis_openstack_utils.cli import formatter


LOG = logging.getLogger(__name__)


class TenantMigrationFormatter(formatter.EntityFormatter):
    columns = (
        "Tenant Name",
        "Tenant ID")

    def _get_formatted_data(self, obj):
        data = (
            obj["name"],
            obj["id"])

        return data


class MigrateTenant(lister.Lister):
    def get_parser(self, prog_name):
        parser = super(MigrateTenant, self).get_parser(prog_name)
        source_group = parser.add_mutually_exclusive_group(required=True)
        source_group.add_argument(
            "--src-tenant-id",
            dest="src_tenant_id",
            help="The tenant id of the security group that is being migrated.")
        source_group.add_argument(
            "--src-tenant-name", dest="src_tenant_name",
            help="The tenant name of the security group that is being "
                 "migrated.")
        instance_options = parser.add_mutually_exclusive_group(required=True)
        instance_options.add_argument(
            "--all-instances", dest="all_instances", action="store_true",
            help="Migrate all instances from source to destination tenant.")
        instance_options.add_argument(
            "--no-instances", dest="no_instances", action="store_true",
            help="Do not migrate any source instances to the destination "
                 "tenant.")
        instance_options.add_argument(
            "--instances", dest="instances", nargs='+',
            help="List of instance names to be migrated.")
        parser.add_argument(
            "--not-a-drill", dest="not_drill", action="store_true",
            default=False,
            help="If unset, tooling will only print the indented operations.")
        replica_group = parser.add_argument_group(
            'Replica Options', 'options related to replicas.')
        replica_group.add_argument(
            "--use-replicas", dest="use_replicas", action="store_true",
            help="If set, tooling will create replicas for selected "
                 "instances.")
        replica_group.add_argument(
            "--execute-replicas", dest='execute_replicas',
            action='store_true',
            help='If set, replicas will be executed.')
        parser.add_argument(
            "--replicate-flavors", dest='replicate_flavors',
            action='store_true',
            help='If set, all source flavors will be recreated on '
                 'destination.')

        return parser

    def take_action(self, args):
        # instantiate all clients:
        source_client = conf.get_source_openstack_client()
        destination_client = conf.get_destination_openstack_client()
        coriolis_client = conf.get_coriolis_client()

        if args.src_tenant_id:
            src_tenant_name = source_client.get_project_name(
                args.src_tenant_id)
        elif args.src_tenant_name:
            src_tenant_name = args.src_tenant_name

        tenant_creation_payload = {
            "tenant_name": src_tenant_name,
            "use_replicas": args.use_replicas,
            "execute_replicas": args.execute_replicas,
            "replicate_flavors": args.replicate_flavors
            }
        if args.no_instances:
            tenant_creation_payload['instances'] = None
        elif args.all_instances:
            tenant_creation_payload['instances'] = []
        elif args.instances:
            tenant_creation_payload['instances'] = args.instances

        tenant_creation_action = (
            tenant_actions.WholeTenantCreationAction(
                tenant_creation_payload,
                source_openstack_client=source_client,
                destination_openstack_client=destination_client,
                coriolis_client=coriolis_client))

        done = tenant_creation_action.check_already_done()
        tenant = None
        if done["done"]:
            LOG.info(
                "Tenant %s Creation seemingly done."
                % done["result"])
            tenant = {
                'name': done["result"],
                'id': destination_client.get_project_id(done["result"])}
        else:
            if args.not_drill:
                try:
                    tenant = tenant_creation_action.execute_operations()
                except (Exception, KeyboardInterrupt):
                    LOG.warn("Error occured while recreating source tenant "
                             "'%s'. Rolling back changes", src_tenant_name)
                    tenant_creation_action.cleanup()
                    raise
            else:
                tenant_creation_action.print_operations()
                tenant = {
                    'id': 'NOT DONE',
                    'name': 'NOT DONE'}

        return TenantMigrationFormatter().list_objects([tenant])
