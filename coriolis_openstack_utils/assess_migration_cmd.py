# Copyright 2018 Cloudbase Solutions Srl
# All Rights Reserved.

import argparse
import json
import yaml

from oslo_log import log as logging

from coriolis_openstack_utils import actions
from coriolis_openstack_utils import conf
from coriolis_openstack_utils import constants
from coriolis_openstack_utils import instances


# Setup logging:
logging.register_options(conf.CONF)
logging.setup(conf.CONF, 'coriolis')
LOG = logging.getLogger(__name__)

# Setup argument parsing:
PARSER = argparse.ArgumentParser(
    description="Coriolis Openstack Instance Metrics.")
PARSER.add_argument(
    "--config-file", metavar="CONF_FILE", dest="conf_file",
    help="Path to the config file.")
PARSER.add_argument(
    "--migration-id", dest="migration_id")
PARSER.add_argument(
    "--format", dest="format",
    choices=["yaml", "json"],
    default="json",
    help="the output format for the data, default is json")

def main():
    args = PARSER.parse_args()
    conf.CONF(
        # NOTE: passing the whole of sys.argv[1:] will make
        # oslo_conf error out with urecognized arguments:
        ["--config-file", args.conf_file],
        project=constants.PROJECT_NAME,
        version=constants.PROJECT_VERSION)

    migration_id = args.migration_id
    source_client = conf.get_source_openstack_client()
    coriolis = conf.get_coriolis_client()
    result = instances.get_migration_assessment(source_client,
                                                coriolis, migration_id)

    if args.format.lower() == "yaml":
        yaml_result = yaml.dump(result, default_flow_style=False, indent=4)
        print(yaml_result)
    elif args.format.lower() == "json":
        json_result = json.dumps(result, indent=4)
        print(json_result)
    else:
        raise ValueError("Undefinded output format.")


if __name__ == "__main__":
    main()
