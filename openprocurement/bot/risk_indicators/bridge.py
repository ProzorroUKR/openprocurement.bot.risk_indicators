from datetime import datetime, timedelta
from time import sleep
import requests
import logging

logger = logging.getLogger("RiskIndicatorBridge")


class RiskIndicatorBridge(object):

    def __init__(self, config):
        config = config["main"]
        self.indicators_host = config["indicators_host"]
        self.queue_types = config.get("queue_types", ("high", "medium", "low"))
        self.queue_limit = config.get("queue_limit", 100)

        self.monitors_host = config["monitors_host"]
        self.monitors_token = config["monitors_token"]
        self.skip_monitoring_statuses = config.get("skip_monitoring_statuses", ("active", "draft"))
        self.expected_stages = {'planning', 'awarding', 'contracting'}

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
                logger.error(e)
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
                logger.error(e)
                errors += 1

        logger.info("Risk processing finished. Number of skipped: {}".format(errors))

    def process_risk(self, risk):
        if risk["topRisk"]:
            monitorings = self.get_tender_monitoring_list(risk["tenderOuterId"])
            has_live_monitoring = any(m["status"] in self.skip_monitoring_statuses for m in monitorings)

            if not has_live_monitoring:
                details = self.get_item_details(risk["tenderId"])
                self.start_monitoring(details)

    # Access APIs methods #

    @property
    def queue(self):
        for queue_type in self.queue_types:
            url = "{}indicators-queue/{}?limit={}&page=0".format(
                self.indicators_host,
                queue_type,
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

    def start_monitoring(self, details):
        indicators_info = details["indicatorsInfo"]
        # 'planning', 'awarding', 'contracting' - SAS API
        # 'Tendering', 'Award' - Indicators API
        stages_convert = {
            "Tendering": "planning",
            "Award": "awarding",
        }
        stages = [stages_convert.get(i["indicatorStage"], i["indicatorStage"])
                  for i in indicators_info
                  if i["indicatorStage"]]

        diff_stages = set(stages) - self.expected_stages
        if diff_stages:
            logger.warning("Found unexpected stages: {}".format(diff_stages))
            stages = list(set(stages) & self.expected_stages)

        self.request(
            "{}/monitorings".format(self.monitors_host),
            method="post",
            json={
                "tender_id": details["id"],
                "reasons": ["indicator"],
                "procuringStages": stages,
                "decision": {
                    "description": "\n".join(
                        ["{}: {}".format(i["indicatorId"], i["indicatorShortName"]) for i in indicators_info]
                    )
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
