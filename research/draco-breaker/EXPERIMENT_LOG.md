# Experiment log — Draco-Breaker

## 2026-10-25 — E000: environment and source reconnaissance

**Status:** blocked for local execution; source reconnaissance completed through GitHub read access.

### What changed
- Created dedicated branch `research/draco-breaker` from `main` in this repository.
- Added research charter at `research/draco-breaker/README.md`.
- This is a research log only; no Draco source was modified.

### Upstream snapshot
- Repository: https://github.com/google/draco
- Observed `main` commit: `d429de84b52a860705507da0884764c5d8321423`
- Commit message: "Pin three.js example to r125 (#1252)"
- Snapshot retrieved from GitHub commit API on 2026-10-25.
- README identifies the 1.5.9 release; main may contain changes after that release.
- CMakeLists and source headers show Apache License 2.0.

### Environment / commands
- Attempted `git clone https://github.com/google/draco.git` in the available local execution environment.
- Result: failed before checkout because `github.com` could not be resolved (DNS/network failure).
- No local Draco build, tests, encoder/decoder run, or compression benchmark was executed.
- Compiler/toolchain checks from the available environment: Linux x86-64, GCC 14.2.0, CMake 3.31.6, 5 logical CPUs visible. These are environment facts, not Draco build facts.

### Source actually inspected
- `CMakeLists.txt`: CMake-based build, default Release configuration, source aggregation.
- `BUILDING.md`: documented out-of-tree CMake build instructions.
- `src/draco/compression/point_cloud/point_cloud_encoder.cc`: shared encode pipeline, header/metadata, geometry data, attribute coding, encode byte accounting.
- `src/draco/compression/point_cloud/point_cloud_kd_tree_encoder.cc`: KD-tree point-cloud encoder entry point.
- `src/draco/compression/attributes/kd_tree_attributes_encoder.cc`: attribute preparation and quantization before tree coding.
- `src/draco/compression/point_cloud/algorithms/dynamic_integer_points_kd_tree_encoder.h`: policy-based dynamic integer KD-tree coding.
- `src/draco/compression/point_cloud/algorithms/float_points_tree_encoder.h`: float quantization and tree coding wrapper.
- `src/draco/compression/attributes/sequential_integer_attribute_encoder.cc`: sequential integer attributes and prediction scheme initialization.
- `src/draco/compression/entropy/shannon_entropy.cc`: entropy calculation helper.
- `src/draco/compression/mesh/mesh_edgebreaker_encoder.cc`: mesh connectivity encoder dispatch.

### Research hypothesis H001: rate-aware point-cloud partition selection
**Hypothesis:** For some nonuniform or anisotropic point-cloud distributions, choosing among candidate splits using estimated total encoded cost could reduce the final stream size compared with the existing split decision.

For candidate split (s):
```
J(s) = L_partition(s) + L_left(s) + L_right(s)
```
Terms must include estimated signaling/model overhead, not just raw residual entropy. Actual encoded bytes are the final metric.

**Expected complexity:** evaluating (k) candidate splits per node adds cost over the current split strategy; exact cost depends on data structures and candidate generation.

**Assumptions:** useful candidate partitions can be evaluated cheaply; local coding costs predict the actual coder sufficiently well; any extra split signaling is smaller than the residual savings.

**Failure cases:** uniform/isotropic clouds, tiny nodes dominated by overhead, misleading entropy estimates, repeated scans, high branching/candidate costs, or output size not tracking estimated entropy.

**Falsification test:** build upstream unchanged, encode identical synthetic and held-out point clouds at matched quantization, decode both, verify point counts and attributes, compare actual bytes and reconstruction errors, and repeat timings. Reject if byte gains are absent or violate the speed/error constraints.

### Results
- No algorithm implementation yet.
- No baseline compression result yet.
- No measured improvement.
- No claim of novelty or superiority.

### Next actions
1. Restore a complete source checkout or obtain a reproducible runner with network access.
2. Build upstream in a clean out-of-tree Release directory and run existing tests.
3. Capture baseline outputs, commands, hardware/compiler details, and repeat timings.
4. Implement one isolated split-cost candidate and compare actual encoded bytes against upstream.
5. Record raw machine-readable results and negative results here and in adjacent result artifacts.


## E001 — Dynamic-programming cyclic face rotation (implementation queued for CI)

