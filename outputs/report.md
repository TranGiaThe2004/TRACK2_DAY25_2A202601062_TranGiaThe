# NimbusAI — GPU Cost Optimization Report

- **Period:** monthly
- **Baseline spend:** $27,133
- **Optimized spend:** $14,626
- **Projected savings:** $12,507 (**46%**)

## Savings by lever

| Lever | Savings (USD) |
|---|---|
| Inference (cascade/cache/batch) | $1,212 |
| Purchasing (spot/reserved) | $10,040 |
| Right-size util-lies | $655 |
| Kill idle GPUs | $600 |

_Scope: the $27,133 baseline spend above is a **composite** = 30 x M2 inference baseline/day (= $1,466/month) + M3 purchasing workload monthly baseline (= $25,667/month). The $/1M-token table below is **inference traffic only** (M2, one sample day) — a different scope; the two totals are not directly comparable._

## Inference Unit Economics ($/1M-token)

_Inference traffic only (M2, one sample day). Sequential order: Cascade -> Cache -> Batch — each lever is measured on top of the previous one._

| Stage | $/day | $/1M-token | Incremental savings $/day | Cumulative savings % |
|---|---|---|---|---|
| Baseline (large model; no cache/batch) | 48.8742 | 6.4880 | 0.0000 | 0.00% |
| + Cascade | 11.4756 | 1.5234 | 37.3985 | 76.52% |
| + Cache (after cascade) | 10.2792 | 1.3645 | 1.1965 | 78.97% |
| + Batch (all three) | 8.4846 | 1.1263 | 1.7946 | 82.64% |

| Isolated lever (vs baseline) | $/day | $/1M-token | Savings vs baseline % |
|---|---|---|---|
| Cascade only | 11.4756 | 1.5234 | 76.52% |
| Cache only | 44.2734 | 5.8772 | 9.41% |
| Batch only | 40.6351 | 5.3943 | 16.86% |

- Sequential per-lever contribution (Cascade -> Cache -> Batch): Cascade $37.3985/day, Cache $1.1965/day, Batch $1.7946/day.
- Largest sequential lever (by max contribution): **Cascade** ($37.3985/day).
- Total sequential savings: $40.3895/day (baseline minus the fully optimized scenario).
- Sequential contributions are order-dependent (Cascade -> Cache -> Batch, each measured on top of the previous one); the isolated single-lever scenarios overlap, so their savings do not add up to the fully optimized total.

## Sustainability

- Energy per query: 0.24 Wh
- Carbon per query: 0.091 gCO2e
- Cheapest+cleanest region: europe-north1

## Reasoning Budget

_Extension 4 — reasoning traffic isolated as a governed cost + energy lever._

| Segment | Requests | Traffic % | Tokens | Optimized $/day | Energy Wh/day |
|---|---|---|---|---|---|
| Reasoning | 201 | 8.4% | 1,241,156 | $1.40 | 29,788 |
| Non-reasoning | 2,199 | 91.6% | 6,291,871 | $7.09 | 1,888 |

- From 8.4% of traffic, reasoning is **16.5% of optimized inference cost** and **94.0% of inference energy** (reasoning energy multiplier x80 via `sustainability.wh_per_query`).
- Primary cap (10% of traffic): keep <= 240 reasoning-mode requests, downgrade 0 -> save $0.00/day ($0.00/month), 0 Wh/day _(non-binding: reasoning is 8.4%, already <= 10% budget)_.
- Sensitivity scenario (5% of traffic — illustrative only; the primary policy remains 10%): keep 120 reasoning-mode requests (input_tokens >= 2,034), downgrade 81 -> save $0.46/day ($13.86/month), 9,977 Wh/day.
- Theoretical ceiling (route every reasoning-mode request to normal mode): save $1.05/day ($31.42/month), 29,612 Wh/day.
- **Routing rule:** Reasoning is 8.4% of traffic, below the 10% budget, so no request needs to be cut right now (input_tokens >= 408 here is only the minimum observed while the cap is non-binding, not a policy threshold). Rule: monitor the reasoning share; if it is forecast to reach or exceed 10%, rank the reasoning candidates by input_tokens descending with a deterministic tie-break (ts, then original order), keep at most floor(10% x total_requests), and recompute the threshold from that batch. input_tokens is only a complexity PROXY in this simulation, not a real difficulty signal.

### Assumptions

