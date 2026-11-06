"""Integration tests for the power format. No deploy, no push.

Covers the real device poll (firmware query string, both panels), final-hold
anchored to an ESPN last-play time and reloaded from state.json, unchanged
frames, the overnight boundary, and saved layout/gallery defaults.

    python3 -m unittest test_integration.py
"""
from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from copy import deepcopy

os.environ.setdefault("TZ", "America/New_York")
time.tzset()

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

if __name__ == "__main__" and "--serve" in sys.argv:
    sys.path.insert(0, HERE)
    import app
    app.serve()
    raise SystemExit(0)


def _at(y, mo, d, h, mi=0):
    return time.mktime((y, mo, d, h, mi, 0, 0, 0, -1))


class G:
    def __init__(self, state, start, us=None, them=None, detail="Final", opp="OPP",
                 status_name="", completed_at=None, completed_source="", event_id="", home=True):
        self.state, self.start, self.us, self.them = state, start, us, them
        self.detail, self.opp, self.opp_name, self.home = detail, opp, opp, home
        self.status_name, self.event_id = status_name, event_id
        self.completed_at, self.completed_source = completed_at, completed_source


class Row:
    def __init__(self, key, live=None, last=None, nxt=None):
        self.key, self.label = key, key
        self.live, self.last, self.next = live, last, nxt


def _reel_box(body):
    if body[:4] != b"REEL" or body[4] != 1:
        raise AssertionError(f"not a REEL ({body[:8]!r})")
    n = struct.unpack_from("<H", body, 5)[0]
    if n < 1:
        raise AssertionError("empty reel")
    x0, y0, x1, y1, _delay = struct.unpack_from("<HHHHH", body, 7)
    return n, (x0, y0, x1, y1)


def _http(url, timeout=20):
    try:
        r = urllib.request.urlopen(url, timeout=timeout)
        return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


class SourceRemote(unittest.TestCase):
    """Read-only identity of this checkout. Does not fetch or push."""

    def test_origin_is_zevmo_and_parent_is_e1003_thirds(self):
        url = subprocess.check_output(["git", "remote", "get-url", "origin"], cwd=ROOT, text=True).strip()
        hostpath = url.split("@")[-1]
        self.assertTrue(hostpath.startswith("github.com/zevmo/eink-quad"), hostpath.split("/", 1)[-1][:40])
        parent = subprocess.check_output(["git", "rev-parse", "e1003-thirds"], cwd=ROOT, text=True).strip()
        self.assertTrue(parent.startswith("f14bfb0"))
        subprocess.check_call(["git", "merge-base", "--is-ancestor", "e1003-thirds", "HEAD"], cwd=ROOT)
        # No other push remote is configured. J-Rod-Ay is not a remote here.
        remotes = subprocess.check_output(["git", "remote"], cwd=ROOT, text=True).split()
        self.assertEqual(remotes, ["origin"])


