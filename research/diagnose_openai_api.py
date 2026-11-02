#!/usr/bin/env python3
"""Perform exactly one synthetic OpenAI test call; log only classified error codes.

Never reveal the API key, raw error JSON, headers, response bodies, account IDs,
or organization details. This diagnostic is not a model benchmark.
"""
import json,os,urllib.request,urllib.error
key=(os.environ.get("OPENAI_API_KEY") or "").strip()
model=os.environ.get("OPENAI_MODEL","gpt-6-luna")
if not key:
    raise SystemExit("NO_API_KEY: GitHub secret missing")
allowed_codes={
    "credit_balance_exhausted","organization_usage_limit_exceeded",
    "organization_spend_limit_exceeded","project_spend_limit_exceeded",
    "rate_limit_exceeded","insufficient_quota","model_not_found",
    "invalid_api_key","billing_not_active","account_deactivated"
}
allowed_types={
    "insufficient_quota","rate_limit_exceeded","invalid_request_error",
    "authentication_error","permission_error","server_error"
}
payload={
    "model":model,
    "input":[{"role":"system","content":"Return a valid JSON object."},
             {"role":"user","content":"Respond with a JSON object containing only key ok set to true."}],
    "text":{"format":{"type":"json_object"}},
    "max_output_tokens":100
}
req=urllib.request.Request("https://api.openai.com/v1/responses",
    data=json.dumps(payload).encode("utf-8"),
    headers={"Authorization":"Bearer "+key,"Content-Type":"application/json"},
    method="POST")
try:
    with urllib.request.urlopen(req,timeout=35) as response:
        d=json.load(response)
        print("PROBE_OK; HTTP",response.status,"model response status",d.get("status","UNKNOWN"))
except urllib.error.HTTPError as exc:
    status=exc.code
    try:
        d=json.loads(exc.read(12000).decode("utf-8"))
        err=d.get("error",{})
        code=str(err.get("code") or "UNKNOWN")
        typ=str(err.get("type") or "UNKNOWN")
    except (UnicodeError,ValueError,KeyError,AttributeError):
        code=typ="UNKNOWN"
    print("PROBE_HTTP",status,
          "error_code",code if code in allowed_codes else "OTHER",
          "error_type",typ if typ in allowed_types else "OTHER")
except urllib.error.URLError:
    print("PROBE_NETWORK_ERROR")
