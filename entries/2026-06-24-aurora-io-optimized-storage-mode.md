# Aurora storage mode: should we switch to I/O-Optimized?

- **Date:** 2026-06-24
- **Author:** Steven Kearnes
- **Status:** draft
- **Tags:** aws, aurora, cost, database, search-performance

## Question

A cost-analysis agent recommended switching the production Aurora PostgreSQL
cluster from **Aurora Standard** storage to **Aurora I/O-Optimized**, on the
grounds that I/O charges dominate the bill. Is that the right call, and how does
it interact with the planned 1-year reserved-instance purchase?

## Summary

**Hold — do not switch to I/O-Optimized yet, and do not buy the reserved
instance yet.** The recommendation is correct *for the data it saw*, but every
month of I/O data we have was produced under the memory-starved regime we only
fixed this morning (the cluster ran on Serverless v2 pinned at the 1-ACU cap
until 2026-06-24 ~03:30 UTC, when it finally moved to provisioned
`db.t4g.large`). We have **zero** data on steady-state I/O for the right-sized
instance. The whole point of the right-size was to fit the ~2.5 GB working set
in cache and collapse read I/O, so I/O is expected to drop well below the
break-even. Re-measure ~1 week out, then decide mechanically:

> Switch to I/O-Optimized only if post-migration steady-state I/O settles above
> **~$30/mo**. Otherwise stay on Standard.

Decide the storage mode *before* buying the 1-year RI — Standard and
I/O-Optimized bill at different rates, and the RI is a 12-month commitment.

## Method

All figures pulled directly from the production account
(`482491871729`, region `us-east-1`, cluster `cluster`, instance
`cluster-instance-0`) on 2026-06-24:

- **Bill (ground truth):** `aws ce get-cost-and-usage`, RDS service, grouped by
  `USAGE_TYPE`, monthly and daily granularity.
- **I/O volume:** `aws cloudwatch get-metric-statistics` for
  `VolumeReadIOPs` / `VolumeWriteIOPs` (daily Sum, 30 days).
- **Compute regime:** `ServerlessDatabaseCapacity` (ACU) metric +
  `describe-db-clusters ServerlessV2ScalingConfiguration` +
  `describe-events` for the instance and cluster.

I/O is billed at **$0.20 per 1M requests** on Standard. The CloudWatch IOPs
estimate (~2.43B reads/mo ≈ $487) was cross-checked against the actual
`Aurora:StorageIOUsage` line item and agreed.

## Findings

### The bill is I/O-dominated — but on pre-fix data

| Month | Compute (ServerlessV2) | **I/O (StorageIOUsage)** | Storage | I/O share |
|-------|------------------------|--------------------------|---------|-----------|
| April | $50 | **$126** | $4 | ~68% |
| May | $52 | **$128** | $4 | ~68% |
| June (to 23rd) | $47 | **$442** | $3 | ~88% |

On its face this clears the I/O-Optimized break-even (~25% of bill) easily.

### Every data point is from the memory-starved regime

- The cluster ran **Serverless v2 capped at MaxCapacity 1.0** for all three
  months. The ACU metric sits at the **1.0 ceiling every day** (Jun 17–23:
  0.59–0.83 average utilization against the cap) — i.e. continuously
  memory-bound, forcing reads to the storage layer. This is the same root cause
  behind the slow search queries.
- The provisioned `db.t4g.large` (8 GB RAM, ~4.8 GB `shared_buffers`) only went
  live at **03:30 UTC on 2026-06-24** — `describe-events` shows three
  back-to-back instance-class modifications ending in "Finished applying
  modification to DB instance class," plus a new cluster parameter group
  (`ord-cluster-20260624023642223000000001`).
- June's spike is further inflated by **transient ingestion / `add_dataset`
  optimization work**: the Jun 19 `VolumeWriteIOPs` spike is 2.2M vs the
  ~300K/day baseline (7×, a re-ingestion), and Jun 4–7 read spikes hit
  $60–74/day during optimization/benchmark passes. Not steady state.

Net: April/May's "quiet" $127/mo and June's $442 are **both** artifacts of the
unfixed problem. We have no representative I/O number for the right-sized
instance.

### Break-even math

- **Standard:** compute + storage + $0.20 per 1M I/O.
- **I/O-Optimized:** no per-I/O charge, but **+~30% compute** and **+~125%
  storage**.
- On `db.t4g.large` (~$108/mo compute on-demand, ~$83 reserved; storage premium
  trivial at a few GB), the I/O-Optimized premium is **~$25–32/mo**.
- Therefore I/O-Optimized wins only if steady-state I/O exceeds **~$30/mo**.

Expectation: with the working set now cached, read I/O should fall far below
$30/mo, making **Standard** the right mode and the original recommendation
obsolete. To be confirmed with post-migration data.

## Conclusions / next steps

1. **Re-pull `Aurora:StorageIOUsage` daily cost ~2026-07-01** (a clean week
   after the migration, excluding any further ingestion runs).
   - <$30/mo → stay on Standard; buy the **Standard** reserved instance.
   - sustained >$40–50/mo → switch to **I/O-Optimized** (live change, no
     downtime; reversible once per 30 days), then buy the matching RI.
2. **Do not buy the 1-year reserved instance until the mode is decided** — the
   two modes bill at different rates and the RI is a 12-month lock-in. Confirm
   how an RI discount applies to I/O-Optimized instance-hours on the AWS pricing
   page before purchase.

## References

- Prod account 482491871729, region us-east-1, cluster `cluster`.
- Backend stack sizing rationale: `ord-infrastructure` `stacks/backend`
  (README "Database sizing"); instance class set in PR #31.
- Related search-performance work: `ord-interface` #196 (index operators),
  #198 (query `statement_timeout`).
- AWS: [Aurora storage configurations / I/O-Optimized](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/aurora-storage-configurations.html).
