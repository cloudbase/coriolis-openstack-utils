# Copyright 2018 Cloudbase Solutions Srl
# All Rights Reserved.

import time

from keystoneauth1 import loading
from keystoneauth1 import session as ks_session
from keystoneauth1.exceptions.http import Forbidden as KeystoneForbidden
from oslo_log import log as logging

from cinderclient import client as cinder_client
from glanceclient import client as glance_client
from keystoneclient import client as keystone_client
from neutronclient.neutron import client as neutron_client
from novaclient import client as nova_client
from swiftclient import client as swift_client


LOG = logging.getLogger()

ALLOW_UNTRUSTED = False
CINDER_API_VERSION = 2
GLANCE_API_VERSION = 1
NOVA_API_VERSION = 2
NEUTRON_API_VERSION = '2.0'


def create_keystone_session(connection_info):
    allow_untrusted = connection_info.get(
        "allow_untrusted", ALLOW_UNTRUSTED)
    verify = not allow_untrusted

    username = connection_info["username"]
    auth = None

    plugin_name = "password"
    password = connection_info["password"]
    plugin_args = {
        "username": username,
        "password": password,
    }

    if not auth:
        project_name = connection_info["project_name"]

        auth_url = connection_info["auth_url"]
        if not auth_url:
            raise ValueError(
                '"auth_url" not provided in "connection_info"')

        plugin_args.update({
            "auth_url": auth_url,
            "project_name": project_name,
        })

        keystone_version = connection_info["identity_api_version"]

        if keystone_version == 3:
            plugin_name = "v3" + plugin_name

            plugin_args["project_domain_name"] = connection_info[
                "project_domain_name"]
            plugin_args["user_domain_name"] = connection_info[
                "user_domain_name"]

        loader = loading.get_plugin_loader(plugin_name)
        auth = loader.load_from_options(**plugin_args)

    return ks_session.Session(auth=auth, verify=verify)


