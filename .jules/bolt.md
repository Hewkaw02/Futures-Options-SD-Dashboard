## 2023-10-27 - O(N^2) Scan on Volume Profile Generation

**Learning:** Generating the volume profile iterated over `all_strikes` while applying list comprehensions scanning the entire dataset `rows` for `Call`/`Put` volumes for each strike, which creates an O(N*M) bottleneck when options chains are very long. The time taken to calculate the volume profile scaled quadratically with the length of the data.

**Action:** Future profile generations that iterate over a unique set of elements should pre-aggregate values from `rows` into dictionaries instead of continuously re-iterating over the entire set of rows.
