"""Run: python3 -m unittest discover -s tests"""

import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import prices  # noqa: E402

TODAY = dt.date(2026, 11, 21)


def row(**kw):
    base = {"name": "ZES", "keys": ["Zorlu Energy Solutions"], "ac": 10.99, "dc": [12.99, 16.49],
            "source": "https://zes.net/tr/fiyatlandirma", "check": "page",
            "checked": "2026-11-21", "changed": "2026-11-05"}
    return {**base, **kw}


class ValidateTest(unittest.TestCase):
    def check(self, rows, **table):
        t = {"country": "TR", "currency": "TRY", "operators": rows, **table}
        return prices.problems(Path("tr.json"), t, TODAY)

    def test_a_good_table_passes(self):
        self.assertEqual(self.check([row(), row(name="Eşarj", keys=[], ac=9.9, dc=13.5,
                                                 source="https://esarj.com/fiyatlandirma")]), [])

    def test_app_only_rows_may_have_no_price(self):
        self.assertEqual(self.check([row(ac=None, dc=None, check="app")]), [])
        self.assertTrue(self.check([row(ac=None, dc=None)]))

    def test_problems(self):
        cases = {
            "out of range": row(dc=16490),
            "[min, max]": row(dc=[1, 2, 3]),
            "future": row(checked="2026-12-01"),
            "after checked": row(changed="2026-11-22"),
            "YYYY-MM-DD": row(checked="21.11.2026"),
            "https": row(source="http://zes.net"),
            "check must": row(check="maybe"),
            "needs a name": row(name=" "),
        }
        for problem, r in cases.items():
            self.assertIn(problem, " ".join(self.check([r])), problem)

    def test_keys_must_not_price_two_operators(self):
        errors = self.check([row(), row(name="Other", keys=["ZES"])])
        self.assertIn("also ZES's", " ".join(errors))

    def test_file_name_and_country_agree(self):
        self.assertIn("country must be TR", " ".join(self.check([row()], country="DE")))


class FoldTest(unittest.TestCase):
    def test_folds_like_the_backend(self):
        self.assertEqual(prices.fold("Eşarj (TR)"), "esarjtr")
        self.assertEqual(prices.fold("Şarj Ağı İşletmecisi"), "sarjagiisletmecisi")


class SummaryTest(unittest.TestCase):
    def test_lists_changes_additions_and_rechecks(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = {"country": "TR", "currency": "TRY", "operators": [
                row(), row(name="Trugo", ac=9.95, dc=[12.0, 14.98], checked="2026-11-14",
                           source="https://trugo.com.tr")]}
            new = {"country": "TR", "currency": "TRY", "operators": [
                row(dc=[13.49, 16.99]), row(name="Trugo", ac=9.95, dc=[12.0, 14.98],
                                            source="https://trugo.com.tr"),
                row(name="Voltrun", keys=[], ac=9.9, dc=12.9, source="https://voltrun.com")]}
            orig_root = prices.ROOT
            try:
                prices.ROOT = Path(tmp)
                import subprocess
                subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp, check=True)
                (Path(tmp) / "tr.json").write_text(json.dumps(old))
                subprocess.run(["git", "add", "tr.json"], cwd=tmp, check=True)
                subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x"],
                               cwd=tmp, check=True)
                (Path(tmp) / "tr.json").write_text(json.dumps(new))
                lines = prices.summary("HEAD")
            finally:
                prices.ROOT = orig_root
        text = "\n".join(lines)
        self.assertIn("**ZES**: DC 12.99–16.49 → 13.49–16.99 TRY/kWh", text)
        self.assertIn("**Voltrun** added: AC 9.9, DC 12.9", text)
        self.assertIn("unchanged, checked again: Trugo", text)


class DueTest(unittest.TestCase):
    def test_rows_checked_a_week_ago_are_due(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "tr.json"
            f.write_text(json.dumps({"country": "TR", "currency": "TRY", "operators": [
                row(checked="2026-11-14"), row(name="New", keys=[], checked="2026-11-20")]}))
            self.assertEqual(prices.due(7, [f], TODAY), ["TR ZES: checked 2026-11-14"])


if __name__ == "__main__":
    unittest.main()