class FinalHold(unittest.TestCase):
    def test_summary_last_play_is_the_end(self):
        import sources as S
        # Shape returned by site.api.espn.com/.../summary (meta.lastPlayWallClock).
        payload = {
            "meta": {"firstPlayWallClock": "2025-11-02T18:02:35Z",
                     "lastPlayWallClock": "2025-11-02T21:36:34Z"},
            "header": {"competitions": [{"date": "2025-11-02T18:00Z",
                                         "status": {"type": {"name": "STATUS_FINAL", "state": "post",
                                                             "detail": "Final", "shortDetail": "Final"}}}]},
        }
        at = S.completion_from_summary(payload)
        self.assertEqual(at, __import__("calendar").timegm(
            time.strptime("2025-11-02T21:36:34", "%Y-%m-%dT%H:%M:%S")))
        # The scheduled start is not an end time.
        self.assertIsNone(S.completion_from_summary({"date": "2025-11-02T18:00Z", "competitions": [
            {"date": "2025-11-02T18:00Z", "status": {"type": {"state": "post", "name": "STATUS_FINAL"}}}] }))

    def test_wallclock_calls_summary_endpoint(self):
        import sources as S
        seen = {}

        def fake(url, params=None):
            seen["url"] = url
            seen["params"] = params
            return {"meta": {"lastPlayWallClock": "2025-11-02T21:36:34Z"}}

        old, S._espn = S._espn, fake
        S._wall_cache.pop("401772765", None)
        try:
            row = Row("jets", last=G("post", 1, 17, 14, event_id="401772765", opp="CIN"))
            at = S.final_wallclock(row)
        finally:
            S._espn = old
        self.assertIn("/football/nfl/summary", seen["url"])
        self.assertEqual(seen["params"]["event"], "401772765")
        self.assertEqual(at, __import__("calendar").timegm(time.strptime("2025-11-02T21:36:34", "%Y-%m-%dT%H:%M:%S")))

    def test_ot_and_persist_across_board_restart(self):
        import app
        import power
        now = time.time()
        # Kickoff 11h ago, last play 2h ago. Scheduled length + 6h has already passed.
        start = now - 11 * 3600
        whistle = now - 2 * 3600
        self.assertFalse(now < start + power.sport_len("navy_fb") + power.HOLD_S)
        store = {}
        looked = {"n": 0}

        def lookup(row):
            looked["n"] += 1
            return whistle

        row = Row("navy_fb", last=G("post", start, 31, 28, "Final/OT", "ARMY", event_id="ot-1"))
        power.stamp_final(row, now, store, lookup)
        self.assertEqual(store["ot-1"]["source"], "espn")
        self.assertEqual(row.last.completed_at, whistle)
        self.assertTrue(power.held_final(row, now))
        # A later poll must not move an ESPN stamp, and must not call ESPN again.
        power.stamp_final(row, now + 3600, store, lookup)
        self.assertEqual(looked["n"], 1)
        self.assertEqual(row.last.completed_at, whistle)
        # Restart: a new Board reads state.json and a bare game picks the stamp back up.
        fd, path = tempfile.mkstemp(prefix="quad-state-", suffix=".json")
        os.close(fd)
        old_path, old_finals = app.STATE_PATH, dict(app.board.finals)
        try:
            app.STATE_PATH = path
            app.board.finals = dict(store)
            app.board._persist()
            fresh = app.Board()
            self.assertEqual(fresh.finals["ot-1"]["at"], whistle)
            bare = Row("navy_fb", last=G("post", start, 31, 28, "Final/OT", "ARMY", event_id="ot-1"))
            calls = {"n": 0}

            def boom(row):
                calls["n"] += 1
                raise AssertionError("ESPN should not be asked once the stamp is saved")

            power.stamp_final(bare, now + 7200, fresh.finals, boom)
            self.assertEqual(calls["n"], 0)
            self.assertEqual(bare.last.completed_at, whistle)
            self.assertTrue(power.held_final(bare, now + 7200))
            self.assertFalse(power.held_final(bare, whistle + power.HOLD_S + 1))
        finally:
            app.STATE_PATH = old_path
            app.board.finals = old_finals
            os.remove(path)

    def test_observed_stamp_does_not_slide_and_cap_bounds_a_lost_clock(self):
        import power
        now = time.time()
        store = {}
        g = G("post", now - 4 * 3600, 2, 1, "Final", "NYR", event_id="obs")
        row = Row("devils", last=g)
        power.stamp_final(row, now, store, lookup=lambda r: None)
        self.assertEqual(g.completed_source, "observed")
        self.assertEqual(g.completed_at, now)
        power.stamp_final(row, now + 5000, store, lookup=lambda r: None)
        self.assertEqual(g.completed_at, now)
        self.assertTrue(power.held_final(row, now + 10))
        # Upgrade to the real whistle when the summary finally answers.
        whistle = now - 30 * 60
        power.stamp_final(row, now + 6000, store, lookup=lambda r: whistle)
        self.assertEqual(g.completed_source, "espn")
        self.assertEqual(g.completed_at, whistle)
        # Lost file, ancient kickoff, re-stamp "now": the cap refuses a fresh 6h.
        ancient = Row("jets", last=G("post", now - 30 * 3600, 10, 7, "Final", "NE", event_id="old"))
        lost = {}
        power.stamp_final(ancient, now, lost, lookup=lambda r: None)
        self.assertEqual(ancient.last.completed_source, "observed")
        self.assertFalse(power.held_final(ancient, now))

    def test_faces_live_final_postponed_noscore_news(self):
        import power
        import sources as S
        now = time.time()
        jets_live = Row("jets", live=G("in", now - 1000, 14, 10, "Q3 1:00", "NE"))
        devils_live = Row("devils", live=G("in", now - 500, 1, 1, "1st 4:00", "NYR"))
        mets_held = Row("mets", last=G("post", now - 6 * 3600, 4, 2, "Final", "ATL",
                                       completed_at=now - 2 * 3600, completed_source="espn", event_id="m"))
        navy_ot = Row("navy_fb", last=G("post", now - 11 * 3600, 31, 28, "Final/OT", "ARMY",
                                        completed_at=now - 2 * 3600, completed_source="espn", event_id="n"))
        expired = Row("rutgers_bb", last=G("post", now - 12 * 3600, 70, 60, "Final", "HALL",
                                           completed_at=now - 8 * 3600, completed_source="espn", event_id="r"))
        face, shown = power.classify([devils_live, jets_live], now)
        self.assertEqual(face, "sports")
        self.assertEqual([r.key for r in shown], ["jets", "devils"])
        face, shown = power.classify([expired, jets_live, mets_held], now)
        self.assertEqual([r.key for r in shown], ["jets", "mets"])
        face, shown = power.classify([navy_ot, expired], now)
        self.assertEqual([r.key for r in shown], ["navy_fb"])
        self.assertEqual(power.classify([expired], now)[0], "news")
        self.assertEqual(power.classify([], now), ("news", []))
        upcoming = Row("nets", nxt=G("pre", now + 5 * 3600, detail="7:30 PM", opp="BOS"))
        self.assertEqual(power.classify([upcoming], now)[0], "news")
        # Past the hold, the same final returns the board to news and stays there.
        later = mets_held.last.completed_at + power.HOLD_S + 5
        self.assertEqual(power.classify([mets_held], later)[0], "news")
        self.assertEqual(power.content_signature([mets_held], later, ["A"], ["B"]),
                         power.content_signature([mets_held], later + 3600, ["A"], ["B"]))

        postponed = S._parse_event("jets", {
            "id": "pp", "date": "2026-11-07T17:00Z",
            "competitions": [{
                "status": {"type": {"state": "post", "name": "STATUS_POSTPONED",
                                    "shortDetail": "Postponed", "completed": False}},
                "competitors": [
                    {"homeAway": "home", "team": {"abbreviation": "NYJ", "id": "nyj"}},
                    {"homeAway": "away", "score": "0", "team": {"abbreviation": "NE"}},
                ],
            }],
        })
        self.assertEqual(postponed.status_name, "STATUS_POSTPONED")
        self.assertTrue(power.is_postponed(postponed))
        prow = Row("jets", last=postponed, nxt=postponed)
        self.assertEqual(power.classify([prow], now)[0], "news")
        self.assertFalse(power.is_active(prow, now))

        noscore = S._parse_event("mets", {
            "id": "ns", "date": "2026-11-07T17:00Z",
            "competitions": [{
                "status": {"type": {"state": "post", "name": "STATUS_FINAL", "shortDetail": "Final",
                                    "completed": True}},
                "competitors": [
                    {"homeAway": "home", "team": {"abbreviation": "NYM", "id": "nym"}},
                    {"homeAway": "away", "team": {"abbreviation": "ATL"}},
                ],
            }],
        })
        self.assertIsNone(noscore.us)
        self.assertEqual(power.classify([Row("mets", last=noscore)], now)[0], "news")


