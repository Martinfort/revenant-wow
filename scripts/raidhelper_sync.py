#!/usr/bin/env python3
"""Raid-Helper -> data/raidhelper.json for the Revenant hub site.

Runs in GitHub Actions every 15 minutes. Reads the server's events with the server API key
(GitHub secret RAIDHELPER_API_KEY) and each upcoming event's sign-ups, and writes a trimmed,
public-safe copy: titles, times, leader, description and sign-up names/classes/roles.
Discord user IDs are NOT published. The file only changes (and is only committed) when an
event or sign-up actually changes.
"""
import json, os, sys, time, urllib.request, urllib.error

API = "https://raid-helper.xyz/api/v4"
KEY = os.environ.get("RAIDHELPER_API_KEY", "").strip()
SERVER = os.environ.get("RAIDHELPER_SERVER_ID", "").strip()
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "raidhelper.json")
STATUS = os.path.join(os.path.dirname(__file__), "..", "data", "raidhelper-status.json")
LAST_ERROR = {}
PAST_HOURS = 12            # keep an event this long after it started
SIGNUP_FIELDS = ("name", "className", "specName", "roleName", "status", "position", "entryTime")
EVENT_FIELDS = ("title", "description", "startTime", "endTime", "leaderName", "channelName", "templateId", "color", "imageUrl", "closeTime", "lastUpdated")


def get(path, auth=True):
    req = urllib.request.Request(API + path, headers={"User-Agent": "revenant-hub-sync"})
    if auth:
        req.add_header("Authorization", KEY)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            reason = json.loads(e.read().decode("utf-8")).get("reason") or ""
        except Exception:
            reason = ""
        LAST_ERROR.update({"request": path.split("/")[1] + ("/" + path.split("/")[3] if path.count("/") >= 3 else ""), "http": e.code, "reason": str(reason)[:200]})
        print(f"Raid-Helper request failed: HTTP {e.code} {reason}", file=sys.stderr)   # never print the key
        return None
    except Exception as e:
        LAST_ERROR.update({"request": path.split("/")[1], "error": type(e).__name__})
        print(f"Raid-Helper request failed: {type(e).__name__}", file=sys.stderr)
        return None


def event_list(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ("postedEvents", "events", "scheduledEvents"):
            if isinstance(data.get(k), list):
                return data[k]
    return []


def to_int(x):
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return None


def status(ok, **extra):
    # A small public status file (no key, no server id) so a failed run can be read from the repo.
    body = {"ok": ok, **extra}
    try:
        with open(STATUS, encoding="utf-8") as f:
            if {k: v for k, v in json.load(f).items() if k != "at"} == body:
                return
    except Exception:
        pass
    body["at"] = int(time.time())
    os.makedirs(os.path.dirname(STATUS), exist_ok=True)
    with open(STATUS, "w", encoding="utf-8") as f:
        json.dump(body, f, indent=1)


def main():
    if not KEY or not SERVER:
        status(False, problem="secrets missing", hasKey=bool(KEY), hasServer=bool(SERVER), serverIdLooksNumeric=SERVER.isdigit())
        print("RAIDHELPER_API_KEY / RAIDHELPER_SERVER_ID secrets are missing", file=sys.stderr)
        return 0
    listing = get(f"/servers/{SERVER}/events")
    if listing is None:
        status(False, problem="could not list events", serverIdLooksNumeric=SERVER.isdigit(), keyLength=len(KEY), **LAST_ERROR)
        return 0
    now = time.time()
    events, keys_seen, su_keys_seen = [], set(), set()
    for ev in event_list(listing):
        eid = str(ev.get("id") or ev.get("eventId") or "")
        start = to_int(ev.get("startTime"))
        if not eid or (start and start < now - PAST_HOURS * 3600):
            continue
        full = get(f"/events/{eid}", auth=False) or ev
        if isinstance(full, dict) and isinstance(full.get("event"), dict):
            full = full["event"]
        keys_seen.update(full.keys())
        out = {"id": eid}
        for k in EVENT_FIELDS:
            if full.get(k) not in (None, ""):
                out[k] = full[k]
        for k in ("startTime", "endTime", "closeTime", "lastUpdated"):
            if k in out:
                out[k] = to_int(out[k])
        sus = []
        for s in full.get("signUps") or []:
            su_keys_seen.update(s.keys())
            sus.append({k: s[k] for k in SIGNUP_FIELDS if s.get(k) not in (None, "")})
        out["signUps"] = sus
        events.append(out)
        time.sleep(0.4)   # stay well inside Raid-Helper's rate limits
    events.sort(key=lambda e: e.get("startTime") or 0)
    status(True, events=len(events), listShape=(type(listing).__name__ + (":" + ",".join(sorted(listing.keys()))[:200] if isinstance(listing, dict) else "")))
    body = {"source": "Raid-Helper", "events": events,
            "_fields": {"event": sorted(keys_seen), "signUp": sorted(su_keys_seen)}}   # field names only, for building the page
    old = None
    try:
        with open(OUT, encoding="utf-8") as f:
            old = json.load(f)
    except Exception:
        pass
    if old and {k: v for k, v in old.items() if k != "updated"} == body:
        print(f"No changes ({len(events)} events)")
        return 0
    body["updated"] = int(now)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(body, f, ensure_ascii=False, indent=1)
    print(f"Wrote {len(events)} events")
    return 0


if __name__ == "__main__":
    sys.exit(main())
