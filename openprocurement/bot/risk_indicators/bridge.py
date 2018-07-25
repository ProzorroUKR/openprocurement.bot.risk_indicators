# -*- coding: utf-8 -*-

from datetime import datetime, timedelta
from time import sleep
import requests
import logging

logging.basicConfig()
logger = logging.getLogger("RiskIndicatorBridge")


class RiskIndicatorBridge(object):

    def __init__(self, config):
        config = config["main"]
        self.indicators_host = config["indicators_host"]
        self.queue_limit = config.get("queue_limit", 100)

        self.monitors_host = config["monitors_host"]
        self.monitors_token = config["monitors_token"]
        self.skip_monitoring_statuses = config.get("skip_monitoring_statuses", ("active", "draft"))

        self.run_interval = timedelta(seconds=config.get("run_interval", 24 * 3600))
        self.queue_error_interval = config.get("queue_error_interval", 30 * 60)
        self.request_retries = config.get("request_retries", 5)
        self.request_timeout = config.get("request_timeout", 10)

    def run(self):
        while True:
            start = datetime.now()
            try:
                self.process_risks()
            except Exception as e:
                logger.exception(e)
                sleep_seconds = self.queue_error_interval
            else:
                run_time = datetime.now() - start
                sleep_seconds = (self.run_interval - run_time).seconds

            if sleep_seconds > 0:
                logger.info("Sleep for {} seconds".format(sleep_seconds))
                sleep(sleep_seconds)

    def process_risks(self):
        errors = 0
        for risk in self.queue:
            try:
                self.process_risk(risk)
            except Exception as e:
                logger.exception(e)
                errors += 1

        logger.info("Risk processing finished. Number of skipped: {}".format(errors))

    def process_risk(self, risk):
        if risk["topRisk"]:
            monitorings = self.get_tender_monitoring_list(risk["tenderOuterId"])
            has_live_monitoring = any(m["status"] in self.skip_monitoring_statuses for m in monitorings)

            if not has_live_monitoring:
                details = self.get_item_details(risk["tenderId"])
                self.start_monitoring(risk, details)

    # Access APIs methods #

    @property
    def queue(self):
        url = "{}indicators-queue/?limit={}&page=0".format(
            self.indicators_host,
            self.queue_limit,
        )

        while url:
            response = self.request(url)
            data = response.get("data", [])
            for risk in data:
                yield risk

            url = response.get("pagination", {}).get("next_page", {}).get("url")

    def get_item_details(self, item_id):
        url = "{}tenders/{}".format(self.indicators_host, item_id)
        return self.request(url)

    def get_tender_monitoring_list(self, tender_id):
        url = "{}tenders/{}/monitorings".format(self.monitors_host, tender_id)
        response = self.request(url)
        return response["data"]

    def start_monitoring(self, risk_info, details):
        indicators_info = {i["indicatorId"]: i for i in details["indicatorsInfo"]}

        indicators = [(i["indicatorId"], i["value"])
                      for key in ("tenderIndicators", "lotIndicators")
                      for i in details["indicators"].get(key)]
        # first with value==True, then sort by id
        indicators = list(sorted(indicators, key=lambda e: (not e[1], e[0])))

        status_to_stages = {
            'active.enquiries': 'planning',
            'active.tendering' : 'planning',
            'active' : 'planning',

            'active.pre-qualification': 'awarding',
            'active.pre-qualification.stand-still': 'awarding',
            'active.auction': 'awarding',
            'active.qualification': 'awarding',
            'active.awarded': 'awarding',
            'award:status:active': 'awarding',

            'unsuccessful': 'contracting',
            'cancelled': 'contracting',
            'complete': 'contracting',
        }
        try:
            stages = [status_to_stages[details['status']]]
        except KeyError:
            logger.warning('Unable to match risk status "%s" to procuringStages: {}' % details['status'])
            stages = []


        self.request(
            "{}monitorings".format(self.monitors_host),
            method="post",
            json={
                "data": {
                    "tender_id": details["id"],
                    "reasons": ["indicator"],
                    "procuringStages": list(stages),
                    "decision": {
                        "description": "\n".join(
                            [
                                u"{}: {} ({})".format(
                                    uid,
                                    indicators_info.get(uid, {}).get("indicatorShortName", ""),
                                    u"Спрацював" if value else u"Не спрацював"
                                ) for uid, value in indicators
                            ]
                        )
                    },
                    "riskIndicators": [uid for uid, value in indicators],
                    "riskIndicatorsTotalImpact": risk_info.get("tenderScore"),
                }
            },
            headers={
                "Authorization": "Bearer {}".format(self.monitors_token)
            }
        )

    # Helper methods #

    class TerminateExecutionException(Exception):
        pass

    def request(self, url, method="get", **kwargs):

        func = getattr(requests, method)
        timeout = kwargs.pop("timeout", self.request_timeout)
        tries = self.request_retries

        while tries:
            try:
                response = func(url, timeout=timeout, **kwargs)
            except Exception as e:
                logger.error(e)
            else:
                status_ok = 201 if method == "post" else 200
                if response.status_code == status_ok:
                    try:
                        json_res = response.json()
                    except Exception as e:
                        logger.error(e)
                    else:
                        return json_res
                else:
                    logger.error("Unsuccessful response code: {}".format(response.status_code))

            sleep(self.request_retries - tries)
            tries -= 1

        raise self.TerminateExecutionException("Access problems with {} {}".format(method, url))
