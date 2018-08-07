# Copyright 2018 Cloudbase Solutions Srl
# All Rights Reserved.

""" Module defining Coriolis transfer-triggering actions such as for
migrations or replicas. """

import abc
from oslo_log import log as logging

from coriolis_openstack_utils import conf
from coriolis_openstack_utils import utils
from coriolis_openstack_utils.actions import base
from coriolis_openstack_utils.actions import coriolis_endpoint_actions
from coriolis_openstack_utils.resource_utils import instances

CONF = conf.CONF
LOG = logging.getLogger(__name__)

MIGRATION_STATUS_ERROR = "ERROR"
MIGRATION_STATUS_COMPLETED = "COMPLETED"
MIGRATION_STATUS_RUNNING = "RUNNING"

REPLICA_EXECUTION_STATUS_ERROR = "ERROR"
REPLICA_EXECUTION_STATUS_NONE = "NO EXECUTION"

TRANSFER_TYPE_REPLICA = 'replica'
TRANSFER_ACTION_TYPE_REPLICA = 'replicate'

TRANSFER_TYPE_MIGRATION = 'migration'
TRANSFER_ACTION_TYPE_MIGRATION = 'migrate'


class TransferAction(base.BaseAction):

    def __init__(
            self, action_payload, source_openstack_client=None,
            coriolis_client=None, destination_openstack_client=None,
            destination_env=None):
        super(TransferAction, self).__init__(
            action_payload, source_openstack_client=source_openstack_client,
            destination_openstack_client=destination_openstack_client,
            coriolis_client=coriolis_client)
        if not destination_openstack_client:
            raise ValueError(
                "Destination openstack client required to migrate.")
        if not destination_env:
            raise ValueError(
                "Destination environment required to migrate.")

        self._destination_env = destination_env

        self.source_endpoint_create_action = (
            coriolis_endpoint_actions.SourceEndpointCreationAction(
                self.payload, coriolis_client=self._coriolis_client,
                source_openstack_client=self._source_openstack_client))
        self.dest_endpoint_create_action = (
            coriolis_endpoint_actions.DestinationEndpointCreationAction(
                self.payload, coriolis_client=self._coriolis_client,
                destination_openstack_client=(
                    self._destination_openstack_client)))

        self.subactions = [
            self.source_endpoint_create_action,
            self.dest_endpoint_create_action]

    def equivalent_to(self, other_action):
        if self.action_type == other_action.action_type:
            if utils.check_dict_equals(self.payload, other_action.payload):
                return True
        return False

    @abc.abstractmethod
    def get_transfers_list(self):
        """ Get all transfer actions of this type. """
        pass

    @abc.abstractmethod
    def check_existing_transfer(self, existing_transfer):
        """ Check existing transfer, based on status, determine if
        a new transfer action must be made. """
        pass

    @abc.abstractmethod
    def get_transfer_status(self, transfer):
        """ Get transfer action status. """
        pass

    @abc.abstractmethod
    def create_transfer(self, source_endpoint, destination_endpoint):
        """ Create transfer action. """
        pass

    def check_already_done(self):
        done = {
            "done": False,
            "result": None}
        instance_name = self.payload["instance_name"]
        source_endpoint_done = (
            self.source_endpoint_create_action.check_already_done())
        destination_endpoint_done = (
            self.dest_endpoint_create_action.check_already_done())

        if not source_endpoint_done["done"]:
            LOG.debug(
                "Source endpoint for migration for VM '%s' not done.",
                instance_name)
            return done
        source_endpoint_id = source_endpoint_done["result"]

        if not destination_endpoint_done["done"]:
            LOG.debug(
                "Destination endpoint for migration for VM '%s' not done.",
                instance_name)
            return done
        destination_endpoint_id = destination_endpoint_done["result"]

        existing_transfer = None
        for transfer in self.get_transfers_list():
            migration_dest_env = transfer.destination_environment.to_dict()
            if (transfer.origin_endpoint_id == source_endpoint_id and
                    transfer.destination_endpoint_id == (
                        destination_endpoint_id) and utils.check_dict_equals(
                            migration_dest_env, self._destination_env)):
                if set(transfer.instances) == set([instance_name]):
                    existing_transfer = transfer
                    break

        if not existing_transfer:
            return done
        else:
            return self.check_existing_transfer(existing_transfer)

    def execute_operations(self, subtasks_pre_executed=False):
        if not subtasks_pre_executed:
            # NOTE: only calls super() when subtasks aren't executed
            super(TransferAction, self).print_operations()

        source_endpoint_done = (
            self.source_endpoint_create_action.check_already_done())
        if not source_endpoint_done["done"]:
            raise Exception(
                "Source endpoint not done for instance '%s'" % (
                    self.payload))

        destination_endpoint_done = (
            self.dest_endpoint_create_action.check_already_done())
        if not destination_endpoint_done["done"]:
            raise Exception(
                "Destination endpoint not done for instance '%s'" % (
                    self.payload))

        source_endpoint = source_endpoint_done['result']
        destination_endpoint = destination_endpoint_done['result']
        transfer = self.create_transfer(source_endpoint, destination_endpoint)

        return {
            "instance_name": self.payload['instance_name'],
            "transfer_id": transfer.id,
            "status": self.get_transfer_status(transfer),
            "origin_endpoint_id": source_endpoint,
            "destination_endpoint_id": destination_endpoint,
            "destination_environment": self._destination_env,
            "new": True}

    def migration_same(self, other_migration):
        if other_migration.status != MIGRATION_STATUS_RUNNING:
            return False
        elif len(other_migration.instances) != 1:
            return False
        elif other_migration.instances[0] != self.payload['instance_name']:
            return False
        other_origin_endpoint = self._coriolis_client.endpoints.get(
            other_migration.origin_endpoint_id)
        other_dest_endpoint = self._coriolis_client.endpoints.get(
            other_migration.origin_endpoint_id)
        other_origin_project_name = getattr(
            other_origin_endpoint.connection_info,
            'project_name', 'barbican_secret')
        other_dest_project_name = getattr(
            other_dest_endpoint.connection_info,
            'project_name', 'barbican_secret')

        if (other_origin_endpoint.name !=
                self.source_endpoint_create_action.get_endpoint_name()):
            return False
        elif (other_dest_endpoint.name !=
              self.dest_endpoint_create_action.get_endpoint_name()):
            return False
        elif (other_origin_project_name !=
              self.source_endpoint_create_action.get_tenant_name()):
            return False
        elif (other_dest_project_name !=
              self.dest_endpoint_create_action.get_tenant_name()):
            return False

        return True

    def cleanup(self):
        for migration in self._coriolis_client.migrations.list():
            if self.migration_same(migration):
                self._coriolis_client.migrations.cancel(migration.id)
                self.source_endpoint_create_action.cleanup()
                self.dest_endpoint_create_action.cleanup()


