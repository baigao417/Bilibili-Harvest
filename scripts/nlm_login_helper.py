"""Helper script: open Chromium for NLM login and verify result."""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import notebooklm_client as nc
from notebooklm.paths import get_storage_path

def status_cb(msg):
    print(f"[STATUS] {msg}", flush=True)

print("=== NotebookLM Login Helper ===", flush=True)
print("Please log in to Google in the browser window.", flush=True)
print("After you see the NotebookLM notebook list, the browser will auto-save.", flush=True)
print("If auto-detect fails, just close the browser manually.", flush=True)
print()

ok = nc.run_browser_login(on_status=status_cb, timeout=600)
print(f"\nLogin result: {ok}", flush=True)

if ok:
    status = nc.check_auth_available()
    print(f"Auth status: {status.value}", flush=True)

    sp = get_storage_path()
    with open(sp) as f:
        data = json.load(f)
    cookies = data.get("cookies", [])
    print(f"Cookies saved: {len(cookies)}", flush=True)
    domains = set(c.get("domain", "") for c in cookies)
    print(f"Domains: {domains}", flush=True)
else:
    print("Login was not completed. Please try again.", flush=True)
