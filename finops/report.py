"""Report assembly — the lab's deliverable: baseline vs optimized + savings chart."""
from __future__ import annotations


def build_report(baseline_usd: float, optimized_usd: float, levers: dict,
                 sustainability: dict | None = None, period: str = "monthly",
                 reasoning=None, carbon_schedule=None,
                 inference_economics=None, baseline_composite=None) -> str:
    """Return a markdown cost-optimization report.

    `reasoning` (optional, Extension 4) is m2_inference_levers.run()["reasoning"].
    `carbon_schedule` (optional, Extension 5) is ext_carbon_aware_scheduling.run().
    `inference_economics` (optional) is m2_inference_levers.run()["inference_economics"]
    and `baseline_composite` (optional) describes how the monthly baseline splits
    across scopes. All are additive: when omitted the report is unchanged.
    """
    savings = baseline_usd - optimized_usd
    pct = (savings / baseline_usd * 100.0) if baseline_usd > 0 else 0.0
    lines = [
        "# NimbusAI — GPU Cost Optimization Report",
        "",
        f"**Period:** {period}  ",
        f"**Baseline spend:** ${baseline_usd:,.0f}  ",
        f"**Optimized spend:** ${optimized_usd:,.0f}  ",
        f"**Projected savings:** ${savings:,.0f}  (**{pct:.0f}%**)",
        "",
        "## Savings by lever",
        "",
        "| Lever | Savings (USD) |",
        "|---|---|",
    ]
    for name, amount in levers.items():
        lines.append(f"| {name} | ${amount:,.0f} |")
    if baseline_composite:
        bc = baseline_composite
        lines += [
            "",
            f"_Scope: the ${baseline_usd:,.0f} baseline spend above is a **composite** = "
            f"{bc['days']} x M2 inference baseline/day (= ${bc['inference_baseline_monthly']:,.0f}/month) "
            f"+ M3 purchasing workload monthly baseline (= ${bc['purchasing_baseline_monthly']:,.0f}/month). "
            f"The $/1M-token table below is **inference traffic only** (M2, one sample day) — a "
            f"different scope; the two totals are not directly comparable._",
        ]
    if inference_economics:
        lines += _inference_economics_section(inference_economics)
    if sustainability:
        lines += [
            "",
            "## Sustainability",
            "",
            f"- Energy per query: {sustainability.get('wh_per_query', 0):.2f} Wh",
            f"- Carbon per query: {sustainability.get('carbon_g', 0):.3f} gCO2e",
            f"- Cheapest+cleanest region: {sustainability.get('best_region', 'n/a')}",
        ]
    if reasoning:
        rb = reasoning
        nr_share = (1.0 - rb["reasoning_traffic_share"]) * 100
        lines += [
            "",
            "## Reasoning Budget",
            "",
            "_Extension 4 — reasoning traffic isolated as a governed cost + energy lever._",
            "",
            "| Segment | Requests | Traffic % | Tokens | Optimized $/day | Energy Wh/day |",
            "|---|---|---|---|---|---|",
            f"| Reasoning | {rb['reasoning_requests']:,} | {rb['reasoning_traffic_share']*100:.1f}% "
            f"| {rb['reasoning_tokens']:,} | ${rb['reasoning_cost_usd_day']:,.2f} | {rb['reasoning_energy_wh_day']:,.0f} |",
            f"| Non-reasoning | {rb['nonreasoning_requests']:,} | {nr_share:.1f}% "
            f"| {rb['nonreasoning_tokens']:,} | ${rb['nonreasoning_cost_usd_day']:,.2f} | {rb['nonreasoning_energy_wh_day']:,.0f} |",
            "",
            f"- From {rb['reasoning_traffic_share']*100:.1f}% of traffic, reasoning is "
            f"**{rb['reasoning_cost_share']*100:.1f}% of optimized inference cost** and "
            f"**{rb['reasoning_energy_share']*100:.1f}% of inference energy** "
            f"(reasoning energy multiplier x{rb['energy_multiplier']:.0f} via `sustainability.wh_per_query`).",
            f"- Primary cap ({rb['cap_frac']*100:.0f}% of traffic): keep <= "
            f"{rb['cap_max_reasoning_requests']:,} reasoning-mode requests, downgrade "
            f"{rb['cap_downgraded_requests']:,} -> save ${rb['cap_savings_usd_day']:,.2f}/day "
            f"(${rb['cap_savings_usd_month']:,.2f}/month), {rb['cap_savings_wh_day']:,.0f} Wh/day"
            + ("" if rb["cap_binding"] else
               f" _(non-binding: reasoning is {rb['reasoning_traffic_share']*100:.1f}%, already "
               f"<= {rb['cap_frac']*100:.0f}% budget)_") + ".",
            f"- Sensitivity scenario ({rb['sensitivity_cap_frac']*100:.0f}% of traffic — "
            f"illustrative only; the primary policy remains 10%): keep "
            f"{rb['sensitivity_kept_reasoning_requests']:,} reasoning-mode requests "
            f"(input_tokens >= {rb['sensitivity_routing_threshold_input_tokens']:,}), downgrade "
            f"{rb['sensitivity_downgraded_requests']:,} -> save "
            f"${rb['sensitivity_savings_usd_day']:,.2f}/day "
            f"(${rb['sensitivity_savings_usd_month']:,.2f}/month), "
            f"{rb['sensitivity_savings_wh_day']:,.0f} Wh/day"
            + ("" if rb["sensitivity_binding"] else " _(non-binding)_") + ".",
            f"- Theoretical ceiling (route every reasoning-mode request to normal mode): save "
            f"${rb['ceiling_savings_usd_day']:,.2f}/day (${rb['ceiling_savings_usd_month']:,.2f}/month), "
            f"{rb['ceiling_savings_wh_day']:,.0f} Wh/day.",
            f"- **Routing rule:** {rb['routing_rule']}",
            "",
            "### Assumptions",
            "",
        ]
        lines += [f"- {a}" for a in rb.get("assumptions", [])]
    if carbon_schedule:
        lines += _carbon_section(carbon_schedule)
    lines += ["", "_Figures are June-2026 as-of snapshots; re-baseline before acting._"]
    return "\n".join(lines)


