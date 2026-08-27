"""Extension 5 — Carbon-Aware Scheduling.

Relocate interruptible (training / batch) workloads to a cleaner grid region and
report the carbon avoided plus the *modeled electricity-cost* delta.

The electricity delta here is NOT a GPU cloud-bill saving; it is only the modeled
cost of the electricity those jobs consume at each region's $/kWh. It is kept out
of the four M5 levers and out of total_savings_pct.

Region carbon intensity (gCO2/kWh) and electricity price ($/kWh) come straight
from finops.sustainability.REGION_CARBON / REGION_PRICE_KWH — nothing is hardcoded
or redefined here. The cleanest region is derived as min(REGION_CARBON).

All figures in the returned dict are full-precision floats; rounding happens only
when printing to the terminal or rendering Markdown.

Run: python missions/ext_carbon_aware_scheduling.py
"""
from __future__ import annotations
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

from missions._common import load_csv, num, catalog_by_type
from finops import sustainability

# The assignment's assumed starting point for interruptible jobs (Guide §10, E5).
BASELINE_REGION = "us-east-1"
# Equal-weight 50/50 blend of normalized cost and normalized carbon.
BALANCED_COST_WEIGHT = 0.5
BALANCED_CARBON_WEIGHT = 0.5


def _minmax_norm(value, lo, hi):
    """Min-max normalize `value` into [0, 1]; a degenerate range (hi == lo) -> 0.0."""
    if hi <= lo:
        return 0.0
    return (value - lo) / (hi - lo)


def _gpu_label(job_row):
    """Human-readable GPU column, e.g. 'H100 x8'."""
    return "{} x{}".format(job_row["gpu_type"], job_row["num_gpus"])


def _analyze_jobs():
    """Per-job carbon/electricity at the baseline region vs the cleanest region.

    Returns (job_rows, total_energy_kwh, cleanest_region). Dict values are kept as
    full-precision floats.
    """
    jobs = load_csv("workloads.csv")
    cat = catalog_by_type()
    cleanest = min(sustainability.REGION_CARBON, key=sustainability.REGION_CARBON.get)

    job_rows = []
    total_kwh = 0.0
    for j in jobs:
        if int(num(j["interruptible"])) != 1:
            continue
        gtype = j["gpu_type"]
        watts = num(cat[gtype]["watts"])
        ngpu = int(num(j["num_gpus"]))
        hpd = num(j["hours_per_day"])
        days = int(num(j["days"]))
        energy_kwh = watts * ngpu * hpd * days / 1000.0
        total_kwh += energy_kwh
        wh = energy_kwh * 1000.0

        base_carbon = sustainability.carbon_g(wh, BASELINE_REGION)
        clean_carbon = sustainability.carbon_g(wh, cleanest)
        base_cost = sustainability.energy_cost_usd(wh, BASELINE_REGION)
        clean_cost = sustainability.energy_cost_usd(wh, cleanest)

        job_rows.append({
            "job_id": j["job_id"],
            "gpu_type": gtype,
            "num_gpus": ngpu,
            "hours_per_day": hpd,
            "days": days,
            "watts": watts,
            "energy_kwh": energy_kwh,
            "baseline_region": BASELINE_REGION,
            "baseline_carbon_gco2e": base_carbon,
            "baseline_electricity_usd": base_cost,
            "cleanest_region": cleanest,
            "cleanest_carbon_gco2e": clean_carbon,
            "cleanest_electricity_usd": clean_cost,
            "carbon_saved_gco2e": base_carbon - clean_carbon,
            "electricity_cost_delta_usd": clean_cost - base_cost,
        })
    return job_rows, total_kwh, cleanest


def _region_table(total_kwh):
    """One row per region present in REGION_CARBON or REGION_PRICE_KWH (union).

    Totals are full-precision floats.
    """
    regions = sorted(set(sustainability.REGION_CARBON) | set(sustainability.REGION_PRICE_KWH))
    table = []
    for r in regions:
        price = sustainability.REGION_PRICE_KWH.get(r)          # $/kWh, from the module dict
        intensity = sustainability.REGION_CARBON.get(r)          # gCO2/kWh, from the module dict
        table.append({
            "region": r,
            "usd_per_kwh": price,
            "gco2_per_kwh": intensity,
            "total_energy_kwh": total_kwh,
            "total_electricity_usd": None if price is None else total_kwh * price,
            "total_carbon_gco2e": None if intensity is None else total_kwh * intensity,
        })
    return table


