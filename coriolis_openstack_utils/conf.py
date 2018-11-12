# Copyright 2018 Cloudbase Solutions Srl
# All Rights Reserved.

from coriolisclient import client as coriolis_client
from oslo_config import cfg as conf

from coriolis_openstack_utils import constants
from coriolis_openstack_utils import openstack_client


CONF = conf.CONF

OPENSTACK_CONNECTION_OPTS = [
    conf.IntOpt("identity_api_version", required=True,
                min=2, max=3, help="Int Keystone API version."),
    conf.StrOpt("auth_url", required=True,
                help="Auth URL to target Keystone."),
    conf.StrOpt("username", required=True,
                help="Username for target Keystone."),
    conf.StrOpt("password", required=True,
                help="Password for given 'username'."),
    # NOTE: not required for all cases:
    conf.StrOpt("project_name", required=True,
                help="Name of tenant on target Keystone."),
    # NOTE: below two are v3 only:
    conf.StrOpt("user_domain_name",
                help="Domain name for the user."),
    conf.StrOpt("project_domain_name",
                help="Domain name for the project."),
    conf.BoolOpt("allow_untrusted", default=False,
                 help="Whether or not skip certificate validation.")
]

# Register base Coriolis conf options:
CONF.register_opts(
    OPENSTACK_CONNECTION_OPTS, constants.CORIOLIS_OPT_GROUP_NAME)

# Define extra options for source/destionation OpenStack:
ENDPOINT_NAME_FORMAT_OPT = conf.StrOpt(
    "endpoint_name_format", required=True,
    help="Format for Endpoint names on source. "
         "Must contain the format string '%(tenant)s'."
         "Can optionally contain '%(region)s' and '%(user)s'")
REGION_CONFIG_OPT = conf.StrOpt(
    "region_name",
    default="",
    help="Name of the Keystone region to use.")
DB_CONNECTION_OPT = conf.StrOpt(
    "cinder_database_connection",
    help="Connection string for Cinder DB.")


# Register source conf options:
SOURCE_OPTS = OPENSTACK_CONNECTION_OPTS + [
    REGION_CONFIG_OPT, DB_CONNECTION_OPT, ENDPOINT_NAME_FORMAT_OPT]
CONF.register_opts(
    SOURCE_OPTS, constants.SOURCE_OPT_GROUP_NAME)

# Register destination conf options:
SKIP_OS_MORPHING_OPT = conf.BoolOpt(
    "skip_os_morphing", default=True,
    help="Whether or not skip the OSMorphing process.")
SHUTDOWN_INSTANCES_OPT = conf.BoolOpt(
    "shutdown_instances", default=False,
    help="Whether or not to shutdown instances during replica execution.")
NETMAP_OPT = conf.DictOpt(
    "network_map", required=True, help="Dict network mapping.")
STORMAP_OPT = conf.DictOpt(
    "storage_map", default={}, help="Dict storage mapping")
ADMIN_ROLE_NAME = conf.StrOpt(
    "admin_role_name", default="admin",
    help="Name of admin role on destination cloud to use.")
NEW_TENANT_ADMIN_USERS_OPT = conf.ListOpt(
    "new_tenant_admin_users", default=[],
    help="List of pre-existing usernames on the destination which "
         "should have an add role added in the newly created tenant(s)")
NEW_TENANT_NAME_OPT = conf.StrOpt(
    "new_tenant_name_format", required=True,
    help="String format for tenant names on the destination. "
         "Must contain the format string '%(original)s'. "
         "Example: %(original)s-Migrated")
NEW_SECGROUP_NAME_OPT = conf.StrOpt(
    "new_secgroup_name_format", required=True,
    help="String format for security group names on the destination. "
         "Must contain the format string '%(original)s'. "
         "Example: %(original)s-Migrated")
NEW_SUBNAME_NAME_OPT = conf.StrOpt(
    "new_subnet_name_format", required=True,
    help="String format for subnet names on the destination. "
         "Must contain the format string '%(original)s'. "
         "Example: %(original)s-Migrated")
NEW_NETWORK_NAME_OPT = conf.StrOpt(
    "new_network_name_format", required=True,
    help="String format for network names on the destination. "
         "Must contain the format string '%(original)s'. "
         "Example: %(original)s-Migrated")
NEW_ROUTER_NAME_OPT = conf.StrOpt(
    "new_router_name_format", required=True,
    help="String format for router names on the destination. ")
NEW_USER_NAME_OPT = conf.StrOpt(
    "new_user_name_format", required=True,
    help="String format for user names on the destination. "
         "Must contain the format string '%(original)s'. "
         "Example: %(original)s-Migrated")
NEW_FLAVOR_NAME_OPT = conf.StrOpt(
    "new_flavor_name_format", required=True,
    help="String format for flavor names on the destination. "
         "Must contain the format string '%(original)s'. "
         "Example: %(original)s-Migrated")
NEW_KEYPAIR_NAME_OPT = conf.StrOpt(
    "new_keypair_name_format", required=True,
    help="String format for keypair names on the destination. "
         "Should contain the format string '%(original)s', "
         "to preserve original name."
         "Example: %(original)s-Migrated")


NEW_TENANT_NEUTRON_QUOTAS_OPT = conf.DictOpt(
    "new_tenant_neutron_quotas", default={"security_group": -1},
    help="Mapping of Neutron quotas to set on the new tenant.")
