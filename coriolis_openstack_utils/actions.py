# Copyright 2018 Cloudbase Solutions Srl
# All Rights Reserved.

import abc
import copy
import time
from six import with_metaclass

from oslo_log import log as logging

from coriolis_openstack_utils import conf
from coriolis_openstack_utils import instances
from coriolis_openstack_utils import openstack_client
from coriolis_openstack_utils import utils


CONF = conf.CONF

ACTION_TYPE_BATCH_MIGRATE = "create_batch_migration"
ACTION_TYPE_CHECK_CREATE_SOURCE_ENDPOINT = "create_source_endpoint"
ACTION_TYPE_CHECK_CREATE_DESTINATION_ENDPOINT = "create_destination_endpoint"
ACTION_TYPE_CHECK_CREATE_TENANT = "create_tenant"
ACTION_TYPE_CHECK_CREATE_MIGRATION = "create_migration"

LOG = logging.getLogger(__name__)


class Action(object, with_metaclass(abc.ABCMeta)):

    @abc.abstractproperty
    def action_type(self):
        pass

    def __init__(self, openstack_client, coriolis_client, action_payload):
        """
        param action_client: type of client needed for the action
        param action_payload: dict(): payload (params) for the action
        """
        self._openstack_client = openstack_client
        self._coriolis_client = coriolis_client
        self.payload = action_payload
        self.subactions = []

    @abc.abstractmethod
    def equivalent_to(self, other_action):
        """ Returns True or False of equivalent to other actions.
        Subactions equivalency is considered implied.
        """
        pass

    @abc.abstractmethod
    def check_already_done(self):
        """ Returns dict of the form:
        {
            "done": True/False,    # whether the action needs doing
            "result": <res type>,  # whatever result would have come out
        }
        """
        pass

    def print_operations(self):
        """
        Prints all operations to be perfomed (including suboperations)
        """
        for action in self.subactions:
            action.print_operations()

    def execute_operations(self):
        """
        Executes the needed operations and returns some status info.
        """
        for action in self.subactions:
            action.execute_operations()


"""
{
    "instance_name": "",
    "instance_id": "",
    "instance_tenant_id": "",
    "instance_tenant_name": "",
    "fixed IP addresses": ["ip1", "ip2"],
    "attached_networks": ["net1", "net2", ...],
    "attached_storage": ["cindervoltype1", "cindervoltype2", ...]
}
"""


