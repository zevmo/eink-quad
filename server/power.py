"""Power-format policy for the two fridge boards. Pure functions, no I/O.

Big E1003 (layout thirds, daily_home default on): one stable thirds face —
Shabbat, newsletter, weather, news (markets off Fri–Sat), trips, calendar, sky.
No sports and no NFL slate. Content refreshes at local windows (default
7:30, 12:30, 18:30) and at Shabbat transitions, not on a short interval.

Small E1001 (layout lower, or gallery unless e1001_home=gallery): Fox News
plus the WSJ tech feed while idle; favorite-team scores only while a game
is on or a final is still inside the hold window. Scores and headlines are
hourly. An unchanged final does not change the content signature, so the
glass is not redrawn just because the clock moved.

This module does not put the radio to sleep. Firmware X-Mode is unchanged:
a reported vbat >= 3.80V (or no vbat) stays "live" and long-polls. Forcing
deep sleep on any battery reading was cancelled. Weekly runtime is not
estimated here.
"""
from __future__ import annotations

import re
import time

# Small-board allowlist only. Order is the on-glass order (it does not shuffle
# when a game goes live). ESPN ids match the ones the previews already used.
FAVORITES = (
    ("jets", "Jets", "football", "nfl", "nyj"),
    ("mets", "Mets", "baseball", "mlb", "nym"),
    ("devils", "Devils", "hockey", "nhl", "nj"),
    ("nets", "Nets", "basketball", "nba", "bkn"),
    ("navy_fb", "Navy", "football", "college-football", "2426"),
    ("rutgers_bb", "Rutgers", "basketball", "mens-college-basketball", "164"),
)
FAVORITE_KEYS = tuple(k for k, *_ in FAVORITES)

# Original thirds geometry, sports/scoreboard replaced with calendar + sky.
# Shopping stays off this face (no shopping content is invented).
DAILY_SLOTS = ["shabbat", "newsletter", "weather", "news", "trips", "calendar", "sky"]
SPORTS_PANELS = {"sports", "scoreboard", "league", "navy"}

# Rough length of a game, then how long a final stays up after that.
SPORT_LEN = {"football": 3.5 * 3600, "basketball": 2.5 * 3600, "hockey": 2.75 * 3600, "baseball": 3.25 * 3600}
HOLD_S = 6 * 3600
SOON_S = 4 * 3600

WINDOWS_DEFAULT = ("7:30", "12:30", "18:30")
QUIET_POWER = "22-7"          # always applied on the power format, local time


def layout_name(c) -> str:
    return str((c or {}).get("layout") or "")


def is_gallery_legacy(c) -> bool:
    """Old rotating E1001 screensaver. Opt in with e1001_home=gallery."""
    return layout_name(c) == "gallery" and (c or {}).get("e1001_home") == "gallery"


def is_lower_cfg(c) -> bool:
    """Static small-board face (news, or favorite scores at game time)."""
    lay = layout_name(c)
    if lay == "lower":
        return True
    if lay == "gallery" and not is_gallery_legacy(c):
        return True
    return False


def daily_home_cfg(c) -> bool:
    """Stable E1003 thirds with no sports. Missing daily_home means on."""
    if layout_name(c) != "thirds":
        return False
    return bool((c or {}).get("daily_home", True))


def windows_on(c) -> bool:
    """Coarse daily windows. The lower board has its own hourly clock;
    the legacy gallery keeps the old interval."""
    if is_lower_cfg(c) or is_gallery_legacy(c):
        return False
    return ((c or {}).get("cadence") or "windows") == "windows"


def _quiet_span(q, t=None) -> bool:
    m = re.fullmatch(r"\s*(\d{1,2})\s*-\s*(\d{1,2})\s*", q or "")
    if not m:
        return False
    a, b = int(m.group(1)), int(m.group(2))
    h = time.localtime(t or time.time()).tm_hour
    return (a <= h < b) if a < b else (h >= a or h < b)


