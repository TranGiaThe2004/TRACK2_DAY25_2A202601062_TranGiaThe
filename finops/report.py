"""Report assembly — the lab's deliverable: baseline vs optimized + savings chart."""
from __future__ import annotations


def build_report(baseline_usd: float, optimized_usd: float, levers: dict,
                 sustainability: dict | None = None, period: str = "monthly",
                 reasoning=None, carbon_schedule=None,
                 inference_economics=None, baseline_composite=None,
                 findings=None) -> str:
    """Return a markdown cost-optimization report.

    `reasoning` (optional, Extension 4) is m2_inference_levers.run()["reasoning"].
    `carbon_schedule` (optional, Extension 5) is ext_carbon_aware_scheduling.run().
    `inference_economics` (optional) is m2_inference_levers.run()["inference_economics"],
    `baseline_composite` (optional) describes how the monthly baseline splits across
    scopes, and `findings` (optional) drives the qualitative "Findings and Prioritized
    Actions" section. All are additive: when omitted the report is unchanged.
    """
    savings = baseline_usd - optimized_usd
    pct = (savings / baseline_usd * 100.0) if baseline_usd > 0 else 0.0
    lines = [
        "# NimbusAI — GPU Cost Optimization Report",
        "",
        f"- **Period:** {period}",
        f"- **Baseline spend:** ${baseline_usd:,.0f}",
        f"- **Optimized spend:** ${optimized_usd:,.0f}",
        f"- **Projected savings:** ${savings:,.0f} (**{pct:.0f}%**)",
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
    if findings:
        lines += _findings_section(levers, findings, inference_economics, carbon_schedule)
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


def _findings_section(levers, findings, inference_economics=None, carbon_schedule=None):
    """Qualitative C.2 analysis: the GPU-Util lie, prioritized actions, sustainability.

    The numeric results are derived from mission outputs: the `levers` dict plus the
    `findings` payload built by m5_report (M1 lies + idle GPUs, M3 purchasing baseline,
    M4 tag coverage) and the already-passed inference_economics / carbon_schedule dicts.
    """
    lies = findings.get("util_lies", [])
    idle_gpus = findings.get("idle_gpus", [])
    rs_lever = levers.get("Right-size util-lies")
    idle_lever = levers.get("Kill idle GPUs")

    out = ["", "## Findings and Prioritized Actions", "", "### 1. The GPU-Util lie", ""]
    if lies:
        names = ", ".join("`%s`" % l["gpu_id"] for l in lies)
        out += [
            f"M1 flags {names}: high GPU-Util but low MFU.",
            "",
            "| GPU | Type | GPU-Util % | MFU | MBU |",
            "|---|---|---|---|---|",
        ]
        for l in lies:
            out.append(
                f"| {l['gpu_id']} | {l['gpu_type']} | {l['gpu_util_pct']:.1f}% "
                f"| {l['mfu']:.3f} | {_fmt(l.get('mbu'), '.3f')} |"
            )
        out += [
            "",
            "A high GPU-Util only means kernel execution was active during many sampling "
            "intervals. It says nothing about how much of the chip's theoretical FLOP "
            "capacity those kernels used. A low MFU means the useful FLOPs delivered were "
            "a small fraction of peak, so the full GPU-hour is paid for a fraction of the "
            "rented compute.",
            "",
            "Plausible causes include memory-bandwidth stalls, kernel-launch overhead, "
            "batch sizes too small to fill the tensor cores, and pipeline bubbles waiting "
            "on data or I/O. The current telemetry (util, achieved TFLOPs, achieved "
            "bandwidth) is not enough to prove which cause dominates on each GPU; that "
            "needs per-kernel profiling. These stay hypotheses, not conclusions.",
            "",
        ]
    if rs_lever is not None:
        out.append(
            f"- Financial impact: right-sizing the util-lie GPUs one tier down is modeled at "
            f"about ${rs_lever:,.0f}/month (M5 \"Right-size util-lies\" lever)."
        )
    if idle_gpus and idle_lever is not None:
        idle_names = ", ".join("`%s` (%dh)" % (g["gpu_id"], g["idle_hours"]) for g in idle_gpus)
        out.append(
            f"- A util-lie is not the same as a fully idle GPU: {idle_names} runs below 10% "
            f"utilization overnight and simply wastes about "
            f"${findings.get('idle_waste_daily', 0):,.0f}/day = ${idle_lever:,.0f}/month "
            f"(M5 \"Kill idle GPUs\" lever). That GPU is idle, not mis-reporting efficiency."
        )

    # --- 2. Prioritized actions ---
    ranked = sorted(levers.items(), key=lambda kv: kv[1], reverse=True)
    out += [
        "",
        "### 2. Prioritized actions (by modeled monthly impact)",
        "",
        "| Rank | Lever | Modeled savings (USD/month) |",
        "|---|---|---|",
    ]
    for i, (name, amount) in enumerate(ranked, start=1):
        out.append(f"| {i} | {name} | ${amount:,.0f} |")

    pbm = findings.get("purchasing_baseline_monthly")
    psp = findings.get("purchasing_savings_pct")
    purchasing_key = "Purchasing (spot/reserved)"
    purchasing_rank = next((i for i, (n, _) in enumerate(ranked, start=1) if n == purchasing_key), None)
    if pbm is not None and psp is not None and purchasing_rank is not None:
        tier_rule = ("spot for interruptible jobs, reserved for steady high-duty-cycle workloads "
                     "above the computed break-even, on-demand otherwise")
        if purchasing_rank == 1:
            out += [
                "",
                f"**{purchasing_key}** ranks first on modeled dollar impact: it applies to the "
                f"whole workload fleet (M3 on-demand baseline ${pbm:,.0f}/month), and matching "
                f"each job to its tier ({tier_rule}) removes about {psp:.1f}% of it.",
            ]
        else:
            out += [
                "",
                f"{purchasing_key} ranks #{purchasing_rank} here, but it still spans the whole "
                f"workload fleet (M3 on-demand baseline ${pbm:,.0f}/month), and tier matching "
                f"({tier_rule}) removes about {psp:.1f}% of it.",
            ]
    if inference_economics:
        ie = inference_economics
        lg = ie["largest_sequential_lever"]
        contrib = ie["sequential_contributions"]
        labels = ie.get("lever_labels", {})
        order = ie.get("sequential_order_label") or " -> ".join(ie["sequential_order"])
        contrib_str = ", ".join(
            f"{labels.get(k, k)} ${contrib[k]:,.4f}/day" for k in ie["sequential_order"]
        )
        out += [
            "",
            f"Within inference, the largest sequential contribution in the order {order} is "
            f"**{lg.get('label', lg['name'])}** (about ${lg['usd_day']:,.4f}/day): {contrib_str}. "
            f"These contributions are order-dependent, and the isolated single-lever savings "
            f"percentages overlap, so they cannot be added together.",
        ]
    out += [
        "",
        "First three actions for NimbusAI:",
        "",
        "1. **Purchasing policy.** Match every workload to spot / reserved / on-demand by its "
        "interruptibility and duty cycle, and checkpoint interruptible jobs so spot reclaims "
        "cost little rework.",
        "2. **Inference model routing.** Ship the cascade (route easy traffic to the small "
        "model) first, then layer prompt caching and the Batch API onto the traffic types "
        "that tolerate them.",
        "3. **Efficiency controls.** Right-size the util-lie GPUs one tier down and auto-stop "
        "idle GPUs, with utilization/MFU monitoring and a rollback path if quality or "
        "throughput regresses.",
    ]
    tc = findings.get("tag_coverage")
    if tc is not None:
        gate = ("the chargeback gate is open" if findings.get("chargeback_ready")
                else "the chargeback gate is not yet open")
        out += [
            "",
            f"Cost accountability: M4 tag coverage is {tc:.1%} and {gate}, so per-team showback / "
            f"chargeback can attach ownership to these actions instead of leaving a shared, "
            f"unattributed bill.",
        ]

    # --- 3. Sustainability and cost ---
    if carbon_schedule:
        c = carbon_schedule
        bvc = c["baseline_vs_cleanest"]
        out += [
            "",
            "### 3. Sustainability and cost",
            "",
            f"Extension 5 models moving the {c['interruptible_job_count']} interruptible jobs "
            f"({c['total_energy_kwh']:,.0f} kWh of configured job-run energy) from "
            f"`{bvc['baseline_region']}` to the cleanest region `{bvc['cleanest_region']}`:",
            "",
            f"- Carbon: {bvc['baseline_carbon_gco2e']:,.0f} -> {bvc['cleanest_carbon_gco2e']:,.0f} "
            f"gCO2e, about {bvc['carbon_saved_gco2e']:,.0f} gCO2e avoided "
            f"({bvc['carbon_reduction_pct']:.1f}% reduction).",
            f"- Modeled electricity: ${bvc['baseline_electricity_usd']:,.2f} -> "
            f"${bvc['cleanest_electricity_usd']:,.2f} "
            f"(delta {bvc['electricity_cost_delta_usd']:+,.2f} USD).",
            "",
            "That electricity figure is a **modeled electricity cost only**. It is not a GPU "
            "cloud-bill saving and is deliberately kept out of the four levers and out of "
            "total_savings_pct.",
            "",
            f"- Cheapest region (min $/kWh): `{c['cheapest_region']}`.",
            f"- Cleanest region (min gCO2/kWh): `{c['cleanest_region']}`.",
            f"- Balanced region (equal-weight 50/50 of normalized cost and carbon): "
            f"`{c['balanced_region']}`.",
            "",
            "Relocation is proposed only for interruptible training / batch jobs, which "
            "tolerate distance and checkpoint-restart. Real-time inference is not moved "
            "automatically: user-perceived latency and data-residency requirements usually "
            "pin its serving region.",
        ]
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