def _balanced(region_table):
    """Transparent 50/50 min-max blend of cost and carbon over the region table.

    Returns (balanced_region, scored_rows). Only regions with BOTH a price and a
    carbon intensity are scored. Normalization, the blended score, and the
    argmin selection all run on unrounded floats; ties break on region name.
    """
    both = [x for x in region_table
            if x["total_electricity_usd"] is not None and x["total_carbon_gco2e"] is not None]
    scored = []
    if not both:
        return None, scored

    costs = [x["total_electricity_usd"] for x in both]
    carbons = [x["total_carbon_gco2e"] for x in both]
    clo, chi = min(costs), max(costs)
    klo, khi = min(carbons), max(carbons)
    for x in both:
        nc = _minmax_norm(x["total_electricity_usd"], clo, chi)
        nk = _minmax_norm(x["total_carbon_gco2e"], klo, khi)
        scored.append({
            "region": x["region"],
            "normalized_cost": nc,
            "normalized_carbon": nk,
            "balanced_score": BALANCED_COST_WEIGHT * nc + BALANCED_CARBON_WEIGHT * nk,
        })
    best = min(scored, key=lambda s: (s["balanced_score"], s["region"]))
    return best["region"], scored


def _print(result):
    cs = result
    print("== Extension 5: Carbon-Aware Scheduling ==")
    print(f"interruptible jobs: {cs['interruptible_job_count']}   "
          f"configured job-run energy: {cs['total_energy_kwh']:,.2f} kWh "
          f"(each job = its own hours_per_day x days, not a calendar month)")
    print(f"baseline region: {cs['baseline_region']}   cleanest: {cs['cleanest_region']}   "
          f"cheapest: {cs['cheapest_region']}   balanced(50/50): {cs['balanced_region']}")
    print()
    print(f"{'job':18}{'gpu':10}{'kWh':>12}{'base gCO2e':>14}{'clean gCO2e':>14}"
          f"{'saved gCO2e':>14}{'elec delta $':>14}")
    for j in cs["jobs"]:
        print(f"{j['job_id']:18}{_gpu_label(j):10}{j['energy_kwh']:>12,.2f}"
              f"{j['baseline_carbon_gco2e']:>14,.1f}{j['cleanest_carbon_gco2e']:>14,.1f}"
              f"{j['carbon_saved_gco2e']:>14,.1f}{j['electricity_cost_delta_usd']:>14,.2f}")
    print()
    print(f"{'region':16}{'$/kWh':>9}{'gCO2/kWh':>11}{'kWh':>12}{'elec $':>12}{'carbon gCO2e':>16}")
    for x in cs["region_table"]:
        price = "n/a" if x["usd_per_kwh"] is None else f"{x['usd_per_kwh']:.3f}"
        inten = "n/a" if x["gco2_per_kwh"] is None else f"{x['gco2_per_kwh']:.0f}"
        cost = "n/a" if x["total_electricity_usd"] is None else f"{x['total_electricity_usd']:,.2f}"
        carb = "n/a" if x["total_carbon_gco2e"] is None else f"{x['total_carbon_gco2e']:,.1f}"
        print(f"{x['region']:16}{price:>9}{inten:>11}{x['total_energy_kwh']:>12,.2f}{cost:>12}{carb:>16}")
    print()
    bvc = cs["baseline_vs_cleanest"]
    print(f"baseline {bvc['baseline_region']} vs cleanest {bvc['cleanest_region']}:")
    print(f"  carbon:     {bvc['baseline_carbon_gco2e']:,.1f} -> {bvc['cleanest_carbon_gco2e']:,.1f} gCO2e"
          f"   (saved {bvc['carbon_saved_gco2e']:,.1f} gCO2e, {bvc['carbon_reduction_pct']:.1f}% reduction)")
    print(f"  modeled electricity: ${bvc['baseline_electricity_usd']:,.2f} -> "
          f"${bvc['cleanest_electricity_usd']:,.2f}   (delta {bvc['electricity_cost_delta_usd']:+,.2f} USD, "
          f"modeled electricity, not a cloud-bill saving)")
    print()
    print("balanced scores (lower = better):")
    for s in cs["balanced_scores"]:
        print(f"  {s['region']:16} norm_cost={s['normalized_cost']:.4f}  "
              f"norm_carbon={s['normalized_carbon']:.4f}  score={s['balanced_score']:.4f}")
    print(f"formula: {cs['balanced_formula']}")
    print()
    print(f"latency trade-off: {cs['latency_note']}")
    print()
    print("assumptions:")
    for a in cs["assumptions"]:
        print(f"  - {a}")


