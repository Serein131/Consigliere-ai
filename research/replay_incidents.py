"""Replay the reviewed development ledger and write a reproducible diagnostic failure queue."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from evaluate import ROOT, evaluate

def replay(paths):
    suites = []
    for path in paths:
        raw = path.read_bytes()
        cases = json.loads(raw)["cases"]
        ids = [case["id"] for case in cases]
        if not cases or len(ids) != len(set(ids)):
            raise ValueError(f"Empty dataset or duplicate ID: {path.name}")
        result = evaluate(cases)
        suites.append({"dataset": path.name, "sha256": hashlib.sha256(raw).hexdigest(), **result})
    return suites

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    directory = ROOT / "research"
    reviewed, foundation, challenge = replay([directory / "incidents/reviewed.json",
                                               directory / "synthetic_cases.json", directory / "challenge_cases.json"])
    version = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    report = {"revision": version, "engine": "rules", "model_calls": 0, "suites": [reviewed, foundation, challenge]}
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    for suite in report["suites"]:
        print(f"{suite['dataset']}: {suite['exact_case_matches']}/{suite['scenarios']} exact")
    # The challenge suite is diagnostic. Human-reviewed cases and the foundation are gates.
    raise SystemExit(int(bool(reviewed["failures"] or foundation["failures"])))
