#!/usr/bin/env python3
"""
Debug: prints raw fields from the first few membership records
and a sample customer record so we can see exact field names.
"""
import os, json, requests
from datetime import datetime, timedelta
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

# Auth
token = s.post(ST_AUTH_URL, data={
    "grant_type": "client_credentials",
    "client_id": ST_CLIENT_ID,
    "client_secret": ST_CLIENT_SECRET,
}, timeout=15).json()["access_token"]

week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

# Pull a few memberships
resp = s.get(
    f"{ST_BASE_URL}/memberships/v2/tenant/{ST_TENANT_ID}/memberships",
    headers=headers(token),
    params={"modifiedOnOrAfter": f"{week_ago}T00:00:00Z", "pageSize": 3},
    timeout=20
)

memberships = resp.json().get("data", [])
print(f"Got {len(memberships)} membership(s)\n")

for i, m in enumerate(memberships):
    print(f"=== MEMBERSHIP {i+1} — ALL FIELDS ===")
    for k, v in m.items():
        print(f"  {k}: {json.dumps(v)[:120]}")

    # Now fetch the customer
    customer_id = (m.get("customer") or {}).get("id") or m.get("customerId")
    if customer_id:
        print(f"\n  --- CUSTOMER RECORD (id={customer_id}) ---")
        cr = s.get(
            f"{ST_BASE_URL}/crm/v2/tenant/{ST_TENANT_ID}/customers/{customer_id}",
            headers=headers(token), timeout=15
        )
        if cr.ok:
            customer = cr.json()
            for k, v in customer.items():
                print(f"    {k}: {json.dumps(v)[:200]}")
        else:
            print(f"  Customer fetch failed: {cr.status_code}")
    print()