def run(verbose: bool = True) -> dict:
    job_rows, total_kwh, cleanest_region = _analyze_jobs()
    region_table = _region_table(total_kwh)
    cheapest_region = min(sustainability.REGION_PRICE_KWH, key=sustainability.REGION_PRICE_KWH.get)
    balanced_region, balanced_scores = _balanced(region_table)

    by_region = {x["region"]: x for x in region_table}
    base = by_region.get(BASELINE_REGION)
    clean = by_region.get(cleanest_region)

    baseline_carbon = base["total_carbon_gco2e"] if base else None
    cleanest_carbon = clean["total_carbon_gco2e"] if clean else None
    baseline_cost = base["total_electricity_usd"] if base else None
    cleanest_cost = clean["total_electricity_usd"] if clean else None

    carbon_saved = None
    carbon_reduction_pct = None
    if baseline_carbon is not None and cleanest_carbon is not None:
        carbon_saved = baseline_carbon - cleanest_carbon          # positive when carbon drops
        if baseline_carbon:
            carbon_reduction_pct = carbon_saved / baseline_carbon * 100.0
    cost_delta = None
    if baseline_cost is not None and cleanest_cost is not None:
        cost_delta = cleanest_cost - baseline_cost

    balanced_formula = (
        "balanced_score = {cw:.2f} * normalized_cost + {kw:.2f} * normalized_carbon, "
        "where normalized_x = (x - min_x) / (max_x - min_x) across the scored regions "
        "and a degenerate range (max == min) normalizes to 0.0. Equal-weight 50/50 choice; "
        "lower score is better."
    ).format(cw=BALANCED_COST_WEIGHT, kw=BALANCED_CARBON_WEIGHT)

    latency_note = (
        "The dataset carries no request latency and no user-location data, so this is a "
        "qualitative note only and no millisecond figures are invented. Relocating workloads "
        "to another region suits interruptible training / batch jobs, which tolerate distance "
        "and checkpoint-restart. It does NOT automatically apply to real-time inference, where "
        "user-perceived latency and data-residency usually pin the serving region."
    )

    assumptions = [
        "Only workloads with interruptible=1 are analyzed.",
        "energy_kwh = watts (price_catalog.csv) x num_gpus x hours_per_day x days / 1000; "
        "watts is the GPU board power held constant while running (no PUE, networking, "
        "storage or idle overhead modeled).",
        "Region carbon intensity (gCO2/kWh) and electricity price ($/kWh) are read from "
        "finops.sustainability.REGION_CARBON / REGION_PRICE_KWH; none are redefined here.",
        "Baseline region is {} (the assignment's assumed starting point); the cleanest "
        "region is derived as min(REGION_CARBON).".format(BASELINE_REGION),
        "The electricity-cost delta is a MODELED electricity cost only. It is NOT a GPU "
        "cloud-bill saving and is excluded from the four M5 levers and total_savings_pct.",
        "balanced_score uses transparent min-max normalization with equal 50/50 weights; "
        "max == min normalizes to 0.0.",
        "Each job's energy covers its own configured run (hours_per_day x days), not a "
        "uniform calendar month.",
    ]

    result = {
        "baseline_region": BASELINE_REGION,
        "cleanest_region": cleanest_region,
        "cheapest_region": cheapest_region,
        "balanced_region": balanced_region,
        "interruptible_job_count": len(job_rows),
        "total_energy_kwh": total_kwh,
        "jobs": job_rows,
        "region_table": region_table,
        "balanced_scores": balanced_scores,
        "balanced_weights": {"cost": BALANCED_COST_WEIGHT, "carbon": BALANCED_CARBON_WEIGHT},
        "balanced_formula": balanced_formula,
        "baseline_vs_cleanest": {
            "baseline_region": BASELINE_REGION,
            "cleanest_region": cleanest_region,
            "baseline_carbon_gco2e": baseline_carbon,
            "cleanest_carbon_gco2e": cleanest_carbon,
            "carbon_saved_gco2e": carbon_saved,
            "carbon_reduction_pct": carbon_reduction_pct,
            "baseline_electricity_usd": baseline_cost,
            "cleanest_electricity_usd": cleanest_cost,
            "electricity_cost_delta_usd": cost_delta,
        },
        "latency_note": latency_note,
        "assumptions": assumptions,
    }

    if verbose:
        _print(result)
    return result


if __name__ == "__main__":
    run()
