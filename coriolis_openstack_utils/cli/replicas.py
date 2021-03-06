# Copyright 2018 Cloudbase Solutions Srl
# All Rights Reserved.

from oslo_log import log as logging

from cliff import lister

from coriolis_openstack_utils.actions import coriolis_transfer_actions
from coriolis_openstack_utils import conf
from coriolis_openstack_utils.cli import formatter


LOG = logging.getLogger(__name__)


class ReplicaFormatter(formatter.EntityFormatter):
    columns = (
        "Instance Name",
        "Replica ID",
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


class CreateReplicas(lister.Lister):
    def get_parser(self, prog_name):
        parser = super(CreateReplicas, self).get_parser(prog_name)
        parser.add_argument(
            "--batch-name", dest="batch_name",
            default="ReplicaBatch",
            help="Human-readable name/id for the batch.")
        parser.add_argument(
            "--execute-replicas", dest="execute_replica", action="store_true",
            default=False,
            help="If set, replicas will be automatically executed.")
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
        execute_replica = args.execute_replica
        replica_payload = {
            "instances": source_vms,
            "batch_name": batch_name,
            "execute_replica": execute_replica}
        batch_replica_action = (
            coriolis_transfer_actions.BatchReplicaAction(
                replica_payload, source_openstack_client=source_client,
                destination_openstack_client=destination_client,
                coriolis_client=coriolis, destination_env=dest_env))

        replicas = []
        done = batch_replica_action.check_already_done()
        if done["done"]:
            LOG.info(
                "Batch seemingly done. (a replica for each VM in the "
                "batch which has equivalent endpoint details was found)")
        else:
            if args.not_drill:
                try:
                    replicas = batch_replica_action.execute_operations()
                except (Exception, KeyboardInterrupt):
                    LOG.warn("Error occured while creating replicas for "
                             "instances '%s'. Rolling back all changes",
                             source_vms)
                    batch_replica_action.cleanup()
                    raise

            else:
                batch_replica_action.print_operations()

        return ReplicaFormatter().list_objects(replicas)
