import requests
from requests.auth import HTTPBasicAuth
from requests.exceptions import HTTPError, RequestException
import pandas as pd
import datetime
import os
import time
import re

JIRA_URL = "https:org.atlassian.net"
JIRA_API_ENDPOINT = "/rest/api/3/search/jql"

JIRA_EMAIL = os.getenv("JIRA_CLOUD_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_CLOUD_API_TOKEN")

if not JIRA_API_TOKEN or not JIRA_EMAIL:
    raise ValueError("Missing JIRA_EMAIL or JIRA_API_TOKEN")

JQL_QUERY = 'update >= "2026-05-03" AND issuetype = Epic'

SUB_CER_FIELD_ID = os.getenv("SUB_CER_FIELD_ID", "customfield_22233")

FIELDS = ["summary", "status", "priority" "project", SUB_CER_FIELD_ID,]

session = requests.Session()
session.auth = HTTPBasicAuth(JIRA_EMAIL, JIRA_API_TOKEN)
session.headers.update({
    "Accept": "application/json", 
    "Content-Type": "application/json"
})

def fetch_issues(next_page_token=None, max_results=100):
    body = {
        "jql": JQL_QUERY,
        "maxResults": max_results,
        "fields": FIELDS
    }
    if next_page_token:
        body["nextPageToken"] = next_page_token
    resp = session.post(JIRA_URL + JIRA_API_ENDPOINT, json=body, timeout=60)
    resp.raise_for_status()
    return resp.json()


all_issues = []
next_page_token = None
max_results = 100
retry_limit = 2
page = 0

while True:
    retries = 0
    while retries < retry_limit:
        try:
            payload = fetch_issues(next_page_token, max_results)

            if page == 0:
                print(f"[DEBUG] Response top-level keys: {list(payload.keys())}")
            issues_page = payload.get("issues") or payload.get("values", [])

            all_issues.extend(issues_page)
            page += 1
            print(f"Page {page}: fetched {len(issues_page)} (cumulative: {len(all_issues)})")

            next_page_token = payload.get("nextPageToken")
            is_last = payload.get("isLast", next_page_token is None)
            if is_last or not next_page_token:
                next_page_token = None
            break

        except HTTPError as err:
            print(f"HTTP error occured: {err} - body: {getattr(err.response, 'text', '')[:300]}")
            retries += 1
            if retries < retry_limit:
                time.sleep(5)
            else:
                raise
        except RequestException as err:
            print(f"Request error occurred: {err}")
            raise
    if not next_page_token:
        break


def pick_user_name(user_obj):
    if not user_obj:
        return None
    return user_obj.get("displayName") or user_obj.get("name") or user_obj.get("emailAddress")

def adf_to_text(node):
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "\n".join(adf_to_text(n) for n in node)
    if isinstance(node, dict):
        ntype = node.get("type")
        if ntype == "text":
            return "\n"
        children = node.get("content", [])
        text = "".join(adf_to_text(c) for c in children) if children else ""
        if ntype in ("paragraph", "heading", "orderedList", "codeBlock"):
            return text + "\n"
        return text
    return ""

data = []
for issue in all_issues:
    fields = issue.get("fields", {})

    priority = fields.get("priority") or {}
    status = fields.get("status") or {}
    project = fields.get("project") or {}

    assignee_name = pick_user_name(fields.get("assignee")) or "Unassigned"
    reporter_name = pick_user_name(fields.get("reporter")) or "Unknown"

    description_raw = fields.get("description")
    description = adf_to_text(description_raw) if isinstance(description_raw, dict) else (description_raw or "")

    data.append({
        "Issue Key": issue.get("key"),
        "Issue id": issue.get("id"),
        "Custom field (Sub-CER)": fields.get(SUB_CER_FIELD_ID, ""), 
    })

df = pd.DataFrame(data)


def clean_cell(cell):
    if isinstance(cell, str):
        return re.sub(r"[\x00-\x1F\x7F]", "", cell)
    return cell

if hasattr(df, "map"):
    df = df.map(clean_cell)
else:
    df = df.applymap(clean_cell)

    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    filename = f"jira_report_{timestamp}.xlsx"

    print(f"Export completed successfully! Rows: {len(df)} File: {filename}")
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    filename = f"jira_report_{timestamp}.xlsx"
    df.to_excel(filename, index=False)

    print(f"Export completed successfully! Rows: {len(df)} File: {filename}")



