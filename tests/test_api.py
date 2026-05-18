import json
import os
import tempfile
import unittest


class TradeApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        os.environ["TRADE_TRACKER_DB"] = os.path.join(self.temp_dir.name, "trades.db")

        import app

        app.DB_PATH = os.environ["TRADE_TRACKER_DB"]
        app.init_db()
        self.app = app

    def test_create_trade_and_dashboard(self):
        trade = self.app.create_trade(
            {
                "symbol": "aapl",
                "side": "long",
                "setup_tag": "Breakout",
                "qty": 10,
                "entry_price": 190,
                "risk_amount": 100,
                "pnl": 50,
            }
        )

        self.assertEqual(trade["symbol"], "AAPL")
        self.assertEqual(trade["side"], "LONG")
        self.assertEqual(self.app.dashboard()["total_pnl"], 50)

    def test_invalid_trade_rejected(self):
        with self.assertRaises(ValueError):
            self.app.create_trade({"symbol": "", "side": "LONG"})


if __name__ == "__main__":
    unittest.main()
