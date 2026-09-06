#!/usr/bin/env python3
"""
app_update_alerts.py

Daily Atlassian app-version report. Discovers the apps actually INSTALLED on
the site, reads each one's installed version, compares it to the latest
published Cloud version on the Atlassian Marketplace, and posts a Slack report
showing what can be updated.

Runs on a schedule (GitHub Actions cron). Pull-based and stateless: the
installed version is read live from the site each run, so there is no state
file to drift and no watchlist to hand-maintain.

DATA SOURCES
------------
1. INSTALLED versions -- UPM REST on the Jira site:
       GET {JIRA_BASE_URL}/rest/plugins/1.0/
       Accept: application/vnd.atl.plugins.installed+json
   Returns plugins[] with .key and .version. This is the same data the admin
   "Connected apps" page renders in its Version field.

   The site also exposes which of those are Marketplace apps (as opposed to
   Atlassian's own bundled system plugins):
       GET {JIRA_BASE_URL}/rest/plugins/1.0/installed-marketplace?updates=true
       Accept: application/vnd.atl.plugins+json
   We intersect the two so the report covers real apps only, not the ~100
   internal system plugins that share the same endpoint.

2. LATEST published version -- public Marketplace API (no auth):
       GET https://marketplace.atlassian.com/rest/2/addons/{key}/versions
           ?hosting=cloud
   Versions come back newest-first under _embedded.versions; we take the first
   entry flagged deployment.cloud=true so we never compare a Data Center
   version against a Cloud install.

SCOPE / KNOWN LIMIT
-------------------
UPM covers CONNECT apps. FORGE apps (e.g. "GitHub for Atlassian") are NOT in
the UPM response -- they live behind a separate, unauthenticated-by-token
GraphQL API on admin.atlassian.com. For those, add an entry to the optional
overrides file (see OVERRIDES_FILE) to pin the installed version manually.
Anything in overrides is merged over whatever UPM reports.

ENV VARS
--------
JIRA_BASE_URL          e.g. https://your-org.atlassian.net   (required)
JIRA_CLOUD_EMAIL       Atlassian account email               (required)
JIRA_CLOUD_API_TOKEN   Atlassian API token                   (required)
SLACK_WEBHOOK_URL      Slack incoming webhook   (required unless DRY_RUN=1)
OVERRIDES_FILE         JSON {app_key: {"name":..., "version":...}} (optional)
DRY_RUN                "1" prints the report instead of posting to Slack
"""

import json
import os
import re
import sys
import time
import logging

import requests
# from requests.auth import HTTPBasicAuth

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("app_update_alerts")

DRY_RUN = os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")

SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")
if not SLACK_WEBHOOK_URL and not DRY_RUN:
    sys.exit("SLACK_WEBHOOK_URL is required (or set DRY_RUN=1 to print instead).")

# JIRA_BASE_URL = os.environ.get("JIRA_BASE_URL", "").rstrip("/")
# JIRA_EMAIL = os.environ.get("JIRA_CLOUD_EMAIL", "")
# JIRA_API_TOKEN = os.environ.get("JIRA_CLOUD_API_TOKEN", "")
# if not (JIRA_BASE_URL and JIRA_EMAIL and JIRA_API_TOKEN):
#     sys.exit("JIRA_BASE_URL, JIRA_CLOUD_EMAIL and JIRA_CLOUD_API_TOKEN are required.")

OVERRIDES_FILE = os.environ.get("OVERRIDES_FILE", "overrides.json")

MARKETPLACE = "https://marketplace.atlassian.com/rest/2/addons"

# UPM (Universal Plugin Manager) on the site. These vendor media types are
# mandatory -- a plain "Accept: application/json" gets a 406 back, naming the
# type it wanted.
UPM_INSTALLED = "/rest/plugins/1.0/"
UPM_MARKETPLACE_APPS = "/rest/plugins/1.0/installed-marketplace"
ACCEPT_INSTALLED = "application/vnd.atl.plugins.installed+json"
ACCEPT_PLUGINS = "application/vnd.atl.plugins+json"

site = requests.Session()
# site.auth = HTTPBasicAuth(JIRA_EMAIL, JIRA_API_TOKEN)

# Run-log link for the Slack footer (GitHub injects these in Actions; empty locally).
_server = os.environ.get("GITHUB_SERVER_URL", "")
_repo = os.environ.get("GITHUB_REPOSITORY", "")
_run = os.environ.get("GITHUB_RUN_ID", "")
RUN_URL = f"{_server}/{_repo}/actions/runs/{_run}" if _run else ""


# --------------------------------------------------------------------------
# version comparison
# --------------------------------------------------------------------------

_LEADING_INT = re.compile(r"\d+")


