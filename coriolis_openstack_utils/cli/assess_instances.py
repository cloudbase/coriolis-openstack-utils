# Copyright 2018 Cloudbase Solutions Srl
# All Rights Reserved.

import yaml
import json

from oslo_log import log as logging

from cliff import command

from coriolis_openstack_utils import conf
from coriolis_openstack_utils import constants
from coriolis_openstack_utils import instances


LOG = logging.getLogger(__name__)


class AssessInstances(command.Command):
    def get_parser(self, prog_name):
        parser = super(AssessInstances, self).get_parser(prog_name)
        parser.add_argument(
            "--format", dest="format",
            choices=["yaml", "json"],
            default="json",
            help="the output format for the data, default is json")
        parser.add_argument(
            "instances", metavar="INSTANCE_NAME", nargs="+")
        return parser

    def take_action(self, args):
        source_client = conf.get_source_openstack_client()
        instance_names = args.instances
        result = instances.get_instances_assessment(
            source_client, instance_names)
        if args.format:
            if args.format.lower() == "yaml":
                yaml_result = yaml.dump(
                        result, default_flow_style=False, indent=4)
                print(yaml_result)
            elif args.format.lower() == "json":
                json_result = json.dumps(result, indent=4)
                print(json_result)
            else:
                raise ValueError("Undefinded output format")
        else:
            json_result = json.dumps(result, indent=4)
            print(json_result)
