# Copyright 2018 Cloudbase Solutions Srl
# All Rights Reserved.

import json
import jsonschema
import yaml

from oslo_log import log as logging

from cliff import lister

from coriolis_openstack_utils import conf
from coriolis_openstack_utils import constants
from coriolis_openstack_utils import instances
from coriolis_openstack_utils import utils


LOG = logging.getLogger(__name__)
INSTANCE_ASSESS_SCHEMA = 'instance_assess_info.json'

class AssessInstances(lister.Lister):
    def get_parser(self, prog_name):
        parser = super(AssessInstances, self).get_parser(prog_name)
        parser.add_argument(
            "--format", dest="format",
            choices=["yaml", "json"],
            default="json",
            help="the output format for the data, default is json")
        parser.add_argument(
            "instances", metavar="INSTANCE_NAME", nargs="+")

    def take_action(self, args):
        conf.CONF(
            # NOTE: passing the whole of sys.argv[1:] will make
            # oslo_conf error out with urecognized arguments:
            ["--config-file", args.conf_file],
            project=constants.PROJECT_NAME,
            version=constants.PROJECT_VERSION)

        source_client = conf.get_source_openstack_client()
        instance_names = args.instances
        assessment_list = instances.get_instances_assessment(
            source_client, instance_names)
        # Validating schema
        schema = utils.get_schema(
            __name__, INSTANCE_ASSESS_SCHEMA)
        for assessment in assessment_list:
            jsonschema.validate(assessment, schema)
            LOG.debug("Validated %s against schema." % assessment)

        # Printing to stdout
        if args.format:
            if args.format.lower() == "yaml":
                yaml_result = yaml.dump(
                    assessment_list, default_flow_style=False, indent=4)
                print(yaml_result)
            elif args.format.lower() == "json":
                json_result = json.dumps(assessment_list, indent=4)
                print(json_result)
            else:
                raise ValueError("Undefinded output format")
        else:
            json_result = json.dumps(assessment_list, indent=4)
            print(json_result)
