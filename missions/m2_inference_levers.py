"""M2 — Inference Cost Levers: $/1M-token, batch x cache x cascade (deck §7).

Run: python missions/m2_inference_levers.py
"""
from __future__ import annotations
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from missions._common import load_csv, num
from finops import pricing, sustainability
import statistics

# $/1M tokens (input, output) — illustrative 2026.
MODEL_PRICES = {"small": (0.20, 0.40), "large": (3.00, 15.00)}

# --- Extension 4: Reasoning Budget ---------------------------------------------
DAYS = 30                 # month projection (matches missions/m5_report.py)
REASONING_CAP_FRAC = 0.10             # primary policy under test: keep reasoning <= 10% of traffic
REASONING_SENSITIVITY_CAP_FRAC = 0.05  # illustrative sensitivity scenario only; primary policy stays 10%


def _median(values):
    """Deterministic median of a list of numbers (0.0 for an empty list)."""
    return float(statistics.median(values)) if values else 0.0


def _normal_output_estimator(rows):
    """Build a deterministic estimator of the *normal* (non-reasoning) output-token
    count a request would have produced.

    Priority: median output_tokens over non-reasoning rows with the same
    (team, route_tier); fallback: same route_tier; fallback: global non-reasoning
    median. Returns a closure `estimate(team, route_tier) -> (tokens, source)`.
    """
    by_team_tier = {}
    by_tier = {}
    glob = []
    for r in rows:
        if int(num(r["is_reasoning"])) != 0:
            continue
        o = int(num(r["output_tokens"]))
        by_team_tier.setdefault((r["team"], r["route_tier"]), []).append(o)
        by_tier.setdefault(r["route_tier"], []).append(o)
        glob.append(o)
    glob_med = _median(glob)

    def estimate(team, route_tier):
        if by_team_tier.get((team, route_tier)):
            return _median(by_team_tier[(team, route_tier)]), "team+route_tier"
        if by_tier.get(route_tier):
            return _median(by_tier[route_tier]), "route_tier"
        return glob_med, "global"

    return estimate


def _simulate_reasoning_cap(rows, cap_frac, estimator):
    """Downgrade the least-complex reasoning requests until reasoning traffic is
    <= cap_frac of total traffic. Complexity proxy = input_tokens (deterministic).

    Downgrading keeps input_tokens / cached_input_tokens / route_tier / is_batch;
    only output_tokens is swapped for the estimate and the reasoning energy multiplier
    (x REASONING_ENERGY_MULTIPLIER) is dropped. Returns $/Wh saved and the routing
    threshold (smallest input_tokens still served as reasoning).
    """
    total = len(rows)
    reasoning = [r for r in rows if int(num(r["is_reasoning"])) == 1]
    max_keep = int(cap_frac * total)  # floor
    ranked = sorted(
        list(enumerate(reasoning)),
        key=lambda p: (-int(num(p[1]["input_tokens"])), p[1]["ts"], p[0]),
    )
    kept = [p[1] for p in ranked[:max_keep]]
    downgraded = [p[1] for p in ranked[max_keep:]]

    if kept:
        threshold = min(int(num(r["input_tokens"])) for r in kept)
    elif reasoning:
        threshold = max(int(num(r["input_tokens"])) for r in reasoning) + 1
    else:
        threshold = 0

    save_cost = 0.0
    save_wh = 0.0
    fallbacks = {}
    for r in downgraded:
        inp = int(num(r["input_tokens"]))
        out = int(num(r["output_tokens"]))
        cached = int(num(r["cached_input_tokens"]))
        is_batch = bool(int(num(r["is_batch"])))
        pin, pout = MODEL_PRICES[r["route_tier"]]
        cur_cost = pricing.request_cost(inp, out, pin, pout, cached_in=cached, batch=is_batch)
        est_out, src = estimator(r["team"], r["route_tier"])
        est_out = int(round(est_out))
        new_cost = pricing.request_cost(inp, est_out, pin, pout, cached_in=cached, batch=is_batch)
        cur_wh = sustainability.wh_per_query(inp + out, is_reasoning=True)
        new_wh = sustainability.wh_per_query(inp + est_out, is_reasoning=False)
        save_cost += cur_cost - new_cost
        save_wh += cur_wh - new_wh
        fallbacks[src] = fallbacks.get(src, 0) + 1

    return {
        "cap_frac": cap_frac,
        "max_reasoning_requests": max_keep,
        "downgraded_requests": len(downgraded),
        "binding": len(downgraded) > 0,
        "routing_threshold_input_tokens": threshold,
        "savings_usd_day": save_cost,
        "savings_usd_month": save_cost * DAYS,
        "savings_wh_day": save_wh,
        "estimator_fallbacks": fallbacks,
    }