def quiet_now(c, t=None) -> bool:
    """Configured quiet, plus 22:00–07:00 on the power format.

    An older saved quiet of 0-6 does not cover 22:00–24:00. The power format
    always does. Shabbat transitions and an in-progress favorite game are
    allowed to update anyway; callers check those separately.
    """
    c = c or {}
    if _quiet_span(c.get("quiet") or "", t):
        return True
    if windows_on(c) or is_lower_cfg(c):
        return _quiet_span(QUIET_POWER, t)
    return False


def daytime(c, t=None) -> bool:
    """Local 07:00–22:00 and not inside quiet. News polls live here."""
    now = t or time.time()
    if quiet_now(c, now):
        return False
    h = time.localtime(now).tm_hour
    return 7 <= h < 22


def parse_hhmm(s):
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", str(s))
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        return None
    return h, mi


def window_stamps(c, now):
    spec = (c or {}).get("content_windows") or list(WINDOWS_DEFAULT)
    t = time.localtime(now)
    base = time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))
    out = []
    for s in spec:
        hm = parse_hhmm(s)
        if hm:
            out.append(base + hm[0] * 3600 + hm[1] * 60)
    return sorted(set(out))


def latest_window(now, c):
    hit = None
    for ts in window_stamps(c, now):
        if ts <= now:
            hit = ts
    return hit


def due_window(last, now, c):
    """Latest window stamp <= now that has not been applied yet."""
    hit = latest_window(now, c)
    if hit is None or hit == last:
        return None
    return hit


def local_hour_id(now) -> int:
    t = time.localtime(now)
    return t.tm_year * 1000000 + t.tm_yday * 100 + t.tm_hour


def market_flip_day(now) -> bool:
    """Local Friday (markets leave) or Sunday (markets return)."""
    return time.localtime(now).tm_wday in (4, 6)


def shabbat_edge(last, sh, now):
    """Candle lighting / havdalah crossed since `last` (epoch of last edge we honoured).

    Absolute times do not tick, but the roll from this week to next should not
    wait for the next window. Edges older than 6h are ignored so a zero `last`
    does not replay last week.
    """
    if sh is None:
        return None
    if not last:
        last = 0
    crossed = None
    for ts in (getattr(sh, "candles", None), getattr(sh, "havdalah", None),
               getattr(sh, "holiday_candles", None)):
        if not ts or not (last < ts <= now) or now - ts > 6 * 3600:
            continue
        if crossed is None or ts > crossed:
            crossed = ts
    return crossed


def full_every_min(c) -> int:
    """Minutes between scheduled full flashes.

    The power format floors a short legacy value (the old 2–4h wipe) to a day.
    0 still means never. Crisp full-flashes on ordinary updates are separate
    and suppressed by partials_preferred.
    """
    try:
        mins = int((c or {}).get("full_every_min") or 0)
    except (TypeError, ValueError):
        mins = 0
    if mins and 0 < mins < 12 * 60 and (windows_on(c) or is_lower_cfg(c)):
        return 24 * 60
    return mins


def partials_preferred(c) -> bool:
    """Ordinary updates stay partial. A full flash is the rare ghost clean,
    a boot, or an explicit full-refresh."""
    return windows_on(c) or is_lower_cfg(c)


def device_mode(vbat):
    """X-Mode. Unchanged on purpose.

    live  — vbat missing, or >= 3.80V. Firmware keeps Wi-Fi up and long-polls.
    sleep — reported vbat under 3.80V. Firmware deep-sleeps for X-Next (600s).

    Forcing sleep on every battery reading was cancelled. Do not "fix" this
    here; it would need a firmware flash the boards are not getting.
    """
    return "live" if (vbat is None or vbat >= 3.80) else "sleep"


def device_next_s(mode) -> int:
    """X-Next. The firmware only sleeps on this when X-Mode is sleep.
    Live mode ignores it and long-polls (about 25s). Not retargeted to the
    content cadence — that was the cancelled deep-sleep change."""
    return 600 if mode == "sleep" else 0


def selected_favorites(cfg) -> list[str]:
    """Favorites the small board may show.

    A config teams list that names some favorites is respected (subset).
    A list with none of them (the old Tampa set) falls back to all six
    so the small board does not grow a Bucs tile.
    """
    listed = [k for k in ((cfg or {}).get("teams") or []) if k in FAVORITE_KEYS]
    if listed:
        return [k for k in FAVORITE_KEYS if k in listed]
    return list(FAVORITE_KEYS)


