# Draco-Breaker research track

This directory tracks experiments aimed at improving 3D geometry compression against unmodified Google Draco. The upstream implementation remains the reference baseline; this repository is a separate research prototype.

## Integrity rules

- Never claim a benchmark ran unless its command and raw output are recorded.
- Never compare compressed sizes unless source geometry, quantization/error tolerance, attributes, and decoder validity are comparable.
- Keep algorithmic compression gains separate from implementation-speed gains.
- Record negative and inconclusive experiments, not just winners.
- Prefer held-out assets and repeated timings; report median and dispersion.
- Do not call a smaller file a win if it violates the declared fidelity or semantic constraints.

## Reference snapshot

- Upstream: https://github.com/google/draco
- Branch inspected: `main`
- HEAD observed on 2026-10-25: `d429de84b52a860705507da0884764c5d8321423`
- This SHA is an observed snapshot, not a claim that it is still the latest upstream HEAD.
- Upstream license: Apache-2.0 (verified from CMake/source headers).
- Local checkout/build: blocked at the start because the available execution environment could not resolve `github.com`. No local Draco build or compression benchmark is claimed.

## First hypothesis: rate-aware point-cloud partitioning

Draco already implements KD-tree point-cloud coding and several coding policies. Investigate whether candidate split selection based on estimated *total* code length can outperform geometric split heuristics on selected distributions.

For candidate split (s), estimate:

```
J(s) = L_partition(s) + L_left(s) + L_right(s)
```

where all terms estimate encoded bits including signaling/model overhead. The candidate must be tested against actual encoded byte counts; entropy estimates alone are not sufficient.

### Falsification criteria

Reject or narrow the hypothesis if:
1. actual bytes do not improve on held-out clouds at matched quantization;
2. improvements disappear after including headers/metadata;
3. encoding cost grows too much for the intended operating mode;
4. decoder correctness, point count, attribute semantics, or error constraints regress.

### Source map

- `src/draco/compression/point_cloud/point_cloud_encoder.cc`: shared point-cloud encode pipeline and accounting.
- `src/draco/compression/point_cloud/point_cloud_kd_tree_encoder.cc`: KD-tree point-cloud encoder entry point.
- `src/draco/compression/attributes/kd_tree_attributes_encoder.cc`: attribute transforms and quantization before KD-tree coding.
- `src/draco/compression/point_cloud/algorithms/dynamic_integer_points_kd_tree_encoder.h`: dynamic integer KD-tree policy and coding.
- `src/draco/compression/point_cloud/algorithms/float_points_tree_encoder.h`: float point quantization and tree encoder wrapper.
- `src/draco/compression/attributes/sequential_integer_attribute_encoder.cc`: sequential integer attributes and prediction setup.
- `src/draco/compression/entropy/shannon_entropy.cc`: entropy accounting utility.
- `src/draco/compression/mesh/mesh_edgebreaker_encoder.cc`: mesh connectivity encoder dispatch.

Source inspection was read-only through GitHub. Exact local line-number mappings and full call-graph validation remain pending a complete checkout.

## Status

Research setup only. No candidate algorithm has been implemented or benchmarked against Draco yet. See [EXPERIMENT_LOG.md](EXPERIMENT_LOG.md).
