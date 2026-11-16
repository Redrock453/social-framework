"""Тести поля role для публікацій фактчека і підрахунку незалежних підтверджень (картка #54).

Правило: independent_count = кількість публікацій з role=origin або role=independent;
reprint не рахується; число завжди виводиться з ролей, вручну не задається.
origin_known = True лише коли є публікація з role=origin. Якщо публікацій немає,
у записі independent_count дорівнює None («невідомо»), а не 0.
"""
from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path

from social.case import create_case, read_jsonl
from social.tools import core


def pub(url: str, role: str, **extra) -> dict:
    return {"url": url, "role": role, **extra}


class IndependentCountTest(unittest.TestCase):
    def test_empty_list_is_zero(self):
        self.assertEqual(core.independent_count([]), 0)
        self.assertEqual(core.independent_count(None), 0)

    def test_only_reprints_is_zero(self):
        self.assertEqual(core.independent_count([pub("https://t.me/a/1", "reprint"),
                                                 pub("https://t.me/b/2", "reprint")]), 0)

    def test_origin_plus_reprints_plus_independent_is_two(self):
        pubs = [pub("https://t.me/a/1", "origin"),
                *[pub(f"https://t.me/r/{i}", "reprint") for i in range(5)],
                pub("https://t.me/b/2", "independent")]
        self.assertEqual(core.independent_count(pubs), 2)

    def test_two_independent_without_origin_is_two(self):
        self.assertEqual(core.independent_count([pub("https://t.me/a/1", "independent"),
                                                 pub("https://t.me/b/2", "independent")]), 2)

    def test_unknown_role_raises(self):
        with self.assertRaises(ValueError):
            core.independent_count([pub("https://t.me/a/1", "supporting")])

    def test_roles_constant(self):
        self.assertEqual(core.PUBLICATION_ROLES, ("origin", "reprint", "independent"))

    def test_origin_known_from_roles(self):
        self.assertIs(core.origin_known([]), False)
        self.assertIs(core.origin_known(None), False)
        self.assertIs(core.origin_known([pub("https://t.me/a/1", "independent")]), False)
        self.assertIs(core.origin_known([pub("https://t.me/a/1", "reprint"),
                                         pub("https://t.me/b/2", "origin")]), True)


class FactCheckPublicationsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.case = create_case(Path(self._tmp.name) / "case", "Тестовий кейс", "Що сталося?")

    def tearDown(self):
        self._tmp.cleanup()

    def records(self) -> list[dict]:
        return read_jsonl(self.case / "wiki/factchecks.jsonl")

    def test_record_stores_publications_and_computed_count(self):
        pubs = [pub("https://t.me/a/1", "origin", channel="a", date="2026-11-10"),
                pub("https://t.me/b/2", "reprint", channel="b"),
                pub("https://t.me/c/3", "independent", channel="c", quote="1113 платників")]
        rec = core.fact_check(self.case, "Твердження", "правда", "B", "пояснення", [], publications=pubs)
        self.assertEqual(rec["independent_count"], 2)
        self.assertIs(rec["origin_known"], True)
        self.assertEqual(rec["publications"], pubs)
        stored = self.records()[0]
        self.assertEqual(stored["independent_count"], 2)
        self.assertEqual([p["role"] for p in stored["publications"]], ["origin", "reprint", "independent"])
        # старі поля лишились, sources заповнено з url публікацій
        self.assertEqual(stored["sources"], ["https://t.me/a/1", "https://t.me/b/2", "https://t.me/c/3"])

    def test_explicit_sources_are_kept(self):
        rec = core.fact_check(self.case, "Твердження", "правда", "B", "пояснення",
                              ["https://example.org/report"],
                              publications=[pub("https://t.me/a/1", "origin")])
        self.assertEqual(rec["sources"], ["https://example.org/report"])
        self.assertEqual(rec["independent_count"], 1)

    def test_no_publications_keeps_old_behaviour(self):
        rec = core.fact_check(self.case, "Твердження", "частково", "C", "пояснення", ["https://example.org"])
        self.assertEqual(rec["sources"], ["https://example.org"])
        self.assertEqual(rec["publications"], [])
        self.assertIsNone(rec["independent_count"])
        self.assertIs(rec["origin_known"], False)
        stored = self.records()[0]
        self.assertIsNone(stored["independent_count"])
        self.assertIs(stored["origin_known"], False)

    def test_empty_publications_list_is_unknown_too(self):
        rec = core.fact_check(self.case, "Твердження", "припущення", "D", "пояснення", [], publications=[])
        self.assertEqual(rec["publications"], [])
        self.assertIsNone(rec["independent_count"])
        self.assertIs(rec["origin_known"], False)

    def test_two_independent_without_origin(self):
        pubs = [pub("https://t.me/a/1", "independent"), pub("https://t.me/b/2", "independent")]
        rec = core.fact_check(self.case, "Твердження", "правда", "B", "два джерела", [], publications=pubs)
        self.assertIs(rec["origin_known"], False)
        self.assertEqual(rec["independent_count"], 2)
        stored = self.records()[0]
        self.assertIs(stored["origin_known"], False)
        self.assertEqual(stored["independent_count"], 2)

    def test_one_origin_means_origin_known(self):
        rec = core.fact_check(self.case, "Твердження", "правда", "B", "першоджерело є", [],
                              publications=[pub("https://t.me/a/1", "origin"),
                                            pub("https://t.me/b/2", "reprint")])
        self.assertIs(rec["origin_known"], True)
        self.assertEqual(rec["independent_count"], 1)

    def test_independent_count_cannot_be_passed_manually(self):
        params = inspect.signature(core.fact_check).parameters
        self.assertNotIn("independent_count", params)
        self.assertNotIn("origin_known", params)

    def test_invalid_role_raises(self):
        with self.assertRaises(ValueError):
            core.fact_check(self.case, "Твердження", "правда", "B", "пояснення", [],
                            publications=[pub("https://t.me/a/1", "supporting")])
        self.assertEqual(self.records(), [])

    def test_missing_url_raises(self):
        with self.assertRaises(ValueError):
            core.fact_check(self.case, "Твердження", "правда", "B", "пояснення", [],
                            publications=[{"role": "origin"}])

    def test_missing_role_raises(self):
        with self.assertRaises(ValueError):
            core.fact_check(self.case, "Твердження", "правда", "B", "пояснення", [],
                            publications=[{"url": "https://t.me/a/1"}])

    def test_two_origins_raise(self):
        with self.assertRaises(ValueError):
            core.fact_check(self.case, "Твердження", "правда", "B", "пояснення", [],
                            publications=[pub("https://t.me/a/1", "origin"),
                                          pub("https://t.me/b/2", "origin")])

    def test_f01_pilot_case(self):
        """Пілот F01: 44 млн грн від 1113 платників на 10.11.2026."""
        claim = ("ВАКС: 1113 платників сплатили 44 млн грн за 10.11.2026 "
                 "(прокурор САП Карась через Радіо Свобода)")
        pubs = [
            pub("https://t.me/svoboda_radio/50334", "origin", channel="svoboda_radio",
                date="2026-11-10", quote="прокурор САП Карась: 1113 платників, 44 млн грн"),
            pub("https://t.me/fuckcorruption/7532", "reprint", channel="fuckcorruption",
                reason="пряма пересилка 50334"),
            pub("https://t.me/hromadske_ua/90854", "reprint", channel="hromadske_ua",
                reason="часткове підтвердження: власний коментар ВАКС лише про суму 44 млн, без 1113; "
                       "повного твердження не підтверджує"),
            pub("https://t.me/cxemu/5124", "reprint", channel="cxemu", reason="пересилка 50334"),
            pub("https://t.me/suspilnenews/79107", "reprint", channel="suspilnenews",
                reason="часткове підтвердження: власний запит до ВАКС без числа 1113; "
                       "повного твердження не підтверджує"),
            pub("https://t.me/ukrpravda_news/86455", "reprint", channel="ukrpravda_news",
                reason="точне 1113 з Карася/РС, не окреме підтвердження"),
            pub("https://t.me/babel/92280", "reprint", channel="babel", reason="атрибуція РС"),
            pub("https://t.me/uniannet/206691", "reprint", channel="uniannet"),
            pub("https://t.me/liganet/53114", "independent", channel="liganet",
                reason="пресслужба ВАКС для LIGA.net сама називає 1113 платників"),
            pub("https://t.me/liganet/53115", "reprint", channel="liganet", reason="повтор власного допису"),
        ]
        rec = core.fact_check(self.case, claim, "правда", "B", "дві незалежні атрибуції числа 1113",
                              [], publications=pubs)
        roles = [p["role"] for p in rec["publications"]]
        self.assertEqual(roles.count("origin"), 1)
        self.assertEqual(roles.count("independent"), 1)
        self.assertEqual(core.independent_count(rec["publications"]), 2)
        self.assertEqual(rec["independent_count"], 2)
        self.assertIs(rec["origin_known"], True)
        stored = self.records()[-1]
        self.assertEqual(stored["independent_count"], 2)
        self.assertIs(stored["origin_known"], True)
        self.assertEqual(stored["sources"], [p["url"] for p in pubs])


if __name__ == "__main__":
    unittest.main()
