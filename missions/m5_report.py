"""M5 — Optimization Report: combine M1-M4 into baseline-vs-optimized (deck §1/§11).

Run: python missions/m5_report.py   ->  outputs/report.md + outputs/savings.png
"""
from __future__ import annotations
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os
from missions._common import num, catalog_by_type, ROOT
from finops import report, sustainability
from missions import (m1_efficiency_audit, m2_inference_levers, m3_purchasing, m4_allocation,
                      ext_carbon_aware_scheduling)

DAYS = 30
# one tier down for over-provisioned ("util-lie") GPUs
RIGHTSIZE_MAP = {"H100": "A100", "H200": "H100", "A100": "A10G", "A10G": "L4", "L4": "L4"}


def run(verbose: bool = True) -> dict:
    r1 = m1_efficiency_audit.run(verbose=False)
    r2 = m2_inference_levers.run(verbose=False)
    r3 = m3_purchasing.run(verbose=False)
    r4 = m4_allocation.run(verbose=False)  # for the C.2 findings section (tag coverage / chargeback)
    r_carbon = ext_carbon_aware_scheduling.run(verbose=False)  # Extension 5 (additive, not a lever)
    cat = catalog_by_type()

    # --- buckets ---
    infer_savings = (r2["baseline_daily"] - r2["optimized_daily"]) * DAYS
    purchasing_savings = r3["on_demand_monthly"] - r3["optimized_monthly"]

    idle_savings = r1["idle_waste_daily"] * DAYS
    rightsize_savings = 0.0
    for lie in r1["lies"]:
        cur = lie["gpu_type"]
        tgt = RIGHTSIZE_MAP.get(cur, cur)
        delta = num(cat[cur]["on_demand_hr"]) - num(cat[tgt]["on_demand_hr"])
        rightsize_savings += max(0.0, delta) * 24 * DAYS

    levers = {
        "Inference (cascade/cache/batch)": round(infer_savings),
        "Purchasing (spot/reserved)": round(purchasing_savings),
        "Right-size util-lies": round(rightsize_savings),
        "Kill idle GPUs": round(idle_savings),
    }
    baseline = r2["baseline_daily"] * DAYS + r3["on_demand_monthly"]
    optimized = baseline - sum(levers.values())
    total_pct = sum(levers.values()) / baseline * 100 if baseline else 0.0

    # --- sustainability snapshot ---
    median_tokens = 800
    wh = sustainability.wh_per_query(median_tokens)
    sust = {
        "wh_per_query": wh,
        "carbon_g": sustainability.carbon_g(wh, "us-east-1"),
        "best_region": min(sustainability.REGION_CARBON, key=sustainability.REGION_CARBON.get),
    }

    # Scope note for the report: the monthly baseline is a composite of two scopes.
    baseline_composite = {
        "inference_baseline_monthly": r2["baseline_daily"] * DAYS,
        "purchasing_baseline_monthly": r3["on_demand_monthly"],
        "days": DAYS,
    }

    # C.2 findings section — all values sourced from r1/r3/r4/levers (nothing hardcoded).
    findings = {
        "util_lies": [
            {"gpu_id": l["gpu_id"], "gpu_type": l["gpu_type"],
             "gpu_util_pct": l["gpu_util_pct"], "mfu": l["mfu"], "mbu": l.get("mbu")}
            for l in r1["lies"]
        ],
        "idle_gpus": [
            {"gpu_id": s["gpu_id"], "gpu_type": s["gpu_type"], "idle_hours": s["idle_hours"]}
            for s in r1["summary"] if s["idle_hours"] > 0
        ],
        "idle_waste_daily": r1["idle_waste_daily"],
        "purchasing_baseline_monthly": r3["on_demand_monthly"],
        "purchasing_savings_pct": r3["savings_pct"],
        "tag_coverage": r4["tag_coverage"],
        "chargeback_ready": r4["chargeback_ready"],
    }

    md = report.build_report(baseline, optimized, levers, sustainability=sust,
                             reasoning=r2.get("reasoning"),
                             carbon_schedule=r_carbon,
                             inference_economics=r2.get("inference_economics"),
                             baseline_composite=baseline_composite,
                             findings=findings)
    out_md = os.path.join(ROOT, "outputs", "report.md")
    os.makedirs(os.path.dirname(out_md), exist_ok=True)
    with open(out_md, "w") as f:
        f.write(md)
    png = report.savings_waterfall(levers, os.path.join(ROOT, "outputs", "savings.png"))

    if verbose:
        print("== M5 Optimization Report ==")
        print(md)
        print(f"\nWritten: outputs/report.md" + (f" + outputs/savings.png" if png else " (matplotlib absent: PNG skipped)"))

    return {"baseline_monthly": round(baseline), "optimized_monthly": round(optimized),
            "levers": levers, "total_savings_pct": round(total_pct, 1),
            "reasoning": r2.get("reasoning"),
            "carbon_schedule": r_carbon,
            "inference_economics": r2.get("inference_economics"),
            "findings": findings}


if __name__ == "__main__":
    run()
