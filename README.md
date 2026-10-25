# MiddleOut-3D

**A Pied Piper-inspired research project for 3D geometry compression.** This is an experimental prototype—not a claim that it beats Draco, LZ4, or other established codecs.

The first milestone is a repeatable measurement pipeline. It includes a small geometry-only codec and reports size, encoding and decoding times, topology preservation, and positional error. It also compares gzip on the exact original file bytes, while clearly marking why that size comparison is not apples-to-apples.

## Why 3D data?

3D meshes contain both coordinates and connectivity. Regular mechanical geometry, smooth surfaces, repeated structures, and large collections of related models can have patterns that a specialized representation might exploit. But there is no universal compression ratio, and lossy neural geometry methods must be compared at equivalent reconstruction quality.

Relevant existing work:

- [Google Draco](https://github.com/google/draco) — established open-source compression for 3D meshes and point clouds.
- [A Predictor for Triangle Mesh Compression Working in Tangent Space (GRAPP 2024)](https://www.scitepress.org/Papers/2024/123529/123529.pdf) — combines weighted parallelogram prediction with local-frame residuals; its authors report better rate-distortion than Draco on their evaluated meshes. Our tangent methods are a smaller research adaptation, not a reproduction of their full codec.
- [Exploiting Connectivity to Improve the Tangential Part of Geometry Prediction (2013)](https://pubmed.ncbi.nlm.nih.gov/23846092/) — uses valence-informed weighted parallelogram prediction; this informs our MO3D v4 predictor.
- The 2024 tangent-space paper also studies non-uniform precision in local coordinates: keeping more precision along the surface normal while relaxing tangential precision can improve rate-distortion at a comparable error budget. Our v5 experiment tests a simple fixed version of this idea, not the paper's complete codec.
- [MPEG G-PCC](https://www.mpeg.org/standards/MPEG-I/9/) — standardized geometry-based point-cloud compression.
- [Neural Compression for 3D Geometry Sets (ICCV 2025)](https://openaccess.thecvf.com/content/ICCV2025/html/Ren_Neural_Compression_for_3D_Geometry_Sets_ICCV_2025_paper.html) — neural compression for collections of 3D mesh models, reporting up to 900× in its studied setting. That result is for a specific representation and task, not a universal per-file promise.
- [Mesh Compression with Quantized Neural Displacement Fields (2025)](https://diglib.eg.org/items/d54ad053-5b75-49a3-91a4-1750449b7418) — neural displacement-field approach for lossy mesh compression.

## Indian mathematical traditions: research inspiration, not claims of a hidden codec

We are testing ideas motivated by documented mathematical traditions and classical patterned writing, but the resulting algorithms are modern implementations and must earn their place in controlled benchmarks.

- **Piṅgala's *Chandaḥśāstra*** describes enumeration and indexing of metrical patterns and counting patterns with a given number of short syllables. Jayant Shah's historical study [A History of Piṅgala's Combinatorics](https://sanskrit.uohyd.ac.in/Algorithms_in_Ancient_India/Material/Pingala.pdf) discusses the mathematics and points out that some later interpretations of *meru-prastāra* are debated. We adapted the rank/unrank principle into MO3D v6/v7 sparse residual coding. It is an experiment inspired by enumerative coding, not a claim that the exact codec appears in the text.
- **The Śulbasūtras** document geometric constructions, including right-triangle relationships and shape/area transformations. See S. G. Dani's [historical review](https://doi.org/10.1007/978-3-031-40846-5_114) and Dani & Limaye's [discussion of geometric constructions](https://publications.azimpremjiuniversity.edu.in/2784/). These texts are a useful reminder to express geometry through invariants and constructions; our tangent-frame predictor is modern computer graphics, not a direct Śulbasūtra algorithm.
- **Vedānta Deśika's *Pādukā Sahasram*** includes the *Citra Paddhati*, a sequence of poetic compositions with patterned arrangements. A [Tirumala Tirupati Devasthanams publication](https://ebooks.tirumala.org/downloads/Vedantha%20Deshika.pdf) describes examples of patterned reading. These are sophisticated literary structures, not an established compression method. They may inspire graph-walk or pattern-ordering hypotheses, but any benefit has to be measured.
- **Modern “Vedic Mathematics” sutras need historical care.** S. G. Dani's [Vedic Mathematics in Perspective](https://www.math.tifr.res.in/~dani/vmissc.pdf) discusses why the claim that the familiar 16-sutra system is directly evidenced in extant Vedic texts is disputed. We therefore use traceable primary-text traditions (such as Piṅgala's combinatorics and the Śulbasūtras) where possible rather than attributing every modern shortcut to the Vedas.

## Current prototype

MO3D has seven versioned coordinate coders:

- **MO3D v1 baseline:** quantized XYZ coordinates stored as fixed-width integers and compressed with zlib.
- **MO3D v2 Prithvi:** quantized coordinates encoded as signed residuals from a deterministic earlier mesh-neighbor, zigzag-coded, varint-encoded, then compressed with zlib.
- **MO3D v3 tangent:** an unweighted parallelogram geometry predictor with residuals expressed in a local orthonormal frame.
- **MO3D v4 weighted tangent:** a valence-informed weighted parallelogram predictor with residuals expressed in the same kind of local frame. The weights approximate local triangle angles from vertex valences and combine them with the known base-triangle angles, following the idea of published weighted-parallelogram research.
- **MO3D v5 normal-fine tangent:** uses the weighted predictor, but quantizes the local normal residual more finely than the two tangential residuals.
- **MO3D v6 Chandas:** the first, fixed enumerative variant; it ranks non-zero positions in each 64-symbol residual block but also encodes seed values in that pattern stream.
- **MO3D v7 adaptive Chandas:** separates absolute seed coordinates from prediction residuals, then chooses per 64-symbol residual block between direct signed varints and an enumeratively ranked non-zero-position pattern. The intent is to avoid paying the sparse-pattern overhead on dense blocks. It is inspired by pattern enumeration in Piṅgala's *Chandaḥśāstra*, not a claim that the exact coding technique appears in that text.

The weighted predictor uses the form

\[
\hat v_O=w_1v_L+w_2v_R+(1-w_1-w_2)v_B
\]

with angle-derived weights inspired by the referenced research. This is a research adaptation, not an exact reproduction of the 2024 paper's full implementation. MO3D retains all earlier decoders and uses a different magic signature for each format version.

### Chandas enumerative residual coding (MO3D v6)

Piṅgala's *Chandaḥśāstra* is a historical source for combinatorial procedures that list and index metrical patterns and count patterns by the number of short syllables; Jayant Shah surveys the methods and their debated historical interpretations in [A History of Piṅgala's Combinatorics](https://sanskrit.uohyd.ac.in/Algorithms_in_Ancient_India/Material/Pingala.pdf). We borrow the *pattern-enumeration* idea as a modern coding hypothesis.

For a block of `n` residual symbols, let the non-zero positions be `S = {s_0 < s_1 < ... < s_(k-1)}`. MO3D v6 ranks the position set with the combinatorial number system:

\[
\operatorname{rank}(S)=\sum_{j=0}^{k-1}\binom{s_j}{j+1}
\]

The stream stores (k), the rank using enough bits for one of the (\binom{n}{k}) possible subsets, and the non-zero signed values. Zero positions are implicit. Current block size is 64; the resulting sparse stream is then compressed with zlib. V6 uses this representation for every symbol block, while v7 keeps the same rank/unrank option but switches to direct signed varints whenever they are no longer than the sparse representation for that block. V6's first benchmark was mixed and slightly larger overall than v4, which motivated the adaptive v7 format. This is connected to modern **enumerative coding**: Fraenkel's 1989 paper discusses number systems for compression of sparse binary strings ([Information and Computation](https://doi.org/10.1016/0890-5401(89)90028-X)). It is not a direct transcription of a Sanskrit algorithm, and zlib may already encode zeros efficiently—so we measure whether this extra layer earns its overhead.

### Adaptive Chandas residual coding (MO3D v7)

V7 separates seed vertices (absolute quantized XYZ triples) from predicted-vertex residuals. Each 64-symbol residual block is encoded in whichever local representation has the lower pre-zlib byte count: ordinary signed zigzag-varints, or the combinatorial rank of its non-zero positions plus only those non-zero values. A one-byte mode flag makes the block decoder unambiguous. This can avoid the largest known weakness of fixed enumerative coding: paying a pattern rank even when most entries are non-zero.

That does not guarantee the full file is smaller than v4: the seed/residual framing and mode flags add overhead, and zlib may already compress many zero runs. The benchmark must verify whether the adaptive layer wins on the complete compressed stream.

### Non-uniform normal/tangent quantization (MO3D v5)

Let the equal-step local-frame quantizer use a step `s = D/(sqrt(3)*L)`, where `D` is the bounding-box diagonal and `L = 2^B - 1`. MO3D v5 tests a normal-step ratio `r` and uses

```text
s_normal  = r * s
s_tangent = s * sqrt((3 - r^2) / 2)   # for each tangential component
```

for `r` in `{0.375, 0.5, 0.625, 0.75, 0.875}`. Smaller `r` means finer quantization along the surface normal. This preserves the squared step budget:

```text
s_normal^2 + 2 * s_tangent^2 = 3 * s^2
```

and therefore the same conservative per-step Euclidean rounding-error ceiling `D/(2*L)`. The encoder records the actual three steps in the stream header. The benchmark selects the smallest ratio candidate that remains within the baseline's measured maximum-error budget, then reports normal- and tangent-direction reconstruction error separately. This is a hypothesis to measure, not a guaranteed rate-distortion improvement.

**Adaptive option:** `--method auto` tests seven single-setting in-house coders under source, BFS, and Morton orderings, plus five normal-step ratios for MO3D v5 under each ordering: up to 33 candidate bitstreams per mesh. It selects the shortest candidate that meets the conservative error bound, so encoding can be much slower; use it when file size matters more than encode time. The separate predictive ordering remains experimental and is excluded from `auto` because its first benchmark was larger and slower. The Draco comparison uses a bit-depth sweep and selects the smallest Draco stream that meets the baseline's conservative per-mesh maximum-error bound.

- **source:** original vertex order.
- **bfs:** deterministic breadth-first graph traversal, with components and neighbors visited in sorted order.
- **morton:** deterministic 3D Morton/Z-order traversal, sorting vertices by a spatial locality code.
- **predictive:** greedy traversal that prioritizes vertices with the smallest estimated local predictor-residual cost. This is a new heuristic, not an established Vedic algorithm; benchmark results decide whether it stays.

The encoder remaps triangle indices consistently, so each traversal represents the same surface. With BFS, Morton, or predictive ordering, the decoded mesh uses the selected reordered vertex indexing rather than recovering the source file's original vertex IDs; current MO3D is geometry-only and does not preserve external per-vertex attributes. The benchmark maps decoded vertices and faces back to source indexing for validation.

Both methods share the same quantizer, metadata and triangle-index stream. This makes the comparison useful for isolating the coordinate coder, though the total file still contains headers and zlib stream overhead.

**Important limitation:** both methods are lossy in position and geometry-only. They preserve triangle index connectivity and reconstructed quantized vertex positions, but drop normals, UV coordinates, colors, textures, materials, and source-format metadata. Do not use this experimental codec as a replacement for production CAD, engineering, or archival data.

## Prithvi: inspiration, not a historical claim

The name is a modern engineering analogy inspired by Atharvaveda 12.1, the *Prithvi Sukta*. Verse 2 describes Earth in terms of heights, slopes, plains, and plants with varied properties. The analogy we borrow is **one shared world supporting many different local forms**: let mesh connectivity predict nearby geometry so that the encoder stores differences, rather than every coordinate independently.

This does **not** imply that the Atharvaveda states or anticipates this mathematical compression algorithm. The predictor is a contemporary, falsifiable engineering hypothesis.

Reference translations: [Atharva-Veda Samhita, Book XII, Hymn 1 (Wikisource)](https://en.wikisource.org/wiki/Atharva-Veda_Samhita/Book_XII/Hymn_1) and [Ralph T. H. Griffith translation (Internet Sacred Text Archive)](https://original.sacred-texts.com/hin/av/av12001.htm).

### Mathematical design

Let original vertex coordinates be $x_i\in\mathbb{R}^3$, per-axis bounds be $b_{\min},b_{\max}$, and precision be $B$ bits. First quantize each coordinate to the integer grid:

\[
Q_i=\operatorname{round}\left(
\frac{x_i-b_{\min}}{b_{\max}-b_{\min}}(2^B-1)
\right)
\]

For constant axes, the normalized coordinate is set to zero. Faces define a mesh adjacency graph $G=(V,E)$. For vertex index $i$, choose the greatest adjacent index lower than $i$:

\[
p(i)=\max\{j\mid j<i,\ (i,j)\in E\}
\]

If no earlier neighbor exists, use the zero vector as the predictor; otherwise $\widehat Q_i=Q_{p(i)}$. The encoder stores the signed residual:

\[
r_i=Q_i-\widehat Q_i
\]

Each signed integer is mapped to a non-negative integer using zigzag coding ($2r$ for $r\ge0$, otherwise $-2r-1$), encoded as a variable-length integer, and compressed with zlib. Since $p(i)<i$, the decoder can reconstruct in vertex-index order:

\[
Q_i=\widehat Q_i+r_i
\]

The decoder recomputes parents from the face stream, so there is no separate parent table. The prediction stream is exact with respect to the quantized grid; the only geometric loss remains the original quantization step.

### Why this may help—and why it may fail

When a vertex's earlier adjacent neighbor is geometrically nearby, its residuals can have small magnitudes and require fewer varint bytes. But vertex ordering is crucial: non-local index assignments can yield large residuals, and the predictor may encode some meshes worse than the absolute baseline. zlib can also compress absolute integer streams efficiently. The benchmark therefore measures Prithvi **against the baseline at the same bit depth** instead of assuming it is better.

## Quick start

Python 3.10+ is recommended.

```bash
python -m venv .venv
# Windows PowerShell: .venv\\Scripts\\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt

# Optional benchmark dependency: Google Draco comparison via DracoPy
python -m pip install -r requirements-benchmark.txt

# Generate reproducible OBJ fixtures without downloading anything
python -m middleout3d generate-fixtures --out samples

# Run the first benchmark; JSON and CSV reports are written
python -m middleout3d benchmark samples --out results/baseline.json --bits 16 --repeats 5

# Encode with the Prithvi predictor, preserving source order
python -m middleout3d encode samples/wavy_grid.obj --out results/wavy-grid.mo3d --bits 16 --method prithvi

# Encode with weighted tangent prediction and breadth-first ordering
python -m middleout3d encode samples/icosphere.obj --out results/icosphere-weighted.mo3d --bits 16 --method weighted_tangent --ordering bfs

# Try finer precision along the local surface normal
python -m middleout3d encode samples/icosphere.obj --out results/icosphere-normal-fine.mo3d --bits 16 --method normal_fine_tangent --ordering bfs --normal-step-ratio 0.375

# Search all coders and all three orderings, retaining the smallest valid bitstream
python -m middleout3d encode samples/wavy_grid.obj --out results/wavy-grid-auto.mo3d --bits 16 --method auto

# Benchmark MO3D candidates and Google Draco; reports include source, BFS,
# Morton, per-mesh adaptive winner, size, timing, and reconstruction error
python -m middleout3d benchmark samples --out results/ordering-study.json --bits 16 --repeats 5

# Decode to a standard mesh file
python -m middleout3d decode results/icosphere.mo3d --out results/icosphere-restored.obj

# Run unit tests
python -m unittest discover -s tests -v
```

Supported mesh input formats depend on trimesh; starter fixtures are OBJ. The decode command supports OBJ, PLY, STL, and OFF output.

## How to read the benchmark

- `gzip_lossless_bytes`: gzip result for the original file bytes, including original formatting and any attributes in that file.
- `mo3d_lossy_geometry_bytes`: absolute-coordinate baseline size containing only geometry and triangle topology.
- `prithvi_bytes`, `tangent_bytes`, `weighted_tangent_bytes`, and `normal_fine_tangent_bytes`: total coder sizes for each ordering.
- `*_size_reduction_vs_baseline_pct`: size difference relative to the absolute baseline under the same ordering.
- `normal_fine_tangent_steps` and `normal_fine_tangent_normal_step_ratio`: selected local-frame quantization steps and ratio for MO3D v5.
- `normal_fine_tangent_normal_component_rmse` / `normal_fine_tangent_tangential_component_rmse`: reconstruction errors projected into the decoder's local normal and tangent axes.
- `normal_fine_tangent_ratio_sweep_candidates`: per-ratio size, timing, geometry-error, and directional-error results.
- `*_geometry_max_vertex_error` and `*_geometry_rmse_vertex_distance`: measured distortion for each coder.
- `best_candidate_method`, `best_candidate_ordering`, and `best_candidate_bytes`: smallest bitstream among the four in-house coders and three orderings for that mesh.
- `adaptive_encode_sweep_estimate_ms`: sum of the in-house candidate median encode times, a rough estimate of the work an exhaustive search requires.
- `draco_bytes`, `draco_quantization_bits`, `draco_max_vertex_error`, `draco_rmse_vertex_distance`, and encode/decode timings: Google Draco via DracoPy. The benchmark sweeps several bit depths around the requested precision and selects the smallest Draco bitstream meeting the baseline's conservative per-mesh maximum-error bound. Actual error is reported alongside size.
- `mo3d_source_to_encoded_ratio`: included as a rough exploratory signal only; **it is not a fair codec comparison**, because MO3D is lossy and drops attributes.
- `geometry_max_vertex_error` / `geometry_rmse_vertex_distance`: distortion between corresponding source vertices and reconstructed vertices.
- `topology_exact`: verifies triangle index connectivity is unchanged.

The benchmark uses repeated runs and reports median wall-clock time. Timing is sensitive to CPU, Python, cache state, input size and system load. Do not compare numbers from different machines as if they were a controlled experiment.

## GitHub Actions

- **Tests** run on pushes, pull requests, and manual dispatch across Python 3.10, 3.12, and 3.13. The workflow runs unit tests and CLI encode/decode smoke tests.
- **Benchmark sample meshes** runs on changes to the codec, tests or workflow, and can also be manually triggered from the Actions tab. It installs the optional DracoPy package, compares all seven in-house coders under source, BFS, Morton, and predictive orderings against Google Draco, checks topology and in-house error bounds, and uploads JSON/CSV reports. Manual dispatch accepts position-bit and repeat-count inputs.

## Research roadmap

1. Establish stable baseline data and test correctness.
2. Add a Draco baseline with matched geometry precision and preserved attributes where supported.
3. Evaluate Prithvi residual coding across multiple vertex orderings and mesh families; compare it against the absolute-coordinate baseline.
4. Add a Draco baseline with equivalent attributes and measured reconstruction error.
5. Separate lossless mesh/attribute compression from lossy geometric quantization.
6. Investigate stronger predictors, local coordinate frames, face-index entropy coding, and file/model-specific structure.
7. Evaluate point clouds and repeated CAD assemblies after mesh benchmarks are trustworthy.
8. Explore neural representations only with fixed distortion targets and full accounting for model weights, per-model codes, encode time, decode time, and decoder size.

## What would count as a win?

A published result must compare equivalent payloads and attribute sets, with the same reconstruction-quality constraint, on the same hardware. Report compression ratio, encode/decode throughput, peak memory where practical, error metrics, and all test files. An algorithm that wins only on our synthetic fixture should be described as a workload-specific result, not a general breakthrough.

## Security and correctness

MO3D v1/v2 is experimental. The decoder validates headers, stream lengths, coordinate counts, and triangle indices, but this has not been audited for hostile input or production use. Do not decode untrusted files in a privileged workflow.

## Predictive-order experiment: negative result

A second hosted run compared the greedy predictive-cost ordering with source/BFS/Morton, all seven in-house coders and Draco. Full machine-readable results are archived in [the GitHub Actions artifact for run 40195070244](https://github.com/lalitkumar790/MiddleOut-3D/actions/runs/40195070244) (one timing repetition per operation; encoded sizes are deterministic for these settings).

Across the six synthetic meshes, predictive ordering was worse than both source order and BFS in aggregate for every in-house coder:

| Coder | Source total | BFS total | Predictive total |
|---|---:|---:|---:|
| Baseline | 62,652 B | 50,330 B | 69,922 B |
| Prithvi | 48,132 B | 37,041 B | 54,050 B |
| Tangent | 49,044 B | 36,077 B | 58,852 B |
| Weighted tangent | 53,828 B | 41,869 B | 63,712 B |
| Normal-fine tangent | 54,259 B | 42,297 B | 64,217 B |
| Chandas | 54,570 B | 42,669 B | 64,628 B |
| Adaptive Chandas | 53,814 B | 42,421 B | 63,616 B |

The predictive ordering was also markedly slower to encode than BFS (for the baseline on the icosphere, 132.7 ms vs 13.9 ms in this single-repeat run). It was never the best in-house coder/ordering combination for any of the six fixture meshes. Accordingly, it remains an opt-in experiment but is no longer considered by `--method auto`. This is a useful negative result: a heuristic that minimizes an estimated coordinate-residual cost can still worsen the complete stream because it ignores face-index coding and other interactions.

## Measured baseline, Prithvi and vertex ordering

See [`BASELINE_RESULTS.md`](BASELINE_RESULTS.md) for the full hosted experiments. The archived [vertex-ordering JSON](results/vertex_ordering_study_2026-10-25.json) and [CSV](results/vertex_ordering_study_2026-10-25.csv) record the first source/BFS/Morton study. A new predictive-cost ordering is now under CI evaluation against the baseline, Prithvi, tangent methods, and Draco.

For six synthetic fixtures at 16 bits per axis:

| Ordering | Absolute baseline total | Prithvi total | Prithvi reduction vs same ordering |
|---|---:|---:|---:|
| Source | 61,956 B | 47,436 B | 23.4360% |
| BFS | 49,634 B | 36,345 B | 26.7740% |
| Morton | 79,687 B | 69,734 B | 12.4901% |

BFS + Prithvi was the smallest tested configuration, but the predictor and BFS ordering were slower than the baseline in the hosted measurements. Morton performed worse on this fixture set. These results are exploratory and do not establish superiority over Draco or LZ4.
