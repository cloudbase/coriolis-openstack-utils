# Copyright 2018 Cloudbase Solutions Srl
# All Rights Reserved.

""" Module defining Coriolis transfer-triggering actions such as for
migrations or replicas. """

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


class MigrationCreationAction(base.BaseAction):
    action_type = base.ACTION_TYPE_CHECK_CREATE_MIGRATION

    def __init__(
            self, action_payload, source_openstack_client=None,
            coriolis_client=None, destination_openstack_client=None,
            destination_env=None):
        """
        param action_payload: dict(): instance_info dict (prevalidated!)

        self.subactions are not meant to be executed!
        """
        super(MigrationCreationAction, self).__init__(
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
        destination_enpoint_id = destination_endpoint_done["result"]

        existing_migration = None
        # NOTE: the `reversed()` is so as to take the migrations in
        # reverse chronological order in order to get the latest one:
        for migration in reversed(self._coriolis_client.migrations.list()):
            migration_dest_env = migration.destination_environment.to_dict()
            if (migration.origin_endpoint_id == source_endpoint_id and
                    migration.destination_endpoint_id == (
                        destination_enpoint_id) and utils.check_dict_equals(
                            migration_dest_env, self._destination_env)):
                if set(migration.instances) == set([instance_name]):
                    existing_migration = migration
                    break

        if existing_migration:
            if existing_migration.status == MIGRATION_STATUS_ERROR:
                LOG.info(
                    "Found existing migration with id '%s' for VM '%s', but "
                    "it is in '%s' state, thus, a new one will be created" % (
                        existing_migration.id, self.payload["instance_name"],
                        existing_migration.status))
            else:
                LOG.info(
                    "Found existing migration with id '%s' for VM '%s'. "
                    "Current status is '%s'. NOT creating a new migration.",
                    existing_migration.id, self.payload["instance_name"],
                    existing_migration.status)
                done = {
                    "done": True,
                    "result": {
                        "instance_name": instance_name,
                        "migration_id": existing_migration.id,
                        "status": existing_migration.status,
                        "origin_endpoint_id":
                            existing_migration.origin_endpoint_id,
                        "destination_endpoint_id":
                            existing_migration.destination_endpoint_id,
                        "destination_environment": self._destination_env,
                        "new": False}}

        return done

    def print_operations(self):
        # NOTE: intenrionally no subop printing:
        # super(MigrationCreationAction, self).print_operations()
        LOG.info(
            "Create migration for VM named '%s' with options: %s" % (
                self.payload["instance_name"], self._destination_env))

    def execute_operations(self, subtasks_pre_executed=False):
        if not subtasks_pre_executed:
            # NOTE: only calls super() when subtasks aren't executed
            super(MigrationCreationAction, self).print_operations()

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

        LOG.info("Creating migration for VM with options '%s'", self.payload)
        # NOTE: "instances" param must be a list:
        instance_name = self.payload["instance_name"]
        instances = [instance_name]
        source_endpoint = source_endpoint_done["result"]
        destination_enpoint = destination_endpoint_done["result"]
        if source_endpoint == destination_enpoint:
            raise Exception(
                "Source and destination connection info looks the same, "
                "cannot migrate to and from the same endpoint: %s" % (
                    source_endpoint))
        skip_os_morphing = CONF.destination.skip_os_morphing
        migration = self._coriolis_client.migrations.create(
            source_endpoint, destination_enpoint,
            self._destination_env, instances,
            skip_os_morphing=skip_os_morphing)

        LOG.info("Created new migration for VM '%s': %s" % (
            (instance_name, migration.id)))
        return {
            "instance_name": instance_name,
            "migration_id": migration.id,
            "status": migration.status,
            "origin_endpoint_id": source_endpoint,
            "destination_endpoint_id": destination_enpoint,
            "destination_environment": self._destination_env,
            "new": True}


class BatchMigrationAction(base.BaseAction):
    # TODET: maybe redundant
    action_type = base.ACTION_TYPE_BATCH_MIGRATE

    DEFAULT_BATCH_NAME = "CoriolisMigrationBatch"

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
        super(BatchMigrationAction, self).__init__(
            action_payload, source_openstack_client=source_openstack_client,
            coriolis_client=coriolis_client,
            destination_openstack_client=destination_openstack_client)

        if not self._source_openstack_client:
            raise ValueError(
                "Source OpenStack client required to migrate.")
        if not self._destination_openstack_client:
            raise ValueError(
                "Destination OpenStack client required to migrate.")
        if not destination_env:
            raise ValueError(
                "Destination environment required to migrate.")

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

        # instantiate all the migration subactions:
        self._completed_migrations = []
        for vm_info in vm_infos:
            instance_name = vm_info["instance_name"]
            LOG.info(
                "Validating configuration for VM: \"%s\"", instance_name)
            instances.validate_migration_options(
                self._source_openstack_client,
                self._destination_openstack_client,
                vm_info, self._destination_env)
            subaction = MigrationCreationAction(
                vm_info, source_openstack_client=self._source_openstack_client,
                coriolis_client=self._coriolis_client,
                destination_openstack_client=(
                    self._destination_openstack_client),
                destination_env=self._destination_env)
            done = subaction.check_already_done()
            if done["done"]:
                migr_instance_name = subaction.payload["instance_name"]
                LOG.info(
                    "Found existing migration for VM \"%s\": ID: \"%s\".",
                    migr_instance_name, done["result"])
                self._completed_migrations.append({
                    "instance_name": migr_instance_name,
                    "existing_migration_id": done["result"]})
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
                "They must either be renamed, or have migration started "
                "manually for them. Duplicates: %s" % duplicates)
        elif len(vm_names) > len(vm_infos):
            missing = []
            found_ones = [vm["instance_name"] for vm in vm_infos]
            for vm_name in vm_names:
                if vm_name not in found_ones:
                    missing.append(vm_name)
            raise Exception(
                "Could not locate the following VMs: %s", missing)

        self._migration_prep_subactions = []
        for migration_action in self.subactions:
            new_migration_subactions = []
            for action in migration_action.subactions:
                action_done = action.check_already_done()
                if action_done["done"]:
                    LOG.info("Action already done: ")
                    action.print_operations()
                    continue

                if not [existing
                        for existing in self._migration_prep_subactions
                        if action.equivalent_to(existing)]:
                    new_migration_subactions.append(action)
                    self._migration_prep_subactions.append(action)
                else:
                    LOG.info("Skipping action: ")
                    action.print_operations()
            # NOTE: we eliminate the unneeded action:
            migration_action.subactions = new_migration_subactions

    def print_operations(self):
        LOG.info(
            "###### Migrate instance batch named '%s' with VMs: '%s'" % (
                self.payload["batch_name"], self.payload["instances"]))
        LOG.info("### Supporting operations: ")
        for action in self._migration_prep_subactions:
            action.print_operations()
        LOG.info("### New migration operations: ")
        for action in self.subactions:
            action.print_operations()
        LOG.info(
            "### Pre-completed migrations: %s", self._completed_migrations)

    def equivalent_to(self, other_action):
        if self.action_type == other_action.action_type:
            return self.payload["instances"] == (
                other_action.payload["instances"])
        return False

    def check_already_done(self):
        migration_ids = []
        for migration_action in self.subactions:
            done = migration_action.check_already_done()
            if not done["done"]:
                LOG.debug(
                    "Migration not done for batch '%s'" % self._batch_name)
                return {"done": False, "result": None}
            else:
                migration_ids.append(done["result"])

        return {
            "done": True,
            "result": self._completed_migrations + migration_ids}

    def execute_operations(self):
        # perform all subactions:
        for action in self._migration_prep_subactions:
            action.execute_operations()

        # start migrations:
        migrations = []
        for migration_action in self.subactions:
            # NOTE: we pre-executed the subtasks:
            migrations.append(
                migration_action.execute_operations(
                    subtasks_pre_executed=True))

        # LOG.info("### Existing migrations: %s", self._completed_migrations)
        # LOG.info("### New migration ids: %s" % migration_ids)
        # done_ids = [migr["existing_migration_id"]
        #             for migr in self._completed_migrations]
        return migrations
