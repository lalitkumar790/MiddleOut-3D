# DP-segmented adaptive enumerative residual coding — experiment E000

**Branch:** research/chandas-segmented-blocks  
**Status:** implementation committed for CI; full payload benchmark pending.

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