def parse_version(v):
    """Return a comparable tuple of ints for an Atlassian version string.

    Handles the shapes these APIs actually return: "3.2.0", "1.4.23-AC",
    "1011.0.4-AC", "1001.0.0-SNAPSHOT". The build suffix after the first "-"
    is a packaging marker, not an ordering component, so it is dropped.
    Returns None if nothing numeric can be recovered.
    """
    if not v or not isinstance(v, str):
        return None
    core = v.strip().split("-", 1)[0].split("+", 1)[0]
    parts = []
    for chunk in core.split("."):
        m = _LEADING_INT.search(chunk)
        parts.append(int(m.group(0)) if m else 0)
    return tuple(parts) if any(parts) or parts else None


def compare_versions(latest, installed):
    """Return "update" | "current" | "ahead" | "unknown".

    "ahead" means the installed version is numerically newer than anything
    published for Cloud -- normally an early-access or vendor-pushed build.
    Worth surfacing rather than silently calling it up to date.
    """
    a, b = parse_version(latest), parse_version(installed)
    if a is None or b is None:
        return "unknown"
    n = max(len(a), len(b))
    a = a + (0,) * (n - len(a))
    b = b + (0,) * (n - len(b))
    if a > b:
        return "update"
    if a < b:
        return "ahead"
    return "current"


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

def _get_with_retry(url, params=None, headers=None, session=None, max_retries=6):
    """GET with backoff on 429 and transient network/5xx errors."""
    getter = (session or requests).get
    delay = 2.0
    for attempt in range(1, max_retries + 1):
        try:
            r = getter(url, params=params, headers=headers, timeout=30)
        except (requests.ConnectionError, requests.Timeout) as e:
            if attempt == max_retries:
                raise
            log.warning("Network error (%s); retry %d/%d in %.0fs.",
                        e.__class__.__name__, attempt, max_retries, delay)
            time.sleep(delay)
            delay = min(delay * 2, 60)
            continue
        if r.status_code == 429 or r.status_code >= 500:
            if attempt == max_retries:
                r.raise_for_status()
            wait = r.headers.get("Retry-After")
            wait = float(wait) if wait and wait.isdigit() else delay
            log.warning("HTTP %s; retry %d/%d in %.0fs.",
                        r.status_code, attempt, max_retries, wait)
            time.sleep(wait)
            delay = min(delay * 2, 60)
            continue
        r.raise_for_status()
        return r
    raise RuntimeError("retry loop exited without returning")


# --------------------------------------------------------------------------
# installed side
# --------------------------------------------------------------------------

def load_overrides():
    """Optional {app_key: {"name":..., "version":...}} for apps UPM can't see
    (Forge apps). Merged over the UPM result."""
    try:
        with open(OVERRIDES_FILE) as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    except ValueError as e:
        log.warning("Ignoring malformed %s: %s", OVERRIDES_FILE, e)
        return {}
    return {k: v for k, v in data.items() if isinstance(v, dict)}


def fetch_installed_apps():
    """Return {app_key: {"name":..., "version":..., "update_flagged": bool}}
    for Marketplace apps installed on the site.

    Two calls, joined on key: the installed collection carries the versions,
    the marketplace collection tells us which keys are real apps rather than
    Atlassian's bundled system plugins.
    """
    installed = _get_with_retry(
         UPM_INSTALLED,
        headers={"Accept": ACCEPT_INSTALLED}, session=site).json()

    by_key = {}
    for p in installed.get("plugins") or []:
        key = p.get("key")
        if key:
            by_key[key] = {"name": p.get("name") or key,
                           "version": p.get("version"),
                           "enabled": p.get("enabled")}

    marketplace_apps = _get_with_retry(
        UPM_MARKETPLACE_APPS, params={"updates": "true"},
        headers={"Accept": ACCEPT_PLUGINS}, session=site).json()

    entries = marketplace_apps.get("plugins") or marketplace_apps.get("entries") or []

    apps = {}
    for e in entries:
        key = e.get("key") or e.get("pluginKey")
        if not key:
            continue
        base = by_key.get(key, {})
        apps[key] = {
            "name": e.get("name") or base.get("name") or key,
            "version": base.get("version"),
            # UPM's own opinion on whether an update exists. Kept for the log
            # as a cross-check; the report's verdict comes from the Marketplace
            # comparison, which also tells us the target version.
            "update_flagged": bool(e.get("updateAvailable")),
        }

    for key, ov in load_overrides().items():
        apps.setdefault(key, {})
        apps[key]["name"] = ov.get("name") or apps[key].get("name") or key
        apps[key]["version"] = ov.get("version") or apps[key].get("version")
        apps[key].setdefault("update_flagged", False)

    return apps


# --------------------------------------------------------------------------
# marketplace side
# --------------------------------------------------------------------------

def latest_cloud_version(body):
    """Newest CLOUD version name from a /versions response, or None.

    Versions live under _embedded.versions as a newest-first list; each entry
    carries deployment flags. We take the first flagged cloud=true so we never
    compare against a Data Center version.
    """
    versions = (body.get("_embedded") or {}).get("versions") or []
    if not isinstance(versions, list):
        return None
    for v in versions:
        if isinstance(v, dict) and (v.get("deployment") or {}).get("cloud") is True:
            return v.get("name")
    return None


