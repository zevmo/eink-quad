"""E1001 lower board: a static Fox + tech news face, or favorite scores.

Scores show only while a favorite is actually playing, or for about six hours
after that game should have ended. The as-of line is the stamp of the last
content change, not the clock, so an unchanged final does not repaint.
No Shabbat, newsletter, or shopping tiles.

fetch_* talks to the network. compose() does not.
"""
from __future__ import annotations

import time

import power
import render as R
import sources as S

# Re-export so app.py can record the signature next to the rows it draws.
content_signature = power.content_signature


def fetch_news(force=False):
    """Latest Fox headlines plus the WSJ tech feed already used by the server."""
    fox = _cached_fox(force)
    tech = _cached_tech(force)
    return {"fox": _pick(fox), "tech": _pick(tech)}


_fox = S.Cached(3500)
_tech = S.Cached(3500)


def _cached_fox(force):
    def fetch():
        return S.fetch_fox(12)
    fetch.__name__ = "fox_latest"
    return _fox.get(fetch, force) or []


def _cached_tech(force):
    def fetch():
        return S.fetch_feed_key("tech")
    fetch.__name__ = "wsj_tech"
    return _tech.get(fetch, force) or []


def _pick(items, n=6, hours=36):
    items = list(items or [])
    cutoff = time.time() - hours * 3600
    fresh = [h for h in items if not getattr(h, "published", 0) or h.published >= cutoff]
    return (fresh or items)[:n]


def fetch_favorites(cfg, force=False):
    """TeamRows for the allowlist only. No odds, no league slate, no extra teams."""
    rows = []
    for key in power.selected_favorites(cfg):
        if key not in S.TEAMS:
            continue
        games = S.team_games(key, fast=True, force=force, ttl=3500) or []
        row = S.TeamRow(key=key, label=S.TEAMS[key][0],
                        record=games[0].record if games else "",
                        logo=next((g.our_logo for g in games if g.our_logo), ""))
        row.live = next((g for g in games if g.state == "in"), None)
        done = [g for g in games if g.state == "post" and g.us is not None]
        row.last = done[-1] if done else None
        # Skip a pre-game that tip-off left behind more than a few hours ago,
        # so it cannot hide the next real start.
        row.next = next((g for g in games if g.state == "pre" and g.start > time.time() - 3 * 3600), None)
        if row.live or row.last or row.next:
            rows.append(row)
    return rows


# ---------------------------------------------------------------- draw

def compose(ctx) -> "R.Image.Image":
    """Full 800x480 (layout units) L image. as-of comes from ctx.gallery['asof']."""
    c, d = R.canvas((R.W, R.H))
    g = ctx.gallery or {}
    asof = g.get("asof") or 0
    face, shown = power.classify(ctx.teams or [], ctx.now)
    if face == "sports" and shown:
        _scores(c, d, shown, asof, ctx.now)
    else:
        _news(c, d, g.get("fox") or [], g.get("tech") or [], asof, ctx.now)
    return c


def _bar(d, w, title, asof, now):
    d.rectangle((0, 0, w, 40), fill=R.INK)
    R.text(d, (14, 20), title, R.F("cb", 22), fill=R.PAPER, anchor="lm")
    t = time.localtime(now)
    date = time.strftime("%a %b ", t) + str(t.tm_mday)
    right = date
    if asof:
        right = f"as of {R.hm(asof)}  ·  {date}"
    R.text(d, (w - 14, 20), right, R.F("m", 16), fill=R.PAPER, anchor="rm")


def _news(c, d, fox, tech, asof, now):
    w, h = R.W, R.H
    _bar(d, w, "NEWS", asof, now)
    mid = w // 2
    d.line((mid, 52, mid, h - 36), fill=R.INK, width=2)
    _column(d, 16, mid - 8, "FOX NEWS", fox)
    _column(d, mid + 16, w - 8, "TECH", tech)
    R.text(d, (16, h - 22), "Fox News  ·  WSJ Tech  ·  hourly in the daytime", R.F("cm", 15))
    d.line((0, h - 1, w, h - 1), fill=R.INK, width=2)


def _column(d, x, right, label, items):
    R.text(d, (x, 52), label, R.F("cb", 18))
    d.line((x, 76, right - 8, 76), fill=R.INK, width=2)
    y = 84
    f = R.F("m", 18)
    titles = power.news_titles(items)[:5]
    width = right - x - 28
    if not titles:
        R.text(d, (x, y), "Nothing new", R.F("m", 18))
        return
    for title in titles:
        if y > R.H - 78:
            break
        lines = R.wrap(d, title, f, width, 2)
        R.text(d, (x, y + 1), "•", R.F("b", 16))
        for i, ln in enumerate(lines):
            R.text(d, (x + 16, y + i * 22), ln, f)
        y += 22 * max(1, len(lines)) + 6


def _scores(c, d, shown, asof, now):
    w, h = R.W, R.H
    _bar(d, w, "SCORES", asof, now)
    R.text(d, (16, 50), "Hourly  ·  not a live clock", R.F("cm", 16))
    d.line((12, 72, w - 12, 72), fill=R.INK, width=2)
    n = max(1, len(shown))
    top, bot = 84, h - 28
    rh = (bot - top) / n
    big = n <= 2
    for i, row in enumerate(shown):
        y = top + i * rh
        _score_row(d, row, 16, y, w - 16, rh, big, now)
        if i:
            d.line((16, int(y), w - 16, int(y)), fill=R.INK, width=1)
    d.line((0, h - 1, w, h - 1), fill=R.INK, width=2)


def _score_row(d, row, x, y, right, rh, big, now):
    active = power.is_active(row, now)
    g = (row.live or row.next) if active else row.last
    if g is None:
        return
    name = getattr(row, "label", row.key)
    kind = "LIVE" if active else "FINAL"
    score = f"{'' if g.us is None else g.us}–{'' if g.them is None else g.them}"
    who = ("vs " if getattr(g, "home", True) else "at ") + (getattr(g, "opp_name", None) or getattr(g, "opp", "") or "")
    detail = "" if kind == "FINAL" else str(getattr(g, "detail", "") or "")
    sub = who if not detail else f"{who}  ·  {detail}"
    nf = R.F("cb", 32 if big else 22)
    sf = R.F("b", 40 if big else 26)
    kf = R.F("csb", 16 if big else 14)
    R.pill(d, x, y + 6, kind, kf, h=22)
    R.text(d, (x + (78 if big else 70), y + (8 if big else 6)), name.upper(), nf, anchor="lt")
    R.text(d, (right, y + (4 if big else 2)), score, sf, anchor="rt")
    R.text(d, (x, y + (36 if big else 30)), R.ellipsize(d, sub, R.F("m", 20 if big else 16), right - x), R.F("m", 20 if big else 16))
