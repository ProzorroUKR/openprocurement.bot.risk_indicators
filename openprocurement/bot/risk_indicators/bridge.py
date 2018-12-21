# -*- coding: utf-8 -*-

from datetime import datetime, timedelta
from collections import defaultdict
from time import sleep
from urllib import quote_plus
import requests
import logging

logging.basicConfig()
logger = logging.getLogger("RiskIndicatorBridge")


class RiskIndicatorBridge(object):

    def __init__(self, config):
        config = config["main"]
        self.indicators_host = config["indicators_host"]
        self.indicators_proxy = config.get("indicators_proxy")
        self.queue_limit = config.get("queue_limit", 100)

        self.monitors_host = config["monitors_host"]
        self.monitors_token = config["monitors_token"]
        self.skip_monitoring_statuses = config.get("skip_monitoring_statuses", ("active", "draft"))

        self.run_interval = timedelta(seconds=config.get("run_interval", 24 * 3600))
        self.queue_error_interval = config.get("queue_error_interval", 30 * 60)
        self.request_retries = config.get("request_retries", 5)
        self.request_timeout = config.get("request_timeout", 10)

        self.process_stats = defaultdict(int)

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
        self.process_stats = defaultdict(int)

        for risk in self.queue:
            try:
                self.process_risk(risk)
            except Exception as e:
                logger.exception(e)
                self.process_stats["failed"] += 1

        logger.info("Risk processing finished: {}".format(dict(self.process_stats)))

    def process_risk(self, risk):
        self.process_stats["processed"] += 1

        if risk["topRisk"]:
            self.process_stats["processed_top"] += 1

            monitorings = self.get_tender_monitoring_list(risk["tenderOuterId"])
            has_live_monitoring = any(m["status"] in self.skip_monitoring_statuses for m in monitorings)

            if not has_live_monitoring:
                self.process_stats["processed_to_start"] += 1

                details = self.get_item_details(risk["tenderId"])
                self.start_monitoring(risk, details)

    # Access APIs methods #

    @property
    def queue(self):
        regions = self.request("{}region-indicators-queue/regions/".format(self.indicators_host))

        for region in regions:
            page, total_pages = 0, 1

            while page < total_pages:
                url = "{}region-indicators-queue/?region={}&limit={}&page={}".format(
                    self.indicators_host,
                    quote_plus(region.encode('utf-8')),
                    self.queue_limit,
                    page
                )
                response = self.request(url)
                data = response.get("data", [])
                for risk in data:
                    yield risk

                total_pages = response.get("pagination", {}).get("totalPages", 1)
                page += 1

    def get_item_details(self, item_id):
        url = "{}tenders/{}".format(self.indicators_host, item_id)
        return self.request(url)

    def get_tender_monitoring_list(self, tender_id):
        url = "{}tenders/{}/monitorings?mode=draft".format(self.monitors_host, tender_id)
        response = self.request(
            url,
            headers={
                "Authorization": "Bearer {}".format(self.monitors_token)
            }
        )
        return response["data"]

    def start_monitoring(self, risk_info, details):
        indicators_info = {i["indicatorId"]: i for i in details["indicatorsInfo"]}

        indicators = [(i["indicatorCode"], i["value"])
                      for key in ("tenderIndicators", "lotIndicators")
                      for i in details["indicators"].get(key)]

        # first with value==True, then sort by id
        indicators = list(sorted(indicators, key=lambda e: (not e[1], e[0])))

        status_to_stages = {
            'active.enquiries': 'planning',
            'active.tendering': 'planning',
            'active': 'planning',

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

        triggered_risks = [uid for uid, value in indicators if value == 1]
        self.request(
            "{}monitorings".format(self.monitors_host),
            method="post",
            json={
                "data": {
                    "tender_id": details["id"],
                    "reasons": ["indicator"],
                    "procuringStages": list(stages),
                    "riskIndicators": triggered_risks,
                    "riskIndicatorsTotalImpact": risk_info.get("tenderScore"),
                    "riskIndicatorsRegion": risk_info.get("region"),
                    "riskIndicatorsImpactCategory": risk_info.get("impactCategory"),
                    "riskIndicatorsLastChecks": {
                        uid: indicators_info[uid].get("lastCheckingDate")
                        for uid in triggered_risks
                        if uid in indicators_info
                    },
                }
            },
            headers={
                "Authorization": "Bearer {}".format(self.monitors_token)
            }
        )

        self.process_stats["created"] += 1

    # Helper methods #

    class TerminateExecutionException(Exception):
        pass

    def request(self, url, method="get", **kwargs):
        if url.startswith(self.indicators_host) and self.indicators_proxy:
            kwargs.update(proxies={
                "http": self.indicators_proxy,
                "https": self.indicators_proxy,
            })

        func = getattr(requests, method)
        timeout = kwargs.pop("timeout", self.request_timeout)
        tries = self.request_retries

        while tries:
            try:
                response = func(url, timeout=timeout, **kwargs)
            except Exception as e:
                logger.exception(e)
            else:
                status_ok = 201 if method == "post" else 200
                if response.status_code == status_ok:
                    try:
                        json_res = response.json()
                    except Exception as e:
                        logger.exception(e)
                    else:
                        return json_res
                else:
                    logger.error("Unsuccessful response code: {}".format(response.status_code))

            sleep(self.request_retries - tries)
            tries -= 1

        raise self.TerminateExecutionException("Access problems with {} {}".format(method, url))
