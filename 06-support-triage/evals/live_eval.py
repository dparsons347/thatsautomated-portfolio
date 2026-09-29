"""Run the ten canned emails through the real model (and HubSpot, if configured).

    docker compose exec triage-api python evals/live_eval.py [--threshold 0.85]

Each run is traced to LangSmith when tracing is on, tagged "eval". Prints one line per email
and exits 1 if any category or route differs from test-data/emails.py.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "test-data")]

from app import llm  # noqa: E402
from app.config import Settings  # noqa: E402
from app.graph import build_graph  # noqa: E402
from app.hubspot import HubSpotLookup, NoCrm  # noqa: E402
from emails import EMAILS  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=float, default=None)
    ap.add_argument("--only", default="", help="comma separated keys")
    args = ap.parse_args()
    s = Settings.from_env()
    t = args.threshold if args.threshold is not None else s.confidence_threshold
    crm = HubSpotLookup(s.hubspot_token, s.hubspot_portal_id) if s.hubspot_token else NoCrm()
    g = build_graph(crm=crm, classifier=llm.classifier(s), drafter=llm.drafter(s), booking_url=s.booking_url)
    only = {k for k in args.only.split(",") if k}
    misses = 0
    print(f"model={s.claude_model} threshold={t:.2f} crm={'hubspot' if s.hubspot_token else 'none'}\n")
    print(f"{'email':22} {'category':16} {'conf':>5}  {'route':8} {'expected':28} ok")
    for e in EMAILS:
        if only and e["key"] not in only:
            continue
        out = g.invoke({
            "message_id": f"eval-{e['key']}", "thread_id": f"eval-{e['key']}",
            "from_email": e["from_email"], "from_name": e["from_name"], "subject": e["subject"],
            "body": e["body"], "thread_history": e.get("history", []),
            "prior_category": e.get("prior_category"), "threshold": t,
        }, config={"run_name": "support-triage", "tags": ["p6", "eval"], "metadata": {"email": e["key"]}})
        c = out["classification"]
        exp = e["expect"]
        ok = c["category"] in exp["category"].split("|") and out["route"] == exp["route"]
        misses += 0 if ok else 1
        print(f"{e['key']:22} {c['category']:16} {c['confidence']:5.2f}  {out['route']:8} "
              f"{exp['category'] + '/' + exp['route']:28} {'yes' if ok else 'NO'}")
        if not ok or out.get("gate_reasons"):
            print(f"{'':24}reason: {c['reason']}")
            for r in out.get("gate_reasons") or []:
                print(f"{'':24}gate: {r}")
    print(f"\n{misses} mismatch(es)")
    return 1 if misses else 0


if __name__ == "__main__":
    sys.exit(main())