def _fmt(value, spec, dash="n/a"):
    """Format `value` with `spec`, or return `dash` when value is None."""
    if value is None:
        return dash
    return format(value, spec)


def _inference_economics_section(ie):
    """Markdown lines for the 'Inference Unit Economics ($/1M-token)' section."""
    order = ie.get("sequential_order_label") or " -> ".join(ie["sequential_order"])
    lever_labels = ie.get("lever_labels", {})
    out = [
        "",
        "## Inference Unit Economics ($/1M-token)",
        "",
        f"_Inference traffic only (M2, one sample day). Sequential order: {order} — each "
        f"lever is measured on top of the previous one._",
        "",
        "| Stage | $/day | $/1M-token | Incremental savings $/day | Cumulative savings % |",
        "|---|---|---|---|---|",
    ]
    for s in ie["stages"]:
        out.append(
            f"| {s.get('label', s['name'])} | {s['usd_day']:,.4f} | {s['per_m']:,.4f} "
            f"| {s['incremental_savings_usd_day']:,.4f} | {s['cumulative_savings_pct']:,.2f}% |"
        )
    out += [
        "",
        "| Isolated lever (vs baseline) | $/day | $/1M-token | Savings vs baseline % |",
        "|---|---|---|---|",
    ]
    for s in ie["isolated"]:
        out.append(
            f"| {s.get('label', s['name'])} | {s['usd_day']:,.4f} | {s['per_m']:,.4f} "
            f"| {s['savings_pct_vs_baseline']:,.2f}% |"
        )
    lg = ie["largest_sequential_lever"]
    contrib = ie["sequential_contributions"]
    contrib_str = ", ".join(
        f"{lever_labels.get(k, k)} ${contrib[k]:,.4f}/day" for k in ie["sequential_order"]
    )
    out += [
        "",
        f"- Sequential per-lever contribution ({order}): {contrib_str}.",
        f"- Largest sequential lever (by max contribution): **{lg.get('label', lg['name'])}** "
        f"(${lg['usd_day']:,.4f}/day).",
        f"- Total sequential savings: ${ie['total_sequential_savings_usd_day']:,.4f}/day "
        f"(baseline minus the fully optimized scenario).",
        f"- {ie['note']}",
    ]
    return out