- Changed files: `middleout3d/codec.py`, `middleout3d/connectivity_benchmark.py`, `middleout3d/cli.py`, and `tests/test_codec.py`; CI workflow added at `.github/workflows/draco-breaker-research.yml`.
- Mathematical idea: each triangle has three cyclic rotations. The next triangle's first delta depends on the previous rotation's last vertex, so dynamic programming keeps three states and finds the globally minimal raw signed-varint byte cost in O(F) time and O(F) backpointer memory.
- Falsification check: compare complete MO3D payload sizes after zlib, not merely the raw-varint objective; verify exact triangle topology and identical position-error budget.
- Commands run in this chat: GitHub API source reads and source transformations only. No Python test, build, or benchmark has run in this execution turn yet.
- Next: GitHub Actions will run tests and a 3-repeat synthetic benchmark, then commit raw JSON/CSV results and measured summary to this branch. No win is claimed until that run succeeds.


## 2026-10-26 — E001 CI failure follow-up: benchmark report schema

- The first run of the DP face-rotation workflow ([run 40219040601](https://github.com/lalitkumar790/MiddleOut-3D/actions/runs/40219040601)) passed all 28 existing unit tests but failed in the benchmark command while writing CSV.
- Root cause: per-mesh JSON rows included `rotate_dp_face_stream` and aggregate rows computed DP reduction percentages, but per-mesh rows omitted `rotate_dp_size_reduction_vs_source_pct` and `rotate_dp_size_reduction_vs_rotate_pct`. The CSV writer indexed those missing fields, causing the reported `KeyError`. Aggregate DP error-budget and topology flags were also missing even though all four strategies were benchmarked.
- Fix in this revision: emit both DP percentages for every per-mesh result; include DP validity flags in aggregates; test JSON rows, aggregate rows and CSV headers/values with a deterministic small mesh; make CI explicitly validate the aggregate DP schema.
- The failed run remains recorded as a failure. This patch is not considered validated until a subsequent test-and-benchmark workflow succeeds and archives its measured results.


## E001 — Dynamic-programming cyclic face rotation

- GitHub Actions run: https://github.com/lalitkumar790/MiddleOut-3D/actions/runs/40224966639
- Source commit tested: f18ba24d3c9570778119acdcaca290292b739ad3.
- Change: added rotate_dp, a three-state dynamic program that minimizes exact uncompressed signed-varint byte cost across cyclic rotations in fixed face order. Complexity is O(F) time and O(F) backpointer storage.
- Rationale: greedy rotation minimizes each triangle's cost conditioned on the previous index but may sacrifice a better continuation; DP preserves the last-index state needed for the optimal global raw-varint sequence.
- Commands actually run: python -m unittest discover -s tests -v; python -m middleout3d benchmark-connectivity samples --out results/draco-breaker-rotate-dp.json --bits 16 --repeats 3.
- Configuration: 6 deterministic synthetic fixtures, 7 codec methods, 3 vertex orderings, 16-bit positions, 3 timing repetitions.
- Actual complete-payload totals across all fixed mesh/method/vertex-order cases: source=1198590 B; greedy_rotate=1175805 B; DP_rotate=1173698 B; BFS=1312998 B; DP_vs_greedy=+0.1792%; case wins/ties/losses=35/0/91 of 126.
- All strategies were required to pass exact oriented topology and the same position-error budget; workflow fails if any check fails. Per-case raw results and timing medians are in results/draco-breaker-rotate-dp.json and .csv.
- Caveat: the DP objective is raw varint bytes, while the benchmark decision uses actual complete compressed MO3D payload bytes after zlib and headers. Synthetic fixtures are development data; this is not a Draco-vs-MO3D result.
- Next: if DP improves actual bytes, validate on held-out licensed meshes and inspect encode-time overhead; otherwise keep it experimental and test better objectives.

- Timing checkpoint from the archived per-case medians (sum across 126 cases, not wall-clock CI duration): greedy rotate encode medians summed to 16,189.86 ms vs 17,938.74 ms for DP (+10.80%); decode medians summed to 13,092.17 ms vs 13,122.58 ms (+0.23%). This confirms the small 0.1792% byte gain comes with measurable encoder cost and frequent per-case losses, so DP remains opt-in and needs a better objective before any broader adoption.
