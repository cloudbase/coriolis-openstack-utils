# Copyright 2018 Cloudbase Solutions Srl
# All Rights Reserved.


from oslo_log import log as logging


LOG = logging.getLogger(__name__)


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
