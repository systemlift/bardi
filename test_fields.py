#!/usr/bin/env python3
"""Print raw API response for one job and its invoices."""
import os, json, requests
from dotenv import load_dotenv

load_dotenv()

ST_AUTH_URL      = "https://auth.servicetitan.io/connect/token"
ST_BASE_URL      = "https://api.servicetitan.io"
ST_TENANT_ID     = os.environ["ST_TENANT_ID"]
ST_CLIENT_ID     = os.environ["ST_CLIENT_ID"]
ST_CLIENT_SECRET = os.environ["ST_CLIENT_SECRET"]
ST_APP_KEY       = os.environ["ST_APP_KEY"]

s = requests.Session()

def headers(token):
    return {"Authorization": f"Bearer {token}", "ST-App-Key": ST_APP_KEY}

token = s.post(ST_AUTH_URL, data={
    "grant_type": "client_credentials",
    "client_id": ST_CLIENT_ID,
    "client_secret": ST_CLIENT_SECRET,
}, timeout=15).json()["access_token"]

# Grab one completed job
resp = s.get(f"{ST_BASE_URL}/jpm/v2/tenant/{ST_TENANT_ID}/jobs",
             headers=headers(token),
             params={"completedOnOrAfter": "2026-05-10T00:00:00Z",
                     "completedOnOrBefore": "2026-05-10T23:59:59Z",
                     "jobStatus": "Completed", "pageSize": 1},
             timeout=20)

job = resp.json()["data"][0]
print("=== JOB KEYS ===")
print(json.dumps(list(job.keys()), indent=2))
print("\n=== JOB VALUES (top-level) ===")
for k, v in job.items():
    if not isinstance(v, (list, dict)):
        print(f"  {k}: {v}")
    else:
        print(f"  {k}: {json.dumps(v)[:120]}")

# Grab its invoices
job_id = job["id"]
resp2 = s.get(f"{ST_BASE_URL}/accounting/v2/tenant/{ST_TENANT_ID}/invoices",
              headers=headers(token),
              params={"jobId": job_id, "pageSize": 5},
              timeout=20)
invoices = resp2.json().get("data", [])
if invoices:
    inv = invoices[0]
    print("\n=== INVOICE KEYS ===")
    print(json.dumps(list(inv.keys()), indent=2))
    print("\n=== INVOICE VALUES ===")
    for k, v in inv.items():
        if not isinstance(v, (list, dict)):
            print(f"  {k}: {v}")
        else:
            print(f"  {k}: {json.dumps(v)[:120]}")
else:
    print("\nNo invoices found for this job.")
