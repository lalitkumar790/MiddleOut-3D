# DP-segmented adaptive enumerative residual coding — experiment E000

**Branch:** research/chandas-segmented-blocks  
**Status:** E001 benchmark complete; E002 cost-computation optimization committed for CI.

## Hypothesis

MO3D v7 chooses between direct signed zigzag-varints and enumerative coding of nonzero positions within fixed 64-symbol blocks. v8 (method chandas_segmented_tangent) adds a shortest-path segmentation over block lengths 16, 32, 64, 128 and 256 symbols; it permits a final tail shorter than 16. The DP cost includes the explicit block-length varint, mode byte and actual chosen block body. It is optimal for that pre-zlib byte objective, not necessarily for zlib-compressed output.

For a block \(r\) of length \(n\) with \(k\) non-zero symbols, the sparse representation spends a subset-rank field of \(\lceil\log_2 {n\choose k}\rceil\) bits (rounded to bytes), a count varint and the signed-magnitude varints. The direct alternative pays one signed-varint per residual. The recurrence selects a sequence of blocks minimizing the sum of these framed block costs:
\[
D(i)=\min_{n\in\mathcal B(i)} C(r_{i:i+n})+D(i+n),\quad D(N)=0.
\]
The fixed five-length candidate set makes search linear in sequence length up to a bounded block-cost factor; choices are deterministic. New MO3D signature v8 / CHS3 signature avoid interpreting these block lengths as v7's fixed 64-symbol frames. Existing v1–v7 decode code paths remain intact.

## Tests and falsification

Tests cover variable-length decoding, malformed block rejection, exhaustive minimum-cost agreement on a small sequence, and v8 mesh round trips with exact oriented topology and the existing conservative max-vertex-error bound. CI adds a CLI encode/decode smoke test and runs the tests across Python 3.10, 3.12 and 3.13.

The benchmark compares full bitstream size, encode/decode time, max vertex error, RMSE and topology for the six deterministic synthetic fixtures, 16-bit geometry, source/BFS/Morton vertex orders, source/greedy-rotate/DP-rotate/BFS face streams, and three repeats. It pairs v8 against fixed-block adaptive v7, v6 sparse enumeration, weighted tangent and the absolute baseline. A result is useful only if all paired candidates pass the same accuracy and topology checks. No win is presumed. Dataset-specific gains would need held-out, license-cleared CAD/robotics/scan assets before any broader claim.

## Historical framing

The algorithm borrows the general rank/unrank/combinatorics motif studied in Piṅgala's prosody tradition. It is a modern DP partitioning and byte-cost objective, not a codec described in the Chandaḥśāstra. See Jayant Shah's historical review hosted by the University of Hyderabad (https://sanskrit.uohyd.ac.in/faculty/amba/PUBLICATIONS/Lectures/UoHyd/Material/Pingala.pdf); the interpretation of particular later meru-prastāra readings is debated. All results will be judged on implementation and benchmarks, not the cultural analogy.


## E001 — DP-segmented adaptive Chandas residual blocks

- GitHub Actions run: https://github.com/lalitkumar790/MiddleOut-3D/actions/runs/40226491358
- Source commit tested: 8adc3d73b0eb319632025120de899e9b6bfde34e.
- Configuration: six deterministic synthetic fixtures, 16-bit positions, three vertex orderings, four face-stream strategies, and three encode/decode timing repetitions.
- The workflow required every codec/order/face-strategy row to pass exact oriented topology and the common per-axis quantization error bound before recording totals.
- Aggregate bytes across the same mesh/order/face-strategy grid: chandas_segmented_tangent=698241 B; chandas_adaptive_tangent=700841 B; chandas_tangent=707773 B; weighted_tangent=698389 B; baseline=782993 B.
- Paired wins/ties/losses (v8 compared to each method): chandas_adaptive_tangent 48/0/24 of 72; chandas_tangent 52/0/20 of 72; weighted_tangent 32/0/40 of 72; baseline 56/0/16 of 72.
- These are synthetic-fixture results only. The segmentation DP minimizes framed pre-zlib bytes; complete MO3D payload bytes determine the empirical result. No general compression or Draco superiority is inferred.



## E002 — prefix-sum cost evaluation optimization

The v8 E001 benchmark passed topology/error checks and reduced complete synthetic payload bytes by 0.371% versus fixed-block adaptive Chandas, but its DP evaluation repeatedly encoded candidate blocks. The revised implementation precomputes direct-varint length sums, nonzero-amplitude byte sums and nonzero counts. Since the sparse position-rank byte length is determined by block length and nonzero count, candidate body length can be calculated exactly as varint(count) + ceil(log2(comb(length,count))) rounded to bytes + nonzero-amplitude varints. This preserves the same pre-zlib byte objective and deterministic tie-breaks while reducing the DP from O(N K Bmax) scanning work to O(N K) candidate evaluation plus one pass to emit chosen blocks. The existing exhaustive small-sequence test continues to check optimal cost. E002's full-payload results are pending.


## E001 — DP-segmented adaptive Chandas residual blocks

- GitHub Actions run: https://github.com/lalitkumar790/MiddleOut-3D/actions/runs/40228505345
- Source commit tested: 291f07ed0ad1f089174d7450e9d7bf4a43cbc824.
- Configuration: six deterministic synthetic fixtures, 16-bit positions, three vertex orderings, four face-stream strategies, and three encode/decode timing repetitions.
- The workflow required every codec/order/face-strategy row to pass exact oriented topology and the common per-axis quantization error bound before recording totals.
- Aggregate bytes across the same mesh/order/face-strategy grid: chandas_segmented_tangent=698241 B; chandas_adaptive_tangent=700841 B; chandas_tangent=707773 B; weighted_tangent=698389 B; baseline=782993 B.
- Paired wins/ties/losses (v8 compared to each method): chandas_adaptive_tangent 48/0/24 of 72; chandas_tangent 52/0/20 of 72; weighted_tangent 32/0/40 of 72; baseline 56/0/16 of 72.
- These are synthetic-fixture results only. The segmentation DP minimizes framed pre-zlib bytes; complete MO3D payload bytes determine the empirical result. No general compression or Draco superiority is inferred.
