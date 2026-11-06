"""Fixture previews of the power format. No network.

  python3 power_preview.py [outdir]

Writes e1003-daily-weekday.png, e1003-daily-shabbat.png,
e1001-lower-news.png, e1001-lower-sports.png, e1001-lower-final.png.
"""
import os
import sys
import time

os.environ["TZ"] = "America/New_York"
time.tzset()

import render as R
import sources as S
import ical
import lower

OUT = sys.argv[1] if len(sys.argv) > 1 else "/opt/cursor/artifacts"
os.makedirs(OUT, exist_ok=True)
H_ = 3600


def at(y, mo, d, h, mi=0):
    return time.mktime((y, mo, d, h, mi, 0, 0, 0, -1))


def weather(now):
    days = []
    for i in range(4):
        t = now + i * 86400
        days.append(S.Day(date=time.strftime("%Y-%m-%d", time.localtime(t)),
                          hi=58 - i, lo=41 - i, code=2 if i else 61, pop=20 + 10 * i,
                          sunrise="6:42 AM", sunset="4:48 PM", uv=2))
    hourly = [(now + i * H_, 52 - i * 0.4, 30 if i < 4 else 10, 61 if i < 3 else 2) for i in range(16)]
    return S.Weather(temp=51, feels=46, code=61, is_day=True, humidity=72, wind=11, wind_dir=40,
                     gust=18, days=days, hourly=hourly, rain_note="Rain tapering by 4 PM", alerts=[])


def heads():
    titles = [
        "NJ Transit adds weekend trains on the Pascack Valley line",
        "Teaneck library sets Sunday hours through the winter",
        "Hudson County park path reopens after the storm",
        "Port Authority delays morning PATH work",
        "School board posts the December calendar",
        "Local clinics expand flu shot hours",
    ]
    return [S.Headline(title=t, section="U.S.", published=at(2026, 11, 4, 9) - i * 3600, summary="")
            for i, t in enumerate(titles)]


def quotes():
    return [
        S.Quote("^GSPC", "S&P 500", 5820, 5788, [5780, 5790, 5805, 5820], "closed", at(2026, 11, 4, 16)),
        S.Quote("^DJI", "Dow", 43810, 43640, [43600, 43720, 43810], "closed", at(2026, 11, 4, 16)),
        S.Quote("^IXIC", "Nasdaq", 18640, 18510, [18500, 18580, 18640], "closed", at(2026, 11, 4, 16)),
    ]


def shabbat(now):
    return S.Shabbat(parsha="Chayei Sarah", candles=at(2026, 11, 6, 16, 22),
                     havdalah=at(2026, 11, 7, 17, 24), hebdate="15th of Cheshvan 5787",
                     holiday="Chanukah", holiday_date="2026-12-05",
                     events=[S.JEvent("holiday", "2026-12-05", "Chanukah", "5:00 PM")])


def calendar(now):
    day = time.strftime("%Y-%m-%d", time.localtime(now))
    nxt = time.strftime("%Y-%m-%d", time.localtime(now + 86400))
    return [
        ical.CalEvent(title="School pickup", start=now + 2 * H_, end=now + 2.5 * H_, day=day),
        ical.CalEvent(title="Dentist", start=now + 26 * H_, end=now + 27 * H_, day=nxt),
    ]


def trips(now):
    return [ical.Trip(name="Miami", start=now + 9 * 86400, end=now + 12 * 86400, segments=[
        ical.Segment(kind="flight", start=now + 9 * 86400 + 8 * H_, end=now + 9 * 86400 + 11 * H_,
                     title="UA 1234", airline="United", iata="UA", number="1234", origin="EWR", dest="MIA")])]


SHUL = {"issue_range": "Nov 7 – Nov 13", "highlights": [
    {"title": "Youth", "body": "Junior congregation meets at 10:15 in the social hall."},
    {"title": "Kiddush", "body": "Kiddush is sponsored in honor of the November birthdays."},
    {"title": "Mazal Tov", "body": "Mazal tov to the Cohen family on the birth of a daughter."},
    {"title": "Learning", "body": "The Wednesday night shiur continues with chapter 4."},
    {"title": "Coming up", "body": "Youth pizza and a parent meeting follow mincha on Sunday."},
    {"title": "Refuah", "body": "Refuah shleimah to those named on the mi sheberach list."},
]}


def e1003(path, now):
    R.set_profile("e1003")
    cfg = {"layout": "thirds", "daily_home": True, "cadence": "windows", "smart_home": True,
           "feeds": ["world", "us"], "tickers": ["^GSPC", "^DJI", "^IXIC"], "radar_nm": 25,
           "teams": ["jets", "mets", "devils"]}
    # A live Jets game must NOT flip this board into a score layout.
    jet = lower_row("jets", live=game("in", now - 4000, 17, 10, "Q3 4:12", "NE"))
    ctx = R.Ctx(now=now, cfg=cfg, weather=weather(now), heads=heads(), quotes=quotes(),
                teams=[jet], league=[game("in", now - 4000, 17, 10, "Q3", "NE")],
                shabbat=shabbat(now), calendar=calendar(now), trips=trips(now), shul=SHUL,
                brief="Rain this afternoon, then a dry evening.",
                indoor_f=68, indoor_rh=40, battery=72, updated=now - 600, day_count=4)
    g = R.compose_gray(ctx)
    assert g.size == (1872, 1404), g.size
    assert R.home_mode(ctx) == "daily"
    boxes, names = R.home_layout(ctx)
    assert "sports" not in names and "calendar" not in names, names
    assert "weather" in names and "shabbat" in names and "newsletter" in names
    if R.is_shabbat_day(now):
        nl = boxes[names.index("newsletter")]
        body = R.W * (R.H - R.GRID_Y)
        assert (nl[2] - nl[0]) * (nl[3] - nl[1]) > 0.5 * body
    g.save(path)
    print("wrote", path, g.size, R.home_mode(ctx), names)


