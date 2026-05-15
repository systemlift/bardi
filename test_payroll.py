#!/usr/bin/env python3
"""Test which payroll filter params actually work."""
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

TEST_JOB_ID    = 425400585   # the one new job from today's run
TEST_INVOICE_ID = None        # will discover below

# First get the invoice ID for this job
inv_resp = s.get(f"{ST_BASE_URL}/accounting/v2/tenant/{ST_TENANT_ID}/invoices",
                 headers=headers(token),
                 params={"jobId": TEST_JOB_ID, "pageSize": 5},
                 timeout=15)
invoices = inv_resp.json().get("data", [])
if invoices:
    TEST_INVOICE_ID = invoices[0]["id"]
    print(f"Invoice ID for job {TEST_JOB_ID}: {TEST_INVOICE_ID}")
    print(f"Invoice total: {invoices[0].get('total')}  balance: {invoices[0].get('balance')}")

print("\n--- gross-pay-items: filter by jobId ---")
r = s.get(f"{ST_BASE_URL}/payroll/v2/tenant/{ST_TENANT_ID}/gross-pay-items",
          headers=headers(token),
          params={"jobId": TEST_JOB_ID, "pageSize": 5}, timeout=10)
print(f"Status: {r.status_code}")
if r.ok:
    items = r.json().get("data", [])
    print(f"Count returned: {len(items)}")
    for item in items[:3]:
        print(f"  jobId in response: {item.get('jobId')}  amount: {item.get('amount')}  hours: {item.get('paidDurationHours')}  date: {item.get('date','')[:10]}")

print("\n--- gross-pay-items: filter by jobIds (plural) ---")
r = s.get(f"{ST_BASE_URL}/payroll/v2/tenant/{ST_TENANT_ID}/gross-pay-items",
          headers=headers(token),
          params={"jobIds": TEST_JOB_ID, "pageSize": 5}, timeout=10)
print(f"Status: {r.status_code}  items: {len(r.json().get('data',[]))}")

print("\n--- payroll-adjustments: filter by jobId ---")
r = s.get(f"{ST_BASE_URL}/payroll/v2/tenant/{ST_TENANT_ID}/payroll-adjustments",
          headers=headers(token),
          params={"jobId": TEST_JOB_ID, "pageSize": 10}, timeout=10)
print(f"Status: {r.status_code}")
if r.ok:
    items = r.json().get("data", [])
    print(f"Count: {len(items)}")
    for item in items:
        print(f"  id: {item.get('id')}  invoiceId: {item.get('invoiceId')}  amount: {item.get('amount')}  memo: {item.get('memo')}")

if TEST_INVOICE_ID:
    print(f"\n--- payroll-adjustments: filter by invoiceId={TEST_INVOICE_ID} ---")
    r = s.get(f"{ST_BASE_URL}/payroll/v2/tenant/{ST_TENANT_ID}/payroll-adjustments",
              headers=headers(token),
              params={"invoiceId": TEST_INVOICE_ID, "pageSize": 10}, timeout=10)
    print(f"Status: {r.status_code}")
    if r.ok:
        items = r.json().get("data", [])
        print(f"Count: {len(items)}")
        for item in items:
            print(f"  amount: {item.get('amount')}  memo: {item.get('memo')}  type: {item.get('type')}")