def _carbon_section(cs):
    """Markdown lines for the Extension 5 'Carbon-Aware Scheduling' section."""
    b = cs["baseline_region"]
    c = cs["cleanest_region"]
    out = [
        "",
        "## Carbon-Aware Scheduling",
        "",
        "_Extension 5 — relocate interruptible (training / batch) jobs to a cleaner grid region. "
        "The electricity delta is a modeled electricity cost only, not a GPU cloud-bill saving, "
        "and is excluded from the four levers and total_savings_pct above._",
        "",
        f"Interruptible jobs analyzed: {cs['interruptible_job_count']}  ·  "
        f"configured job-run energy: {cs['total_energy_kwh']:,.2f} kWh "
        f"(each job = its own hours_per_day x days, not a calendar month)",
        "",
        f"| Job | GPU | Energy kWh | Baseline gCO2e ({b}) | Cleanest gCO2e ({c}) "
        f"| Carbon saved gCO2e | Electricity delta USD |",
        "|---|---|---|---|---|---|---|",
    ]
    for j in cs["jobs"]:
        out.append(
            f"| {j['job_id']} | {j['gpu_type']} x{j['num_gpus']} | {j['energy_kwh']:,.2f} "
            f"| {j['baseline_carbon_gco2e']:,.1f} | {j['cleanest_carbon_gco2e']:,.1f} "
            f"| {j['carbon_saved_gco2e']:,.1f} | {j['electricity_cost_delta_usd']:+,.2f} |"
        )
    out += [
        "",
        "_Electricity delta sign: negative = the cleaner region also costs less modeled electricity._",
        "",
        "| Region | $/kWh | gCO2/kWh | Total energy kWh | Total electricity USD | Total carbon gCO2e |",
        "|---|---|---|---|---|---|",
    ]
    for x in cs["region_table"]:
        out.append(
            f"| {x['region']} | {_fmt(x['usd_per_kwh'], '.3f')} | {_fmt(x['gco2_per_kwh'], '.0f')} "
            f"| {x['total_energy_kwh']:,.2f} | {_fmt(x['total_electricity_usd'], ',.2f')} "
            f"| {_fmt(x['total_carbon_gco2e'], ',.1f')} |"
        )
    bvc = cs["baseline_vs_cleanest"]
    out += [
        "",
        f"**Baseline ({b}) vs cleanest ({c}):**",
        "",
        f"- Carbon: {_fmt(bvc['baseline_carbon_gco2e'], ',.1f')} -> "
        f"{_fmt(bvc['cleanest_carbon_gco2e'], ',.1f')} gCO2e "
        f"(saved {_fmt(bvc['carbon_saved_gco2e'], ',.1f')} gCO2e, "
        f"{_fmt(bvc['carbon_reduction_pct'], '.1f')}% reduction)",
        f"- Modeled electricity: ${_fmt(bvc['baseline_electricity_usd'], ',.2f')} -> "
        f"${_fmt(bvc['cleanest_electricity_usd'], ',.2f')} "
        f"(delta {_fmt(bvc['electricity_cost_delta_usd'], '+,.2f')} USD — modeled electricity, "
        f"not a cloud-bill saving)",
        "",
        f"- **Cheapest region** (min $/kWh): {cs['cheapest_region']}",
        f"- **Cleanest region** (min gCO2/kWh): {cs['cleanest_region']}",
        f"- **Balanced region** (equal-weight 50/50): {cs['balanced_region']}",
        "",
        "| Region | normalized_cost | normalized_carbon | balanced_score |",
        "|---|---|---|---|",
    ]
    for s in cs["balanced_scores"]:
        out.append(
            f"| {s['region']} | {s['normalized_cost']:.4f} | {s['normalized_carbon']:.4f} "
            f"| {s['balanced_score']:.4f} |"
        )
    out += [
        "",
        f"_Balanced formula:_ {cs['balanced_formula']}",
        "",
        f"**Latency trade-off:** {cs['latency_note']}",
        "",
        "### Carbon-Aware Scheduling — Assumptions",
        "",
    ]
    out += [f"- {a}" for a in cs.get("assumptions", [])]
    return out


def savings_waterfall(levers: dict, path: str) -> str:
    """Write a simple savings bar chart PNG. Returns the path. No-op if matplotlib absent."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return ""
    names = list(levers.keys())
    vals = [levers[n] for n in names]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.bar(names, vals, color="#2e548a")
    ax.set_ylabel("Savings (USD / month)")
    ax.set_title("GPU cost savings by FinOps lever")
    plt.xticks(rotation=20, ha="right")
    plt.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path
