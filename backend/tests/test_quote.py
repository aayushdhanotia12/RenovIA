"""Quote engine: one test per line type, each named after its worked example.

Figures use the PLACEHOLDER price list (catalog/kober/data/prices.placeholder.json):
Diseño "estandar" 1,800 MXN/m, Estilo "premium_plus" 2,800 MXN/m, Basi-K 1,200 MXN/m,
Original Q profile +5%, 700 mm width +35%, install 450 MXN/m, joint 600 MXN,
Spläsh premium_plus 1,400 MXN/m², Spläsh install 250 MXN/m², IVA 16%, 10% allowance.
"""

import unittest

from backend.app.catalogue import get_catalogue
from backend.app.money import Money, div_round_half_up, round_outward
from backend.app.quote import CountertopRun, QuoteError, QuoteRequest, SplashRun, choose_pieces, price_quote

CAT = get_catalogue()


def carrara(runs, **kw):
    return QuoteRequest(countertop_finish_id="diseno-white-carrara", profile_id="original_q",
                        countertop_runs=tuple(runs), **kw)


class MoneyTests(unittest.TestCase):
    def test_money_rejects_a_float_amount(self):
        with self.assertRaises(TypeError):
            Money(1.5, "MXN")

    def test_money_rejects_a_bool_and_a_lowercase_currency(self):
        with self.assertRaises(TypeError):
            Money(True, "MXN")
        with self.assertRaises(ValueError):
            Money(100, "mxn")

    def test_money_refuses_to_add_two_currencies(self):
        with self.assertRaises(ValueError):
            Money(100, "MXN") + Money(100, "USD")

    def test_half_up_rounding_of_1_5_centavos_gives_2(self):
        self.assertEqual(div_round_half_up(3, 2), 2)
        self.assertEqual(div_round_half_up(-3, 2), -2)

    def test_range_634230_to_789786_rounds_outward_to_630000_and_790000(self):
        lo, hi = round_outward(Money(634230, "MXN"), Money(789786, "MXN"), 10000)
        self.assertEqual((lo.minor, hi.minor), (630000, 790000))


class PieceTests(unittest.TestCase):
    def test_2530mm_needed_takes_one_3000mm_piece(self):
        self.assertEqual(choose_pieces(2530, [2400, 3000, 3600]), (3000,))

    def test_4620mm_needed_takes_two_2400mm_pieces(self):
        self.assertEqual(choose_pieces(4620, [2400, 3000, 3600]), (2400, 2400))

    def test_3700mm_tie_prefers_the_longer_piece_3000_plus_1200(self):
        self.assertEqual(choose_pieces(3700, [1200, 1800, 2400, 3000, 3600]), (3000, 1200))


