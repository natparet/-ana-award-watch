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
  RETURN_MONTHS  default ""           months for flights home (Tokyo -> US); blank = all
  TRACK_RETURN   default "true"       set "false" to watch outbound only
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
    lines = []
    for label, d in (("OUTBOUND (to Tokyo)", "out"), ("RETURN (to US)", "return")):
        part = [e for e in new if e.get("direction", "out") == d]
        if not part:
            continue
        lines.append(label)
        lines += [f"{e['date']}  {e['origin']}->{e['dest']}  {e['seats'] or '?'} seat(s)" for e in part[:10]]
        if len(part) > 10:
            lines.append(f"...and {len(part) - 10} more")
        lines.append("")
    msg = "\n".join(lines) + "\nVerify on United/ANA, then call Virgin BEFORE transferring points."
    req = urllib.request.Request(
        f"https://ntfy.sh/{urllib.parse.quote(topic)}",
        data=msg.encode(),
        headers={"Title": f"ANA business space: {len(new)} new date(s)",
                 "Priority": "high", "Tags": "airplane"},
    )
    urllib.request.urlopen(req, timeout=30)

def months_list(v):
    return [m.strip() for m in v.split(",") if m.strip()]

def search(key, cfg, origins, dests, months, direction, start, end):
    rows = fetch_all(key, origins, dests, start.isoformat(), end.isoformat())
    found = extract(rows, cfg["min_seats"], cfg["nonstop_only"])
    found = [e for e in found if e["date"] >= start.isoformat()]
    if months:
        found = [e for e in found if e["date"][:7] in months]
    for e in found:
        e["direction"] = direction
    return rows, found

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
        "months": months_list(env("MONTHS")),
        "track_return": env("TRACK_RETURN", "true").lower() != "false",
        "return_months": months_list(env("RETURN_MONTHS")),
    }
    today = dt.date.today()
    start = today + dt.timedelta(days=cfg["min_days_ahead"])
    end = today + dt.timedelta(days=num(env("DAYS_AHEAD", "360")) or 360)

    rows, current = search(key, cfg, cfg["origins"], cfg["dests"], cfg["months"], "out", start, end)
    raw = len(rows)
    if cfg["track_return"]:
        # Return flights: Tokyo -> any of the US airports being watched.
        rows, back = search(key, cfg, cfg["dests"], cfg["origins"], cfg["return_months"], "return", start, end)
        raw += len(rows)
        current += back

    k = lambda e: f"{e['date']}|{e['origin']}|{e['dest']}"
    old = json.loads(DATA.read_text()) if DATA.exists() else {}
    seen_before = {k(e) for e in old.get("results", [])}
    new = [e for e in current if k(e) not in seen_before]

    DATA.parent.mkdir(exist_ok=True)
    DATA.write_text(json.dumps({
        "checked_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
        "config": cfg,
        "raw_rows": raw,
        "results": current,
        "new_this_run": [k(e) for e in new],
    }, indent=2))

    print(f"{raw} rows from seats.aero -> {len(current)} ANA dates, {len(new)} new")
    notify(env("NTFY_TOPIC"), new)

if __name__ == "__main__":
    main()
