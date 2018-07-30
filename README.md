# coriolis-openstack-utils
Coriolis Utilities for Migrating between OpenStack Environments

This repository is a collection of utilities which aid in the
assessment, planning, and execution of migrations between two OpenStack
deployments using project [Coriolis](https://github.com/cloudbase/coriolis).

## Installation (using git)

```bash
git clone https://github.com/cloudbase/coriolis-openstack-utils
cd coriolis-openstack-utils
pip3 install .
```

## Configuration:

Regardless of the utility used, the same parameters are required throughout,
and need to be supplied using an .ini file.

These parateters include:
  * connection info for Coriolis deployment
  * connection info for source OpenStack
  * connection info for destination OpenStack
  * other destination-related parameters (such as the `network_map`)

An example configuration may be found in the project root directory, and used
as a starting point for using the tools.

## Included utilities:

### 1. coriolis-openstack-util

This utility aims to automate the following common tasks:
  * cross-tenant instance discovery for source OpenStack
  * validation of migration parameters (such as the `network_map`)
  * [optional] create tenant(s) on destination OpenStack to migrate into
  * [configurable] set appropriate quotas on destination tenant(s) to ensure
    migration runs smoothly
  * create Coriolis Endpoint(s) with appropriate tenant(s) for source OpenStack
  * create Coriolis Endpoint(s) with appropriate tenant(s) for destination OpenStack
  * create a Coriolis Migration for each instance
  * gather and aggregate information about particular VMs on the source OpenStack
  * gather and aggregate information about the migration statistics of successfully lift-and-shifted VMs
  * recreate Neutron resources such as networks, subnets and routers on the destination

Additionally, all operations are idempotent, which means that running the
utility twice will:
  * [optional] not create the tenant if it already exists
  * not create a new Coriolis endpoint for source/destination OpenStack should
    there already exist endpoints with the desired connection information
  * not create a new migration for VMs which already have an existing
    Coriolis migration that is either still running, or successfully completed
  * not create a new resource(router, security group, network) in a respective
    tenant if a similar one with the same name is found.

#### Notable parameters to all commands:
 * `--not-a-drill`: if set, will execute commands, if unset, will only print intended commands
 * `--config-file`: file path to the configuration file.


### Migrate tenant:
This command migrates a tenant, and all of its components: routers, networks, subnets, security groups and
instances (optional).
These components can also be migrated separately from the source tenant to any destination tenant.

```bash
coriolis-openstack-util migrate tenant --config-file ./path/to/conf.ini \
--src-tenant-name $TENANT_NAME \
--not-a-drill \
--no-instances \
```

**Notable parameters:**
  * `--all-instances`: if set, will create migrations or replicas for all instances from the source tenant
  * `--no-instances`: if set, will *not* create migrations or replicas for any instances from the source tenant
  * `--instances`: list of instance names that will be replicated or migrated
  * `--use-replicas`: if set, will create replicas, if unset, will create migrations
  * `--execute-replicas`: if set, will also immediately execute replicas

### Migrate instances batch:

The command may be used with any given number of names of VMs on the source
cloud (regardless if they are in the same tenant provided in the configuration
or not) granted that the credentials for the source provided to the tool can access the VMs.

```bash
coriolis-openstack-util migrate batch --config-file ./path/to/conf.ini My-Pet-VM-1 My-Pet-VM-2 ...
```

For safety, the above will only *print* out the operations which will be
undertaken. It is **highly** recommended that you read through the output to
ensure all the proposed actions are correct before proceeding.

In order to actually have the utility perform all necessary API calls, the
`--not-a-drill` flag needs to be supplied.

**Notable params:**
  * `--dont-recreate-tenants`: if set, will *not* create destination tenants
    (they will need to be pre-created by the migration administrator, or with the `migrate tenant` command)

### Assess migration
The command may be used with any number of migration ids, its purpose is to give to the user
information about a running or completed migration such as:
* instance information
* migration status
* migration time

```bash
coriolis-openstack-util --config-file ./path/to/conf.ini assess migration MIGRATION-ID1 MIGRATION-ID2 ...
```
**Notable params:**
  * `--format`: the output format of the migration information. Can be excel, json, or yaml.
    Default is json.
  * `--excel-filepath`: only if *excel* format specified, file path where the excel will be written.

### Assess instance
This command aggregates relevant information (resource footprint, OS type, and compatibility with Coriolis)
on any number of source VMs referenced by name.

```bash
coriolis-openstack-util --config-file ./path/to/conf.ini assess instance INSTANCE_NAME1 INSTANCE_NAME2 ...
```

**Notable params:**
  * `--format`: the output format of the migration information: yaml, json(default) or excel
  * `--excel-filepath`: only if *excel* format specified, file path where the excel file will be written

### Migrate network
Recreate a network, alongside all of its subnets.
```bash
coriolis-openstack-util --config-file .path/to/conf.ini migrate network \
--src-network-name $NET_NAME \
--dest-tenant-name $TENANT_NAME \
--not-a-drill
```
### Migrate router
Recreate a router, with routes to migrated networks according to the `new_network_name_format` config option.
```bash
coriolis-openstack-util --config-file ./path/to/conf.ini migrate router \
--src-router-name $ROUTER_NAME \
--dest-tenant-name $TENANT_NAME \
--not-a-drill
```
### Migrate security group
Recreate security group with all of its rules.
```bash
coriolis-openstack-util --config-file ./path/to/conf.ini migrate secgroup \
--src-tenant-name $TENANT_NAME \
--dest-tenant-name $TENANT_NAME \
--not-a-drill \
$SECURITY_GROUP_NAME
```
### Migrate subnet
Recreate subnet from source network to destination migrated network with new name according to the
`new_network_name` config option.
```bash
coriolis-openstack-util --config-file ./path/to/conf.ini migrate subnet \
--src-network-id $SRC_NETWORK_ID \
--not-a-drill \
$SUBNET_NAME
```
### Migrate user
Create a new user on the destination OpenStack named according to the `new_user_name_format`.
The password the user created with can be configured with the `new_user_password` configuration option.
By default, gives admin rights in tenants in which it had rights on source, mapped according to the
`new_tenant_name_format` config option, but can be overriden with the `--admin-role-tenants` parameter.
```bash
coriolis-openstack-util --config-file ./path/to/conf.ini migrate user \
--src-user-name $USER_NAME \
--not-a-drill
```

**Notable params:**
  * `--admin-role-tenants`: (optional) destination tenant names where the user will be given admin rights.
