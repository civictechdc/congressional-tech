# `ct-n6lj`: High-Cardinality `NULL` Undated Bucket (`coverage_daily`) DataFusion Operator & Memory Receipt

- **Ticket**: `ct-n6lj`
- **Dataset**: `coverage_daily` (`RefreshTransform::Aggregate` over `survivor_items`)
- **Grouping Key**: `effective_pub_date` (`Date32`, `NULL` undated bucket)
- **Aggregates**:
  - `rows`: `count_rows` (`COUNT(*)`)
  - `items`: `count_distinct(item_id)` (`COUNT(DISTINCT "item_id")`)
  - `outlets`: `count_distinct(outlet_id)` (`COUNT(DISTINCT "outlet_id")`)
  - `stories`: `count_distinct(story_id)` (`COUNT(DISTINCT "story_id")`)
  - `identical_text_group_ids`: `collect_set(identical_text_group_id)` (`COALESCE(array_sort(ARRAY_AGG(DISTINCT "identical_text_group_id") FILTER (WHERE "identical_text_group_id" IS NOT NULL)), make_array())`)
- **Machine-Readable Receipt**: `output/docspec-reuse-20261020/hot-group-null-bucket-receipt.json`

## 1. Resource Budget & Admission Split (`Limits`)

Under `Limits { compute_threads: 4, memory_bytes: 134_217_728 (128 MiB), scratch_bytes: 134_217_728 (128 MiB), batch_rows: 1024, max_batch_bytes: 4_194_304 (4 MiB), max_metadata_bytes: 4_194_304 (4 MiB) }`:
- **DataFusion `FairSpillPool`**: `67_108_864` bytes (`64 MiB`)
- **Admission Semaphore (`budget.bytes`)**: `67_108_864` bytes (`64 MiB`)

## 2. Physical Plan & Operator Metrics (`DisplayableExecutionPlan::with_metrics`)

### Profile A: `null_bucket_200_rows` (`200` items, `80` repeated text groups, `50` outlets, `60` stories in `NULL` bucket)

```text
ProjectionExec: expr=[effective_pub_date@1 as effective_pub_date, count(Int64(1))@2 as rows, count(DISTINCT aggregate_input.item_id)@3 as items, count(DISTINCT aggregate_input.outlet_id)@4 as outlets, count(DISTINCT aggregate_input.story_id)@5 as stories, CASE WHEN __common_expr_1@0 IS NOT NULL THEN __common_expr_1@0 ELSE [] END as identical_text_group_ids], metrics=[output_rows=1, elapsed_compute=5.54µs, output_bytes=1596.0 B, output_batches=1, expr_0_eval_time=128ns, expr_1_eval_time=86ns, expr_2_eval_time=87ns, expr_3_eval_time=45ns, expr_4_eval_time=45ns, expr_5_eval_time=3.09µs]
  ProjectionExec: expr=[array_sort(array_agg(DISTINCT aggregate_input.identical_text_group_id) FILTER (WHERE aggregate_input.identical_text_group_id IS NOT NULL)@5) as __common_expr_1, effective_pub_date@0 as effective_pub_date, count(Int64(1))@1 as count(Int64(1)), count(DISTINCT aggregate_input.item_id)@2 as count(DISTINCT aggregate_input.item_id), count(DISTINCT aggregate_input.outlet_id)@3 as count(DISTINCT aggregate_input.outlet_id), count(DISTINCT aggregate_input.story_id)@4 as count(DISTINCT aggregate_input.story_id)], metrics=[output_rows=1, elapsed_compute=592.54µs, output_bytes=1596.0 B, output_batches=1, expr_0_eval_time=585.96µs, expr_1_eval_time=295ns, expr_2_eval_time=86ns, expr_3_eval_time=86ns, expr_4_eval_time=87ns, expr_5_eval_time=44ns]
    AggregateExec: mode=FinalPartitioned, gby=[effective_pub_date@0 as effective_pub_date], aggr=[count(Int64(1)), count(DISTINCT aggregate_input.item_id), count(DISTINCT aggregate_input.outlet_id), count(DISTINCT aggregate_input.story_id), array_agg(DISTINCT aggregate_input.identical_text_group_id) FILTER (WHERE aggregate_input.identical_text_group_id IS NOT NULL)], metrics=[output_rows=1, elapsed_compute=425.63µs, output_bytes=2.2 KB, output_batches=1, spill_count=0, spilled_bytes=0.0 B, spilled_rows=0, peak_mem_used=84.00 K, aggregate_arguments_time=2.71µs, aggregation_time=738.00µs, emitting_time=90.88µs, time_calculating_group_ids=961ns]
      RepartitionExec: partitioning=Hash([effective_pub_date@0], 4), input_partitions=4, metrics=[output_rows=1, elapsed_compute=81.58µs, output_bytes=36.9 KB, output_batches=1, spill_count=0, spilled_bytes=0.0 B, spilled_rows=0, fetch_time=12.19ms, repartition_time=92.50µs, send_time=1.34µs]
        AggregateExec: mode=Partial, gby=[effective_pub_date@2 as effective_pub_date], aggr=[count(Int64(1)), count(DISTINCT aggregate_input.item_id), count(DISTINCT aggregate_input.outlet_id), count(DISTINCT aggregate_input.story_id), array_agg(DISTINCT aggregate_input.identical_text_group_id) FILTER (WHERE aggregate_input.identical_text_group_id IS NOT NULL)], metrics=[output_rows=1, elapsed_compute=540.38µs, output_bytes=47.5 KB, output_batches=1, spill_count=0, spilled_bytes=0.0 B, spilled_rows=0, skipped_aggregation_rows=0, peak_mem_used=71.5 K, aggregate_arguments_time=4.33µs, aggregation_time=907.88µs, emitting_time=119.83µs, time_calculating_group_ids=3.54µs, reduction_factor=0.5% (1/200)]
          RepartitionExec: partitioning=RoundRobinBatch(4), input_partitions=1, metrics=[output_rows=200, elapsed_compute=4.83µs, output_bytes=14.4 KB, output_batches=1, spill_count=0, spilled_bytes=0.0 B, spilled_rows=0, fetch_time=2.57ms, repartition_time=1ns, send_time=5.75µs]
            DataSourceExec: NativeScan: rows=Some(200), projection=[item_id, outlet_id, effective_pub_date, story_id, identical_text_group_id], metrics=[]
```

