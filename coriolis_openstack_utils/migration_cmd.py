# Copyright 2018 Cloudbase Solutions Srl
# All Rights Reserved.

import argparse

from oslo_log import log as logging

from coriolis_openstack_utils import actions
from coriolis_openstack_utils import conf
from coriolis_openstack_utils import constants


# Setup logging:
logging.register_options(conf.CONF)
logging.setup(conf.CONF, 'coriolis')
LOG = logging.getLogger(__name__)

# Setup argument parsing:
PARSER = argparse.ArgumentParser(
    description="Coriolis Openstack utils.")
PARSER.add_argument(
    "-v", "--verbose", action="store_true",
    help="Increase log verbosity")
PARSER.add_argument(
    "--config-file", metavar="CONF_FILE", dest="conf_file",
    help="Path to the config file.")
PARSER.add_argument(
    "--dont-recreate-tenants",
    dest="dont_recreate_tenants", default=False, action="store_true",
    help="Whether or not to use existing tenants on the destination, "
         "or attempt to create a new corrresponding one for each "
         "source tenant.")
PARSER.add_argument(
    "--batch-name", dest="batch_name",
    default="MigrationBatch",
    help="Human-readable name/id for the batch.")
PARSER.add_argument(
    "--not-a-drill", dest="not_drill", action="store_true",
    default=False,
    help="If unset, tooling will only print the indented operations.")
PARSER.add_argument(
    "instances", metavar="INSTANCE_NAME", nargs="+")


def main():
    args = PARSER.parse_args()
    conf.CONF(
        # NOTE: passing the whole of sys.argv[1:] will make
        # oslo_conf error out with urecognized arguments:
        ["--config-file", args.conf_file],
        project=constants.PROJECT_NAME,
        version=constants.PROJECT_VERSION)

    # instantiate all clients:
    coriolis = conf.get_coriolis_client()
    source_client = conf.get_source_openstack_client()
    destination_client = conf.get_destination_openstack_client()
    dest_env = conf.get_destination_openstack_environment()

    source_vms = args.instances
    batch_name = args.batch_name
    migration_payload = {
        "instances": source_vms,
        "batch_name": batch_name,
        "create_tenants": not args.dont_recreate_tenants}
    batch_migration_action = actions.BatchMigrationAction(
        source_client, coriolis, migration_payload,
        destination_openstack_client=destination_client,
        destination_env=dest_env)

    done = batch_migration_action.check_already_done()
    if done["done"]:
        LOG.info(
            "Batch seemingly done. (a migration for each VM in the "
            "batch which has equivalent endpoint details was found)")
        migration_ids = done["result"]
        LOG.info("All migration IDs for this batch: %s", migration_ids)
    else:
        if args.not_drill:
            migration_ids = batch_migration_action.execute_operations()
            LOG.info("All migration IDs for this batch: %s", migration_ids)
        else:
            batch_migration_action.print_operations()


if __name__ == "__main__":
    main()
