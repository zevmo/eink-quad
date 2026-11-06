"""Policy and paint tests for the two-board power format. No network."""
import os
import time
import unittest

os.environ["TZ"] = "America/New_York"
os.environ.setdefault("QUAD_MODEL", "e1001")
time.tzset()

import power
import render as R
import lower


def _at(y, mo, d, h, mi=0):
    return time.mktime((y, mo, d, h, mi, 0, 0, 0, -1))


class G:
    def __init__(self, state, start, us=None, them=None, detail="", opp="OPP", home=True,
                 status_name="", completed_at=None, completed_source="", event_id=""):
        self.state, self.start = state, start
        self.us, self.them = us, them
        self.detail, self.opp, self.opp_name, self.home = detail, opp, opp, home
        self.status_name, self.event_id = status_name, event_id
        self.completed_at, self.completed_source = completed_at, completed_source


class Row:
    def __init__(self, key, live=None, last=None, nxt=None):
        self.key, self.label = key, key.upper()
        self.live, self.last, self.next = live, last, nxt


class PowerPolicy(unittest.TestCase):
    def test_nav_stays_off_sports_and_shabbat_pages(self):
        import app
        self.assertEqual(app.nav_pages({"layout": "lower"}), ["quad"])
        daily = app.nav_pages({"layout": "thirds", "daily_home": True})
        self.assertIn("shabbat", daily)
        self.assertIn("newsletter", daily)
        self.assertNotIn("sports", daily)
        self.assertNotIn("scoreboard", daily)
        self.assertNotIn("shopping", daily)
        self.assertIn("sports", app.nav_pages({"layout": "quad"}))

    def test_device_mode_unchanged(self):
        # Charged boards stay live. Forcing sleep on any vbat was cancelled.
        self.assertEqual(power.device_mode(None), "live")
        self.assertEqual(power.device_mode(3.80), "live")
        self.assertEqual(power.device_mode(4.05), "live")
        self.assertEqual(power.device_mode(3.79), "sleep")
        self.assertEqual(power.device_next_s("live"), 0)
        self.assertEqual(power.device_next_s("sleep"), 600)

    def test_quiet_union_and_windows(self):
        c = {"cadence": "windows", "layout": "thirds", "quiet": "0-6",
             "content_windows": ["7:30", "12:30", "18:30"], "daily_home": True}
        self.assertTrue(power.quiet_now(c, _at(2026, 11, 6, 23)))
        self.assertTrue(power.quiet_now(c, _at(2026, 11, 6, 3)))
        self.assertTrue(power.quiet_now(c, _at(2026, 11, 6, 6, 30)))
        self.assertFalse(power.quiet_now(c, _at(2026, 11, 6, 7, 30)))
        self.assertFalse(power.quiet_now(c, _at(2026, 11, 6, 21)))
        early = _at(2026, 11, 6, 6)
        noon = _at(2026, 11, 6, 15)
        eve = _at(2026, 11, 6, 18, 30)
        self.assertIsNone(power.due_window(None, early, c))
        hit = power.due_window(None, noon, c)
        self.assertEqual(hit, _at(2026, 11, 6, 12, 30))
        self.assertIsNone(power.due_window(hit, noon, c))
        self.assertEqual(power.due_window(hit, eve, c), eve)
        interval = {"cadence": "interval", "layout": "quad", "quiet": ""}
        self.assertFalse(power.quiet_now(interval, _at(2026, 11, 6, 23)))

    def test_faces(self):
        self.assertTrue(power.daily_home_cfg({"layout": "thirds"}))
        self.assertFalse(power.daily_home_cfg({"layout": "thirds", "daily_home": False}))
        self.assertTrue(power.is_lower_cfg({"layout": "gallery"}))
        self.assertTrue(power.is_lower_cfg({"layout": "lower"}))
        self.assertFalse(power.is_lower_cfg({"layout": "gallery", "e1001_home": "gallery"}))
        self.assertTrue(power.is_gallery_legacy({"layout": "gallery", "e1001_home": "gallery"}))
        self.assertTrue(power.windows_on({"layout": "thirds"}))
        self.assertFalse(power.windows_on({"layout": "gallery"}))
        self.assertEqual(power.selected_favorites({"teams": ["bucs", "rays"]}), list(power.FAVORITE_KEYS))
        self.assertEqual(power.selected_favorites({"teams": ["devils", "jets", "bucs"]}), ["jets", "devils"])

    def test_full_flash_floor(self):
        self.assertEqual(power.full_every_min({"cadence": "windows", "layout": "thirds", "full_every_min": 240}), 1440)
        self.assertEqual(power.full_every_min({"cadence": "windows", "layout": "thirds", "full_every_min": 0}), 0)
        self.assertEqual(power.full_every_min({"cadence": "interval", "layout": "quad", "full_every_min": 240}), 240)
        self.assertEqual(power.full_every_min({"cadence": "windows", "layout": "thirds", "full_every_min": 1800}), 1800)
        self.assertTrue(power.partials_preferred({"layout": "thirds", "cadence": "windows"}))

    def test_shabbat_edge(self):
        class Sh:
            candles, havdalah, holiday_candles = 1000.0, 2000.0, None
        self.assertEqual(power.shabbat_edge(0, Sh(), 1500), 1000)
        self.assertIsNone(power.shabbat_edge(1000, Sh(), 1500))
        self.assertEqual(power.shabbat_edge(1500, Sh(), 2000), 2000)
        self.assertIsNone(power.shabbat_edge(0, Sh(), 1000 + 7 * 3600))
        self.assertIsNone(power.shabbat_edge(0, None, 1500))
        self.assertTrue(power.market_flip_day(_at(2026, 11, 6, 0, 5)))   # Friday
        self.assertTrue(power.market_flip_day(_at(2026, 11, 8, 0, 5)))   # Sunday
        self.assertFalse(power.market_flip_day(_at(2026, 11, 7, 0, 5)))  # Saturday

    def test_scores_face(self):
        now = _at(2026, 11, 7, 20)
        live = Row("jets", live=G("in", now - 3600, 17, 13, "Q3 6:02", "LV"))
        expired = Row("mets", last=G("post", now - 30 * 3600, 5, 3, "Final", "ATL",
                                     completed_at=now - 30 * 3600, completed_source="espn"))
        face, shown = power.classify([expired, live], now)
        self.assertEqual(face, "sports")
        self.assertEqual([r.key for r in shown], ["jets"])
        held = Row("devils", last=G("post", now - 5 * 3600, 2, 1, "Final", "NYR",
                                    completed_at=now - 2 * 3600, completed_source="espn"))
        face, shown = power.classify([held], now)
        self.assertEqual(face, "sports")
        self.assertEqual(shown[0].key, "devils")
        old = Row("devils", last=G("post", now - 20 * 3600, 2, 1, "Final", "NYR"))
        self.assertEqual(power.classify([old], now)[0], "news")
        soon = Row("nets", nxt=G("pre", now + 2 * 3600, detail="7:00 PM", opp="BOS"))
        self.assertEqual(power.classify([soon], now)[0], "news")
        self.assertTrue(power.starts_soon([soon], now))
        self.assertFalse(power.starts_soon([soon], now - 10 * 3600))

    def test_unchanged_final_signature(self):
        now = _at(2026, 11, 7, 22)
        row = Row("jets", last=G("post", now - 4 * 3600, 21, 17, "Final", "NE",
                                 completed_at=now - 3600, completed_source="espn"))
        fox, tech = ["Jets practice"], ["Chip report"]
        a = power.content_signature([row], now, fox, tech)
        b = power.content_signature([row], now + 50 * 60, fox, tech)
        self.assertEqual(a, b)
        row.last.us = 24
        self.assertNotEqual(a, power.content_signature([row], now, fox, tech))
        # past the hold, the face is news again even if the final score is untouched
        later = now + 12 * 3600
        self.assertEqual(power.content_signature([row], later, fox, tech)[0], "news")
        self.assertEqual(power.content_signature([row], later, fox, tech),
                         power.content_signature([row], later + 600, fox, tech))

    def test_ot_hold_follows_last_play_not_schedule(self):
        """A game that ended in OT 2h ago is still up, even though start+typical
        length+6h has already passed. A final whose last play was 7h ago is not,
        even if the old scheduled window would still be open."""
        now = _at(2026, 11, 8, 23, 30)
        ot = Row("navy_fb", last=G("post", now - 11 * 3600, 28, 21, "Final/OT", "ARMY",
                                   completed_at=now - 2 * 3600, completed_source="espn", event_id="ot"))
        self.assertTrue(power.held_final(ot, now))
        self.assertFalse(now < (now - 11 * 3600) + power.sport_len("navy_fb") + power.HOLD_S)
        short = Row("mets", last=G("post", now - 8 * 3600, 3, 2, "Final", "ATL",
                                   completed_at=now - 7 * 3600, completed_source="espn", event_id="reg"))
        self.assertFalse(power.held_final(short, now))
        self.assertTrue(now < (now - 8 * 3600) + power.sport_len("mets") + power.HOLD_S)
        # ESPN end still holds when the game started a day earlier (resume / late).
        late = Row("jets", last=G("post", now - 26 * 3600, 20, 17, "Final/OT", "NE",
                                  completed_at=now - 3600, completed_source="espn", event_id="late"))
        self.assertTrue(power.held_final(late, now))


