#!/usr/bin/env python3
"""Collect safe LAN/Nest health data and publish local-status.json to GitHub.

This script is intended to run on the Docker VM inside the home network.
It never publishes HA tokens, GitHub tokens, MAC addresses, or API responses.
"""

import base64
import json
import os
import re
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_ENV_FILE = "/home/kelly/.config/command-center/status.env"
DEFAULT_REPO = "khennig16/website"
DEFAULT_BRANCH = "main"
DEFAULT_REMOTE_PATH = "local-status.json"

HOSTS = [
    ("Proxmox host", "192.168.4.5", (8006,), "Proxmox hypervisor · VM 100 and CT 101"),
    ("Docker VM", "192.168.4.2", (80, 443), "VM 100 · local status collector"),
    ("OPNsense", "192.168.4.1", (443,), "LAN gateway · HTTPS reachability"),
    ("Main Eero", "192.168.4.10", (80,), "Eero bridge/access point · ICMP reachability"),
    ("Office Eero", "192.168.4.11", (80,), "Eero bridge/access point · ICMP reachability"),
]


def load_env_file(path):
    """Load simple KEY=value entries without overriding real environment vars."""
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


def now():
    return datetime.now(timezone.utc).isoformat()


def ping(address):
    started = time.perf_counter()
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", "1", address],
            capture_output=True,
            text=True,
            timeout=3,
        )
        elapsed = round((time.perf_counter() - started) * 1000, 1)
        match = re.search(r"time[=<]([0-9.]+)\s*ms", result.stdout)
        return result.returncode == 0, (float(match.group(1)) if match else elapsed), "icmp"
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False, None, "icmp"


def tcp_fallback(address, ports):
    """Use an admin/service port only when ICMP is blocked."""
    for port in ports:
        started = time.perf_counter()
        try:
            with socket.create_connection((address, port), timeout=2):
                return True, round((time.perf_counter() - started) * 1000, 1), f"tcp/{port}"
        except OSError:
            continue
    return False, None, "unreachable"


def check_host(name, address, ports, description):
    up, latency, method = ping(address)
    if not up:
        up, latency, method = tcp_fallback(address, ports)
    return {
        "name": name,
        "address": address,
        "up": up,
        "latency_ms": latency,
        "check": method,
        "description": description,
    }


def ha_temperature():
    entity_id = os.getenv("NEST_ENTITY_ID", "").strip()
    ha_url = os.getenv("HA_URL", "").strip().rstrip("/")
    token = os.getenv("HA_TOKEN", "").strip()
    base = {"configured": bool(entity_id and ha_url and token), "available": False}
    if not entity_id:
        base["message"] = "NEST_ENTITY_ID is not configured"
        return base
    if not ha_url or not token:
        base["message"] = "HA_URL or HA_TOKEN is not configured"
        return base
    url = f"{ha_url}/api/states/{urllib.parse.quote(entity_id, safe='')}"
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "Kel-Homelab-Local-Collector/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            data = json.load(response)
        attributes = data.get("attributes") or {}
        candidates = [attributes.get("current_temperature"), attributes.get("temperature"), data.get("state")]
        temperature = next((value for value in candidates if isinstance(value, (int, float))), None)
        if temperature is None:
            base["message"] = "Nest entity returned no temperature"
            return base
        return {
            "configured": True,
            "available": True,
            "temperature": temperature,
            "unit": attributes.get("temperature_unit", "°C"),
            "state": str(data.get("state", "available")),
        }
    except urllib.error.HTTPError as error:
        base["message"] = f"Home Assistant HTTP {error.code}"
        return base
    except Exception as error:
        base["message"] = str(error)[:140]
        return base


def github_headers(token):
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "Kel-Homelab-Local-Collector/1.0",
    }


def publish_to_github(payload):
    token = os.getenv("GITHUB_STATUS_TOKEN", "").strip()
    repo = os.getenv("GITHUB_STATUS_REPO", DEFAULT_REPO).strip()
    branch = os.getenv("GITHUB_STATUS_BRANCH", DEFAULT_BRANCH).strip()
    remote_path = os.getenv("GITHUB_STATUS_FILE", DEFAULT_REMOTE_PATH).strip().lstrip("/")
    if not token:
        return False, "GITHUB_STATUS_TOKEN is not configured"

    api_url = f"https://api.github.com/repos/{repo}/contents/{urllib.parse.quote(remote_path, safe='/')}"
    content = json.dumps(payload, indent=2).encode("utf-8")
    encoded = base64.b64encode(content).decode("ascii")

    for attempt in range(2):
        sha = None
        try:
            request = urllib.request.Request(api_url, headers=github_headers(token))
            with urllib.request.urlopen(request, timeout=12) as response:
                sha = json.load(response).get("sha")
        except urllib.error.HTTPError as error:
            if error.code != 404:
                return False, f"GitHub read HTTP {error.code}"
        except Exception as error:
            return False, f"GitHub read failed: {str(error)[:100]}"

        body = {"message": "Update local homelab status", "content": encoded, "branch": branch}
        if sha:
            body["sha"] = sha
        request = urllib.request.Request(
            api_url,
            data=json.dumps(body).encode("utf-8"),
            headers={**github_headers(token), "Content-Type": "application/json"},
            method="PUT",
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                if 200 <= response.status < 300:
                    return True, "published"
        except urllib.error.HTTPError as error:
            if error.code == 409 and attempt == 0:
                continue
            return False, f"GitHub publish HTTP {error.code}"
        except Exception as error:
            return False, f"GitHub publish failed: {str(error)[:100]}"
    return False, "GitHub publish conflict"


def main():
    load_env_file(os.getenv("STATUS_ENV_FILE", DEFAULT_ENV_FILE))
    nest = ha_temperature()
    hosts = [check_host(name, address, ports, description) for name, address, ports, description in HOSTS]
    hosts.append({
        "name": "Nest thermostat",
        "address": "192.168.4.45",
        "up": nest["available"],
        "latency_ms": None,
        "check": "home-assistant",
        "description": "Status is based on Home Assistant, not ICMP ping",
    })
    payload = {
        "generated_at": now(),
        "overall": "up" if all(item["up"] for item in hosts) else "down",
        "collector": {"name": "Docker VM", "address": "192.168.4.2"},
        "hosts": hosts,
        "nest": nest,
    }

    output_path = Path(os.getenv("LOCAL_STATUS_OUTPUT", "/tmp/local-status.json"))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    published, message = publish_to_github(payload)
    print(json.dumps({"generated_at": payload["generated_at"], "published": published, "message": message}))
    return 0 if published else 2


if __name__ == "__main__":
    raise SystemExit(main())