class MigrationCreationAction(TransferAction):
    """ (dict) action_payload must contain:
        - (string) instance_tenant_name
        - (string) instance_name
    """
    action_type = base.ACTION_TYPE_CHECK_CREATE_MIGRATION

    def get_transfers_list(self):
        return reversed(self._coriolis_client.migrations.list())

    def get_transfer_status(self, transfer):
        return transfer.status

    def check_existing_transfer(self, existing_transfer):
        migration = existing_transfer
        if migration.status == MIGRATION_STATUS_ERROR:
            LOG.info(
                "Found existing migration with id '%s' for VM '%s', but "
                "it is in '%s' state, thus, a new one will be created" % (
                    migration.id, self.payload["instance_name"],
                    migration.status))
            done = {
                "done": False,
                "result": None}
            return done
        else:
            LOG.info(
                "Found existing migration with id '%s' for VM '%s'. "
                "Current status is '%s'. NOT creating a new migration.",
                migration.id, self.payload["instance_name"],
                migration.status)
            done = {
                "done": True,
                "result": {
                    "instance_name": self.payload['instance_name'],
                    "transfer_id": migration.id,
                    "status": migration.status,
                    "origin_endpoint_id":
                        migration.origin_endpoint_id,
                    "destination_endpoint_id":
                        migration.destination_endpoint_id,
                    "destination_environment": self._destination_env,
                    "new": False}}

        return done

    def print_operations(self):
        # NOTE: intentionally no subop printing:
        # super(MigrationCreationAction, self).print_operations()
        LOG.info(
            "Create migration for VM named '%s' with options: %s" % (
                self.payload["instance_name"], self._destination_env))

    def create_transfer(self, source_endpoint, destination_endpoint):
        skip_os_morphing = CONF.destination.skip_os_morphing
        return self._coriolis_client.migrations.create(
            source_endpoint, destination_endpoint,
            self._destination_env, [self.payload['instance_name']],
            skip_os_morphing=skip_os_morphing)