class TenantCreationAction(Action):

    action_type = ACTION_TYPE_CHECK_CREATE_TENANT
    NEW_PROJECT_DESCRIPTION = (
        "Created by the Coriolis OpenStack utilities for source tenant '%s'.")

    @property
    def tenant_name_format(self):
        return CONF.destination.new_tenant_name_format

    def get_new_tenant_name(self):
        return self.tenant_name_format % {
            "original": self.payload["instance_tenant_name"]}

    def _update_tenant_quotas(self):
        """ Updates all tenant quotas necessary for the migration.

        Updates quotas are:
            - neutron/security_group -- set to -1 (unlimited)
            - cinder/volumes -- set to -1 (unlimited)
            - nova/instances -- set to -1 (unlimited)
        """
        tenant_name = self.get_new_tenant_name()
        tenant_id = self._openstack_client.get_project_id(tenant_name)

        # update Neutron quotas:
        neutron_quotas = CONF.destination.new_tenant_neutron_quotas
        updated_neutron_quotas = {
            k: int(neutron_quotas[k]) for k in neutron_quotas}
        LOG.info(
            "Adding Neutron quotas for tenant '%s': %s",
            tenant_name, updated_neutron_quotas)
        self._openstack_client.neutron.update_quota(
            tenant_id, body={"quota": updated_neutron_quotas})

        # update Cinder quotas:
        cinder_quotas = CONF.destination.new_tenant_cinder_quotas
        updated_cinder_quotas = {
            k: int(cinder_quotas[k]) for k in cinder_quotas}
        LOG.info(
            "Adding Cinder quotas for tenant '%s': %s",
            tenant_name, updated_cinder_quotas)
        self._openstack_client.cinder.quotas.update(
            tenant_id, **updated_cinder_quotas)

        # update Nova quotas:
        nova_quotas = CONF.destination.new_tenant_nova_quotas
        updated_nova_quotas = {
            k: int(nova_quotas[k]) for k in nova_quotas}
        LOG.info(
            "Adding Nova quotas for tenant '%s': %s",
            tenant_name, updated_nova_quotas)
        self._openstack_client.nova.quotas.update(
            tenant_id, **updated_nova_quotas)

    def _allow_secgroup_traffic(self):
        tenant_name = self.get_new_tenant_name()
        tenant_id = self._openstack_client.get_project_id(
            tenant_name)

        # NOTE: in order to see the new secgroup we must use the
        # right tenant name:
        new_connection_info = copy.deepcopy(
            self._openstack_client.connection_info)
        new_connection_info["project_name"] = tenant_name
        new_client = openstack_client.OpenStackClient(new_connection_info)

        # NOTE: secgroup may not have been created yet, wait for it:
        LOG.info(
            "Waiting for tenant '%s' default security group creation.",
            tenant_name)
        while True:
            secgroups = new_client.neutron.list_security_groups()[
                "security_groups"]
            secgroups = [s for s in secgroups if s["tenant_id"] == tenant_id]
            if len(secgroups) > 1:
                raise Exception(
                    "Multiple 'default' secgroups found in destination tenant "
                    "'%s'. Please delete all but one, or rerun without the "
                    "tenant security group option." % tenant_name)

            if not secgroups:
                time.sleep(4)
            else:
                break

        # NOTE: the 'default' secgroup should always be there:
        secgroup = secgroups[0]
        generic_allow_rule = {
            "security_group_id": secgroup["id"],
            # NOTE: egress traffic is allowed by default:
            "direction": "ingress",
            # NOTE: intentionally not setting 'port_range_{min,max}'
            "remote_ip_prefix": "0.0.0.0/0"}

        protocols = CONF.destination.new_tenant_allowed_protocols
        for protocol in protocols:
            rule = copy.deepcopy(generic_allow_rule)
            rule["protocol"] = protocol

            LOG.info(
                "Adding rule to allow '%s' traffic in new tenant '%s'",
                protocol, tenant_name)
            new_client.neutron.create_security_group_rule({
                "security_group_rule": rule})

    def equivalent_to(self, other_action):
        if other_action.action_type == self.action_type:
            if self.payload["instance_tenant_name"] == (
                    other_action.payload.get("instance_tenant_name")):
                return True

        return False

    def print_operations(self):
        super(TenantCreationAction, self).print_operations()
        tenant_name = self.get_new_tenant_name()
        LOG.info(
            "Create new destination tenant named '%s' "
            "and set appropriate usage quotas. " % (
                tenant_name))

    def check_already_done(self):
        tenant_name = self.get_new_tenant_name()

        for tenant in self._openstack_client.list_project_names():
            if tenant == tenant_name:
                LOG.debug("Tenant with name '%s' already exists. Skipping." % (
                    tenant_name))
                return {"done": True, "result": tenant_name}
        return {"done": False, "result": None}

    def execute_operations(self):
        super(TenantCreationAction, self).print_operations()
        original_tenant_name = self.payload["instance_tenant_name"]
        tenant_name = self.get_new_tenant_name()

        done = self.check_already_done()
        if done["done"]:
            LOG.info(
                "Tenant named '%s' already exists, updating quotas.",
                tenant_name)
            self._update_tenant_quotas()
            return done["result"]

        description = self.NEW_PROJECT_DESCRIPTION % original_tenant_name
        LOG.info("Creating destination tenant with name '%s'" % tenant_name)
        new_project_id = self._openstack_client.create_project(
            tenant_name, description)

        LOG.info(
            "Waiting for creation of destination tenant '%s'.", tenant_name)
        # NOTE: depending on the destination OpenStack setup, the above tenant
        # might not be immediately visible, so we must wait for it:
        self._openstack_client.wait_for_project_creation(tenant_name)

        # add user roles:
        LOG.info("Adding admin user(s) to new tenant '%s'", tenant_name)
        users = [self._openstack_client.connection_info["username"]]
        users.extend(
            CONF.destination.new_tenant_admin_users)
        for user in users:
            self._openstack_client.add_admin_role_to_project(
                tenant_name, user,
                admin_role_name=CONF.destination.admin_role_name)

        # update quotas:
        self._update_tenant_quotas()

        # open default secgroup:
        if CONF.destination.new_tenant_open_default_secgroup:
            self._allow_secgroup_traffic()

        return new_project_id