### Profile B: `null_bucket_2000_rows` (`2,000` items, `800` repeated text groups, `200` outlets, `300` stories in `NULL` bucket)

```text
ProjectionExec: expr=[effective_pub_date@1 as effective_pub_date, count(Int64(1))@2 as rows, count(DISTINCT aggregate_input.item_id)@3 as items, count(DISTINCT aggregate_input.outlet_id)@4 as outlets, count(DISTINCT aggregate_input.story_id)@5 as stories, CASE WHEN __common_expr_1@0 IS NOT NULL THEN __common_expr_1@0 ELSE [] END as identical_text_group_ids], metrics=[output_rows=1, elapsed_compute=5.25µs, output_bytes=9.3 KB, output_batches=1, expr_0_eval_time=86ns, expr_1_eval_time=86ns, expr_2_eval_time=212ns, expr_3_eval_time=45ns, expr_4_eval_time=45ns, expr_5_eval_time=3.17µs]
  ProjectionExec: expr=[array_sort(array_agg(DISTINCT aggregate_input.identical_text_group_id) FILTER (WHERE aggregate_input.identical_text_group_id IS NOT NULL)@5) as __common_expr_1, effective_pub_date@0 as effective_pub_date, count(Int64(1))@1 as count(Int64(1)), count(DISTINCT aggregate_input.item_id)@2 as count(DISTINCT aggregate_input.item_id), count(DISTINCT aggregate_input.outlet_id)@3 as count(DISTINCT aggregate_input.outlet_id), count(DISTINCT aggregate_input.story_id)@4 as count(DISTINCT aggregate_input.story_id)], metrics=[output_rows=1, elapsed_compute=748.42µs, output_bytes=9.3 KB, output_batches=1, expr_0_eval_time=741.46µs, expr_1_eval_time=211ns, expr_2_eval_time=336ns, expr_3_eval_time=86ns, expr_4_eval_time=86ns, expr_5_eval_time=87ns]
    AggregateExec: mode=FinalPartitioned, gby=[effective_pub_date@0 as effective_pub_date], aggr=[count(Int64(1)), count(DISTINCT aggregate_input.item_id), count(DISTINCT aggregate_input.outlet_id), count(DISTINCT aggregate_input.story_id), array_agg(DISTINCT aggregate_input.identical_text_group_id) FILTER (WHERE aggregate_input.identical_text_group_id IS NOT NULL)], metrics=[output_rows=1, elapsed_compute=2.49ms, output_bytes=12.7 KB, output_batches=1, spill_count=0, spilled_bytes=0.0 B, spilled_rows=0, peak_mem_used=454.5 K, aggregate_arguments_time=2.50µs, aggregation_time=6.58ms, emitting_time=220.50µs, time_calculating_group_ids=628ns]
      RepartitionExec: partitioning=Hash([effective_pub_date@0], 4), input_partitions=4, metrics=[output_rows=2, elapsed_compute=95.13µs, output_bytes=73.9 KB, output_batches=1, spill_count=0, spilled_bytes=0.0 B, spilled_rows=0, fetch_time=33.99ms, repartition_time=140.29µs, send_time=2.72µs]
        AggregateExec: mode=Partial, gby=[effective_pub_date@2 as effective_pub_date], aggr=[count(Int64(1)), count(DISTINCT aggregate_input.item_id), count(DISTINCT aggregate_input.outlet_id), count(DISTINCT aggregate_input.story_id), array_agg(DISTINCT aggregate_input.identical_text_group_id) FILTER (WHERE aggregate_input.identical_text_group_id IS NOT NULL)], metrics=[output_rows=2, elapsed_compute=4.45ms, output_bytes=95.2 KB, output_batches=2, spill_count=0, spilled_bytes=0.0 B, spilled_rows=0, skipped_aggregation_rows=0, peak_mem_used=337.3 K, aggregate_arguments_time=16.17µs, aggregation_time=10.39ms, emitting_time=275.21µs, time_calculating_group_ids=30.59µs, reduction_factor=0.1% (2/2.00 K)]
          RepartitionExec: partitioning=RoundRobinBatch(4), input_partitions=1, metrics=[output_rows=2.00 K, elapsed_compute=6.08µs, output_bytes=138.4 KB, output_batches=2, spill_count=0, spilled_bytes=0.0 B, spilled_rows=0, fetch_time=4.01ms, repartition_time=1ns, send_time=8.50µs]
            DataSourceExec: NativeScan: rows=Some(2000), projection=[item_id, outlet_id, effective_pub_date, story_id, identical_text_group_id], metrics=[]
```

