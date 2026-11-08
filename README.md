# Quad Board

An e-paper kitchen dashboard for the Seeed reTerminal E1001. Four corners of your day on a 7.5" screen: the weather, the news and markets, your teams, and whatever is flying over the house right now.

![Quad Board cycling through its pages](docs/img/demo.gif)

**[See the project page →](https://j-rod-ay.github.io/eink-quad/)**

🖥️ **The screen: [Seeed reTerminal E1001 on Amazon](https://link.amazon/B0gH6ekeP)** — 7.5″ 800×480 mono e-paper, ESP32-S3, battery. *(affiliate link)*

## What's on it

| Corner | Shows |
|---|---|
| **Weather** | current conditions, rain chance for the next few hours, 3-day forecast, 15-minute rain nowcast, NWS alerts |
| **News & markets** | index and ticker moves, rotating WSJ headlines |
| **Your teams** | live score, last result or next game for any ESPN team, with TV and the betting line |
| **Plane overhead** | airline, route, aircraft, altitude and which way to look, from live ADS-B. An ISS pass or a visible rocket launch takes this corner over |

A strip under the header carries one line: your own pinned message, a severe weather alert, or a sentence from Claude that ties the day together (optional).

The three buttons on top work as **home**, **previous page** and **next page**. Each corner has its own detail page:

| | |
|---|---|
| ![Weather](docs/img/weather.png) | ![News & markets](docs/img/news.png) |
| ![Scores](docs/img/sports.png) | ![Sky above](docs/img/sky.png) |

## How it works

The screen doesn't decide anything. A small Python server renders every pixel with Pillow, diffs the frame against what's already on the glass, and hands the board only the rectangles that changed. The board long-polls over HTTPS (or deep-sleeps between checks on battery) and plays those rectangles as ~1 s partial refreshes. A full refresh with 4 grey levels runs on the regular update, and a flashing one every couple of hours wipes ghosting.

Changing the layout, the cadence or a data source never means reflashing. Everything is a setting on the server's web dashboard.

```
server/    Python: data sources, renderer, long-poll server, settings dashboard
firmware/  PlatformIO / Arduino for the reTerminal E1001 (ESP32-S3)
docs/      the project page and screenshots
```

## Data sources

All keyless: Open-Meteo (forecast + nowcast), api.weather.gov (alerts, US only), WSJ RSS, Yahoo Finance spark, ESPN's site API, adsb.lol + adsbdb, CelesTrak + Launch Library 2. The one-line brief uses the [`claude`](https://docs.claude.com/en/docs/claude-code) CLI if it's installed and logged in. Turn `llm_brief` off otherwise.

## Setup

### Hardware
- **[Seeed reTerminal E1001](https://link.amazon/B0gH6ekeP)** — 7.5" 800×480 mono e-paper, ESP32-S3 *(affiliate link; also at [Seeed](https://www.seeedstudio.com/))*
- An always-on machine for the server (VPS, Raspberry Pi, NAS), reachable from the board over **HTTPS**. Put it behind nginx or Caddy. The firmware doesn't verify certificates, so a self-signed one works too.

### Server

```sh
cd server
pip install -r requirements.txt
cp quad.env.example quad.env       # set QUAD_TOKEN and QUAD_ADMIN
set -a; . ./quad.env; set +a
python app.py                      # listens on 127.0.0.1:8740
```

Open `http://127.0.0.1:8740/?k=<QUAD_ADMIN>` to set your location, units, feeds, tickers, teams, panel order and refresh cadence. Settings are saved to `config.json`.

**Preview without hardware:** `python cases.py` renders every screen with live data to `case_*.png`.

**Your teams:** the built-in keys are the Tampa ones (`bucs`, `lightning`, `rays`, `gators_fb`, `gators_bb`). Add your own in `config.json` with ESPN's sport, league and team id or abbreviation:

```json
{
  "city": "Chicago",
  "lat": 41.8781, "lon": -87.6298,
  "custom_teams": {
    "bears": ["Bears", "football", "nfl", "chi"],
    "cubs":  ["Cubs", "baseball", "mlb", "chc"]
  },
  "teams": ["bears", "cubs"]
}
```

### Firmware

```sh
cd firmware
cp src/secrets.example.h src/secrets.h   # your server's host and QUAD_TOKEN
pio run -t upload --upload-port COM9     # or upload.bat COM9 on Windows
```

On first boot the board opens a Wi-Fi setup portal named `QuadBoard-XXXX`. Join it from your phone and pick your network. To get back to it later, hold the right button and tap the left one.

`firmware/serial.ps1 -Port COM9` resets the board and prints its boot log.

## Two fridge boards

The big E1003 keeps one daily face and does not rotate or take a sports or Sunday NFL layout: Shabbat times, the newsletter, weather, news, and his next trip. There is no calendar tile and no overhead-plane radar. On Friday and Saturday the newsletter takes most of the screen; weather and Shabbat times stay, and stock quotes stay off. Those panels refresh around **7:30, 12:30 and 18:30** America/New_York, and also at candle lighting, havdalah, and the Friday/Sunday market change. **22:00–07:00** stays quiet.

The small E1001 shows Fox News and WSJ tech, hourly in the daytime. At game time it switches to Jets, Mets, Devils, Nets, Navy football, and Rutgers basketball only. One game fills the screen, with each club's real mark and a large score. Two or more shrink into smaller panels so they all fit. Marks come from the ESPN logo the schedule already carries; if a file is missing, the name and score still draw. A favorite that is actually playing updates about every **15 minutes**, with an **as of** time that moves only when the score or the headlines change. Finals stay up for six hours after ESPN's last play (overtime included), saved in `state.json`. If that timestamp is missing, the clock starts when the final is first seen and is not moved later. An unchanged final does not redraw. It does not show Shabbat, the newsletter, or a shop tile.

Partials redraw only the regions that changed. A full flash is the occasional ghost clean, not every update.

The charge line is each board's own last voltage, turned into a percent with Seeed's resting-voltage table (there is no fuel gauge, so it reads high while charging). No report shows as "batt —". A report older than 20 minutes shows "old". The small board's score updates are a full black-and-white refresh: the fast partial leaves large type gray on that panel.

**Radio.** Firmware `5min-1` deep-sleeps between checks with Wi-Fi off. Automatic checks are never closer than 5 minutes, lined up on the 5-minute clock so 7:30, 12:30, 18:30, the hourly news, and the :00/:15/:30/:45 sports marks are not pushed to the next hour. A button wakes either board immediately and is not part of that floor. The E1003 touch pad does not wake it; the touch chip is held in reset while the processor sleeps. The server answers `X-Mode: sleep` and `X-Next: 300`. Do not put that server on the VM until this firmware is on the boards: the firmware already there still long-polls only while the server says live, and it will sleep if the server says sleep. Nothing here was measured on a full charge, and a week per charge is not a claim.

## Notes

- Times use the server's `TZ` (defaults to `America/New_York`).
- The notes feature reads a separate "note box" project's database and is off unless `QUAD_NOTES_DB` is set.
- Team logos and airline logos are downloaded at runtime and cached in `server/cache/`. None are shipped in this repo.

## License

MIT. Bundled fonts carry their own licences, listed in [`server/fonts/LICENSES.md`](server/fonts/LICENSES.md).
