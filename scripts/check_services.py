#!/usr/bin/env python3
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SERVICES = [
    ("Homepage", "https://homepage.khennig.com/"),
    ("Cameras / Frigate", "https://cam.khennig.com/"),
    ("Home Assistant", "https://ha.khennig.com/"),
    ("Speedtest Tracker", "https://speedtest.khennig.com/"),
    ("Public website", "https://khennig.com/"),
]

def check(name, url):
    started = time.perf_counter()
    request = urllib.request.Request(url, headers={"User-Agent": "Kel-Homelab-Monitor/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            code = response.getcode()
        up = 200 <= code < 400 or code in (401, 403)
        return {"name": name, "url": url, "up": up, "http_code": code, "latency_ms": round((time.perf_counter() - started) * 1000)}
    except urllib.error.HTTPError as error:
        up = error.code in (401, 403)
        return {"name": name, "url": url, "up": up, "http_code": error.code, "latency_ms": round((time.perf_counter() - started) * 1000), "error": "HTTP response"}
    except Exception as error:
        return {"name": name, "url": url, "up": False, "http_code": None, "latency_ms": round((time.perf_counter() - started) * 1000), "error": str(error)[:140]}

results = [check(name, url) for name, url in SERVICES]
payload = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "overall": "up" if all(item["up"] for item in results) else "down",
    "services": results,
}
Path("status.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
