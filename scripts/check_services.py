#!/usr/bin/env python3
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SERVICES = [
    ("Homepage", "https://homepage.khennig.com/", "Dashboard endpoint behind the reverse proxy"),
    ("Cameras / Frigate", "https://cam.khennig.com/", "Camera portal and Frigate access point"),
    ("Home Assistant", "https://ha.khennig.com/", "Home Assistant external endpoint"),
    ("Speedtest Tracker", "https://speedtest.khennig.com/", "Speedtest results and API site"),
    ("Public website", "https://khennig.com/", "GitHub Pages public site"),
]

def check(name, url, description):
    started = time.perf_counter()
    request = urllib.request.Request(url, headers={"User-Agent": "Kel-Homelab-Monitor/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            code = response.getcode()
        up = 200 <= code < 400 or code in (401, 403)
        return {
            "name": name,
            "url": url,
            "up": up,
            "http_code": code,
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "description": description,
            "status_text": "Reachable; endpoint allows automated access" if code < 400 else "Reachable; endpoint protects automated access",
        }
    except urllib.error.HTTPError as error:
        up = error.code in (401, 403)
        return {
            "name": name,
            "url": url,
            "up": up,
            "http_code": error.code,
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "description": description,
            "status_text": "Reachable; endpoint requires a browser/session" if up else "HTTP error",
            "error": "HTTP response",
        }
    except Exception as error:
        return {
            "name": name,
            "url": url,
            "up": False,
            "http_code": None,
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "description": description,
            "status_text": "No HTTP response",
            "error": str(error)[:140],
        }

results = [check(name, url, description) for name, url, description in SERVICES]
payload = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "overall": "up" if all(item["up"] for item in results) else "down",
    "services": results,
}
Path("status.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
