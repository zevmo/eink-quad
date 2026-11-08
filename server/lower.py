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


def fetch_favorites(cfg, force=False, ttl=3500):
    """TeamRows for the allowlist only. No odds, no league slate, no extra teams.
    ttl is how long a fetched schedule may be reused. Live polls pass ~15 min."""
    rows = []
    for key in power.selected_favorites(cfg):
        if key not in S.TEAMS:
            continue
        games = S.team_games(key, fast=True, force=force, ttl=ttl) or []
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
    batt = R.battery_caption(ctx.battery, getattr(ctx, "battery_age_s", None))
    if face == "sports" and shown:
        _scores(c, d, shown, asof, ctx.now, batt)
    else:
        _news(c, d, g.get("fox") or [], g.get("tech") or [], asof, ctx.now, batt)
    return c


def _bar(d, w, title, asof, now, batt=""):
    d.rectangle((0, 0, w, 40), fill=R.INK)
    R.text(d, (14, 20), title, R.F("cb", 22), fill=R.PAPER, anchor="lm")
    t = time.localtime(now)
    date = time.strftime("%a %b ", t) + str(t.tm_mday)
    right = date
    if asof:
        right = f"as of {R.hm(asof)}  ·  {date}"
    if batt:
        right = f"{batt}   {right}"
    R.text(d, (w - 14, 20), right, R.F("m", 16), fill=R.PAPER, anchor="rm")


def _news(c, d, fox, tech, asof, now, batt=""):
    w, h = R.W, R.H
    _bar(d, w, "NEWS", asof, now, batt)
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


def sports_metrics(n, body=None):
    """Logo and type sizes for n games on the E1001. One game is a poster.
    Two share the screen as smaller posters. Three or more are rows, and the
    score stays large enough to read after the logos shrink."""
    n = max(1, int(n))
    body = 414 if body is None else body
    band = body / n
    if n == 1:
        return {"logo": 188, "score": 112, "name": 36, "detail": 24, "band": band, "mode": "hero"}
    if n == 2:
        return {"logo": 78, "score": 64, "name": 26, "detail": 18, "band": band, "mode": "pair"}
    logo = int(max(40, min(56, band - 20)))
    score = int(max(30, min(46, band * 0.46)))
    name = int(max(16, min(22, band * 0.24)))
    detail = int(max(13, min(16, band * 0.18)))
    return {"logo": logo, "score": score, "name": name, "detail": detail, "band": band, "mode": "row"}


def layout_for(n, w=None, h=None):
    """Pixel boxes for each game. Each band has us/them logo rects (x, y, size)."""
    w = int(w or R.W)
    h = int(h or R.H)
    n = max(1, int(n))
    top, bot = 46, h - 20
    m = sports_metrics(n, bot - top)
    logo = m["logo"]
    bands = []
    if m["mode"] == "row":
        rh = (bot - top) / n
        for i in range(n):
            y0 = top + i * rh
            y1 = y0 + rh
            cy = y0 + (rh - 16 - logo) / 2
            bands.append({
                "y0": y0, "y1": y1,
                "us": (12, int(cy), logo),
                "them": (int(w - 12 - logo), int(cy), logo),
            })
    else:
        gap = 28 if n == 1 else 22
        col = (w - 3 * gap) / 2
        rh = (bot - top) / n
        for i in range(n):
            y0 = top + i * rh
            y_logo = int(y0 + (8 if n == 1 else 4))
            bands.append({
                "y0": y0, "y1": y0 + rh,
                "us": (int(gap + col / 2 - logo / 2), y_logo, logo),
                "them": (int(w - gap - col / 2 - logo / 2), y_logo, logo),
            })
    m["bands"] = bands
    return m


def _scores(c, d, shown, asof, now, batt=""):
    w, h = R.W, R.H
    _bar(d, w, "SCORES", asof, now, batt)
    n = max(1, len(shown))
    lay = layout_for(n, w, h)
    for i, row in enumerate(shown):
        if i:
            y = int(lay["bands"][i]["y0"])
            d.line((16, y, w - 16, y), fill=R.INK, width=1)
        _game_panel(c, d, row, now, lay, i, w)
    R.text(d, (16, h - 8), "Every 15 min while live  ·  not a live clock", R.F("cm", 13), anchor="ls")
    d.line((0, h - 1, w, h - 1), fill=R.INK, width=2)