def sport_of(key) -> str:
    for k, _lab, sport, _lg, _id in FAVORITES:
        if k == key:
            return sport
    return "football"


def sport_len(key) -> float:
    return SPORT_LEN.get(sport_of(key), 3 * 3600)


def is_active(row, now) -> bool:
    """Game time, including a start ESPN has not flipped to in yet.
    A start still in the future is not game time."""
    g = getattr(row, "live", None)
    if g is not None and getattr(g, "state", "") == "in":
        return True
    nxt = getattr(row, "next", None)
    if nxt is None or getattr(nxt, "state", "") == "post":
        return False
    start = getattr(nxt, "start", None) or 0
    return start <= now < start + sport_len(getattr(row, "key", ""))


def held_final(row, now) -> bool:
    """Final stays up until about 6h after the game should have ended."""
    if is_active(row, now):
        return False
    g = getattr(row, "last", None)
    if g is None or getattr(g, "state", "") != "post":
        return False
    if getattr(g, "us", None) is None or getattr(g, "them", None) is None:
        return False
    start = getattr(g, "start", 0) or 0
    return now < start + sport_len(getattr(row, "key", "")) + HOLD_S


def _order(row) -> int:
    try:
        return FAVORITE_KEYS.index(row.key)
    except ValueError:
        return 99


def classify(rows, now):
    """('sports'|'news', rows to draw).

    Active games beat an expired final: the face is sports when anything is
    live, and expired finals are not drawn beside it. When the only remaining
    games are finals past the hold, the face goes back to news.
    """
    rows = [r for r in (rows or []) if getattr(r, "key", None) in FAVORITE_KEYS]
    active = [r for r in rows if is_active(r, now)]
    held = [r for r in rows if held_final(r, now)]
    active.sort(key=_order)
    held.sort(key=_order)
    if active or held:
        return "sports", active + held
    return "news", []


def starts_soon(rows, now, horizon=SOON_S) -> bool:
    """Worth an hourly sports poll: live, held final, or tip within `horizon`."""
    face, _shown = classify(rows, now)
    if face == "sports":
        return True
    for r in rows or []:
        if getattr(r, "key", None) not in FAVORITE_KEYS:
            continue
        nxt = getattr(r, "next", None)
        if nxt is not None and 0 < (getattr(nxt, "start", 0) or 0) - now <= horizon:
            return True
    return False


def _grow(g):
    if g is None:
        return None
    return (getattr(g, "state", ""), getattr(g, "us", None), getattr(g, "them", None),
            str(getattr(g, "detail", "") or ""), str(getattr(g, "opp", "") or ""))


def news_titles(items) -> tuple:
    out = []
    for h in items or []:
        if isinstance(h, dict):
            t = h.get("title") or h.get("headline") or ""
        else:
            t = getattr(h, "title", "") or ""
        t = " ".join(str(t).split())
        if t:
            out.append(t)
    return tuple(out)


def content_signature(rows, now, fox, tech):
    """What a redraw is allowed to depend on. No clock, no as-of stamp.

    The same final score produces the same signature, so the server must not
    paint again. as-of on the glass advances only when this changes.
    """
    face, shown = classify(rows, now)
    if face == "sports":
        bits = []
        for r in shown:
            if is_active(r, now):
                bits.append((r.key, "active", _grow(getattr(r, "live", None) or getattr(r, "next", None))))
            else:
                bits.append((r.key, "final", _grow(getattr(r, "last", None))))
        return ("sports", tuple(bits))
    return ("news", news_titles(fox), news_titles(tech))


def describe(c, snap=None) -> str:
    snap = snap or {}
    if is_lower_cfg(c):
        sig = snap.get("lower_sig") or ("news",)
        face = sig[0] if sig else "news"
        return f"Small board: {face} · hourly · quiet 22:00–07:00"
    if daily_home_cfg(c) and windows_on(c):
        return "Big board: daily thirds, no sports · 7:30 / 12:30 / 18:30 · quiet 22:00–07:00"
    if windows_on(c):
        return "Windows cadence · quiet 22:00–07:00"
    return "Interval cadence"
