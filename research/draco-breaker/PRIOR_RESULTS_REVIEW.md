# Prior-results review — 2026-10-25

This is a review of machine-readable results already committed to the repository's `main` branch. I did not rerun the experiments in this review. Figures below are copied from the stored JSON artifacts and retain their stated limitations.

## Evidence inspected

1. `results/face_connectivity_study_2026-10-25.json`
   - Recorded workflow: https://github.com/lalitkumar790/MiddleOut-3D/actions/runs/40196914983
   - Source commit: `ef4005001a46ae9ea3356c6a045e9b844af17a39`
   - 6 synthetic meshes, 7 coders, 3 vertex orders, 3 face orders, 16 bits/axis, 1 timing repeat.
2. `results/predictive_ordering_study_2026-10-25.json`
   - Recorded workflow: https://github.com/lalitkumar790/MiddleOut-3D/actions/runs/40195070244
   - Source commit: `f0224b447bb110f99b66767e23bb66d6ca0092e7`
   - 6 synthetic meshes, 7 in-house coders plus Draco comparison, source/BFS/Morton/predictive order, 1 timing repeat.

## Finding A — cyclic face rotation is a useful low-risk candidate

The stored face-ordering study reports the following aggregate payload totals across its six synthetic meshes and seven coders:

| Vertex order | Source face stream | Rotate face stream | Size reduction |
|---|---:|---:|---:|
| source | 376,567 B | 362,336 B | 3.7791% |
| BFS | 293,014 B | 292,587 B | 0.1457% |
| Morton | 529,009 B | 520,882 B | 1.5363% |

The artifact states that topology and error-budget checks passed. Rotation preserves face row order and winding, selecting a cyclic start intended to reduce signed-varint index-delta cost. This is a real positive result *for the in-house codec and this synthetic test set*, not proof of a Draco improvement or general mesh-compression win. The source-order aggregate benefit is strongest; the BFS-order gain is marginal and should be tested for robustness with more assets/repeats.

## Finding B — predictive vertex ordering was a negative result

The predictive-ordering artifact reports that predictive ordering increases aggregate size relative to source/BFS/Morton for every in-house coder in the six-fixture synthetic set. For the baseline encoder, summed single-run encode time was:

- source: 16.5068 ms
- BFS: 44.9180 ms
- predictive: 411.0551 ms

The report itself notes one-repeat timing, no separated warm-up, and machine-specific values. The size regression plus roughly 9.2x time vs BFS and 24.9x vs source makes this traversal a poor default candidate for further optimization. Preserve the negative result and keep predictive ordering out of automatic selection unless a substantially different hypothesis is tested.

## Finding C — direct Draco comparison is mixed, not a universal win

The predictive-ordering JSON records independently selecting the smallest in-house method/order per mesh as 25,807 bytes across six fixtures versus 28,275 bytes for Draco, described in the artifact as an 8.73% smaller aggregate. However, Draco is smaller on three of the six fixtures. The selection is per-fixture oracle-style selection among candidates, not evidence that one fixed algorithm universally beats Draco. Dataset is synthetic, timing is one repeat, and the quality matching procedure uses a short Draco quantization sweep against a conservative maximum-error budget.

This result is useful as a lead, but must be expanded to held-out real meshes, repeated timing, full quality/attribute semantics, and a transparent comparison of per-mesh results before making any broad claim.

## Research priority update

The most immediately actionable validated lead in this repository is not a speculative new KD-tree implementation: it is testing whether **locally cost-minimizing cyclic triangle rotation** remains beneficial on more realistic mesh assets and whether a similar local delta-cost decision can be applied to the actual Draco bitstream without violating its format. The latter requires source checkout/build access and is not implemented here.

For the first Draco-specific study:
1. keep Draco upstream unchanged;
2. use matched decoded maximum error and document attribute loss explicitly;
3. compare actual final bytes and encode/decode times;
4. include repeated runs and more than six synthetic meshes;
5. report per-mesh wins/losses, not only aggregate totals;
6. treat in-house format results and Draco encoder changes as separate experiments.

No code or benchmark was executed during this review; this is a source/artifact review of committed results.