def fetch_latest_version(app_key):
    """Latest published Cloud version for one app, or None if unavailable.

    A 404 is expected and benign: private/unlisted apps and some Atlassian
    first-party apps have no public Marketplace listing.
    """
    url = f"{MARKETPLACE}/{app_key}/versions"
    try:
        body = _get_with_retry(url, {"hosting": "cloud", "limit": 10}).json()
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else "?"
        if status == 404:
            log.info("No public Marketplace listing for %s; skipping.", app_key)
        else:
            log.error("Failed to fetch latest for %s: HTTP %s", app_key, status)
        return None
    except Exception as e:
        log.error("Failed to fetch latest for %s: %s", app_key, e)
        return None
    return latest_cloud_version(body)


# --------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------

def build_rows(apps):
    """Return list of dicts: name, key, installed, latest, status."""
    rows = []
    for key, info in sorted(apps.items(), key=lambda kv: (kv[1].get("name") or "").lower()):
        latest = fetch_latest_version(key)
        installed = info.get("version")
        status = compare_versions(latest, installed) if latest else "unknown"
        if latest and info.get("update_flagged") and status == "current":
            # UPM says an update exists but versions match. Usually a pending
            # permission approval rather than a version bump.
            status = "action"
        rows.append({"name": info.get("name") or key, "key": key,
                     "installed": installed, "latest": latest, "status": status})
    return rows


def _table(rows, cols=(30, 14, 14)):
    w_name, w_cur, w_new = cols
    out = ["```",
           f"{'App':<{w_name}} {'Installed':<{w_cur}} {'Latest':<{w_new}} Status",
           f"{'-'*w_name} {'-'*w_cur} {'-'*w_new} ------"]
    label = {"update": "UPDATE", "current": "current", "ahead": "ahead",
             "unknown": "unknown", "action": "check UI"}
    for r in rows:
        out.append(f"{(r['name'] or '')[:w_name]:<{w_name}} "
                   f"{(r['installed'] or '?'):<{w_cur}} "
                   f"{(r['latest'] or '?'):<{w_new}} "
                   f"{label.get(r['status'], r['status'])}")
    out.append("```")
    return "\n".join(out)


def build_report(rows):
    """Full inventory: every installed app, its version, what's available,
    and which ones can be updated."""
    date = time.strftime("%B %d, %Y")
    updatable = [r for r in rows if r["status"] == "update"]

    disclaimer = (
        "\n_Apps requiring additional permissions or manual intervention may "
        "not be reflected above. Please confirm updates in the "
        "<https://admin.atlassian.com|Connected Apps UI>._")
    run_link = f"\n<{RUN_URL}|View full run details>" if RUN_URL else ""
    footer = disclaimer + run_link

    if not rows:
        return (f":package: *Atlassian App Update Report — {date}*\n"
                f"No installed Marketplace apps found." + footer)

    if updatable:
        header = (f":package: *Atlassian App Update Report — {date}*\n"
                  f"*{len(updatable)}* of *{len(rows)}* app(s) can be updated:\n")
        body = _table(updatable)
        rest = [r for r in rows if r["status"] != "update"]
        if rest:
            body += f"\n\n_Other tracked apps ({len(rest)}):_\n" + _table(rest)
    else:
        header = (f":package: *Atlassian App Update Report — {date}*\n"
                  f"All *{len(rows)}* tracked app(s) are up to date.\n")
        body = _table(rows)

    return header + body + footer


def post_report(text):
    """Post the report to Slack. Retry 429, fail loudly on a dead webhook,
    skip a single malformed message."""
    if DRY_RUN:
        print(text)
        return True
    for attempt in range(1, 6):
        r = requests.post(SLACK_WEBHOOK_URL, json={"text": text}, timeout=10)
        if r.status_code == 429:
            wait = r.headers.get("Retry-After")
            wait = float(wait) if wait and wait.isdigit() else attempt
            log.warning("Slack rate-limited; retry attempt %d in %.0fs.", attempt, wait)
            time.sleep(wait)
            continue
        if r.status_code in (401, 403, 404):
            # Webhook is dead -- every report will fail, not just this one.
            # Fail the job so GitHub's failed-run email fires (can't announce a
            # dead webhook through the dead webhook).
            raise RuntimeError(
                f"Slack webhook appears dead (HTTP {r.status_code}); "
                f"reporting is down until fixed. Response: {r.text}")
        if 400 <= r.status_code < 500:
            log.error("Slack rejected report (%s): %s", r.status_code, r.text)
            return False
        r.raise_for_status()
        return True
    raise RuntimeError("Slack still rate-limited after retries; report not sent this run.")


def main():
    apps = fetch_installed_apps()
    log.info("Discovered %d installed Marketplace app(s).", len(apps))

    rows = build_rows(apps)
    counts = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1

    report = build_report(rows)
    delivered = post_report(report)
    log.info("Done. %s; delivered=%s.",
             ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "no apps",
             delivered)


if __name__ == "__main__":
    try:
        main()
    except requests.HTTPError as e:
        log.error("HTTP error: %s", e)
        sys.exit(1)