class ReplicaCreationAction(TransferAction):
    """ (dict) action_payload must contain:
        - (string) instance_tenant_name
        - (string) instance_name
        - (boolean) execute_replica
    """
    action_type = base.ACTION_TYPE_CHECK_CREATE_REPLICA

    @staticmethod
    def last_execution_status(replica):
        if replica.executions:
            return sorted(
                replica.executions,
                key=lambda execution: execution.created_at,
                reverse=True)[0].status
        return REPLICA_EXECUTION_STATUS_NONE

    def get_transfers_list(self):
        return reversed(self._coriolis_client.replicas.list())

    def get_transfer_status(self, transfer):
        status = "NOT EXECUTED"
        if transfer.executions:
            last_execution_status = self.last_execution_status(transfer)
            status = "EXECUTION " + last_execution_status

        return status

    def check_existing_transfer(self, existing_transfer):
        replica = existing_transfer
        last_execution_status = self.last_execution_status(
            replica)

        if last_execution_status == REPLICA_EXECUTION_STATUS_ERROR:
            LOG.info(
                "Found existing execution for replica with id '%s' "
                "for VM '%s', but execution is in '%s' state, thus, a new one "
                "will be created" % (replica.id, self.payload["instance_name"],
                                     last_execution_status))
            done = {
                "done": False,
                "result": None,
            }
            return done
        else:
            LOG.info(
                "Found existing replica with id '%s' for VM '%s'. "
                "Current execution status is '%s'. NOT creating a new "
                "execution.", replica.id, self.payload["instance_name"],
                last_execution_status)
            done = {
                "done": True,
                "result": {
                    "instance_name": self.payload['instance_name'],
                    "transfer_id": replica.id,
                    "status": self.get_transfer_status(replica),
                    "origin_endpoint_id":
                        replica.origin_endpoint_id,
                    "destination_endpoint_id":
                        replica.destination_endpoint_id,
                    "destination_environment": self._destination_env,
                    "new": False}}

        return done

    def create_transfer(self, source_endpoint, destination_endpoint):
        replica = self._coriolis_client.replicas.create(
            source_endpoint, destination_endpoint,
            self._destination_env, [self.payload['instance_name']])

        if self.payload['execute_replica'] is True:
            shutdown_instances = CONF.destination.shutdown_instances
            self._coriolis_client.replica_executions.create(
                replica.id, shutdown_instances=shutdown_instances)

        return replica

    def print_operations(self):
        # NOTE: intentionally no subop printing:
        # super(MigrationCreationAction, self).print_operations()
        LOG.info(
            "Create migration for VM named '%s' with options: %s" % (
                self.payload["instance_name"], self._destination_env))


