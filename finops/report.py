"""Report assembly — the lab's deliverable: baseline vs optimized + savings chart."""
from __future__ import annotations


def build_report(baseline_usd: float, optimized_usd: float, levers: dict,
                 sustainability: dict | None = None, period: str = "monthly",
                 reasoning=None) -> str:
    """Return a markdown cost-optimization report.

    `reasoning` (optional, Extension 4) is the dict returned under
    m2_inference_levers.run()["reasoning"]; when omitted the report is unchanged.
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
    lines += ["", "_Figures are June-2026 as-of snapshots; re-baseline before acting._"]
    return "\n".join(lines)


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
