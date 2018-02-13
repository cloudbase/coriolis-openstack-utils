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

### 1. coriolis-util-migrate

This utility aims to automate the following common tasks:
  * cross-tenant instance discovery for source OpenStack
  * validation of migration parameters (such as the `network_map`)
  * [optional] create tenant(s) on destination OpenStack to migrate into
  * [configurable] set appropriate quotas on destination tenant(s) to ensure
    migration runs smoothly
  * create Coriolis Endpoint(s) with appropriate tenant(s) for source OpenStack
  * create Coriolis Endpoint(s) with appropriate tenant(s) for destination OpenStack
  * create a Coriolis Migration for each instance


Additionally, all operations are idempotent, which means that running the
utility twice will:
  * [optional] not create the destination tenant if it already exists
  * not create a new Coriolis endpoint for source/destination OpenStack should
    there already exist endpoints with the desired connection information
  * not create a new migration for VMs which already have an existing
    Coriolis migration that is either still running, or successfully completed


#### Usage example:

The utility may be used with any given number of names of VMs on the source
cloud (regardless if they are in the same tenant provided in the configuration
or not)

```bash
coriolis-util-migrate --config-file ./path/to/conf.ini My-Pet-VM-1 My-Pet-VM-2 ...
```

For safety, the above will only *print* out the operations which will be
undertaken. It is **highly** recommended that you read through the output to
ensure all the proposed actions are correct before proceeding.

In order to actually have the utility perform all necessary API calls, the
`--not-a-drill` flag needs to be supplied.


#### Notable parameters:
  * `--not-a-drill`: if set, the utility will go through the process of
    executing all the necessary actions (without it, the utility only prints
    the actions it would take)
  * `--dont-recreate-tenants`: if set, will *not* create destination tenants
    (they will need to be pre-created by the migration administrator)
