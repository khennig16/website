# External homelab status page

This package gives `https://khennig.com/status.html` two independent data paths:

- GitHub Actions checks the public HTTPS services from outside the house.
- A small collector runs on the Docker VM and publishes sanitized LAN health data.

The page can therefore stay online when the house is down. When the Docker VM
cannot publish, the page keeps the last home report and marks it **STALE**.

## Upload to GitHub

Upload these files to the root of `khennig16/website`:

- `status.html`
- `status.json`
- `local-status.json`
- `scripts/check_services.py`
- `scripts/publish_local_status.py`
- `.github/workflows/check-services.yml`

`status.html` becomes `https://khennig.com/status.html`. The workflow updates
`status.json` every five minutes. Run **Actions → Check homelab services → Run
workflow** once after uploading, then open the page.

## Configure the Docker-side collector

Copy `scripts/publish_local_status.py` to the Docker VM, for example:

```text
/home/kelly/update-external-local-status.py
```

Create or edit `/home/kelly/.config/command-center/status.env` on the Docker VM:

```bash
GITHUB_STATUS_TOKEN=put-your-fine-grained-token-here
GITHUB_STATUS_REPO=khennig16/website
GITHUB_STATUS_BRANCH=main
GITHUB_STATUS_FILE=local-status.json

# Use the Home Assistant URL reachable from the Docker VM.
HA_URL=https://ha.khennig.com
HA_TOKEN=your-home-assistant-long-lived-token
NEST_ENTITY_ID=climate.your_nest_entity
```

The GitHub token should be a fine-grained token limited to this repository with
only **Contents: Read and write**. Keep this file on the Docker VM and never
upload it to GitHub. Protect it with:

```bash
chmod 600 /home/kelly/.config/command-center/status.env
chmod 700 /home/kelly/update-external-local-status.py
```

Find the Nest entity ID in Home Assistant under **Developer Tools → States**.
It may be a `climate.*` entity or a temperature `sensor.*` entity. Until it is
configured, the Nest card safely shows **SETUP** instead of exposing credentials.

Test it manually:

```bash
set -a
. /home/kelly/.config/command-center/status.env
set +a
python3 /home/kelly/update-external-local-status.py
```

The script checks Proxmox `192.168.4.5`, Docker VM `192.168.4.2`, OPNsense
`192.168.4.1`, main Eero `192.168.4.10`, and office Eero `192.168.4.11`.
It also checks the Nest device at `192.168.4.45`; the temperature itself comes
from Home Assistant rather than directly from the Nest device. Nest reachability
is based on the Home Assistant reading instead of ping, because the thermostat
can ignore ICMP while still working normally.
The other devices use ICMP first and a limited TCP reachability fallback when
ICMP is blocked. It publishes only names, private addresses, descriptions,
up/down state, latency, the check method, and the Nest temperature.

For public services, HTTP 200 means the endpoint responded normally. HTTP 401 or
403 means the endpoint is reachable but protected from an automated request;
the page labels that as **REACHABLE**, not as a full application health check.

## Run it automatically

After the manual test succeeds, add a cron entry on the Docker VM:

```cron
*/5 * * * * set -a; . /home/kelly/.config/command-center/status.env; set +a; python3 /home/kelly/update-external-local-status.py >> /home/kelly/local-status.log 2>&1
```

If the house loses power or internet, the GitHub page remains reachable, the
external cards show the failure, and the home cards show when their last report
was received.
