# -*- coding: utf-8 -*-
from openprocurement.bot.risk_indicators.bridge import RiskIndicatorBridge
from datetime import timedelta
import requests
import unittest
import logging.config
import yaml
import mock
import os.path


queue_data = [
    {
        "tenderId": "UA-1",
        "tenderOuterId": "1",
        "topRisk": False,
    },
    {
        "tenderId": "UA-2",
        "tenderOuterId": "2",
        "topRisk": True,
    },
    {
        "tenderId": "UA-3",
        "tenderOuterId": "3",
        "topRisk": True,
    },
    {
        "tenderId": "UA-4",
        "tenderOuterId": "4",
        "topRisk": True,
    },
]

tender_monitoring_data = {
    "1": [],
    "2": [{"status": "active"}],
    "3": [{"status": "draft"}],
    "4": [{"status": "cancelled"}],
}

indicators_info = [
    {
        "indicatorId": "1",
        "indicatorStage": "Award",
        "indicatorShortName": u"Пояснення 1",
    },
    {
        "indicatorId": "2",
        "indicatorStage": "Tendering",
        "indicatorShortName": u"Пояснення 2",
    },
    {
        "indicatorId": "3",
        "indicatorStage": "",
        "indicatorShortName": u"Пояснення 3",
    },
    {
        "indicatorId": "4",
        "indicatorStage": "Something else",
        "indicatorShortName": u"Пояснення 4",
    },
    {
        "indicatorId": "5",
        "indicatorStage": "Something else 2",
        "indicatorShortName": u"Пояснення 5",
    }
]

indicators = {
    "lotIndicators": [
        {"indicatorId": "1", "value": 1},
        {"indicatorId": "2", "value": 0},
    ],
    "tenderIndicators": [
        {"indicatorId": "3", "value": 0},
        {"indicatorId": "4", "value": 1},
    ],
}


def get_request_mock(url, **kwargs):
    response = requests.Response()
    response.status_code = 200

    if "indicators-queue" in url:
        content = {"data": queue_data}

    elif "/tenders/" in url:
        if "/monitorings" in url:
            tender_id = url.split("/")[-2]
            content = {"data": tender_monitoring_data.get(tender_id)}
        else:
            tender_id = url.split("/")[-1][3:]
            content = {
                "id": tender_id,
                "indicatorsInfo": indicators_info,
                "indicators": indicators,

            }
    else:
        raise NotImplementedError("Unknown request: {} {}".format(url, kwargs))

    response.json = mock.Mock(return_value=content)
    return response