NEW_TENANT_CINDER_QUOTAS_OPT = conf.DictOpt(
    "new_tenant_cinder_quotas", default={"volumes": -1},
    help="Mapping of Cinder quotas to set on the new tenant.")
NEW_TENANT_NOVA_QUOTAS_OPT = conf.DictOpt(
    "new_tenant_nova_quotas", default={"instances": -1},
    help="Mapping of Nova quotas to set on the new tenant.")
NEW_TENANT_OPEN_DEFAULT_SECGROUP_OPT = conf.BoolOpt(
    "new_tenant_open_default_secgroup", default=False,
    help="If set, the 'default' security group of newly-created "
         "tenants will have rules allowing traffic on ALL ports for ALL "
         "protocols.")
NEW_NETWORK_TYPE_OPT = conf.DictOpt(
    "network_type_mapping", default={},
    help="Mapping between source network type and destination network type.")
NEW_PHYSICAL_NETWORK_OPT = conf.DictOpt(
    "physical_network_mapping", default={},
    help="Mapping between physical networks on source and destination.")
EXTERNAL_NETWORK_MAP_OPT = conf.DictOpt(
    "external_network_name_map", default={},
    help="Mapping between external networks on source and destination.")
NEW_USERS_PASSWORD_OPT = conf.StrOpt(
    "new_users_password",
    help="Default password for newly-migrated users.")
COPY_ROUTES_OPT = conf.BoolOpt(
    "copy_routes", default=False,
    help="Whether to copy static routes from source routers.")


# TODO (aznashwan): determine value of adding extra migration opts:
DESTINATION_OPTS = OPENSTACK_CONNECTION_OPTS + [
    REGION_CONFIG_OPT, NETMAP_OPT, STORMAP_OPT, ENDPOINT_NAME_FORMAT_OPT,
    SKIP_OS_MORPHING_OPT, ADMIN_ROLE_NAME, NEW_TENANT_NAME_OPT,
    NEW_TENANT_NEUTRON_QUOTAS_OPT, NEW_TENANT_CINDER_QUOTAS_OPT,
    NEW_TENANT_NOVA_QUOTAS_OPT, NEW_TENANT_ADMIN_USERS_OPT,
    NEW_TENANT_OPEN_DEFAULT_SECGROUP_OPT, NEW_SECGROUP_NAME_OPT,
    NEW_SUBNAME_NAME_OPT, NEW_NETWORK_NAME_OPT, NEW_NETWORK_TYPE_OPT,
    NEW_PHYSICAL_NETWORK_OPT, NEW_ROUTER_NAME_OPT, EXTERNAL_NETWORK_MAP_OPT,
    NEW_USER_NAME_OPT, NEW_USERS_PASSWORD_OPT, SHUTDOWN_INSTANCES_OPT,
    NEW_FLAVOR_NAME_OPT, NEW_KEYPAIR_NAME_OPT, COPY_ROUTES_OPT]
CONF.register_opts(
    DESTINATION_OPTS, constants.DESTINATION_OPT_GROUP_NAME)


def get_conn_info_for_group(group_name):
    """ Returns the connection info dict for the specified option group.
    """
    if not hasattr(CONF, group_name):
        raise ValueError(
            "Group '%s' not found in the config." % group_name)

    confgroup = getattr(CONF, group_name)
    conn_info = {
        "identity_api_version": confgroup.identity_api_version,
        "auth_url": confgroup.auth_url,
        "username": confgroup.username,
        "password": confgroup.password,
        "project_name": confgroup.project_name,
        "allow_untrusted": confgroup.allow_untrusted
    }

    if int(conn_info["identity_api_version"]) == 3:
        udom = confgroup.user_domain_name
        pdom = confgroup.project_domain_name
        if None in (udom, pdom):
            raise ValueError(
                "Must specify both 'user_domain_name' and "
                "'project_domain_name' in group '%s' when using "
                "Keystone v3." % group_name)

        conn_info["user_domain_name"] = udom
        conn_info["project_domain_name"] = pdom

    if hasattr(confgroup, "region_name"):
        # NOTE: only set if needed:
        if confgroup.region_name:
            conn_info["region_name"] = confgroup.region_name

    if hasattr(confgroup, "cinder_database_connection"):
        # NOTE: only set if needed:
        if confgroup.cinder_database_connection:
            conn_info["cinder_database_connection"] = (
                confgroup.cinder_database_connection)

    return conn_info


def get_source_openstack_client():
    conn_info = get_conn_info_for_group(
        constants.SOURCE_OPT_GROUP_NAME)
    return openstack_client.OpenStackClient(conn_info)


def get_destination_openstack_client():
    conn_info = get_conn_info_for_group(
        constants.DESTINATION_OPT_GROUP_NAME)
    return openstack_client.OpenStackClient(
        conn_info)


def get_coriolis_client():
    conn_info = get_conn_info_for_group(
        constants.CORIOLIS_OPT_GROUP_NAME)
    session = openstack_client.create_keystone_session(conn_info)
    return coriolis_client.Client(session=session)


def get_destination_openstack_environment():
    """ Returns the `--destination-env` for migations. """
    confgroup = getattr(CONF, constants.DESTINATION_OPT_GROUP_NAME)
    return {
        "network_map": confgroup.network_map,
        "storage_map": confgroup.storage_map
    }
