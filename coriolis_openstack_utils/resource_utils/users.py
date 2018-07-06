# Copyright 2018 Cloudbase Solutions Srl
# All Rights Reserved.

from oslo_log import log as logging
from coriolis_openstack_utils import conf


LOG = logging.getLogger(__name__)
CONF = conf.CONF


def list_users(openstack_client, filters={}):
    return openstack_client.keystone.users.list(**filters)


def get_user(openstack_client, user_id):
    return openstack_client.keystone.users.get(user_id)


def get_body(openstack_client, user_id):

    relevant_keys = {'enabled', 'name', 'email'}
    src_body = get_user(openstack_client, user_id)
    if not isinstance(src_body, dict):
        src_body = src_body.to_dict()

    src_body = {k: v for k, v in src_body.items() if k in relevant_keys}

    return src_body


def create_user(openstack_client, body):
    body['password'] = CONF.destination.new_users_password
    return openstack_client.keystone.users.create(**body).id


def add_admin_roles(openstack_client, user_name, project_name_list):
    for project_name in project_name_list:
        dest_projects = len(
            list_users(openstack_client, filters={'name': project_name}))
        if dest_projects == 1:
            LOG.info("Adding admin role to user '%s' in project '%s'"
                     % (user_name, project_name))
            openstack_client.add_admin_role_to_project(project_name, user_name)
        elif dest_projects == 0:
            LOG.info("Tenant named '%s' not found, skipping admin "
                     "role adding." % project_name)


def get_user_admin_tenants(openstack_client, user_id, admin_role_name='admin'):
    admin_roles = [r for r in openstack_client.keystone.roles.list()
                   if r.name == admin_role_name]

    if not admin_roles:
        raise Exception(
            "Could not locate admin role named '%s' on destination" % (
                admin_role_name))

    admin_role_id = admin_roles[0].id
    admin_tenant_ids = []
    for role_assignment in openstack_client.keystone.role_assignments.list(
            user=user_id):
        if role_assignment.role['id'] == admin_role_id:
            admin_tenant_ids.append(role_assignment.scope['project']['id'])

    admin_tenant_names = [openstack_client.get_project_name(tenant_id)
                          for tenant_id in admin_tenant_ids]

    return admin_tenant_names