class game(S.Game):
    def __init__(self, state, start, us=None, them=None, detail="", opp="OPP"):
        super().__init__(team="", abbr="", opp=opp, opp_name=opp, home=True, start=start,
                         state=state, detail=detail, us=us, them=them)


def lower_row(key, live=None, last=None, nxt=None):
    row = S.TeamRow(key=key, label=dict(jets="Jets", mets="Mets", devils="Devils",
                                        nets="Nets", navy_fb="Navy", rutgers_bb="Rutgers")[key])
    row.live, row.last, row.next = live, last, nxt
    return row


def e1001_news(path, now):
    R.set_profile("e1001")
    fox = [{"title": t} for t in (
        "Senate schedule slips as the spending vote waits",
        "Storm tracks up the coast into the weekend",
        "Transit agency posts the holiday timetable",
        "City sets a new water-main repair window",
        "School calendar adds two half days",
    )]
    tech = [{"title": t} for t in (
        "Chip export rules tighten for a second round",
        "A smaller laptop battery still lasts the flight",
        "Browser update closes a certificate bug",
        "Researchers publish a quieter fan design",
    )]
    ctx = R.Ctx(now=now, cfg={"layout": "lower", "cadence": "windows"},
                gallery={"asof": now - 2400, "fox": fox, "tech": tech})
    g = R.compose_gray(ctx)
    assert g.size == (800, 480), g.size
    g.save(path)
    print("wrote", path)


def ended(state, start, us, them, detail, opp, completed_at, source="espn"):
    g = game(state, start, us, them, detail, opp)
    g.completed_at = completed_at
    g.completed_source = source
    return g


def e1001_sports(path, now, rows, asof):
    R.set_profile("e1001")
    ctx = R.Ctx(now=now, cfg={"layout": "lower", "cadence": "windows"},
                teams=rows, gallery={"asof": asof})
    g = R.compose_gray(ctx)
    assert g.size == (800, 480)
    g.save(path)
    print("wrote", path, power_face(rows, now))


def power_face(rows, now):
    import power
    return power.classify(rows, now)[0]


if __name__ == "__main__":
    wed = at(2026, 11, 4, 15, 10)     # Wednesday
    fri = at(2026, 11, 6, 12, 30)     # Friday — markets must stay off
    e1003(os.path.join(OUT, "e1003-daily-weekday.png"), wed)
    e1003(os.path.join(OUT, "e1003-daily-shabbat.png"), fri)
    e1001_news(os.path.join(OUT, "e1001-lower-news.png"), wed)
    sat = at(2026, 11, 7, 20, 5)
    e1001_sports(os.path.join(OUT, "e1001-lower-one-game.png"), sat, [
        lower_row("jets", live=game("in", sat - 4000, 17, 13, "Q3 6:02", "Patriots")),
    ], sat - 900)
    e1001_sports(os.path.join(OUT, "e1001-lower-sports.png"), sat, [
        lower_row("jets", live=game("in", sat - 5000, 17, 13, "Q3 6:02", "Patriots")),
        lower_row("devils", live=game("in", sat - 2400, 2, 1, "2nd 8:11", "Rangers")),
        lower_row("mets", last=ended("post", sat - 8 * H_, 5, 3, "Final", "Braves", sat - 3 * H_)),
    ], sat - 1800)
    # Fixture: two finals still inside six hours of their actual end.
    e1001_sports(os.path.join(OUT, "e1001-lower-final.png"), sat, [
        lower_row("navy_fb", last=ended("post", sat - 5 * H_, 28, 21, "Final", "Army", sat - 2 * H_)),
        lower_row("rutgers_bb", last=ended("post", sat - 4 * H_, 71, 68, "Final", "Seton Hall", sat - 1 * H_)),
    ], sat - 3600)
    # Revised: Navy ended in OT two hours ago (kickoff was 11h ago, so a
    # scheduled-length hold would already have dropped it). Rutgers' last play
    # was eight hours ago and must not be on the glass.
    ot_rows = [
        lower_row("navy_fb", last=ended("post", sat - 11 * H_, 31, 28, "Final/OT", "Army", sat - 2 * H_)),
        lower_row("rutgers_bb", last=ended("post", sat - 11 * H_, 70, 68, "Final", "Seton Hall", sat - 8 * H_)),
    ]
    import power
    face, shown = power.classify(ot_rows, sat)
    assert face == "sports" and [r.key for r in shown] == ["navy_fb"], (face, [r.key for r in shown])
    e1001_sports(os.path.join(OUT, "e1001-lower-final-ot.png"), sat, ot_rows, sat - 2 * H_)
