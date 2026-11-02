"""Credential and request-shape diagnosis. Never print secrets or raw API errors."""
import json
import os
import urllib.error
import urllib.request

RAW_KEY = os.environ.get("GEMINI_API_KEY", "")
KEY = RAW_KEY.strip()
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
HOST = "https://generativelanguage.googleapis.com/v1beta"

def classify_message(raw):
    try:
        body = json.loads(raw.decode("utf-8", errors="ignore"))["error"]
        status = body.get("status", "UNKNOWN")
        message = str(body.get("message", "")).lower()
    except (ValueError, TypeError, KeyError, AttributeError):
        return "UNKNOWN", "UNAVAILABLE"
    if "api key not valid" in message or "invalid api key" in message or "api_key_invalid" in message:
        hint = "INVALID_API_KEY"
    elif "leaked" in message or "blocked" in message:
        hint = "BLOCKED_KEY"
    elif "billing" in message or "payment" in message:
        hint = "BILLING_OR_PROJECT"
    elif "not supported" in message or "not found" in message or "not available" in message:
        hint = "UNSUPPORTED_MODEL_OR_FEATURE"
    elif "temperature" in message or "generationconfig" in message or "responsemimetype" in message:
        hint = "CONFIGURATION_PARAMETER"
    elif "service account" in message or "permission" in message or "restricted" in message:
        hint = "KEY_RESTRICTION_OR_PROJECT_PERMISSION"
    else:
        hint = "OTHER"
    return status, hint

def get(path, body=None):
    data=None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(HOST+path, data=data,
        headers={"x-goog-api-key": KEY, "Content-Type": "application/json"},
        method="GET" if body is None else "POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            r.read(2048)
            return (r.status, "OK", "OK")
    except urllib.error.HTTPError as exc:
        status, hint = classify_message(exc.read(16384))
        return (exc.code, status, hint)
    except urllib.error.URLError:
        return ("NETWORK", "NETWORK", "UNAVAILABLE")

print("Key has value:", bool(KEY))
print("Key has leading/trailing whitespace:", KEY != RAW_KEY)
print("Key has internal whitespace:", any(c.isspace() for c in KEY))
if not KEY:
    raise SystemExit("No key configured; no requests made.")
checks = [
    ("list_models", "/models", None),
    ("simple_generate", f"/models/{MODEL}:generateContent",
     {"contents":[{"role":"user","parts":[{"text":"Say hello in one word."}]}]}),
    ("json_generate", f"/models/{MODEL}:generateContent",
     {"contents":[{"role":"user","parts":[{"text":"Return JSON object with ok true."}]}],
      "generationConfig":{"temperature":0,"responseMimeType":"application/json"}}),
]
for name, path, body in checks:
    code, status, hint = get(path, body)
    print(name + ": HTTP=" + str(code) + " status=" + status + " category=" + hint)
    if name == "list_models" and code not in (200, 201):
        break