- input_tokens is only a complexity PROXY in this simulation, not a real difficulty signal.
- Downgrading a reasoning-mode request keeps input_tokens, cached_input_tokens, route_tier and is_batch; only output_tokens is replaced by an estimate and the x80 reasoning energy factor is removed.
- Estimated normal output_tokens = median output_tokens of non-reasoning requests with the same (team, route_tier); fallback order: same route_tier; then the global non-reasoning median.
- Money uses pricing.request_cost with MODEL_PRICES by route_tier; the x80 reasoning factor applies to ENERGY only (sustainability.wh_per_query).
- Energy per request uses sustainability.wh_per_query(input_tokens + output_tokens); the simulation does NOT separately model any energy saved by cached input.
- Month = 30 days (matches M5); the dataset is a single sample day.
- Primary cap keeps floor(0.10 x total_requests) reasoning-mode requests; the 5% row is an illustrative sensitivity scenario only, the primary policy remains 10%.

## Carbon-Aware Scheduling

_Extension 5 — relocate interruptible (training / batch) jobs to a cleaner grid region. The electricity delta is a modeled electricity cost only, not a GPU cloud-bill saving, and is excluded from the four levers and total_savings_pct above._

Interruptible jobs analyzed: 5  ·  configured job-run energy: 1,789.00 kWh (each job = its own hours_per_day x days, not a calendar month)

| Job | GPU | Energy kWh | Baseline gCO2e (us-east-1) | Cleanest gCO2e (europe-north1) | Carbon saved gCO2e | Electricity delta USD |
|---|---|---|---|---|---|---|
| job-train-llm | H100 x8 | 1,568.00 | 595,840.0 | 47,040.0 | 548,800.0 | -47.04 |
| job-train-embed | A100 x4 | 80.00 | 30,400.0 | 2,400.0 | 28,000.0 | -2.40 |
| job-finetune | H100 x2 | 25.20 | 9,576.0 | 756.0 | 8,820.0 | -0.76 |
| job-dev-sandbox | A10G x2 | 52.80 | 20,064.0 | 1,584.0 | 18,480.0 | -1.58 |
| job-batch-eval | H100 x1 | 63.00 | 23,940.0 | 1,890.0 | 22,050.0 | -1.89 |

_Electricity delta sign: negative = the cleaner region also costs less modeled electricity._

| Region | $/kWh | gCO2/kWh | Total energy kWh | Total electricity USD | Total carbon gCO2e |
|---|---|---|---|---|---|
| europe-central2 | 0.180 | 660 | 1,789.00 | 322.02 | 1,180,740.0 |
| europe-north1 | 0.090 | 30 | 1,789.00 | 161.01 | 53,670.0 |
| us-east-1 | 0.120 | 380 | 1,789.00 | 214.68 | 679,820.0 |
| us-east-wa | 0.055 | 90 | 1,789.00 | 98.39 | 161,010.0 |
| us-west-2 | 0.070 | 120 | 1,789.00 | 125.23 | 214,680.0 |

**Baseline (us-east-1) vs cleanest (europe-north1):**

- Carbon: 679,820.0 -> 53,670.0 gCO2e (saved 626,150.0 gCO2e, 92.1% reduction)
- Modeled electricity: $214.68 -> $161.01 (delta -53.67 USD — modeled electricity, not a cloud-bill saving)

- **Cheapest region** (min $/kWh): us-east-wa
- **Cleanest region** (min gCO2/kWh): europe-north1
- **Balanced region** (equal-weight 50/50): us-east-wa

| Region | normalized_cost | normalized_carbon | balanced_score |
|---|---|---|---|
| europe-central2 | 1.0000 | 1.0000 | 1.0000 |
| europe-north1 | 0.2800 | 0.0000 | 0.1400 |
| us-east-1 | 0.5200 | 0.5556 | 0.5378 |
| us-east-wa | 0.0000 | 0.0952 | 0.0476 |
| us-west-2 | 0.1200 | 0.1429 | 0.1314 |

_Balanced formula:_ balanced_score = 0.50 * normalized_cost + 0.50 * normalized_carbon, where normalized_x = (x - min_x) / (max_x - min_x) across the scored regions and a degenerate range (max == min) normalizes to 0.0. Equal-weight 50/50 choice; lower score is better.

**Latency trade-off:** The dataset carries no request latency and no user-location data, so this is a qualitative note only and no millisecond figures are invented. Relocating workloads to another region suits interruptible training / batch jobs, which tolerate distance and checkpoint-restart. It does NOT automatically apply to real-time inference, where user-perceived latency and data-residency usually pin the serving region.

### Carbon-Aware Scheduling — Assumptions

