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
    "--format", dest="format",
    choices=["yaml", "json"],
    default="json",
    help="the output format for the data, default is json")
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

    source_client = conf.get_source_openstack_client()
    instance_names = args.instances
    result = instances.get_instances_assessment(source_client, instance_names)
    if args.format:
        if args.format.lower() == "yaml":
            yaml_result = yaml.dump(result, default_flow_style=False, indent=4)
            print(yaml_result)
        elif args.format.lower() == "json":
            json_result = json.dumps(result, indent=4)
            print(json_result)
        else:
            raise ValueError("Undefinded output format")
    else:
        json_result = json.dumps(result, indent=4)
        print(json_result)


if __name__ == "__main__":
    main()