class CountertopTests(unittest.TestCase):
    def test_run_2300mm_carrara_original_q_is_one_3000mm_piece_at_5670_mxn(self):
        q = price_quote(carrara([CountertopRun("A", 2300)]), CAT)
        piece = [ln for ln in q.lines if ln.kind == "countertop_piece"]
        self.assertEqual(len(piece), 1)
        self.assertEqual((piece[0].qty, piece[0].unit_price.minor), (1, 567000))
        self.assertIn("2.30 m + 10% allowance = 2.53 m -> 3.00 m", piece[0].detail)

    def test_run_2300mm_install_is_1035_mxn_and_total_with_iva_is_7777_80(self):
        q = price_quote(carrara([CountertopRun("A", 2300)]), CAT)
        install = next(ln for ln in q.lines if ln.kind == "install_countertop")
        self.assertEqual(install.total.minor, 103500)
        self.assertEqual((q.subtotal.minor, q.tax.minor, q.total.minor), (670500, 107280, 777780))

    def test_run_2300mm_typed_by_customer_shows_6300_to_7900_mxn(self):
        q = price_quote(carrara([CountertopRun("A", 2300)], scale_confidence="low"), CAT)
        self.assertEqual((q.estimate_low.minor, q.estimate_high.minor), (630000, 790000))
        self.assertTrue(q.estimate_only)

    def test_run_4200mm_needs_two_2400mm_pieces_and_one_joint(self):
        q = price_quote(carrara([CountertopRun("A", 4200)]), CAT)
        piece = next(ln for ln in q.lines if ln.kind == "countertop_piece")
        join = next(ln for ln in q.lines if ln.kind == "join")
        self.assertEqual((piece.qty, piece.unit_price.minor, piece.total.minor), (2, 453600, 907200))
        self.assertEqual((join.qty, join.total.minor), (1, 60000))

    def test_estilo_run_1000mm_uses_the_short_1200mm_piece_at_3360_mxn(self):
        req = QuoteRequest("estilo-caracatta", "original", (CountertopRun("A", 1000, depth_mm=600),))
        piece = next(ln for ln in price_quote(req, CAT).lines if ln.kind == "countertop_piece")
        self.assertEqual((piece.description.endswith("645 x 1200 mm"), piece.unit_price.minor), (True, 336000))

    def test_estilo_run_1000mm_at_700mm_deep_has_no_short_piece_so_2400mm_at_9072_mxn(self):
        req = QuoteRequest("estilo-caracatta", "original", (CountertopRun("A", 1000, depth_mm=700),))
        piece = next(ln for ln in price_quote(req, CAT).lines if ln.kind == "countertop_piece")
        self.assertEqual((piece.description.endswith("700 x 2400 mm"), piece.unit_price.minor), (True, 907200))

    def test_basik_run_3100mm_needs_two_2400mm_pieces_at_2880_mxn_each(self):
        req = QuoteRequest("basik-almond-leather", "basik", (CountertopRun("A", 3100),))
        piece = next(ln for ln in price_quote(req, CAT).lines if ln.kind == "countertop_piece")
        self.assertEqual((piece.qty, piece.unit_price.minor), (2, 288000))

    def test_estilo_run_3600mm_lists_the_3000mm_piece_first_and_explains_the_run_once(self):
        req = QuoteRequest("estilo-caracatta", "original", (CountertopRun("A", 3600, depth_mm=600),))
        q = price_quote(req, CAT)
        pieces = [ln for ln in q.lines if ln.kind == "countertop_piece"]
        self.assertEqual(len(pieces), 2)
        self.assertTrue(pieces[0].description.endswith("645 x 3000 mm"))
        self.assertTrue(pieces[1].description.endswith("645 x 1200 mm"))
        self.assertEqual(pieces[0].detail, "Run A: 3.60 m + 10% allowance = 3.96 m -> 3.00 m + 1.20 m")
        self.assertEqual(pieces[1].detail, "Run A: extra piece for the same run, joined (see above)")
        self.assertEqual(next(ln for ln in q.lines if ln.kind == "join").qty, 1)

    def test_two_sinks_add_two_undermount_fittings_at_1500_mxn(self):
        q = price_quote(carrara([CountertopRun("A", 2300)], sinks=2), CAT)
        sink = next(ln for ln in q.lines if ln.kind == "sink_undermount")
        self.assertEqual((sink.qty, sink.total.minor), (2, 300000))


class ItemTests(unittest.TestCase):
    """What each pointer on the render shows: an item's share of the quote, IVA included."""

    def test_run_2300mm_with_one_sink_shows_countertop_7777_80_and_sink_1740_with_iva(self):
        q = price_quote(carrara([CountertopRun("A", 2300)], sinks=1), CAT)
        items = {it.item: it for it in q.items}
        self.assertEqual([it.item for it in q.items], ["countertop", "sink"])
        self.assertEqual((items["countertop"].subtotal.minor, items["countertop"].tax.minor,
                          items["countertop"].total.minor), (670500, 107280, 777780))
        self.assertEqual((items["sink"].subtotal.minor, items["sink"].total.minor), (150000, 174000))
        self.assertEqual(sum(it.total.minor for it in q.items), q.total.minor)

    def test_each_quote_line_names_the_item_it_belongs_to(self):
        lines = price_quote(carrara([CountertopRun("A", 2300)], sinks=1), CAT).to_json()["lines"]
        self.assertEqual({ln["kind"]: ln["item"] for ln in lines}["sink_undermount"], "sink")
        self.assertTrue(all(ln["item"] == "countertop" for ln in lines if ln["kind"] != "sink_undermount"))

    def test_items_always_add_up_to_the_total_even_when_iva_rounds(self):
        req = carrara([CountertopRun("A", 2333)], sinks=1, splash_finish_id="estilo-caracatta",
                      splash_runs=(SplashRun("S1", 2333, 537),))
        q = price_quote(req, CAT)
        self.assertEqual(sum(it.tax.minor for it in q.items), q.tax.minor)
        self.assertEqual(sum(it.total.minor for it in q.items), q.total.minor)

    def test_typed_measurements_give_each_item_a_range_around_its_total(self):
        q = price_quote(carrara([CountertopRun("A", 2300)], scale_confidence="low"), CAT)
        top = q.items[0]
        self.assertLessEqual(top.low.minor, top.total.minor)
        self.assertGreaterEqual(top.high.minor, top.total.minor)
        self.assertLess(top.low.minor, top.high.minor)

    def test_carrara_2300mm_original_q_to_original_saves_313_20_and_essence_adds_939_60(self):
        q = price_quote(carrara([CountertopRun("A", 2300)]), CAT)
        diff = {o.profile_id: o.difference.minor for o in q.profile_options}
        self.assertEqual(diff, {"original": -31320, "slim": -31320, "essence": 93960})
        self.assertEqual(q.profile_options[-1].profile_id, "essence")  # cheapest change first

    def test_a_basik_finish_offers_no_other_profile(self):
        q = price_quote(QuoteRequest("basik-almond-leather", "basik", (CountertopRun("A", 2300),)), CAT)
        self.assertEqual(q.profile_options, [])


