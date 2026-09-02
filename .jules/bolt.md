## 2023-10-27 - O(N^2) Scan on Volume Profile Generation

**Learning:** Generating the volume profile iterated over `all_strikes` while applying list comprehensions scanning the entire dataset `rows` for `Call`/`Put` volumes for each strike, which creates an O(N*M) bottleneck when options chains are very long. The time taken to calculate the volume profile scaled quadratically with the length of the data.

**Action:** Future profile generations that iterate over a unique set of elements should pre-aggregate values from `rows` into dictionaries instead of continuously re-iterating over the entire set of rows.

## 2023-10-27 - O(N^2) Scan on Max Pain Calculation

**Learning:** Calculating max pain evaluated the pain generated across all active strikes (O(N)) for each individual settlement price evaluated (O(N)), leading to an O(N^2) bottleneck.

**Action:** Replace nested loops performing repeated cumulative accumulation with single-pass accumulation using pre-calculated running totals (prefix/suffix sums) when possible, converting O(N^2) logic into O(N).

## 2024-05-19 - DataFrame Iterrows Bottleneck

**Learning:** `DataFrame.iterrows()` creates significant overhead by constructing a new `Series` object for every row. This was identified as a bottleneck in `update_dashboard.py` during `get_intraday_data` execution.

**Action:** Replace `iterrows()` with `zip()` iteration over the specific column `Series`. This yields the underlying scalar values directly and provides a massive speedup (e.g. over 90% faster) while maintaining the same order and output.