def _reasoning_budget(rows, split):
    """Assemble the Extension-4 report dict from per-segment tallies gathered in run().

    `split` keys: r_n, nr_n, r_tok, nr_tok, r_cost, nr_cost, r_wh, nr_wh.
    All money uses pricing.request_cost; all energy uses sustainability.wh_per_query
    (the x REASONING_ENERGY_MULTIPLIER factor applies to ENERGY only, never to $).
    """
    total_req = split["r_n"] + split["nr_n"]
    total_cost = split["r_cost"] + split["nr_cost"]
    total_wh = split["r_wh"] + split["nr_wh"]
    total_tok = split["r_tok"] + split["nr_tok"]

    estimator = _normal_output_estimator(rows)
    cap = _simulate_reasoning_cap(rows, REASONING_CAP_FRAC, estimator)
    sensitivity = _simulate_reasoning_cap(rows, REASONING_SENSITIVITY_CAP_FRAC, estimator)
    ceiling = _simulate_reasoning_cap(rows, 0.0, estimator)  # route every reasoning req to normal mode

    traffic_share = (split["r_n"] / total_req) if total_req else 0.0
    thr = cap["routing_threshold_input_tokens"]
    proxy_note = ("input_tokens is only a complexity PROXY in this simulation, "
                  "not a real difficulty signal")
    if cap["binding"]:
        rule = ("Serve a request in reasoning mode only if input_tokens >= {t} "
                "(threshold derived from data so reasoning stays <= {p:.0f}% of traffic). "
                "{note}.").format(t=thr, p=REASONING_CAP_FRAC * 100, note=proxy_note)
    else:
        rule = ("Reasoning is {s:.1f}% of traffic, below the {p:.0f}% budget, so no request "
                "needs to be cut right now (input_tokens >= {t} here is only the minimum "
                "observed while the cap is non-binding, not a policy threshold). Rule: monitor "
                "the reasoning share; if it is forecast to reach or exceed {p:.0f}%, rank the "
                "reasoning candidates by input_tokens descending with a deterministic tie-break "
                "(ts, then original order), keep at most floor({p:.0f}% x total_requests), and "
                "recompute the threshold from that batch. {note}."
                ).format(s=traffic_share * 100, p=REASONING_CAP_FRAC * 100, t=thr, note=proxy_note)

    return {
        "total_requests": total_req,
        "reasoning_requests": split["r_n"],
        "nonreasoning_requests": split["nr_n"],
        "reasoning_traffic_share": traffic_share,
        "reasoning_tokens": split["r_tok"],
        "nonreasoning_tokens": split["nr_tok"],
        "reasoning_token_share": (split["r_tok"] / total_tok) if total_tok else 0.0,
        "reasoning_cost_usd_day": round(split["r_cost"], 4),
        "nonreasoning_cost_usd_day": round(split["nr_cost"], 4),
        "reasoning_cost_share": (split["r_cost"] / total_cost) if total_cost else 0.0,
        "reasoning_energy_wh_day": round(split["r_wh"], 2),
        "nonreasoning_energy_wh_day": round(split["nr_wh"], 2),
        "reasoning_energy_share": (split["r_wh"] / total_wh) if total_wh else 0.0,
        "energy_multiplier": sustainability.REASONING_ENERGY_MULTIPLIER,
        "cap_frac": REASONING_CAP_FRAC,
        "cap_max_reasoning_requests": cap["max_reasoning_requests"],
        "cap_downgraded_requests": cap["downgraded_requests"],
        "cap_binding": cap["binding"],
        "cap_routing_threshold_input_tokens": cap["routing_threshold_input_tokens"],
        "cap_savings_usd_day": round(cap["savings_usd_day"], 4),
        "cap_savings_usd_month": round(cap["savings_usd_month"], 2),
        "cap_savings_wh_day": round(cap["savings_wh_day"], 1),
        "cap_estimator_fallbacks": cap["estimator_fallbacks"],
        "sensitivity_note": "illustrative sensitivity scenario only; the primary policy remains 10%",
        "sensitivity_cap_frac": REASONING_SENSITIVITY_CAP_FRAC,
        "sensitivity_max_reasoning_requests": sensitivity["max_reasoning_requests"],
        "sensitivity_kept_reasoning_requests": split["r_n"] - sensitivity["downgraded_requests"],
        "sensitivity_downgraded_requests": sensitivity["downgraded_requests"],
        "sensitivity_binding": sensitivity["binding"],
        "sensitivity_routing_threshold_input_tokens": sensitivity["routing_threshold_input_tokens"],
        "sensitivity_savings_usd_day": round(sensitivity["savings_usd_day"], 4),
        "sensitivity_savings_usd_month": round(sensitivity["savings_usd_month"], 2),
        "sensitivity_savings_wh_day": round(sensitivity["savings_wh_day"], 1),
        "sensitivity_estimator_fallbacks": sensitivity["estimator_fallbacks"],
        "ceiling_downgraded_requests": ceiling["downgraded_requests"],
        "ceiling_savings_usd_day": round(ceiling["savings_usd_day"], 4),
        "ceiling_savings_usd_month": round(ceiling["savings_usd_month"], 2),
        "ceiling_savings_wh_day": round(ceiling["savings_wh_day"], 1),
        "ceiling_estimator_fallbacks": ceiling["estimator_fallbacks"],
        "routing_rule": rule,
        "assumptions": [
            proxy_note + ".",
            "Downgrading a reasoning-mode request keeps input_tokens, cached_input_tokens, "
            "route_tier and is_batch; only output_tokens is replaced by an estimate and "
            "the x{:.0f} reasoning energy factor is removed.".format(
                sustainability.REASONING_ENERGY_MULTIPLIER),
            "Estimated normal output_tokens = median output_tokens of non-reasoning requests "
            "with the same (team, route_tier); fallback order: same route_tier; then the "
            "global non-reasoning median.",
            "Money uses pricing.request_cost with MODEL_PRICES by route_tier; the "
            "x{:.0f} reasoning factor applies to ENERGY only "
            "(sustainability.wh_per_query).".format(sustainability.REASONING_ENERGY_MULTIPLIER),
            "Energy per request uses sustainability.wh_per_query(input_tokens + output_tokens); "
            "the simulation does NOT separately model any energy saved by cached input.",
            "Month = {} days (matches M5); the dataset is a single sample day.".format(DAYS),
            "Primary cap keeps floor({:.2f} x total_requests) reasoning-mode requests; "
            "the {:.0f}% row is an illustrative sensitivity scenario only, the primary "
            "policy remains 10%.".format(
                REASONING_CAP_FRAC, REASONING_SENSITIVITY_CAP_FRAC * 100),
        ],
    }


