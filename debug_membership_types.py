#!/usr/bin/env python3
"""Debug: prints all membership types from the API."""
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

print("=== MEMBERSHIP TYPES ===")
r = s.get(
    f"{ST_BASE_URL}/memberships/v2/tenant/{ST_TENANT_ID}/membership-types",
    headers=headers(token),
    params={"pageSize": 50},
    timeout=20
)
print(f"Status: {r.status_code}")
if r.ok:
    types = r.json().get("data", [])
    print(f"Count: {len(types)}\n")
    for t in types:
        print(f"  id: {t.get('id')}  name: {t.get('name')}  active: {t.get('active')}")
else:
    print(f"Error: {r.text}")

# Also check what endpoint structure looks like
print("\n=== RAW FIRST TYPE (all fields) ===")
if r.ok and r.json().get("data"):
    first = r.json()["data"][0]
    for k, v in first.items():
        print(f"  {k}: {json.dumps(v)[:100]}")