class OpenStackClient(object):

    def __init__(self, connection_info):
        if connection_info is None:
            connection_info = {}
        region_name = connection_info.get("region_name")

        self.connection_info = connection_info
        session = create_keystone_session(connection_info)
        self.session = session

        identity_api_version = connection_info["identity_api_version"]
        self.keystone = keystone_client.Client(
            version=identity_api_version, session=session)

        nova_region_name = connection_info.get(
            "nova_region_name", region_name)
        self.nova = nova_client.Client(
            NOVA_API_VERSION, session=session, region_name=nova_region_name)

        neutron_region_name = connection_info.get(
            "neutron_region_name", region_name)
        self.neutron = neutron_client.Client(
            NEUTRON_API_VERSION, session=session,
            region_name=neutron_region_name)

        glance_version = connection_info.get(
            "glance_api_version", 2)
        glance_region_name = connection_info.get(
            "glance_region_name", region_name)
        self.glance = glance_client.Client(
            glance_version, session=session, region_name=glance_region_name)

        cinder_region_name = connection_info.get(
            "cinder_region_name", region_name)
        self.cinder = cinder_client.Client(
            CINDER_API_VERSION, session=session,
            region_name=cinder_region_name)

        untrusted_swift = connection_info.get(
            "allow_untrusted_swift", False)
        swift_region_name = connection_info.get(
            "swift_region_name", region_name)
        swift_os_options = None
        if swift_region_name:
            swift_os_options = {"region_name": swift_region_name}

        self.swift = swift_client.Connection(
            session=session, insecure=untrusted_swift,
            os_options=swift_os_options)

    def get_tenants_list(self):
        """ For some credentials, it is not possible to list tenants not
        created by the respective user, as such, we impose filtering on the
        tenant listing."""
        try:
            return self.keystone.tenants.list()
        except KeystoneForbidden:
            user_id = self.session.get_user_id()
            return self.keystone.tenants.list(user=user_id)
        return []

    def get_projects_list(self):
        """ For some credentials, it is not possible to list projects not
        created by the respective user, as such, we impose filtering on the
        project listing."""
        try:
            return self.keystone.projects.list()
        except KeystoneForbidden:
            user_id = self.session.get_user_id()
            return self.keystone.projects.list(user=user_id)
        return []

    def wait_for_project_creation(
            self, project_name, period=2, tries=30):
        """ Waits for tenant with specified name to appear. """
        i = 0
        project = None
        projects = None
        while i < tries:
            if int(self.connection_info["identity_api_version"]) == 2:
                projects = self.get_tenants_list()
            else:
                projects = self.get_projects_list()

            filtered = [p for p in projects if p.name == project_name]
            if len(filtered) == 0:
                LOG.debug(
                    "Waiting %d seconds for tenant named '%s'",
                    period, project_name)
            elif len(filtered) > 1:
                raise Exception(
                    "Multiple tenants named '%s' found using conn info"
                    " '%s'" % (project_name, self.connection_info))
            elif len(filtered) == 1:
                LOG.debug("Found tenant named '%s'", project_name)
                project = filtered[0]
                break

            time.sleep(period)
            i = i + 1

        if not project:
            raise Exception(
                "Wait (%d seconds) failed for tenant named '%s' using "
                "conn info: %s" % (
                    period * tries, project_name, self.connection_info))

    def get_project_name(self, project_id):
        project = None
        if int(self.connection_info["identity_api_version"]) == 2:
            project = self.keystone.tenants.get(project_id)
        else:
            project = self.keystone.projects.get(project_id)

        return project.name

    def get_project_id(self, project_name):
        projects = None
        if int(self.connection_info["identity_api_version"]) == 2:
            projects = self.get_tenants_list()
        else:
            projects = self.get_projects_list()

        filtered = [p for p in projects if p.name == project_name]
        if not filtered:
            raise Exception(
                "Cannot locate project with name '%s' using conn info "
                "%s." % (project_name, self.connection_info))
        elif len(filtered) > 1:
            raise Exception(
                "Multiple tenants named '%s' found using conn info '%s'" % (
                    project_name, self.connection_info))

        return filtered[0].id

    def list_project_names(self):
        projects = None
        if int(self.connection_info["identity_api_version"]) == 2:
            projects = self.get_tenants_list()
        else:
            projects = self.get_projects_list()

        return [p.name for p in projects]

    def add_admin_role_to_project(
            self, project_name, username, admin_role_name="admin"):
        project_id = self.get_project_id(project_name)
        # get user ID:
        users = [u for u in self.keystone.users.list() if u.name == username]
        if not users:
            raise Exception(
                "Could not find user named '%s' with conn info '%s'" % (
                    username, self.connection_info))
        elif len(users) > 1:
            raise Exception(
                "Multiple users with name '%s' found with conn info '%s'" % (
                    username, self.connection_info))
        user_id = users[0].id

        # get admin role ID:
        admin_roles = [
            r for r in self.keystone.roles.list()
            if r.name == admin_role_name]
        if not admin_roles:
            raise Exception(
                "Could not locate admin role named '%s' on destination" % (
                    admin_role_name))
        elif len(admin_roles) > 1:
            raise Exception(
                "More that one admin role named '%s' was found." % (
                    admin_role_name))
        admin_role_id = admin_roles[0].id

        LOG.info(
            "Adding admin role for user '%s' in tenant '%s'",
            username, project_name)
        if int(self.connection_info["identity_api_version"]) == 2:
            self.keystone.roles.add_user_role(
                user_id, admin_role_id, tenant=project_id)
        else:
            self.keystone.roles.grant(
                admin_role_id, user=user_id, project=project_id)

    def create_project(self, project_name, project_description):
        project = None

        if int(self.connection_info["identity_api_version"]) == 2:
            project = self.keystone.tenants.create(
                project_name, project_description)
        else:
            # NOTE: the `domain_name`.lower() is a workaround to needing
            # the domain ID (not the name!)
            domain_name = self.connection_info["project_domain_name"].lower()
            project = self.keystone.projects.create(
                project_name, domain_name,
                description=project_description)

        return project.id

    def delete_project_by_name(self, project_name):
        project_id = self.get_project_id(project_name)
        self.keystone.projects.delete(project_id)