class SplashTests(unittest.TestCase):
    def test_splash_3100_by_600mm_caracatta_is_one_600x3600_panel_at_3024_mxn(self):
        req = carrara([CountertopRun("A", 2300)], splash_finish_id="estilo-caracatta",
                      splash_runs=(SplashRun("S1", 3100, 600),))
        q = price_quote(req, CAT)
        panel = next(ln for ln in q.lines if ln.kind == "splash_panel")
        install = next(ln for ln in q.lines if ln.kind == "install_splash")
        self.assertEqual((panel.qty, panel.unit_price.minor), (1, 302400))
        self.assertEqual(install.total.minor, 46500)
        self.assertEqual(install.description, "Spläsh installation, 1.86 m²")


class RuleTests(unittest.TestCase):
    def test_basik_finish_in_original_q_profile_is_refused(self):
        with self.assertRaises(QuoteError):
            price_quote(QuoteRequest("basik-almond-leather", "original_q", (CountertopRun("A", 2000),)), CAT)

    def test_porfido_nero_in_slim_is_refused(self):
        with self.assertRaises(QuoteError):
            price_quote(QuoteRequest("estilo-porfido-nero", "slim", (CountertopRun("A", 2000),)), CAT)

    def test_unknown_finish_id_is_refused(self):
        with self.assertRaises(QuoteError):
            price_quote(QuoteRequest("diseno-made-up-marble", "original", (CountertopRun("A", 2000),)), CAT)

    def test_a_float_length_is_refused(self):
        with self.assertRaises(QuoteError):
            price_quote(carrara([CountertopRun("A", 2300.0)]), CAT)

    def test_depth_1200mm_has_no_standard_countertop(self):
        with self.assertRaises(Exception):
            price_quote(carrara([CountertopRun("A", 2300, depth_mm=1200)]), CAT)


class LanguageTests(unittest.TestCase):
    def test_spanish_quote_says_tramo_and_merma_for_run_a(self):
        req = QuoteRequest("diseno-white-carrara", "original_q", (CountertopRun("A", 2300),), language="es")
        q = price_quote(req, CAT)
        piece = next(ln for ln in q.lines if ln.kind == "countertop_piece")
        self.assertIn("Tramo A: 2.30 m + 10% de merma = 2.53 m -> 3.00 m", piece.detail)
        self.assertTrue(piece.description.startswith("Cubierta White Carrara"))
        self.assertIn("Precios de ejemplo", q.assumptions[0])


class FinalQuoteTests(unittest.TestCase):
    def test_final_quote_after_site_visit_is_a_single_figure(self):
        q = price_quote(carrara([CountertopRun("A", 2300)]), CAT, final=True)
        self.assertFalse(q.estimate_only)
        self.assertEqual(q.estimate_low, q.total)
        self.assertEqual(q.estimate_high, q.total)

    def test_visit_fee_500_mxn_shows_as_580_with_iva_and_is_free_if_the_customer_hires_the_job(self):
        j = price_quote(carrara([CountertopRun("A", 2300)]), CAT).to_json()
        self.assertEqual((j["visit_fee"]["minor"], j["visit_fee_rule"]), (58000, "free_if_hired"))
        self.assertNotIn("balance", j)  # nothing is paid up front, so there is no balance to show

    def test_placeholder_price_list_is_declared_on_every_quote(self):
        q = price_quote(carrara([CountertopRun("A", 2300)]), CAT)
        self.assertEqual(q.price_list_status, "PLACEHOLDER")
        self.assertIn("placeholders", q.assumptions[0])


if __name__ == "__main__":
    unittest.main()
