"""
ANA business-class award watcher: NYC -> Tokyo Haneda.

Asks seats.aero for ANA-operated business award space (the partner pool that
Virgin Atlantic books from), saves it to docs/data.json for the dashboard,
and pings your phone via ntfy.sh when NEW dates appear.

Env vars (set as GitHub secrets):
  SEATS_AERO_API_KEY  - from seats.aero > Settings > API (Pro account)
  NTFY_TOPIC          - any hard-to-guess name, e.g. "natalie-ana-7f3k2"
Optional:
  ORIGINS        default "JFK"
  DESTINATIONS   default "HND"        (use "HND,NRT" to also watch Narita)
  MIN_SEATS      default "1"          (set "2" if two people travel together)
  NONSTOP_ONLY   default "true"
  DAYS_AHEAD     default "360"
  MIN_DAYS_AHEAD default "0"          (e.g. "60" = ignore anything departing in the next 60 days)
  MONTHS         default ""           (e.g. "2027-03,2027-04,2027-10" = only these months; blank = all)
"""
import json, os, sys, urllib.request, urllib.parse, datetime as dt
from pathlib import Path

API = "https://seats.aero/partnerapi/search"
DATA = Path(__file__).parent / "docs" / "data.json"

def env(name, default=""):
    return os.environ.get(name, "").strip() or default  # unset GitHub vars arrive as ""

def fetch_all(key, origins, dests, start, end):
    params = {
        "origin_airport": origins,
        "destination_airport": dests,
        "cabins": "business",
        "start_date": start,
        "end_date": end,
        "take": "1000",
    }
    rows, cursor = [], None
    for _ in range(20):  # pagination safety cap
        if cursor:
            params["cursor"] = str(cursor)
        req = urllib.request.Request(
            API + "?" + urllib.parse.urlencode(params),
            headers={"Partner-Authorization": key, "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            body = json.load(r)
        rows += body.get("data") or []
        if not body.get("hasMore"):
            break
        cursor = body.get("cursor")
    return rows

def num(x):
    try:
        return int(str(x).replace(",", ""))
    except (TypeError, ValueError):
        return 0

def is_ana(airlines):
    return "NH" in [a.strip() for a in str(airlines or "").split(",")]

def extract(rows, min_seats, nonstop_only):
    """Collapse seats.aero rows into one entry per date+route of ANA business space."""
    found = {}
    for r in rows:
        route = r.get("Route") or {}
        o, d = route.get("OriginAirport"), route.get("DestinationAirport")
        date = r.get("Date") or (r.get("ParsedDate") or "")[:10]
        if not (o and d and date):
            continue
        # Prefer the nonstop-specific fields when present.
        if r.get("JDirect") or r.get("JDirectAirlines"):
            airlines = r.get("JDirectAirlines") or r.get("JAirlines")
            seats = num(r.get("JDirectRemainingSeats") or r.get("JRemainingSeats"))
            nonstop = True
        else:
            airlines, seats, nonstop = r.get("JAirlines"), num(r.get("JRemainingSeats")), False
        if not r.get("JAvailable") or not is_ana(airlines):
            continue
        if nonstop_only and not nonstop:
            continue
        if seats and seats < min_seats:   # 0 = unknown, keep it
            continue
        k = f"{date}|{o}|{d}"
        e = found.setdefault(k, {"date": date, "origin": o, "dest": d, "seats": 0,
                                 "nonstop": nonstop, "programs": [], "updated": ""})
        e["seats"] = max(e["seats"], seats)
        src = r.get("Source") or route.get("Source") or "?"
        if src not in e["programs"]:
            e["programs"].append(src)
        e["updated"] = max(e["updated"], r.get("UpdatedAt") or "")
    return sorted(found.values(), key=lambda e: (e["date"], e["origin"], e["dest"]))

def notify(topic, new):
    if not topic or not new:
        return
    lines = [f"{e['date']}  {e['origin']}->{e['dest']}  "
             f"{e['seats'] or '?'} seat(s)" for e in new[:15]]
    if len(new) > 15:
        lines.append(f"...and {len(new) - 15} more")
    msg = "\n".join(lines) + "\n\nVerify on United/ANA, then call Virgin BEFORE transferring points."
    req = urllib.request.Request(
        f"https://ntfy.sh/{urllib.parse.quote(topic)}",
        data=msg.encode(),
        headers={"Title": f"ANA business space: {len(new)} new date(s)",
                 "Priority": "high", "Tags": "airplane"},
    )
    urllib.request.urlopen(req, timeout=30)

def main():
    key = env("SEATS_AERO_API_KEY")
    if not key:
        sys.exit("Missing SEATS_AERO_API_KEY")
    cfg = {
        "origins": env("ORIGINS", "JFK"),
        "dests": env("DESTINATIONS", "HND"),
        "min_seats": num(env("MIN_SEATS", "1")) or 1,
        "nonstop_only": env("NONSTOP_ONLY", "true").lower() != "false",
        "min_days_ahead": num(env("MIN_DAYS_AHEAD", "0")),
        "months": [m.strip() for m in env("MONTHS").split(",") if m.strip()],
    }
    today = dt.date.today()
    start = today + dt.timedelta(days=cfg["min_days_ahead"])
    end = today + dt.timedelta(days=num(env("DAYS_AHEAD", "360")) or 360)

    rows = fetch_all(key, cfg["origins"], cfg["dests"], start.isoformat(), end.isoformat())
    current = extract(rows, cfg["min_seats"], cfg["nonstop_only"])
    current = [e for e in current if e["date"] >= start.isoformat()]
    if cfg["months"]:
        current = [e for e in current if e["date"][:7] in cfg["months"]]

    old = json.loads(DATA.read_text()) if DATA.exists() else {}
    seen_before = {f"{e['date']}|{e['origin']}|{e['dest']}" for e in old.get("results", [])}
    new = [e for e in current if f"{e['date']}|{e['origin']}|{e['dest']}" not in seen_before]

    DATA.parent.mkdir(exist_ok=True)
    DATA.write_text(json.dumps({
        "checked_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
        "config": cfg,
        "raw_rows": len(rows),
        "results": current,
        "new_this_run": [f"{e['date']}|{e['origin']}|{e['dest']}" for e in new],
    }, indent=2))

    print(f"{len(rows)} rows from seats.aero -> {len(current)} ANA dates, {len(new)} new")
    notify(env("NTFY_TOPIC"), new)

if __name__ == "__main__":
    main()
