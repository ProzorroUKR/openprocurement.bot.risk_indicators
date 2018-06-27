from openprocurement.bot.risk_indicators.main import main
import unittest
import mock


class MainScriptTest(unittest.TestCase):

    @mock.patch('openprocurement.bot.risk_indicators.main.sys')
    def test_no_config(self, sys):
        sys.argv = ["cmd"]

        with mock.patch('openprocurement.bot.risk_indicators.main.logger.critical') as log_critical:
            main()

        log_critical.assert_called_once_with("Config is not provided")

    @mock.patch('openprocurement.bot.risk_indicators.main.sys')
    def test_missed_config(self, sys):
        sys.argv = ["cmd", "openprocurement/bot/risk_indicators/config_what.yml"]

        with mock.patch('openprocurement.bot.risk_indicators.main.logger.critical') as log_critical:
            main()

        log_critical.assert_called_once_with("Invalid configuration file")

    @mock.patch('openprocurement.bot.risk_indicators.main.sys')
    def test_incorrect_config(self, sys):
        sys.argv = ["cmd", "openprocurement/bot/risk_indicators/main.py"]

        with mock.patch('openprocurement.bot.risk_indicators.main.logger.critical') as log_critical:
            main()

        log_critical.assert_any_call("Invalid configuration file")

    @mock.patch('openprocurement.bot.risk_indicators.main.sys')
    def test_run(self, sys):
        sys.argv = ["cmd", "openprocurement/bot/risk_indicators/tests/test_config.yaml"]

        with mock.patch('openprocurement.bot.risk_indicators.main.RiskIndicatorBridge') as bridge:
            bridge.return_value = mock.MagicMock()
            main()

        bridge.assert_called_once()
        bridge.return_value.run.assert_called_once()

    @mock.patch('openprocurement.bot.risk_indicators.main.sys')
    def test_run_exception(self, sys):
        sys.argv = ["cmd", "openprocurement/bot/risk_indicators/tests/test_config.yaml"]

        with mock.patch('openprocurement.bot.risk_indicators.main.logger.critical') as log_critical:
            with mock.patch('openprocurement.bot.risk_indicators.main.RiskIndicatorBridge') as bridge:
                bridge.side_effect = ValueError(7)
                main()

        bridge.assert_called_once()
        log_critical.assert_any_call("Unhandled exception: 7")

