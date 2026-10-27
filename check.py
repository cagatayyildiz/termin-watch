#!/usr/bin/env python3
"""Check Tübingen Bürgerbüro (Ummeldung) for slots on or before DEADLINE; alert via ntfy.sh."""
import datetime as dt
import html
import os
import re
import sys
import time
import urllib.request

BOOK_URL = (
    "https://tempus-termine.com/termine/index.php?anr=107&anwendung=1&allestandorte=1"
    "&action=open&page=standortauswahl&tasks=4623&kuerzel=UMMELD&schlangen=1-2-3-12-13-14-15-26"
)
DEADLINE = dt.date.fromisoformat(os.environ.get("DEADLINE", "2026-11-10"))
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")


def fetch():
    req = urllib.request.Request(BOOK_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def parse(page):
    text = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page)))
    # "Den frühesten Termin am Standort 1 Mittwoch 25.11. um 10:15 Uhr buchen" + location names "1. Bürgerbüro Stadtmitte"
    names = dict(re.findall(r"\b(\d)\. ((?:Bürgerbüro|Verwaltungsstelle) [^\d]+?) ", text))
    today = dt.date.today()
    slots = []
    for loc, day, month, hhmm in re.findall(
        r"Termin am Standort (\d+) \w+ (\d{1,2})\.(\d{1,2})\. um (\d{1,2}:\d{2})", text
    ):
        d = dt.date(today.year, int(month), int(day))
        if d < today - dt.timedelta(days=31):  # year rollover (e.g. January slot seen in December)
            d = d.replace(year=today.year + 1)
        slots.append((d, hhmm, names.get(loc, f"Standort {loc}")))
    return sorted(slots)


def notify(title, msg):
    if not NTFY_TOPIC:
        print("(NTFY_TOPIC not set, not sending)")
        return
    req = urllib.request.Request(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=msg.encode(),
        headers={"Title": title.encode("utf-8"), "Priority": "urgent", "Tags": "rotating_light", "Click": BOOK_URL},
    )
    urllib.request.urlopen(req, timeout=30)


def check_once(last_hits):
    """Print current slots; alert if hits changed since last_hits. Returns current hits."""
    slots = parse(fetch())
    if not slots:
        print("No slots parsed - page layout may have changed")
        sys.exit(1)  # makes the GitHub run red so a broken parser is visible
    print(dt.datetime.now().strftime("--- %H:%M:%S"))
    for d, t, loc in slots:
        print(f"{d:%a %d.%m.%Y} {t}  {loc}")
    hits = [s for s in slots if s[0] <= DEADLINE]
    if hits and hits != last_hits:  # don't re-alert every 2 min for the same slot
        body = "\n".join(f"{d:%a %d.%m.} {t} – {loc}" for d, t, loc in hits) + "\nTap to book."
        print("HIT!\n" + body)
        notify(f"Ummeldung Termin by {DEADLINE:%d.%m.} available!", body)
    elif not hits:
        print(f"Nothing on or before {DEADLINE}.")
    return hits


def main():
    if "--test-alert" in sys.argv:
        notify("Termin watcher test", "Alerts work. Tap to open the booking page.")
        return
    # LOOP_MINUTES > 0: keep checking every INTERVAL seconds (GitHub's own cron fires only every few hours)
    end = time.time() + 60 * int(os.environ.get("LOOP_MINUTES", "0"))
    interval = int(os.environ.get("INTERVAL", "120"))
    hits = None
    while True:
        try:
            hits = check_once(hits)
        except (OSError, ValueError) as e:  # network hiccup: retry next round
            print(f"fetch failed: {e}")
        if time.time() + interval > end:
            break
        time.sleep(interval)


if __name__ == "__main__":
    main()
