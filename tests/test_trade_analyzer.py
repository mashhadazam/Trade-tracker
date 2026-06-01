from __future__ import annotations

import importlib.util
import tempfile
import unittest
from io import StringIO
from pathlib import Path

PANDAS_AVAILABLE = importlib.util.find_spec("pandas") is not None


CSV = """Date/Time,Symbol,Description,Asset Category,Buy/Sell,Quantity,Price,Proceeds,Commission,Realized P&L,Expiry,Strike,Put/Call,Underlying,Order ID,Execution ID,Account
2026-05-01 10:00:00,SPXW,SPXW 2026-05-01 5000 P,Index Option,SELL,1,1.50,150,-1,0,2026-05-01,5000,P,SPXW,100,E1,U123
2026-05-01 10:00:01,SPXW,SPXW 2026-05-01 4950 P,Index Option,BUY,1,0.50,-50,-1,0,2026-05-01,4950,P,SPXW,100,E2,U123
2026-05-01 11:00:00,SPXW,SPXW 2026-05-01 5000 P,Index Option,BUY,1,0.40,-40,-1,60,2026-05-01,5000,P,SPXW,101,E3,U123
2026-05-01 11:00:01,SPXW,SPXW 2026-05-01 4950 P,Index Option,SELL,1,0.10,10,-1,30,2026-05-01,4950,P,SPXW,101,E4,U123
"""


@unittest.skipUnless(PANDAS_AVAILABLE, "pandas is required for trade_analyzer tests")
class TradeAnalyzerTests(unittest.TestCase):
    def test_importer_maps_ibkr_columns_and_stores_raw_executions(self):
        from trade_analyzer.src.import_ibkr import import_csv, load_executions

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "trades.db"
            imported = import_csv(StringIO(CSV), db_path)
            stored = load_executions(db_path)

        self.assertEqual(len(imported), 4)
        self.assertEqual(len(stored), 4)
        self.assertEqual(stored.loc[0, "underlying"], "SPXW")
        self.assertEqual(stored.loc[0, "option_type"], "P")
        self.assertEqual(stored.loc[0, "side"], "SELL")

    def test_reconstructs_credit_spread_and_daily_metrics(self):
        from trade_analyzer.src.import_ibkr import read_ibkr_csv
        from trade_analyzer.src.metrics import summary_metrics
        from trade_analyzer.src.reconstruct_spreads import reconstruct_spreads
        from trade_analyzer.src.rules import append_rule_results

        executions = read_ibkr_csv(StringIO(CSV))
        spreads = append_rule_results(reconstruct_spreads(executions))
        summary = summary_metrics(spreads)

        self.assertEqual(len(spreads), 1)
        spread = spreads.iloc[0]
        self.assertEqual(spread["strategy"], "Bull Put Credit Spread")
        self.assertEqual(spread["short_strike"], 5000)
        self.assertEqual(spread["long_strike"], 4950)
        self.assertEqual(spread["width"], 50)
        self.assertEqual(spread["entry_credit_or_debit"], 1.0)
        self.assertEqual(spread["close_credit_or_debit"], -0.3)
        self.assertEqual(summary["trade_count"], 1)
        self.assertGreaterEqual(spread["overall_rule_score"], 75)


if __name__ == "__main__":
    unittest.main()