class BatchTransferAction(base.BaseAction):
    DEFAULT_BATCH_NAME = "CoriolisTransferBatch"

    @abc.abstractproperty
    def transfer_type(self):
        """replica or migration"""
        pass

    @abc.abstractproperty
    def transfer_action_type(self):
        """replicate or migrate"""
        pass

    @abc.abstractmethod
    def create_transfer_subaction(self, vm_info):
        pass

    def __init__(
            self, action_payload, source_openstack_client=None,
            coriolis_client=None, destination_openstack_client=None,
            destination_env=None):
        """
        param action_payload: dict(): dict of the form: {
            "instances": ["vmname1", "vmname2", "vmname3", ...],
            "batch_name": "string batch name",
            "create_tenants": True/False
        }
        """
        super(BatchTransferAction, self).__init__(
            action_payload, source_openstack_client=source_openstack_client,
            coriolis_client=coriolis_client,
            destination_openstack_client=destination_openstack_client)

        if not self._source_openstack_client:
            raise ValueError(
                "Source OpenStack client required to %s ."
                % self.transfer_action_type)
        if not self._destination_openstack_client:
            raise ValueError(
                "Destination OpenStack client required to %s ."
                % self.transfer_action_type)
        if not destination_env:
            raise ValueError(
                "Destination environment required to %s ."
                % self.transfer_action_type)

        self._create_tenants = self.payload.get("create_tenants", False)
        self._source_openstack_client = source_openstack_client
        self._destination_env = destination_env
        self._destination_openstack_client = destination_openstack_client
        self._batch_name = self.payload.get(
            "batch_name", self.DEFAULT_BATCH_NAME)

        vm_names = action_payload.get("instances")
        if not vm_names:
            raise ValueError("No VMs provided for batch: %s" % vm_names)

        LOG.info("Gathering info on selected VMs.")
        vm_infos = instances.find_source_instances_by_name(
            self._source_openstack_client, vm_names)

        # instantiate all the transfer subactions:
        self._completed_transfers = []
        for vm_info in vm_infos:
            instance_name = vm_info["instance_name"]
            LOG.info(
                "Validating configuration for VM: \"%s\"", instance_name)
            instances.validate_transfer_options(
                self._source_openstack_client,
                self._destination_openstack_client,
                vm_info, self._destination_env)
            subaction = self.create_transfer_subaction(vm_info)
            done = subaction.check_already_done()
            if done["done"]:
                transfer_instance_name = subaction.payload["instance_name"]
                LOG.info(
                    "Found existing %s for VM \"%s\": ID: \"%s\".",
                    self.transfer_type, transfer_instance_name, done["result"])
                self._completed_transfers.append({
                    "instance_name": transfer_instance_name,
                    "existing_%s_id" % self.transfer_type: done["result"]})
                continue
            self.subactions.append(subaction)

        if len(vm_names) < len(vm_infos):
            processed = []
            duplicates = []
            for vm_info in vm_infos:
                vm_name = vm_info["instance_name"]
                if vm_name in processed:
                    duplicates.append("VM: %s (tenant %s)" % (
                        vm_name, vm_info["instance_tenant_name"]))
                processed.append(vm_name)
            raise Exception(
                "There are instances with identical names on the source. "
                "They must either be renamed, or have %s started "
                "manually for them. Duplicates: %s" %
                (self.transfer_action_type + "s", duplicates))
        elif len(vm_names) > len(vm_infos):
            missing = []
            found_ones = [vm["instance_name"] for vm in vm_infos]
            for vm_name in vm_names:
                if vm_name not in found_ones:
                    missing.append(vm_name)
            raise Exception(
                "Could not locate the following VMs: %s", missing)

        self._transfer_prep_subactions = []
        for transfer_action in self.subactions:
            new_transfer_subactions = []
            for action in transfer_action.subactions:
                action_done = action.check_already_done()
                if action_done["done"]:
                    LOG.info("Action already done: ")
                    action.print_operations()
                    continue

                if not [existing
                        for existing in self._transfer_prep_subactions
                        if action.equivalent_to(existing)]:
                    new_transfer_subactions.append(action)
                    self._transfer_prep_subactions.append(action)
                else:
                    LOG.info("Skipping action: ")
                    action.print_operations()
            # NOTE: we eliminate the unneeded action:
            transfer_action.subactions = new_transfer_subactions

    def print_operations(self):
        LOG.info(
            "###### %s instance batch named '%s' with VMs: '%s'" % (
                self.transfer_type.capitalize(),
                self.payload["batch_name"], self.payload["instances"]))
        LOG.info("### Supporting operations: ")
        for action in self._transfer_prep_subactions:
            action.print_operations()
        LOG.info("### New  %s operations: " % self.transfer_type)
        for action in self.subactions:
            action.print_operations()
        LOG.info(
            "### Pre-completed %s : %s", self.transfer_type + 's',
            self._completed_transfers)

    def equivalent_to(self, other_action):
        if self.action_type == other_action.action_type:
            return self.payload["instances"] == (
                other_action.payload["instances"])
        return False

    def check_already_done(self):
        transfer_ids = []
        for migration_action in self.subactions:
            done = migration_action.check_already_done()
            if not done["done"]:
                LOG.debug(
                    "%s not done for batch '%s'" %
                    (self.transfer_type.capitalize(), self._batch_name))
                return {"done": False, "result": None}
            else:
                transfer_ids.append(done["result"])

        return {
            "done": True,
            "result": self._completed_transfers + transfer_ids}

    def execute_operations(self):
        # perform all subactions:
        for action in self._transfer_prep_subactions:
            action.execute_operations()

        # start migrations:
        transfers = []
        for transfer_action in self.subactions:
            # NOTE: we pre-executed the subtasks:
            transfers.append(
                transfer_action.execute_operations(
                    subtasks_pre_executed=True))

        # LOG.info("### Existing migrations: %s", self._completed_migrations)
        # LOG.info("### New migration ids: %s" % migration_ids)
        # done_ids = [migr["existing_migration_id"]
        #             for migr in self._completed_migrations]

        return transfers

    def cleanup(self):
        for action in self.subactions:
            action.cleanup()
        for action in self._transfer_prep_subactions:
            action.cleanup()


class BatchMigrationAction(BatchTransferAction):
    action_type = base.ACTION_TYPE_BATCH_MIGRATE

    @property
    def transfer_type(self):
        return TRANSFER_TYPE_MIGRATION

    @property
    def transfer_action_type(self):
        return TRANSFER_ACTION_TYPE_MIGRATION

    def create_transfer_subaction(self, vm_info):
        return MigrationCreationAction(
            vm_info, source_openstack_client=self._source_openstack_client,
            destination_openstack_client=self._destination_openstack_client,
            destination_env=self._destination_env,
            coriolis_client=self._coriolis_client)


class BatchReplicaAction(BatchTransferAction):
    action_type = base.ACTION_TYPE_BATCH_REPLICATE

    @property
    def transfer_type(self):
        return TRANSFER_TYPE_REPLICA

    @property
    def transfer_action_type(self):
        return TRANSFER_ACTION_TYPE_REPLICA

    def create_transfer_subaction(self, vm_info):
        vm_info['execute_replica'] = self.payload['execute_replica']
        return ReplicaCreationAction(
            vm_info, source_openstack_client=self._source_openstack_client,
            destination_openstack_client=self._destination_openstack_client,
            destination_env=self._destination_env,
            coriolis_client=self._coriolis_client)