- Only workloads with interruptible=1 are analyzed.
- energy_kwh = watts (price_catalog.csv) x num_gpus x hours_per_day x days / 1000; watts is the GPU board power held constant while running (no PUE, networking, storage or idle overhead modeled).
- Region carbon intensity (gCO2/kWh) and electricity price ($/kWh) are read from finops.sustainability.REGION_CARBON / REGION_PRICE_KWH; none are redefined here.
- Baseline region is us-east-1 (the assignment's assumed starting point); the cleanest region is derived as min(REGION_CARBON).
- The electricity-cost delta is a MODELED electricity cost only. It is NOT a GPU cloud-bill saving and is excluded from the four M5 levers and total_savings_pct.
- balanced_score uses transparent min-max normalization with equal 50/50 weights; max == min normalizes to 0.0.
- Each job's energy covers its own configured run (hours_per_day x days), not a uniform calendar month.

## Findings and Prioritized Actions

### 1. The GPU-Util lie

M1 flags `gpu-h100-4`, `gpu-a10g-1`: high GPU-Util but low MFU.

| GPU | Type | GPU-Util % | MFU | MBU |
|---|---|---|---|---|
| gpu-h100-4 | H100 | 98.2% | 0.194 | 0.207 |
| gpu-a10g-1 | A10G | 96.9% | 0.268 | 0.302 |

A high GPU-Util only means kernel execution was active during many sampling intervals. It says nothing about how much of the chip's theoretical FLOP capacity those kernels used. A low MFU means the useful FLOPs delivered were a small fraction of peak, so the full GPU-hour is paid for a fraction of the rented compute.

Plausible causes include memory-bandwidth stalls, kernel-launch overhead, batch sizes too small to fill the tensor cores, and pipeline bubbles waiting on data or I/O. The current telemetry (util, achieved TFLOPs, achieved bandwidth) is not enough to prove which cause dominates on each GPU; that needs per-kernel profiling. These stay hypotheses, not conclusions.

- Financial impact: right-sizing the util-lie GPUs one tier down is modeled at about $655/month (M5 "Right-size util-lies" lever).
- A util-lie is not the same as a fully idle GPU: `gpu-h100-5` (8h) runs below 10% utilization overnight and simply wastes about $20/day = $600/month (M5 "Kill idle GPUs" lever). That GPU is idle, not mis-reporting efficiency.

### 2. Prioritized actions (by modeled monthly impact)

| Rank | Lever | Modeled savings (USD/month) |
|---|---|---|
| 1 | Purchasing (spot/reserved) | $10,040 |
| 2 | Inference (cascade/cache/batch) | $1,212 |
| 3 | Right-size util-lies | $655 |
| 4 | Kill idle GPUs | $600 |

**Purchasing (spot/reserved)** ranks first on modeled dollar impact: it applies to the whole workload fleet (M3 on-demand baseline $25,667/month), and matching each job to its tier (spot for interruptible jobs, reserved for steady high-duty-cycle workloads above the computed break-even, on-demand otherwise) removes about 39.1% of it.

Within inference, the largest sequential contribution in the order Cascade -> Cache -> Batch is **Cascade** (about $37.3985/day): Cascade $37.3985/day, Cache $1.1965/day, Batch $1.7946/day. These contributions are order-dependent, and the isolated single-lever savings percentages overlap, so they cannot be added together.

First three actions for NimbusAI:

1. **Purchasing policy.** Match every workload to spot / reserved / on-demand by its interruptibility and duty cycle, and checkpoint interruptible jobs so spot reclaims cost little rework.
2. **Inference model routing.** Ship the cascade (route easy traffic to the small model) first, then layer prompt caching and the Batch API onto the traffic types that tolerate them.
3. **Efficiency controls.** Right-size the util-lie GPUs one tier down and auto-stop idle GPUs, with utilization/MFU monitoring and a rollback path if quality or throughput regresses.

Cost accountability: M4 tag coverage is 91.8% and the chargeback gate is open, so per-team showback / chargeback can attach ownership to these actions instead of leaving a shared, unattributed bill.

### 3. Sustainability and cost

Extension 5 models moving the 5 interruptible jobs (1,789 kWh of configured job-run energy) from `us-east-1` to the cleanest region `europe-north1`:

- Carbon: 679,820 -> 53,670 gCO2e, about 626,150 gCO2e avoided (92.1% reduction).
- Modeled electricity: $214.68 -> $161.01 (delta -53.67 USD).

That electricity figure is a **modeled electricity cost only**. It is not a GPU cloud-bill saving and is deliberately kept out of the four levers and out of total_savings_pct.

- Cheapest region (min $/kWh): `us-east-wa`.
- Cleanest region (min gCO2/kWh): `europe-north1`.
- Balanced region (equal-weight 50/50 of normalized cost and carbon): `us-east-wa`.

Relocation is proposed only for interruptible training / batch jobs, which tolerate distance and checkpoint-restart. Real-time inference is not moved automatically: user-perceived latency and data-residency requirements usually pin its serving region.

_Figures are June-2026 as-of snapshots; re-baseline before acting._