class SourceEndpointCreationAction(Action):
    """
    NOTE: should be instantiated with the OpenStackClient for source/dest.
    """

    ENDPOINT_TYPE_SOURCE = "source"
    ENDPOINT_TYPE_DESTINATION = "destination"

    ENDPOINT_TYPE_OPENSTACK = "openstack"
    DEFAULT_REGION_NAME = "NoRegion"
    DEFAULT_ENDPOINT_DESCRIPTION = "Created by the Coriolis OpenStack utils."
    SOURCE_TENANT_NAME_FORMAT = "%(original)s"

    action_type = ACTION_TYPE_CHECK_CREATE_SOURCE_ENDPOINT

    @property
    def endpoint_type(self):
        return self.ENDPOINT_TYPE_SOURCE

    @property
    def tenant_name_format(self):
        return self.SOURCE_TENANT_NAME_FORMAT

    @property
    def endpoint_name_format(self):
        return CONF.source.endpoint_name_format

    def get_tenant_name(self):
        return self.tenant_name_format % {
            "original": self.payload["instance_tenant_name"]}

    def get_endpoint_name(self):
        connection_info = self._openstack_client.connection_info
        return self.endpoint_name_format % {
            "region": connection_info.get(
                "region_name", self.DEFAULT_REGION_NAME),
            "tenant": self.get_tenant_name(),
            "user": connection_info["username"]}

    def equivalent_to(self, other_action):
        if other_action.action_type == self.action_type:
            # NOTE: we only really need to check the tenant name, as
            # connection info should be the same, and the same action
            # type scoping won't lead to source endpoints overriding
            # destination endpoints or vice-versa.
            if (self.payload["instance_tenant_name"] ==
                    other_action.payload["instance_tenant_name"]):
                return True

        return False

    def print_operations(self):
        super(SourceEndpointCreationAction, self).print_operations()
        tenant_name = self.get_tenant_name()
        connection_info = self._openstack_client.connection_info
        host_auth_url = connection_info["auth_url"]
        endpoint_name = self.get_endpoint_name()

        LOG.info(
            "Create %s endpoint named '%s' for tenant '%s' with "
            "connection info for host '%s'." % (
                self.endpoint_type, endpoint_name,
                tenant_name, host_auth_url))

    def check_already_done(self):
        super(SourceEndpointCreationAction, self).execute_operations()
        connection_info = copy.deepcopy(
            self._openstack_client.connection_info)
        # override the con info with the right one:
        tenant_name = self.get_tenant_name()
        connection_info["project_name"] = tenant_name

        endpoint_name = self.get_endpoint_name()
        existing_endpoint = None
        done = {"done": False, "result": None}
        endpoint_name = None
        for endpoint in self._coriolis_client.endpoints.list():
            existing_connection_info = endpoint.connection_info.to_dict()
            conn_infos_equal = utils.check_dict_equals(
                connection_info, existing_connection_info)
            if endpoint.name == endpoint_name:
                if not conn_infos_equal:
                    raise Exception(
                        "Found existing %s endpoint named '%s' (ID '%s') with "
                        "conn info '%s' (expecting conn info '%s')" % (
                            self.endpoint_type, endpoint_name, endpoint.id,
                            existing_connection_info, connection_info))

                LOG.debug("Found existing %s endpoint named '%s'",
                          self.endpoint_type, endpoint_name)
                existing_endpoint = endpoint
                break
            elif conn_infos_equal:
                LOG.debug(
                    "Found existing %s endpoint with conn info '%s': ID '%s'",
                    self.endpoint_type, connection_info, endpoint.id)
                existing_endpoint = endpoint
                break

        if existing_endpoint:
            done = {"done": True, "result": existing_endpoint.id}

        return done

    def execute_operations(self):
        done = self.check_already_done()
        if done["done"]:
            return done["result"]

        connection_info = copy.deepcopy(
            self._openstack_client.connection_info)
        tenant_name = self.get_tenant_name()
        connection_info["project_name"] = tenant_name

        endpoint_name = self.get_endpoint_name()

        LOG.info("Creating new endpoint named '%s'", endpoint_name)
        endpoint = self._coriolis_client.endpoints.create(
            endpoint_name, self.ENDPOINT_TYPE_OPENSTACK,
            connection_info, self.DEFAULT_ENDPOINT_DESCRIPTION)

        return endpoint.id