def run(verbose: bool = True) -> dict:
    rows = load_csv("token_usage.csv")
    base_cost = opt_cost = 0.0
    total_tokens = 0
    # Extension 4: reasoning vs non-reasoning tallies (does not affect the figures above)
    r_n = nr_n = 0
    r_tok = nr_tok = 0
    r_cost = nr_cost = 0.0
    r_wh = nr_wh = 0.0
    for r in rows:
        inp, out = int(num(r["input_tokens"])), int(num(r["output_tokens"]))
        cached = int(num(r["cached_input_tokens"]))
        is_batch = bool(int(num(r["is_batch"])))
        is_reasoning = bool(int(num(r["is_reasoning"])))
        total_tokens += inp + out
        # BASELINE: naive deployment — everything on the large model, no cache, no batch
        lin, lout = MODEL_PRICES["large"]
        base_cost += pricing.request_cost(inp, out, lin, lout)
        # OPTIMIZED: cascade (route_tier), prompt caching, batch API
        pin, pout = MODEL_PRICES[r["route_tier"]]
        opt_req = pricing.request_cost(inp, out, pin, pout, cached_in=cached, batch=is_batch)
        opt_cost += opt_req
        # Extension 4: attribute the optimized cost + energy to the reasoning segment
        wh = sustainability.wh_per_query(inp + out, is_reasoning=is_reasoning)
        if is_reasoning:
            r_n += 1
            r_tok += inp + out
            r_cost += opt_req
            r_wh += wh
        else:
            nr_n += 1
            nr_tok += inp + out
            nr_cost += opt_req
            nr_wh += wh

    base_pm = pricing.dollars_per_million(base_cost, total_tokens)
    opt_pm = pricing.dollars_per_million(opt_cost, total_tokens)
    savings_pct = (1 - opt_cost / base_cost) * 100 if base_cost else 0.0

    reasoning = _reasoning_budget(rows, {
        "r_n": r_n, "nr_n": nr_n, "r_tok": r_tok, "nr_tok": nr_tok,
        "r_cost": r_cost, "nr_cost": nr_cost, "r_wh": r_wh, "nr_wh": nr_wh,
    })

    if verbose:
        print("== M2 Inference Cost Levers ==")
        print(f"requests={len(rows)}  tokens={total_tokens:,}")
        print(f"baseline  : ${base_cost:,.2f}/day   ${base_pm:.3f}/1M-token")
        print(f"optimized : ${opt_cost:,.2f}/day   ${opt_pm:.3f}/1M-token")
        print(f"savings   : {savings_pct:.1f}%  (cascade + caching + batch)")
        print(f"discount stack (batch + 100% cache): {pricing.discount_stack(batch=True, cache_hit_frac=1.0):.3f} of naive")

        rb = reasoning
        print()
        print("-- Extension 4: Reasoning Budget --")
        print(f"reasoning traffic : {rb['reasoning_requests']}/{rb['total_requests']} req "
              f"({rb['reasoning_traffic_share']*100:.1f}%)  |  cost share {rb['reasoning_cost_share']*100:.1f}%"
              f"  |  energy share {rb['reasoning_energy_share']*100:.1f}%")
        print(f"reasoning / day   : ${rb['reasoning_cost_usd_day']:.2f}   {rb['reasoning_energy_wh_day']:,.0f} Wh"
              f"   (reasoning energy multiplier x{rb['energy_multiplier']:.0f} vs normal)")
        print(f"non-reasoning /day: ${rb['nonreasoning_cost_usd_day']:.2f}   {rb['nonreasoning_energy_wh_day']:,.0f} Wh")
        print(f"cap {rb['cap_frac']*100:.0f}% traffic (primary policy): keep <= {rb['cap_max_reasoning_requests']} req, "
              f"downgrade {rb['cap_downgraded_requests']} -> save ${rb['cap_savings_usd_day']:.2f}/day "
              f"${rb['cap_savings_usd_month']:.2f}/mo {rb['cap_savings_wh_day']:,.0f} Wh/day"
              + ("" if rb['cap_binding'] else
                 f"   [non-binding: reasoning already {rb['reasoning_traffic_share']*100:.1f}%"
                 f" <= {rb['cap_frac']*100:.0f}%]"))
        print(f"sensitivity {rb['sensitivity_cap_frac']*100:.0f}% (illustrative only; primary policy stays 10%): "
              f"keep {rb['sensitivity_kept_reasoning_requests']}, downgrade {rb['sensitivity_downgraded_requests']} "
              f"(input_tokens >= {rb['sensitivity_routing_threshold_input_tokens']}) -> save "
              f"${rb['sensitivity_savings_usd_day']:.2f}/day ${rb['sensitivity_savings_usd_month']:.2f}/mo "
              f"{rb['sensitivity_savings_wh_day']:,.0f} Wh/day"
              + ("" if rb['sensitivity_binding'] else "   [non-binding]"))
        print(f"ceiling (all reasoning -> normal mode): save ${rb['ceiling_savings_usd_day']:.2f}/day "
              f"${rb['ceiling_savings_usd_month']:.2f}/mo {rb['ceiling_savings_wh_day']:,.0f} Wh/day")
        print(f"routing rule      : {rb['routing_rule']}")

    return {
        "baseline_daily": round(base_cost, 2), "optimized_daily": round(opt_cost, 2),
        "baseline_per_m": round(base_pm, 3), "optimized_per_m": round(opt_pm, 3),
        "savings_pct": round(savings_pct, 1), "total_tokens": total_tokens,
        "reasoning": reasoning,
    }


if __name__ == "__main__":
    run()