class Paint(unittest.TestCase):
    def test_markets_and_daily_slots(self):
        R.set_profile("e1003")
        friday = _at(2026, 11, 6, 12)
        wed = _at(2026, 11, 4, 15)
        self.assertFalse(R.show_markets(R.Ctx(now=friday, cfg={"layout": "thirds"})))
        self.assertTrue(R.show_markets(R.Ctx(now=wed, cfg={"layout": "thirds"})))
        sunday = _at(2026, 11, 8, 15)
        league = [G("in", sunday - 1800)]
        daily = R.Ctx(now=sunday, cfg={"layout": "thirds", "daily_home": True, "smart_home": True},
                      league=league, teams=[Row("jets", live=G("in", sunday - 100))])
        self.assertEqual(R.home_mode(daily), "daily")
        boxes, names = R.home_layout(daily)
        self.assertEqual(names, power.DAILY_SLOTS)
        self.assertNotIn("sports", names)
        self.assertNotIn("calendar", names)
        self.assertNotIn("sky", names)
        self.assertNotIn("scoreboard", names)
        self.assertNotIn("league", names)
        self.assertNotIn("shopping", names)
        for need in ("shabbat", "newsletter", "weather"):
            self.assertIn(need, names)
        self.assertEqual(len(boxes), len(names))
        # GT911 hit-test still maps a slot (layout units, same math as app.tap).
        x0, y0, x1, y1 = boxes[0]
        ux, uy = (x0 + x1) / 2, (y0 + y1) / 2
        hit = next(name for (a, b, c, d), name in zip(boxes, names) if a <= ux < c and b <= uy < d)
        self.assertEqual(hit, "shabbat")
        slate = R.Ctx(now=sunday, cfg={"layout": "thirds", "daily_home": False, "smart_home": True},
                      league=league)
        self.assertEqual(R.home_mode(slate), "nfl")
        # Friday/Saturday: newsletter is the majority; weather and Shabbat stay; no markets, no calendar.
        shab = R.Ctx(now=friday, cfg={"layout": "thirds", "daily_home": True},
                     quotes=[type("Q", (), {"name": "S&P 500"})()])
        sboxes, snames = R.home_layout(shab)
        self.assertEqual(snames, power.DAILY_SHABBAT)
        self.assertNotIn("calendar", snames)
        self.assertNotIn("sports", snames)
        self.assertIn("weather", snames)
        self.assertIn("shabbat", snames)
        self.assertFalse(R.show_markets(shab))
        nl = sboxes[snames.index("newsletter")]
        body = R.W * (R.H - R.GRID_Y)
        self.assertGreater((nl[2] - nl[0]) * (nl[3] - nl[1]), 0.5 * body)
        wboxes, wnames = R.home_layout(R.Ctx(now=wed, cfg={"layout": "thirds", "daily_home": True}))
        self.assertIn("weather", wnames)
        self.assertNotIn("calendar", wnames)
        self.assertNotIn("sky", wnames)
        self.assertEqual(wnames, power.DAILY_SLOTS)
        trip = wboxes[wnames.index("trips")]
        self.assertEqual(trip[2], R.W)  # Next Trip takes the old radar column too

    def test_one_game_fills_the_panel(self):
        R.set_profile("e1001")
        now = _at(2026, 11, 4, 20)
        row = Row("jets", live=G("in", now - 1000, 17, 13, "Q3 6:02", "Patriots"))
        img = lower.compose(R.Ctx(now=now, cfg={"layout": "lower"}, teams=[row], gallery={"asof": now - 600}))
        # Rows of ink below the header. A one-game score has to occupy the body,
        # not a short list under the title.
        ink_rows = sum(1 for y in range(80, img.size[1] - 8)
                       if any(img.getpixel((x, y)) < 180 for x in range(20, img.size[0] - 20, 6)))
        self.assertGreater(ink_rows, 180)
        # Three games still draw, but one game's ink is taller than a short list.
        rows = [
            Row("jets", live=G("in", now - 1000, 17, 13, "Q3", "NE")),
            Row("devils", live=G("in", now - 800, 2, 1, "2nd", "NYR")),
            Row("nets", live=G("in", now - 600, 88, 80, "4th", "BOS")),
        ]
        many = lower.compose(R.Ctx(now=now, cfg={"layout": "lower"}, teams=rows, gallery={"asof": now - 600}))
        self.assertEqual(many.size, img.size)

    def test_lower_paint_ignores_clock(self):
        R.set_profile("e1001")
        now = _at(2026, 11, 4, 15, 10)
        asof = now - 3600
        fox = [{"title": "Senate schedule slips"}, {"title": "Storm tracks up the coast"}]
        tech = [{"title": "Chip export rules tighten"}]
        cfg = {"layout": "lower", "cadence": "windows", "e1001_home": "lower"}
        ctx = R.Ctx(now=now, cfg=cfg, gallery={"asof": asof, "fox": fox, "tech": tech}, teams=[])
        a = lower.compose(ctx)
        self.assertEqual(a.size, (800, 480))
        b = lower.compose(R.Ctx(now=now + 1800, cfg=cfg, gallery={"asof": asof, "fox": fox, "tech": tech}))
        self.assertEqual(a.tobytes(), b.tobytes())
        c = lower.compose(R.Ctx(now=now + 1800, cfg=cfg, gallery={
            "asof": asof, "fox": fox + [{"title": "A new headline"}], "tech": tech}))
        self.assertNotEqual(a.tobytes(), c.tobytes())
        row = Row("jets", live=G("in", now - 1000, 10, 7, "Q2 1:00", "BUF"))
        s1 = lower.compose(R.Ctx(now=now, cfg=cfg, teams=[row], gallery={"asof": asof}))
        s2 = lower.compose(R.Ctx(now=now + 1800, cfg=cfg, teams=[row], gallery={"asof": asof}))
        self.assertEqual(s1.tobytes(), s2.tobytes())
        row.live.us = 13
        s3 = lower.compose(R.Ctx(now=now + 1800, cfg=cfg, teams=[row], gallery={"asof": asof}))
        self.assertNotEqual(s1.tobytes(), s3.tobytes())
        # header band is ink (sample the corner, not a white glyph)
        self.assertLess(s1.getpixel((4, 8)), 40)
        self.assertLess(a.getpixel((4, 8)), 40)


if __name__ == "__main__":
    unittest.main()