class DestinationEndpointCreationAction(SourceEndpointCreationAction):

    action_type = ACTION_TYPE_CHECK_CREATE_DESTINATION_ENDPOINT

    @property
    def endpoint_type(self):
        return self.ENDPOINT_TYPE_DESTINATION

    @property
    def tenant_name_format(self):
        return CONF.destination.new_tenant_name_format

    @property
    def endpoint_name_format(self):
        return CONF.destination.endpoint_name_format


class MigrationCreationAction(Action):

    MIGRATION_STATUS_ERROR = "ERROR"
    MIGRATION_STATUS_COMPLETED = "COMPLETED"

    action_type = ACTION_TYPE_CHECK_CREATE_MIGRATION

    def __init__(
            self, source_openstack_client, coriolis_client,
            action_payload, destination_openstack_client=None,
            destination_env=None, create_tenant=False):
        """
        param action_payload: dict(): instance_info dict (prevalidated!)

        self.subactions are not meant to be executed!
        """
        # NOTE: no client passed to super()
        super(MigrationCreationAction, self).__init__(
            None, coriolis_client, action_payload)
        if not destination_openstack_client:
            raise ValueError(
                "Destination openstack client required to migrate.")
        if not destination_env:
            raise ValueError(
                "Destination environment required to migrate.")

        self._source_client = source_openstack_client
        self._destination_env = destination_env
        self._destination_client = destination_openstack_client

        self.source_endpoint_create_action = SourceEndpointCreationAction(
            self._source_client, self._coriolis_client, self.payload)
        self.dest_endpoint_create_action = DestinationEndpointCreationAction(
            self._destination_client, self._coriolis_client, self.payload)

        self.subactions = [
            self.source_endpoint_create_action,
            self.dest_endpoint_create_action]

        self._create_tenant = create_tenant
        self.dest_tenant_create_action = None
        if create_tenant:
            self.dest_tenant_create_action = TenantCreationAction(
                self._destination_client, self._coriolis_client, self.payload)
            self.subactions.insert(0, self.dest_tenant_create_action)

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

        if self._create_tenant:
            dest_tenant_done = (
                self.dest_tenant_create_action.check_already_done())
            if not dest_tenant_done["done"]:
                LOG.debug(
                    "Destination tenant for migration for VM '%s' not done.",
                    instance_name)
                return done

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
            if existing_migration.status == self.MIGRATION_STATUS_ERROR:
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

        if self._create_tenant:
            tenant_done = self.dest_tenant_create_action.check_already_done()
            if not tenant_done["done"]:
                raise Exception(
                    "Tenant not done for instance: %s" % self.payload)

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


class BatchMigrationAction(Action):
    # TODET: maybe redundant
    action_type = ACTION_TYPE_BATCH_MIGRATE

    DEFAULT_BATCH_NAME = "CoriolisMigrationBatch"

    def __init__(
            self, source_openstack_client, coriolis_client,
            action_payload, destination_openstack_client=None,
            destination_env=None):
        """
        param action_payload: dict(): dict of the form: {
            "instances": ["vmname1", "vmname2", "vmname3", ...],
            "batch_name": "string batch name",
            "create_tenants": True/False
        }
        """
        super(BatchMigrationAction, self).__init__(
            None, coriolis_client, action_payload)

        if not destination_openstack_client:
            raise ValueError(
                "Destination openstack client required to migrate.")
        if not destination_env:
            raise ValueError(
                "Destination environment required to migrate.")

        self._create_tenants = self.payload.get("create_tenants", False)
        self._source_client = source_openstack_client
        self._destination_env = destination_env
        self._destination_client = destination_openstack_client
        self._batch_name = self.payload.get(
            "batch_name", self.DEFAULT_BATCH_NAME)

        vm_names = action_payload.get("instances")
        if not vm_names:
            raise ValueError("No VMs provided for batch: %s" % vm_names)

        LOG.info("Gathering info on selected VMs.")
        vm_infos = instances.find_source_instances_by_name(
            self._source_client, vm_names)

        # instantiate all the migration subactions:
        self._completed_migrations = []
        for vm_info in vm_infos:
            instance_name = vm_info["instance_name"]
            LOG.info(
                "Validating configuration for VM: \"%s\"", instance_name)
            instances.validate_migration_options(
                self._source_client, self._destination_client,
                vm_info, self._destination_env)
            subaction = MigrationCreationAction(
                self._source_client, self._coriolis_client, vm_info,
                destination_openstack_client=self._destination_client,
                destination_env=self._destination_env,
                create_tenant=self._create_tenants)
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
