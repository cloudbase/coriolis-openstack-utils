# Copyright 2018 Cloudbase Solutions Srl
# All Rights Reserved.
import yaml
import json
import xlsxwriter
import math
import jsonschema

from oslo_log import log as logging

from cliff.command import Command

from coriolis_openstack_utils import conf
from coriolis_openstack_utils import constants
from coriolis_openstack_utils import instances
from coriolis_openstack_utils import utils
from oslo_utils import units


LOG = logging.getLogger(__name__)
INSTANCE_ASSESS_SCHEMA = 'instance_assess_info.json'


def write_excel(result_list, file_path):
    workbook = xlsxwriter.Workbook(file_path)
    LOG.debug("Opening excel % for writing." % file_path)
    worksheet = workbook.add_worksheet()
    name_col = 0
    worksheet.write(0, name_col, "VM Name")
    src_tenant_col = name_col + 1
    worksheet.write(0, src_tenant_col, "Source Tenant Name")
    dst_tenant_col = src_tenant_col + 1
    worksheet.write(0, dst_tenant_col, "Destination Tenant Name")
    image_size_col = dst_tenant_col + 1
    worksheet.write(0, image_size_col, "Glance Image Size(GB)")
    flavor_size_col = image_size_col + 1
    worksheet.write(0, flavor_size_col, "VM Flavor Size(GB)")
    volume_size_col = flavor_size_col + 1
    worksheet.write(0, volume_size_col, "VM Volumes(GB)")
    migr_time_col = volume_size_col + 1
    worksheet.write(0, migr_time_col, "VM Migration Time")

    row = 1
    for assessment_list in result_list:
        for assessment in assessment_list:
            for key, value in assessment.items():
                if key == "instance_name":
                    worksheet.write(row, name_col, value)
                elif key == "source_tenant_name":
                    worksheet.write(row, src_tenant_col, value)
                elif key == "storage":
                    if 'image' in value:
                        image_size = math.ceil(
                            value['image']['size_bytes'] / units.Gi)
                    else:
                        image_size = "deleted"
                    flavor_size = math.ceil(
                        value['flavor']['flavor_disk_size'] / units.Gi)
                    volume_list = [vol['size_bytes'] for
                                   vol in value['volumes']]
                    volumes_size = math.ceil(sum(volume_list) / units.Gi)
                    worksheet.write(row, image_size_col, image_size)
                    worksheet.write(row, flavor_size_col, flavor_size)
                    worksheet.write(row, volume_size_col, volumes_size)
                elif key == "migration":
                    migration_time = value['migration_time']
                    worksheet.write(row, migr_time_col, migration_time)
            row += 1
    workbook.close()


class AssessMigrations(Command):
    def get_parser(self, prog_name):
        parser = super(AssessMigrations, self).get_parser(prog_name)
        parser.add_argument(
            "--format", dest="format",
            choices=["yaml", "json", "excel"],
            default="json",
            help="the output format for the data, default is json")
        parser.add_argument(
            "--excel-filepath",
            default="migration_assessment.xlsx",
            help="default filepath for excel format")
        parser.add_argument(
            "--all",
            default=False,
            help="Show all migrations.")
        parser.add_argument(
            "migrations", metavar="MIGRATION_ID", nargs="*")

    def take_action(self, args):
        conf.CONF(
            # NOTE: passing the whole of sys.argv[1:] will make
            # oslo_conf error out with urecognized arguments:
            ["--config-file", args.conf_file],
            project=constants.PROJECT_NAME,
            version=constants.PROJECT_VERSION)
        migration_ids = args.migrations
        source_client = conf.get_source_openstack_client()
        coriolis = conf.get_coriolis_client()
        result_list = instances.get_migrations_assessment(
            source_client, coriolis, migration_ids, args.show_all)

        # Validate against json schema
        schema = utils.get_schema(
            __name__, INSTANCE_ASSESS_SCHEMA)
        for assessment_list in result_list:
            for assessment in assessment_list:
                LOG.debug("Validated %s against schema." % assessment)
                jsonschema.validate(assessment, schema)

        # Print to stdout
        if args.format.lower() == "yaml":
            yaml_result = yaml.dump(
                result_list, default_flow_style=False, indent=4)
            print(yaml_result)
        elif args.format.lower() == "json":
            json_result = json.dumps(result_list, indent=4)
            print(json_result)
        elif args.format.lower() == "excel":
            write_excel(result_list, args.excel_filepath)
        else:
            raise ValueError("Undefinded output format.")
