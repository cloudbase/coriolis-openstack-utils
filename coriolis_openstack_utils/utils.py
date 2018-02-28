# Copyright 2018 Cloudbase Solutions Srl
# All Rights Reserved.
import jinja2
import json

from oslo_log import log as logging


LOG = logging.getLogger(__name__)
DEFAULT_SCHEMAS_DIRECTORY = "schemas"


def check_dict_equals(dict1, dict2):
    """ Recursively checks whether two dicts are equal. """
    LOG.debug("Comparing dicts:\n%s\n%s", dict1, dict2)

    if (type(dict1), type(dict2)) != (dict, dict):
        LOG.debug("Bad types:\n%s\n%s", dict1, dict2)
        return False

    keys1 = set(dict1)
    keys2 = set(dict2)
    if keys1 != keys2:
        LOG.debug("Different key sets for:\n%s\n%s", dict1, dict2)
        return False

    for key in keys1:
        e1 = dict1[key]
        e2 = dict2[key]

        if dict in (type(e1), type(e2)):
            if not check_dict_equals(e1, e2):
                return False
        else:
            if not e1 == e2:
                return False

    return True


def get_schema(package_name, schema_name,
               schemas_directory=DEFAULT_SCHEMAS_DIRECTORY):
    """Loads the schema using jinja2 template loading.

    Loads the schema with the given 'schema_name' using jinja2 template
    loading from the provided 'package_name' under the given
    'schemas_directory'.
     """
    template_env = jinja2.Environment(
        loader=jinja2.PackageLoader(package_name, schemas_directory))

    schema = json.loads(template_env.get_template(schema_name).render())

    return schema