## 3. Summary Table

| Profile | Input Rows (`NULL` key) | Distinct `identical_text_group_id` | `AggregateExec (Partial)` `peak_mem_used` | `AggregateExec (FinalPartitioned)` `peak_mem_used` | `spill_count` / `spilled_bytes` | Final Output Batch Bytes | Tight Admission Refusal | Tight `FairSpillPool` Refusal |
|---|---:|---:|---:|---:|---|---:|---|---|
| `null_bucket_200_rows` (`1x`) | `200` | `80` | `71,488 B` (`71.5 K`) | `84,000 B` (`84.0 K`) | `0` / `0 B` | `1,596 B` | `capacity` | `query` |
| `null_bucket_2000_rows` (`10x`) | `2,000` | `800` | `337,312 B` (`337.3 K`) | `454,496 B` (`454.5 K`) | `0` / `0 B` | `9,516 B` | `capacity` | `query` |

- **Column Pruning**: `NativeScan` projects only `[item_id, outlet_id, effective_pub_date, story_id, identical_text_group_id]`, pruning `current_version_id`, `text_group_id`, and occurrence address columns (`__docspec_occurrence_file`, `__docspec_occurrence_row`) before hash aggregation.
- **No Full-Input Sort**: Both `Partial` and `FinalPartitioned` stages execute as hash `AggregateExec` without `SortExec`; `array_sort` runs in the final `ProjectionExec` on the single deduplicated list (`80` or `800` elements) in `< 0.75 ms`.
- **Fail-Closed Under Constrained Limits**: Exhausting either the admission semaphore (`capacity`) or DataFusion's `FairSpillPool` (`query`) during `DistinctArrayAggAccumulator` / `CountDistinct` accumulation aborts the refresh cleanly while preserving the prior `coverage_daily` release pin (`prior_release_preserved = true`).