class BridgeTest(unittest.TestCase):

    def setUp(self):
        config_path = os.path.join(os.path.dirname(__file__), "test_config.yaml")
        with open(config_path) as config_file_obj:
            self.config = yaml.load(config_file_obj.read())

        logging.config.dictConfig(self.config)

    @mock.patch("openprocurement.bot.risk_indicators.bridge.RiskIndicatorBridge.process_risks")
    def test_process_risks_exception(self, process_risks_mock):
        process_risks_mock.side_effect = Exception("Shit happens")

        bridge = RiskIndicatorBridge(self.config)

        sleep_mock = mock.Mock()
        sleep_mock.side_effect = StopIteration
        with mock.patch("openprocurement.bot.risk_indicators.bridge.sleep", sleep_mock):
            try:
                bridge.run()
            except StopIteration:
                pass

        sleep_mock.assert_called_once_with(bridge.queue_error_interval)

    @mock.patch("openprocurement.bot.risk_indicators.bridge.RiskIndicatorBridge.process_risk")
    def test_process_risk_exception(self, process_risk_mock):
        process_risk_mock.side_effect = Exception("Shit happens")

        bridge = RiskIndicatorBridge(self.config)

        with mock.patch("openprocurement.bot.risk_indicators.bridge.RiskIndicatorBridge.queue", range(12)):

            sleep_mock = mock.Mock()
            sleep_mock.side_effect = StopIteration
            with mock.patch("openprocurement.bot.risk_indicators.bridge.sleep", sleep_mock):
                try:
                    bridge.run()
                except StopIteration:
                    pass

        sleep_mock.assert_called_once_with((bridge.run_interval - timedelta(seconds=1)).seconds)

    @mock.patch("openprocurement.bot.risk_indicators.bridge.requests")
    def test_request_exception(self, requests_mock):
        requests_mock.get.side_effect = Exception("Shit happens")

        bridge = RiskIndicatorBridge(self.config)
        bridge.request_retries = 2

        try:
            bridge.request("http://localhost")
        except bridge.TerminateExecutionException as e:
            print(str(e))
        else:
            raise AssertionError("TerminateExecutionException expected")

        self.assertEqual(len(requests_mock.get.call_args_list), 2)
        requests_mock.get.assert_called_with('http://localhost', timeout=bridge.request_timeout)

    @mock.patch("openprocurement.bot.risk_indicators.bridge.requests")
    def test_request_json_exception(self, requests_mock):
        requests_mock.get.return_value = requests.Response()
        requests_mock.get.return_value.status_code = 200

        bridge = RiskIndicatorBridge(self.config)
        bridge.request_retries = 2

        try:
            bridge.request("http://localhost")
        except bridge.TerminateExecutionException as e:
            print(str(e))
        else:
            raise AssertionError("TerminateExecutionException expected")

        self.assertEqual(len(requests_mock.get.call_args_list), 2)
        requests_mock.get.assert_called_with('http://localhost', timeout=bridge.request_timeout)

    @mock.patch("openprocurement.bot.risk_indicators.bridge.requests")
    def test_request_unsuccessful_code(self, requests_mock):
        requests_mock.get.return_value = requests.Response()
        requests_mock.get.return_value.status_code = 500
        requests_mock.get.return_value.json = mock.Mock(return_value=[])

        bridge = RiskIndicatorBridge(self.config)
        bridge.request_retries = 2

        try:
            bridge.request("http://localhost")
        except bridge.TerminateExecutionException as e:
            print(str(e))
        else:
            raise AssertionError("TerminateExecutionException expected")

        self.assertEqual(len(requests_mock.get.call_args_list), 2)
        requests_mock.get.assert_called_with('http://localhost', timeout=bridge.request_timeout)

    @mock.patch("openprocurement.bot.risk_indicators.bridge.requests")
    def test_run(self, requests_mock):
        requests_mock.get = get_request_mock
        requests_mock.post = mock.Mock(return_value=mock.MagicMock(status_code=201))

        bridge = RiskIndicatorBridge(self.config)

        sleep_mock = mock.Mock()
        sleep_mock.side_effect = StopIteration
        with mock.patch("openprocurement.bot.risk_indicators.bridge.sleep", sleep_mock):
            try:
                bridge.run()
            except StopIteration:
                pass

        requests_mock.post.assert_called_once_with(
            'https://audit-api-dev.prozorro.gov.ua/api/2.4/monitorings',
            headers={
                'Authorization': 'Bearer 11111111111111111111111111111111'
            },
            json={
                "data": {
                    'reasons': ['indicator'],
                    'decision': {'description': u'1: Пояснення 1 (Спрацював)\n4: Пояснення 4 (Спрацював)\n'
                                                u'2: Пояснення 2 (Не спрацював)\n3: Пояснення 3 (Не спрацював)'},
                    'procuringStages': ['awarding'],
                    'tender_id': '4'
                }
            },
            timeout=bridge.request_timeout
        )

    @mock.patch("openprocurement.bot.risk_indicators.bridge.requests")
    def test_start_monitoring(self, requests_mock):
        post_mock = mock.Mock(return_value=mock.MagicMock(status_code=201))
        requests_mock.post = post_mock

        bridge = RiskIndicatorBridge(self.config)

        details = {
            "id": "f" * 32,
            "indicators": indicators,
            "indicatorsInfo": indicators_info
        }

        bridge.start_monitoring(details)
        post_mock.assert_called_once_with(
            'https://audit-api-dev.prozorro.gov.ua/api/2.4/monitorings',
            headers={'Authorization': 'Bearer 11111111111111111111111111111111'},
            json={
                'data': {
                    'reasons': ['indicator'],
                    'decision': {
                        'description': u'1: Пояснення 1 (Спрацював)\n4: Пояснення 4 (Спрацював)\n'
                                       u'2: Пояснення 2 (Не спрацював)\n3: Пояснення 3 (Не спрацював)'
                    },
                    'procuringStages': ['awarding'],
                    'tender_id': 'ffffffffffffffffffffffffffffffff',
                }
            },
            timeout=bridge.request_timeout
        )