class FramesAndNight(unittest.TestCase):
    def setUp(self):
        import app
        import render as R
        self.app, self.R = app, R
        self.cfg = deepcopy(app.cfg)
        self.state = app.STATE_PATH
        self.finals = dict(app.board.finals)
        self.snap = app.board.snap
        app.board.snap = {}
        self.beats = dict(app.board.beats)
        self.version = app.board.version
        self.image = app.board.final.copy()
        self.take = app.board.take
        self.sig = app.board.snap.get("lower_sig")
        self.asof = app.board.snap.get("lower_asof")
        fd, self.tmp = tempfile.mkstemp(prefix="quad-state-", suffix=".json")
        os.close(fd)
        app.STATE_PATH = self.tmp
        R.set_profile("e1001")
        if app.board.final.size != (R.PW, R.PH):
            app.board.final = __import__("PIL").Image.new("1", (R.PW, R.PH), 1)
        app.board.finals = {}
        app.board.beats = {}
        app.board.force_full = False

    def tearDown(self):
        app = self.app
        app.cfg.clear()
        app.cfg.update(self.cfg)
        app.STATE_PATH = self.state
        app.board.finals = self.finals
        app.board.snap = self.snap
        app.board.beats = self.beats
        app.board.version = self.version
        app.board.final = self.image
        app.board.take = self.take
        app.board.snap["lower_sig"] = self.sig
        app.board.snap["lower_asof"] = self.asof
        try:
            os.remove(self.tmp)
        except OSError:
            pass

    def _use(self, **over):
        cfg = {**self.app.DEFAULTS, "weekly_jewish": False, "crisp": False}
        cfg.update(over)
        self.app.cfg.clear()
        self.app.cfg.update(cfg)

    def test_unchanged_final_and_headlines_do_not_redraw(self):
        import lower
        import sources as S
        app = self.app
        self._use(layout="lower", e1001_home="lower", cadence="windows")
        now = time.time()
        row = Row("jets", last=G("post", now - 5 * 3600, 21, 17, "Final", "NE",
                                 completed_at=now - 2 * 3600, completed_source="espn", event_id="jf"))
        news = {"fox": [S.Headline("Senate vote waits", "Fox News", now - 4000)],
                "tech": [S.Headline("Chip rules tighten", "Tech", now - 5000)]}
        app.board.snap = {"teams": [row], "lower_news": news}
        calls = {"n": 0, "s": 0}

        def same_news(force=False):
            calls["n"] += 1
            return {"fox": list(news["fox"]), "tech": list(news["tech"])}

        def same_sports(cfg, force=False, ttl=3500):
            return_row = row
            calls["s"] += 1
            return [return_row]

        old_n, old_s = lower.fetch_news, lower.fetch_favorites
        lower.fetch_news, lower.fetch_favorites = same_news, same_sports
        try:
            self.assertTrue(app.board.refresh_lower(force=True))
            with app.board.cond:
                app.board.redraw("first", major=True)
            version, blob, asof = app.board.version, app.board.final.tobytes(), app.board.snap["lower_asof"]
            self.assertFalse(app.board.refresh_lower(force=True))
            self.assertFalse(app.board.button(0) or False)
            # button returns None; the point is the glass did not move
            self.assertEqual(app.board.version, version)
            self.assertEqual(app.board.final.tobytes(), blob)
            self.assertEqual(app.board.snap["lower_asof"], asof)
            self.assertGreaterEqual(calls["n"], 1)
            self.assertGreaterEqual(calls["s"], 1)
            # A failed retry keeps the previous payload and still does not paint.
            def boom_news(force=False):
                raise RuntimeError("fox down")

            def boom_sports(cfg, force=False, ttl=3500):
                raise RuntimeError("espn down")

            lower.fetch_news, lower.fetch_favorites = boom_news, boom_sports
            self.assertFalse(app.board.refresh_lower(force=True))
            self.assertEqual(app.board.version, version)
            self.assertEqual(app.board.final.tobytes(), blob)
            self.assertEqual(app.board.snap["lower_asof"], asof)
            # New hour, same bytes from the source: still no paint.
            app.board.beats["lower_news"] = power_hour_before()
            app.board.beats["lower_sports"] = app.board.beats["lower_news"]
            lower.fetch_news, lower.fetch_favorites = same_news, same_sports
            calls["n"] = calls["s"] = 0
            app.board._tick_lower(time.time())
            self.assertGreaterEqual(calls["n"] + calls["s"], 1)
            self.assertEqual(app.board.version, version)
            self.assertEqual(app.board.final.tobytes(), blob)
        finally:
            lower.fetch_news, lower.fetch_favorites = old_n, old_s

    def test_score_change_does_redraw(self):
        import lower
        app = self.app
        self._use(layout="lower", e1001_home="lower")
        now = time.time()
        row = Row("jets", last=G("post", now - 4 * 3600, 21, 17, "Final", "NE",
                                 completed_at=now - 3600, completed_source="espn", event_id="jf2"))
        app.board.snap = {"teams": [row], "lower_news": {"fox": [], "tech": []}}

        def changed(cfg, force=False, ttl=3500):
            return [row]

        old_s, old_n = lower.fetch_favorites, lower.fetch_news
        lower.fetch_favorites = changed
        lower.fetch_news = lambda force=False: {"fox": [], "tech": []}
        try:
            app.board.refresh_lower(force=True)
            with app.board.cond:
                app.board.redraw("paint", major=True)
            blob, version = app.board.final.tobytes(), app.board.version
            row.last.us = 24
            self.assertTrue(app.board.refresh_lower(force=True, news=False))
            with app.board.cond:
                app.board.redraw("score", major=False)
        finally:
            lower.fetch_favorites, lower.fetch_news = old_s, old_n
        self.assertNotEqual(app.board.final.tobytes(), blob)
        self.assertGreater(app.board.version, version)

    def test_overnight_only_shabbat_edges(self):
        import power
        app = self.app
        self._use(layout="thirds", daily_home=True, cadence="windows",
                  content_windows=["7:30", "12:30", "18:30"], quiet="0-6", weekly_jewish=False)
        taken = []
        app.board.take = lambda name, force=False: taken.append(name)

        def run(at, beats):
            taken.clear()
            app.board.beats = dict(beats)
            app.board.snap["shabbat"] = beats.get("shabbat_obj")
            app.board.force_full = False
            old = app.time.time
            app.time.time = lambda: at
            try:
                app.board.tick()
            finally:
                app.time.time = old
            return list(taken)

        # 02:00, nothing time-critical: no fetch at all.
        night = _at(2026, 11, 4, 2, 0)  # Wednesday
        self.assertEqual(run(night, {"day": "2026-11-04", "shabbat_edge": night}), [])
        # Saturday midnight is quiet and is not a market flip.
        sat = _at(2026, 11, 7, 0, 5)
        self.assertEqual(run(sat, {"day": "2026-11-06", "shabbat_edge": sat}), [])
        # Friday midnight flips markets even inside quiet hours.
        fri = _at(2026, 11, 6, 0, 5)
        got = run(fri, {"day": "2026-11-05", "shabbat_edge": fri})
        self.assertIn("news", got)
        self.assertIn("shabbat", got)
        self.assertNotIn("sports", got)
        self.assertNotIn("sky", got)
        # Havdalah after 22:00 still updates, and does not pull the whole board.
        hav = _at(2026, 11, 6, 22, 25)
        import sources as S
        sh = S.Shabbat(candles=_at(2026, 11, 6, 16, 20), havdalah=_at(2026, 11, 6, 22, 20))
        got = run(hav, {"day": "2026-11-06", "shabbat_edge": _at(2026, 11, 6, 18), "shabbat_obj": sh})
        self.assertEqual(sorted(got), ["news", "shabbat"])
        # 07:29 is still quiet and before the 7:30 window.
        early = _at(2026, 11, 4, 7, 29)
        self.assertEqual(run(early, {"day": "2026-11-04", "shabbat_edge": early}), [])
        # 07:30 is the morning window. Sports is not on this face.
        morn = _at(2026, 11, 4, 7, 30)
        got = run(morn, {"day": "2026-11-04", "shabbat_edge": morn})
        self.assertIn("weather", got)
        self.assertIn("news", got)
        self.assertNotIn("sports", got)
        self.assertNotIn("calendar", got)

    def test_live_scores_poll_every_15_minutes(self):
        import lower
        import power
        app = self.app
        self._use(layout="lower", e1001_home="lower", cadence="windows")
        t0 = (int(time.time()) // power.LIVE_POLL_S) * power.LIVE_POLL_S + 30
        row = Row("jets", live=G("in", t0 - 1000, 10, 7, "Q2 8:00", "BUF"))
        app.board.snap = {"teams": [row], "lower_news": {"fox": [], "tech": []},
                          "lower_sig": power.content_signature([row], t0, [], []),
                          "lower_asof": t0 - 100}
        app.board.beats = {}
        calls = {"s": 0}

        def same(cfg, force=False, ttl=3500):
            calls["s"] += 1
            return [row]

        old_s, old_n = lower.fetch_favorites, lower.fetch_news
        lower.fetch_favorites = same
        lower.fetch_news = lambda force=False: {"fox": [], "tech": []}
        try:
            app.board._tick_lower(t0)
            self.assertEqual(calls["s"], 1)
            version, blob, asof = app.board.version, app.board.final.tobytes(), app.board.snap["lower_asof"]
            app.board._tick_lower(t0 + 5 * 60)
            self.assertEqual(calls["s"], 1)
            app.board._tick_lower(t0 + power.LIVE_POLL_S)
            self.assertEqual(calls["s"], 2)
            # Same score: no new frame and the as-of stamp stays put.
            self.assertEqual(app.board.version, version)
            self.assertEqual(app.board.final.tobytes(), blob)
            self.assertEqual(app.board.snap["lower_asof"], asof)
        finally:
            lower.fetch_favorites, lower.fetch_news = old_s, old_n

    def test_saved_layout_defaults(self):
        import power
        import render as R
        # gallery + old Tampa teams, no e1001_home key: the small face, not the screensaver.
        gallery = {"layout": "gallery", "gallery_rotate_min": 5,
                   "slots": ["weather", "news", "sports", "sky"],
                   "teams": ["bucs", "lightning", "rays"]}
        self.assertTrue(power.is_lower_cfg(gallery))
        self.assertFalse(power.is_gallery_legacy(gallery))
        self.assertEqual(power.selected_favorites(gallery), list(power.FAVORITE_KEYS))
        self.assertTrue(power.is_gallery_legacy({"layout": "gallery", "e1001_home": "gallery"}))
        # thirds with the old sports slots and no daily_home key: still the daily face.
        saved = {"layout": "thirds", "smart_home": True, "daily_home": True,
                 "slots": ["shabbat", "newsletter", "weather", "news", "trips", "sports", "scoreboard"]}
        # missing daily_home is the same as true
        saved.pop("daily_home")
        self.assertTrue(power.daily_home_cfg(saved))
        sunday = _at(2026, 11, 8, 15)
        R.set_profile("e1003")
        try:
            ctx = R.Ctx(now=sunday, cfg=saved, league=[G("in", sunday - 1800, 10, 7)],
                        teams=[Row("jets", live=G("in", sunday - 100, 7, 3, "Q2", "BUF"))])
            self.assertEqual(R.home_mode(ctx), "daily")
            names = R.home_layout(ctx)[1]
            self.assertNotIn("sports", names)
            self.assertNotIn("league", names)
            self.assertIn("shabbat", names)
            self.assertIn("newsletter", names)
            self.assertIn("weather", names)
            self.assertNotIn("calendar", names)
            fri = R.Ctx(now=_at(2026, 11, 6, 12), cfg=saved)
            fnames = R.home_layout(fri)[1]
            self.assertEqual(fnames, power.DAILY_SHABBAT)
            self.assertNotIn("calendar", fnames)
            self.assertFalse(R.show_markets(fri))
        finally:
            R.set_profile("e1001")


def power_hour_before():
    import power
    t = time.localtime(time.time() - 3700)
    return t.tm_year * 1000000 + t.tm_yday * 100 + t.tm_hour


class DevicePoll(unittest.TestCase):
    """Real HTTP poll, firmware query string, one process per panel."""

    def _serve(self, model, cfg):
        tmp = tempfile.mkdtemp(prefix=f"quad-{model}-")
        cfg_path = os.path.join(tmp, "config.json")
        state_path = os.path.join(tmp, "state.json")
        with open(cfg_path, "w") as f:
            json.dump(cfg, f)
        port = 18740 if model == "e1003" else 18741
        env = os.environ.copy()
        env.update({
            "TZ": "America/New_York",
            "QUAD_MODEL": model,
            "QUAD_PORT": str(port),
            "QUAD_BIND": "127.0.0.1",
            "QUAD_TOKEN": "test-device",
            "QUAD_ADMIN": "test-admin",
            "QUAD_CONFIG": cfg_path,
            "QUAD_STATE": state_path,
            "QUAD_NO_WARM": "1",
            "QUAD_SESSION_SECRET": "test-secret",
        })
        proc = subprocess.Popen([sys.executable, __file__, "--serve"], cwd=HERE, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        base = f"http://127.0.0.1:{port}"
        deadline = time.time() + 30
        last = ""
        while time.time() < deadline:
            if proc.poll() is not None:
                last = proc.stdout.read() if proc.stdout else ""
                break
            try:
                code, _, _ = _http(base + "/healthz", timeout=2)
                if code == 200:
                    return proc, base
            except Exception as e:
                last = str(e)
            time.sleep(0.2)
        proc.kill()
        raise AssertionError(f"{model} server did not start: {last[:500]}")

    def _stop(self, proc):
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        if proc.stdout:
            proc.stdout.close()

    def _poll(self, base, model, vbat, v="0", extra=""):
        q = (f"/api/device/poll?k=test-device&v={v}&wait=0&vbat={vbat:.3f}"
             f"&rssi=-61&g=1&m={model}&t=21.5&rh=44{extra}")
        return _http(base + q, timeout=30)

    def test_e1003_and_e1001_polls(self):
        big = {"layout": "thirds", "quiet": "0-6", "interval_min": 15, "live_fast": True,
               "full_every_min": 240, "slots": ["shabbat", "newsletter", "weather", "news",
                                                "trips", "sports", "scoreboard"],
               "teams": ["bucs", "jets"]}
        small = {"layout": "gallery", "gallery_rotate_min": 5, "quiet": "0-6",
                 "slots": ["weather", "news", "sports", "sky"],
                 "teams": ["bucs", "lightning", "rays"]}
        for model, cfg, size in (("e1003", big, (1872, 1404)), ("e1001", small, (800, 480))):
            proc, base = self._serve(model, cfg)
            try:
                code, hdrs, body = self._poll(base, model, 3.900, extra="&boot=1")
                self.assertEqual(code, 200, body[:200])
                self.assertEqual(hdrs["X-Mode"], "live")
                self.assertEqual(hdrs["X-Next"], "0")
                self.assertEqual(_reel_box(body)[1][2:], size)
                version = hdrs["X-Version"]
                code, hdrs, body = self._poll(base, model, 3.500, v=version)
                self.assertEqual(code, 204, body[:200])
                self.assertEqual(hdrs["X-Mode"], "sleep")
                self.assertEqual(hdrs["X-Next"], "600")
                # 3.80 stays live. A bad token is not a reel.
                code, hdrs, _ = self._poll(base, model, 3.800, v=version)
                self.assertEqual(code, 204)
                self.assertEqual(hdrs["X-Mode"], "live")
                self.assertEqual(hdrs["X-Next"], "0")
                bad = _http(base + f"/api/device/poll?k=nope&v=0&wait=0&vbat=3.900&m={model}&g=1")
                self.assertEqual(bad[0], 404)
                st = _http(base + "/api/state?k=test-admin")
                self.assertEqual(st[0], 200, st[2][:200])
                state = json.loads(st[2])
                if model == "e1003":
                    self.assertEqual(state["cfg"]["layout"], "thirds")
                    self.assertTrue(state["cfg"]["daily_home"])
                    self.assertEqual(state["cfg"]["cadence"], "windows")
                    self.assertNotIn("sports", state["cfg"]["slots"])
                    self.assertIn("shabbat", state["cfg"]["slots"])
                    self.assertIn("newsletter", state["cfg"]["slots"])
                    self.assertIn("weather", state["cfg"]["slots"])
                    self.assertIn("no sports", state["power"]["line"])
                    self.assertNotIn("calendar", state["cfg"]["slots"])
                else:
                    self.assertEqual(state["cfg"]["layout"], "gallery")
                    self.assertEqual(state["cfg"]["e1001_home"], "lower")
                    self.assertIn("Small board", state["power"]["line"])
                    # A tap must not 500 and must not rotate a gallery category.
                    before = version
                    code, hdrs, body = self._poll(base, model, 3.900, v=before, extra="&tx=100&ty=200")
                    self.assertIn(code, (200, 204))
                    self.assertEqual(hdrs["X-Version"], before)
            finally:
                self._stop(proc)


if __name__ == "__main__":
    unittest.main()
