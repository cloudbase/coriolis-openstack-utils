# Copyright 2018 Cloudbase Solutions Srl
# All Rights Reserved.

from oslo_config import cfg as conf
from oslo_log import log as logging

CONF = conf.CONF


def get_logger(module_name):
    log = logging.getLogger(module_name)

    fh = logging.logging.FileHandler(CONF.log_file)
    level = logging.INFO
    if CONF.verbose:
        level = logging.DEBUG
    fh.setLevel(level)

    formatter = logging.logging.Formatter("%(levelname)s\t%(message)s")
    fh.setFormatter(formatter)
    log.logger.addHandler(fh)

    return log
