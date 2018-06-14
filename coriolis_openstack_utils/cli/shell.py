# Copyright 2018 Cloudbase Solutions Srl
# All Rights Reserved.

"""
Coriolis command line utilities for OpenStack -> OpenStack migrations.
"""

import sys

from cliff import app
from cliff import commandmanager
from oslo_log import log as logging

from coriolis_openstack_utils import conf
from coriolis_openstack_utils import constants


CONF = conf.CONF


class CoriolisOpenStackUtilsApp(app.App):
    """ Coriolis command line utilities for OpenStack -> OpenStack migrations.
    """

    OPENSTACK_UTILS_VERSION = "1.1.0"
    OPENSTACK_UTILS_COMMAND_MANANGER = "coriolis_openstack_utils"

    def __init__(self, **kwargs):
        super(CoriolisOpenStackUtilsApp, self).__init__(
            description=__doc__.strip(),
            version=self.OPENSTACK_UTILS_VERSION,
            command_manager=commandmanager.CommandManager(
                self.OPENSTACK_UTILS_COMMAND_MANANGER),
            deferred_help=True,
            **kwargs)

    def build_option_parser(self, description, version, argparse_kwargs=None):
        """ Entry point for defining global arguments. """
        parser = super(CoriolisOpenStackUtilsApp, self).build_option_parser(
            description, version, argparse_kwargs)
        parser.add_argument(
            "--config-file", metavar="CONF_FILE", dest="conf_file",
            help="Path to the config file.")
        parser.epilog = (
            "See 'coriolis-openstack-util help COMMAND' for help on individual"
            " subcommands offered by the utility.")

        return parser

    def run(self, argv):
        # display usage if no args provided:
        known_args, remainder = self.parser.parse_known_args()
        if known_args.conf_file is None:
            self.stderr.write(self.parser.format_usage())
            return 1
        CONF(
            # NOTE: passing the whole of sys.argv[1:] will make
            # oslo_conf error out with urecognized arguments:
            ["--config-file", known_args.conf_file],
            project=constants.PROJECT_NAME,
            version=constants.PROJECT_VERSION)
        if not remainder:
            self.stderr.write(self.parser.format_usage())
            return 1
        return super(CoriolisOpenStackUtilsApp, self).run(remainder)


def _setup_logging():
    # TODO(aznashwan): setup logging for OpenStack client libs too:
    logging.register_options(conf.CONF)
    logging.setup(conf.CONF, 'coriolis')


def main(argv=sys.argv[1:]):
    _setup_logging()
    app = CoriolisOpenStackUtilsApp()
    return app.run(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
