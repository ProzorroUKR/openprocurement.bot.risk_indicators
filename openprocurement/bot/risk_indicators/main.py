#!/bin/python
from openprocurement.bot.risk_indicators.bridge import RiskIndicatorBridge
import logging
import logging.config
import yaml
import sys
import os

logger = logging.getLogger("RiskIndicatorBridge")


def main(config_path=None):
    if config_path is None:
        if len(sys.argv) < 2:
            logger.critical("Config is not provided")
            return
        config_path = sys.argv[1]
        
    if not os.path.isfile(config_path):
        logger.critical('Invalid configuration file')
        return

    try:
        with open(config_path) as config_file_obj:
            config = yaml.load(config_file_obj.read())
    except Exception as e:
        logger.critical('Invalid configuration file')
        logger.critical(str(e))
        return

    try:
        logging.config.dictConfig(config)
        RiskIndicatorBridge(config).run()
    except Exception as e:
        logger.critical("Unhandled exception: {}".format(e))