def _game_of(row, now):
    active = power.is_active(row, now)
    g = (row.live or row.next) if active else row.last
    if g is None:
        return None
    kind = "LIVE" if active else "FINAL"
    detail = str(getattr(g, "detail", "") or "").strip()
    if kind == "FINAL" and detail.lower() in ("", "final"):
        detail = ""
    place = "home" if getattr(g, "home", True) else "away"
    bits = [kind]
    if detail:
        bits.append(detail)
    bits.append(place)
    us_name = getattr(row, "label", None) or getattr(g, "team", None) or row.key
    them_name = getattr(g, "opp_name", None) or getattr(g, "opp", None) or ""
    us_logo = getattr(g, "our_logo", "") or getattr(row, "logo", "") or ""
    them_logo = getattr(g, "opp_logo", "") or ""
    return {
        "g": g, "kind": kind, "status": "  ·  ".join(bits),
        "us_name": str(us_name), "them_name": str(them_name),
        "us_logo": us_logo, "them_logo": them_logo,
        "us": _pts(getattr(g, "us", None)), "them": _pts(getattr(g, "them", None)),
    }


def _pts(n):
    return "–" if n is None else str(n)


def _paste_logo(c, url, x, y, size, align="center"):
    """Cached 1-bit mark. False when the file is missing; the score still draws.

    Poster slots bottom-align a wide wordmark so it sits on the name instead
    of floating in the middle of a square of paper.
    """
    import logos
    from PIL import Image, ImageChops
    size = int(size)
    x, y = int(x), int(y)
    if not url or size < 8:
        return False
    img = logos.panel(url, size)
    if img is None:
        return False
    if align == "bottom":
        ink = ImageChops.invert(img).point(lambda v: 255 if v > 8 else 0).getbbox()
        if ink and ink[3] < size:
            moved = Image.new("L", (size, size), 255)
            moved.paste(img, (0, size - ink[3]))
            img = moved
    w, h = c.size
    if x < 0 or y < 0 or x + size > w or y + size > h:
        return False
    c.paste(ImageChops.darker(c.crop((x, y, x + size, y + size)), img), (x, y))
    return True


def _game_panel(c, d, row, now, lay, index, w):
    info = _game_of(row, now)
    if info is None:
        return
    band = lay["bands"][index]
    mode = lay["mode"]
    ux, uy, usz = band["us"]
    tx, ty, tsz = band["them"]
    align = "center" if mode == "row" else "bottom"
    got_us = _paste_logo(c, info["us_logo"], ux, uy, usz, align)
    got_them = _paste_logo(c, info["them_logo"], tx, ty, tsz, align)
    if mode == "row":
        _row_panel(d, info, band, lay, w)
    else:
        _poster(d, info, band, lay, w, got_us, got_them)


def _poster(d, info, band, lay, w, got_us, got_them):
    """One or two games: logo, name, then a score that dominates the band.
    A missing logo is just a larger name in that box, not a drawn crest."""
    name_f = R.F("cb", lay["name"])
    score_f = R.F("b", lay["score"])
    placed = []
    for side, got in (("us", got_us), ("them", got_them)):
        x, y, size = band[side]
        cx = x + size / 2
        label = info["us_name" if side == "us" else "them_name"].upper()
        if got:
            score_y = y + size + lay["name"] + 14
        else:
            big = max(36, int(size * 0.62))
            bf = R.F("cb", big)
            R.text(d, (cx, y + size / 2), R.ellipsize(d, label, bf, size + 24), bf, anchor="mm")
            score_y = y + size + 8
        placed.append((cx, score_y, label, got, size))
    score_y = max(p[1] for p in placed)
    for cx, _sy, label, got, size in placed:
        if got:
            R.text(d, (cx, score_y - lay["name"] - 8), R.ellipsize(d, label, name_f, size + 36), name_f, anchor="ma")
        R.text(d, (cx, score_y), info["us"] if cx < w / 2 else info["them"], score_f, anchor="ma")
    rule = score_y + lay["score"] * 0.38
    d.line((w / 2 - 18, rule, w / 2 + 18, rule), fill=R.INK, width=max(2, lay["score"] // 28))
    R.text(d, (w / 2, band["y1"] - 4), info["status"], R.F("m", lay["detail"]), anchor="ms")


def _row_panel(d, info, band, lay, w):
    """Three or more games. One row: marks on the outside, score in the middle."""
    ux, uy, size = band["us"]
    tx, ty, _ = band["them"]
    name_f = R.F("cb", lay["name"])
    score_f = R.F("b", lay["score"])
    score = f"{info['us']}–{info['them']}"
    sw = d.textlength(score, font=score_f)
    cx = w / 2
    cy = uy + size / 2
    R.text(d, (cx, cy), score, score_f, anchor="mm")
    gap_l = ux + size + 8
    gap_r = tx - 8
    name_w = max(40, cx - sw / 2 - gap_l - 8)
    opp_w = max(40, gap_r - (cx + sw / 2) - 8)
    us_label = info["us_name"].upper()
    them_label = info["them_name"].upper()
    R.text(d, (gap_l, cy), R.ellipsize(d, us_label, name_f, name_w), name_f, anchor="lm")
    R.text(d, (gap_r, cy), R.ellipsize(d, them_label, name_f, opp_w), name_f, anchor="rm")
    R.text(d, (cx, band["y1"] - 2), info["status"], R.F("m", lay["detail"]), anchor="ms")
