"""Power-format policy for the two fridge boards. Pure functions, no I/O.

Big E1003 (layout thirds, daily_home default on): one stable thirds face —
Shabbat, newsletter, weather, news (markets off Fri–Sat), and his next trip.
No calendar, no sports, and no overhead-plane radar. On Friday and Saturday
the newsletter takes the majority of the body.
No sports and no NFL slate. Content refreshes at local windows (default
7:30, 12:30, 18:30) and at Shabbat transitions, not on a short interval.

Small E1001 (layout lower, or gallery unless e1001_home=gallery): Fox News
plus the WSJ tech feed while idle; favorite-team scores only while a game
is on or a final is still inside the hold window. Scores and headlines are
hourly. An unchanged final does not change the content signature, so the
glass is not redrawn just because the clock moved.

The radio sleeps between checks. X-Mode is sleep on every poll, and X-Next
is 300 seconds, which is the automatic floor. The firmware aligns that to
the 5-minute unix boundary and will not honor a shorter interval, so a
charged battery no longer keeps Wi-Fi up. A button is the exception and is
not this interval. Weekly runtime is not estimated here.
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

# Weekday thirds. Order matches daily_weekday boxes. No calendar, no sports,
# no overhead sky. Shabbat swaps to DAILY_SHABBAT (newsletter majority).
DAILY_SLOTS = ["shabbat", "weather", "newsletter", "news", "trips"]
DAILY_SHABBAT = ["newsletter", "shabbat", "weather", "news"]
LIVE_POLL_S = 15 * 60
SPORTS_PANELS = {"sports", "scoreboard", "league", "navy"}

# How long a started-but-not-yet-flipped game still counts as on. Not the final hold.
SPORT_LEN = {"football": 3.5 * 3600, "basketball": 2.5 * 3600, "hockey": 2.75 * 3600, "baseball": 3.25 * 3600}
# Longest a game is allowed to have run when we only observed the final ourselves
# and then lost that stamp. OT fits; the scheduled length does not cap a known ESPN end.
MAX_PLAY = {"football": 6 * 3600, "basketball": 4 * 3600, "hockey": 4.5 * 3600, "baseball": 7 * 3600}
HOLD_S = 6 * 3600
SOON_S = 4 * 3600
POSTPONED_NAMES = {"STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_CANCELLED", "STATUS_DELAYED",
                   "STATUS_SUSPENDED", "STATUS_FORFEIT", "STATUS_RAINDELAY"}

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


def live_slot(now) -> int:
    """15-minute bucket for in-progress favorite scores."""
    return int(now // LIVE_POLL_S)


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
    """Ordinary big-board updates stay partial. A full flash there is the rare
    ghost clean, a boot, or an explicit full refresh."""
    return windows_on(c) or is_lower_cfg(c)


def solid_black_full(c) -> bool:
    """E1001 UC8179 fast partials leave large black type gray. The lower face
    sends a 1-bit full (reel flag bit0, no grey payload) so display::full()
    runs. That path is already in the firmware; it does not need a flash.
    The E1003 TCON partial is a different driver and stays partial."""
    return is_lower_cfg(c)


# Automatic checks are never closer than this. The firmware also refuses a
# shorter X-Next, including the old live-mode 25-second long-poll.
POLL_FLOOR_S = 300


def device_mode(vbat=None):
    """X-Mode. Sleep on every poll.

    vbat is still reported and still draws the battery line. It does not
    decide whether the radio stays up. The firmware deep-sleeps, with Wi-Fi
    off, until the next check. A button wakes it without waiting out the floor.
    """
    del vbat
    return "sleep"


def device_next_s(mode=None, now=None) -> int:
    """X-Next. Always the 5-minute floor.

    Not 0, not 25, and not the old 600. The firmware treats anything shorter
    than this as 300, then shortens the actual sleep only enough to land on
    the next 5-minute unix boundary. `mode` is accepted so older callers keep
    working. A longer hint is not sent: the windows and the :15 sports marks
    already sit on that grid, so sleeping longer would only make them late.
    """
    del mode, now
    return POLL_FLOOR_S


def next_slot(now) -> int:
    """Unix time of the next 5-minute boundary strictly after `now`."""
    now = int(now)
    return now - (now % POLL_FLOOR_S) + POLL_FLOOR_S


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


def max_play(key) -> float:
    return MAX_PLAY.get(sport_of(key), 6 * 3600)


def is_postponed(g) -> bool:
    """Postponed, cancelled, delayed, or suspended. Not a final and not game time."""
    if g is None:
        return False
    name = (getattr(g, "status_name", "") or "").upper()
    if name in POSTPONED_NAMES:
        return True
    detail = (getattr(g, "detail", "") or "").lower()
    return any(w in detail for w in ("postpon", "cancel", "delayed", "suspend"))


def is_active(row, now) -> bool:
    """Game time, including a start ESPN has not flipped to in yet.
    A start still in the future is not game time. A postponement is not either."""
    g = getattr(row, "live", None)
    if g is not None and getattr(g, "state", "") == "in" and not is_postponed(g):
        return True
    nxt = getattr(row, "next", None)
    if nxt is None or is_postponed(nxt) or getattr(nxt, "state", "") == "post":
        return False
    start = getattr(nxt, "start", None) or 0
    return start <= now < start + sport_len(getattr(row, "key", ""))


def _scored_final(g) -> bool:
    return (g is not None and getattr(g, "state", "") == "post" and not is_postponed(g)
            and getattr(g, "us", None) is not None and getattr(g, "them", None) is not None)


def final_key(row, g) -> str:
    eid = str(getattr(g, "event_id", "") or "")
    if eid:
        return eid
    return f"{getattr(row, 'key', '')}:{int(getattr(g, 'start', 0) or 0)}:{getattr(g, 'opp', '')}"


def stamp_final(row, now, store, lookup=None):
    """Pin the actual end of a scored final onto the game and into `store`.

    ESPN's last-play time wins and is kept. Otherwise the first time we see the
    final is the end, and that stamp is not moved later (a restart reloads it).
    A postponed game or a final with no score is not stamped.
    """
    g = getattr(row, "last", None)
    if not _scored_final(g):
        return
    key = final_key(row, g)
    rec = dict(store.get(key) or {})
    if getattr(g, "completed_source", "") == "espn" and g.completed_at and rec.get("source") != "espn":
        rec = {"at": float(g.completed_at), "source": "espn"}
        store[key] = rec
    if rec.get("source") != "espn" and lookup is not None:
        try:
            espn = lookup(row)
        except Exception:
            espn = None
        if espn:
            rec = {"at": float(espn), "source": "espn"}
            store[key] = rec
    if rec.get("source") == "espn" and rec.get("at"):
        g.completed_at = float(rec["at"])
        g.completed_source = "espn"
        return
    if rec.get("at"):
        g.completed_at = float(rec["at"])
        g.completed_source = rec.get("source") or "observed"
        return
    at = float(getattr(g, "completed_at", None) or now)
    src = "espn" if getattr(g, "completed_source", "") == "espn" else "observed"
    store[key] = {"at": at, "source": src}
    g.completed_at = at
    g.completed_source = src


def stamp_rows(rows, now, store, lookup=None):
    for row in rows or []:
        stamp_final(row, now, store, lookup)
    dead = [k for k, rec in list(store.items())
            if now - float((rec or {}).get("at") or now) > 14 * 86400]
    for k in dead:
        store.pop(k, None)


def hold_deadline(row, g):
    """When this final leaves the glass, or None.

    A known ESPN end (last play, including OT) gets a full 6h after that
    instant, not after the scheduled length. An observed stamp is also 6h,
    but not past start + max play + 6h, so losing state.json cannot keep a
    long-finished game up by re-stamping 'now' on every boot.
    """
    if not _scored_final(g):
        return None
    at = getattr(g, "completed_at", None)
    if not at:
        return None
    deadline = float(at) + HOLD_S
    if (getattr(g, "completed_source", "") or "") == "observed":
        cap = (getattr(g, "start", 0) or float(at)) + max_play(getattr(row, "key", "")) + HOLD_S
        deadline = min(deadline, cap)
    return deadline


def held_final(row, now) -> bool:
    """Scored final still inside the 6h window after it actually ended."""
    if is_active(row, now):
        return False
    g = getattr(row, "last", None)
    deadline = hold_deadline(row, g)
    return deadline is not None and now < deadline


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
        return f"Small board: {face} · live scores every 15 min · quiet 22:00–07:00"
    if daily_home_cfg(c) and windows_on(c):
        return "Big board: daily thirds, no sports · 7:30 / 12:30 / 18:30 · quiet 22:00–07:00"
    if windows_on(c):
        return "Windows cadence · quiet 22:00–07:00"
    return "Interval cadence"
