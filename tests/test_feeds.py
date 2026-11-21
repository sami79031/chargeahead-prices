"""Run: python3 -m unittest discover -s tests"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import feeds  # noqa: E402

AD_HOC = {"id": "t1", "currency": "EUR", "type": "AD_HOC_PAYMENT", "last_updated": "2026-11-09T11:50:36Z",
          "elements": [{"price_components": [{"type": "ENERGY", "price": 0.5, "vat": 21, "step_size": 1},
                                             {"type": "TIME", "price": 1.2, "vat": 21, "step_size": 60}]},
                       {"price_components": [{"type": "TIME", "price": 6.0, "vat": 21}],
                        "restrictions": {"min_duration": 5400}}]}


class TariffTest(unittest.TestCase):
    def test_energy_and_time_with_vat_blocking_fee_left_out(self):
        lo, hi, per_min, per_session, _, _ = feeds.tariff_rate(AD_HOC)
        self.assertEqual((lo, hi), (0.605, 0.605))
        self.assertAlmostEqual(per_min, 1.2 * 1.21 / 60, places=4)
        self.assertIsNone(per_session)

    def test_ocpdb_taxes(self):
        t = {"type": "AD_HOC_PAYMENT", "elements": [{"price_components": [
            {"type": "ENERGY", "price": 0.496, "taxes": [{"name": "VAT", "percentage": "19"}], "tax_included": False}]}]}
        self.assertEqual(feeds.tariff_rate(t)[0], round(0.496 * 1.19, 4))
        t["elements"][0]["price_components"][0]["tax_included"] = True
        self.assertEqual(feeds.tariff_rate(t)[0], 0.496)

    def test_unknown_vat_gives_no_price(self):
        t = {"type": None, "elements": [{"price_components": [{"type": "ENERGY", "price": 0.36, "vat": None}]}]}
        self.assertIsNone(feeds.tariff_rate(t))
        t["elements"][0]["price_components"][0]["vat"] = 0.21   # a fraction, read as 21%
        self.assertEqual(feeds.tariff_rate(t)[0], round(0.36 * 1.21, 4))
        free_time = {"type": None, "elements": [{"price_components": [
            {"type": "ENERGY", "price": 0.5, "vat": 21}, {"type": "TIME", "price": 0, "vat": None}]}]}
        self.assertIsNotNone(feeds.tariff_rate(free_time), "a free component needs no VAT")

    def test_power_bands_only_from_restrictions(self):
        def tariff(*bands):
            return {"type": None, "elements": [
                {"price_components": [{"type": "ENERGY", "price": p, "vat": 21}], "restrictions": r}
                for p, r in bands]}
        one = feeds.tariff_rate(tariff((0.5, {"min_power": 50})))
        self.assertEqual(one[4:], (50.0, None))
        zero = feeds.tariff_rate(tariff((0.5, {"min_power": 150, "max_power": 0})))
        self.assertEqual(zero[4:], (150.0, None), "max_power 0 is no limit")
        upside = feeds.tariff_rate(tariff((0.5, {"min_power": 150, "max_power": 50})))
        self.assertEqual(upside[4:], (None, None))
        two = feeds.tariff_rate(tariff((0.4, {"max_power": 50}), (0.6, {"min_power": 50})))
        self.assertEqual(two[:2], (0.484, 0.726))
        self.assertEqual(two[4:], (None, None), "several bands become one range")

    def test_only_paying_at_the_charger(self):
        self.assertIsNone(feeds.tariff_rate({**AD_HOC, "type": "REGULAR"}))
        self.assertIsNotNone(feeds.tariff_rate({**AD_HOC, "type": None}))
        no_energy = {"type": None, "elements": [{"price_components": [{"type": "TIME", "price": 1}]}]}
        self.assertIsNone(feeds.tariff_rate(no_energy))
        typo = {"type": None, "elements": [{"price_components": [{"type": "ENERGY", "price": 49}]}]}
        self.assertIsNone(feeds.tariff_rate(typo))


class SitesTest(unittest.TestCase):
    def location(self, **kw):
        return {"id": "L1", "coordinates": {"latitude": "52.36878", "longitude": "4.92901"},
                "operator": {"name": "Fastned"}, "evses": [
                    {"connectors": [{"power_type": "DC", "max_electric_power": 300000, "tariff_ids": ["t1"]}]},
                    {"connectors": [{"power_type": "DC", "max_electric_power": 50000, "tariff_ids": ["t1"]}]},
                    {"connectors": [{"power_type": "AC_3_PHASE", "max_electric_power": 22000, "tariff_ids": ["missing"]}]}],
                **kw}

    def test_a_site_per_priced_location(self):
        [site] = feeds.sites_of([self.location()], {"t1": AD_HOC}, lambda loc: "NDW")
        lat, lon, op, rates, src, checked, cur = site
        self.assertEqual((lat, lon, op, src, checked, cur), (52.36878, 4.92901, "Fastned", "NDW", "2026-11-09", "EUR"))
        self.assertEqual(len(rates), 1)
        # No band: the tariff has no power restriction.
        self.assertEqual(rates[0][:5], [1, None, None, 0.605, 0.605])

    def test_tariffs_found_through_evse_associations(self):
        loc = self.location()
        for i, evse in enumerate(loc["evses"]):
            evse["uid"] = f"e{i}"
            for con in evse["connectors"]:
                con["tariff_ids"] = ["does-not-resolve"]
        [site] = feeds.sites_of([loc], {}, lambda l: "X", evse_tariffs={"e0": AD_HOC})
        self.assertEqual(site[3][0][:5], [1, None, None, 0.605, 0.605])

    def test_sites_outside_the_country_are_left_out(self):
        far = self.location(coordinates={"latitude": "39.6", "longitude": "-95.8"})
        self.assertEqual(feeds.sites_of([far], {"t1": AD_HOC}, lambda l: "NDW", box=feeds.BOXES["NL"]), [])

    def test_unlicensed_and_unpriced_locations_are_left_out(self):
        self.assertEqual(feeds.sites_of([self.location()], {"t1": AD_HOC}, lambda loc: None), [])
        self.assertEqual(feeds.sites_of([self.location()], {}, lambda loc: "NDW"), [])


class ShrinkTest(unittest.TestCase):
    def test_a_country_that_halved_is_not_published(self):
        previous = {"countries": {"NL": 47000, "DE": 26000}}
        self.assertEqual(feeds.shrunk({"NL": 47100, "DE": 0}, previous), ["DE"])
        self.assertEqual(feeds.shrunk({"NL": 30000, "DE": 25000}, previous), [])
        self.assertEqual(feeds.shrunk({"NL": 10}, None), [])


class CellsTest(unittest.TestCase):
    def test_cells_share_rates_and_list_an_index(self):
        sites = [(52.36878, 4.92901, "Fastned", [[1, 50.0, 300.0, 0.69, 0.69, None, None]], "NDW", "2026-11-09", "EUR"),
                 (52.36, 4.90, "EFL", [[1, 50.0, 300.0, 0.69, 0.69, None, None]], "NDW", "2026-11-01", "EUR"),
                 (48.137, 11.575, "EnBW", [[1, 50.0, 300.0, 0.59, 0.59, None, None]], "X", "2026-11-01", "EUR")]
        with tempfile.TemporaryDirectory() as tmp:
            feeds.write_cells(sites, tmp)
            index = json.loads((Path(tmp) / "ocpi" / "index.json").read_text())
            self.assertEqual(index["cells"], ["240_57", "261_24"])
            cell = json.loads((Path(tmp) / "ocpi" / "261_24.json").read_text())
        self.assertEqual(len(cell["sites"]), 2)
        self.assertEqual(len(cell["rates"]), 1)
        self.assertEqual(cell["sites"][0][:2], [52.36878, 4.92901])


if __name__ == "__main__":
    unittest.main()
