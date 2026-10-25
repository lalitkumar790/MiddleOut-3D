# Research notes: MiddleOut-3D and the Prithvi predictor

## Core hypothesis

A geometry-aware encoding can outperform generic byte compression on some 3D mesh datasets. The current hypothesis is narrower: a deterministic mesh-neighbor predictor may produce smaller residual streams than the prototype's absolute-coordinate representation on mesh families whose vertex ordering follows local geometry.

## Inspiration: Atharvaveda 12.1

Atharvaveda Book XII, Hymn 1 is commonly titled the Prithvi Sukta or Hymn to Earth. In Ralph T. H. Griffith's translation, verse 2 describes the Earth through heights, slopes, level plains, and plants with varied properties. See the [Wikisource edition](https://en.wikisource.org/wiki/Atharva-Veda_Samhita/Book_XII/Hymn_1) and [Griffith translation](https://original.sacred-texts.com/hin/av/av12001.htm).

The analogy is “one shared world supporting diverse local forms.” For a mesh, triangle connectivity describes local relationships; the codec uses one neighboring vertex to predict another, then stores only the residual.

This is a modern design inspiration only. We do not claim that the Vedic text gives, encodes, or historically anticipates the algorithm below.

## Prithvi algorithm (implemented)

Given a triangle mesh with vertices $x_i\in\mathbb{R}^3$ and faces $F$:

1. Quantize coordinates using the same axis-aligned bounds and $B$-bit grid as the baseline:
   $Q_i=\operatorname{round}(((x_i-b_{\min})/(b_{\max}-b_{\min}))(2^B-1))$.
2. Build the undirected adjacency implied by all triangle edges.
3. For vertex index $i$, choose its greatest earlier adjacent vertex: $p(i)=\max\{j< i\mid(i,j)\in E\}$. If no such vertex exists, use the zero vector.
4. Predict $\widehat Q_i=Q_{p(i)}$ and store the residual $r_i=Q_i-\widehat Q_i$.
5. Map signed residuals to non-negative integers by zigzag coding, encode each with unsigned varints, and zlib-compress the coordinate stream.
6. Store the same triangle-index stream used by the baseline, so a decoder can reconstruct the face graph and deterministically recompute each parent.

Because every parent has an index smaller than its child, decoding is causal: reconstruct $Q_i=\widehat Q_i+r_i$ in increasing vertex-index order. The residual representation is exact for the quantized integer grid. Geometry remains lossy only because of coordinate quantization.

## Research-informed methods: tangent residuals and weighted prediction

Two relevant works shaped the next prototype:

- Vaněček, Hácha and Váša, **“A Predictor for Triangle Mesh Compression Working in Tangent Space” (GRAPP 2024)**, [paper PDF](https://www.scitepress.org/Papers/2024/123529/123529.pdf). It combines local-coordinate residuals with weighted parallelogram prediction; the authors report improved rate-distortion relative to Draco on their test meshes.
- Váša and Brunnett, **“Exploiting Connectivity to Improve the Tangential Part of Geometry Prediction” (IEEE TVCG, 2013)**, [PubMed record](https://pubmed.ncbi.nlm.nih.gov/23846092/). The paper describes a weighted predictor using known base-triangle angles and valence-derived estimates for the target triangle.

The results of these papers do not automatically transfer to our prototype. Our implementation is a smaller adaptation: it uses our own causal stencil traversal and quantization/varint format, and does not reproduce the full connectivity coding, context models, quantization scheme, or evaluation pipeline used in the publications.

### MO3D v3: local-frame residuals

For a target vertex \(O\), use an earlier base triangle with vertices \(L,R,B\). The classic parallelogram prediction is

\[
\hat v_O=v_L+v_R-v_B.
\]

Construct a deterministic orthonormal frame from the base triangle and prediction. Express the residual in that local frame:

\[
r_{\mathrm{local}}=F^\top(v_O-\hat v_O).
\]

Quantize the three local components with a scalar step derived from the mesh bounding-box diagonal, then zigzag/varint-code them and compress with zlib. Seed vertices that lack a causal stencil use absolute quantized coordinates.

If \(D\) is the bounding-box diagonal and \(L=2^B-1\), the selected scalar step is

\[
s=\frac{D}{\sqrt{3}L}.
\]

Each local component's rounding error is at most \(s/2\), giving a conservative Euclidean bound \(\sqrt{3}s/2=D/(2L)\), matching the baseline quantizer's bounding-box half-diagonal bound. This sets the same worst-case budget, not identical actual distortion; the benchmark measures each reconstruction error directly.

### MO3D v4: valence-weighted tangent prediction

The weighted predictor generalizes the classic parallelogram to

\[
\hat v_O=w_1v_L+w_2v_R+(1-w_1-w_2)v_B.
\]

Let \(\alpha,\beta\) be the known interior angles at \(L,R\) in the base triangle. Estimate the three new-triangle angles from vertex valences \(d_L,d_R,d_O\): first use inverse-valence values \(1/d_i\), then normalize them to sum to \(\pi\); \(\gamma,\delta\) are the estimates at \(L,R\). The implementation uses the weighted-parallelogram relation reported in the literature:

\[
w_1=\frac{\cot\beta+\cot\delta}{\cot\delta+\cot\gamma},
\qquad
w_2=\frac{\cot\alpha+\cot\gamma}{\cot\delta+\cot\gamma}.
\]

For degenerate or ill-conditioned stencils, it falls back to the classic parallelogram predictor. The same deterministic weights and local frame are recomputed by the decoder from topology and previously reconstructed positions, so weights are not stored per vertex. The predictor remains experimental, especially for boundary vertices and irregular valences.

### MO3D v5: finer quantization along the surface normal

The 2024 tangent-space paper reports that local-coordinate quantization need not allocate equal precision to the normal and tangent directions. This is motivated by the fact that normal-direction error can more visibly alter the reconstructed surface. The full paper uses a more sophisticated encoder and evaluates rate-distortion; this implementation tests a small fixed-step allocation.

Let \(s=D/(\sqrt{3}L)\), where \(D\) is the mesh bounding-box diagonal and \(L=2^B-1\). In the local frame, the first residual component is normal to the base triangle and the remaining two are tangential. MO3D v5 tests a normal-step ratio \(r\), with \(r\in\{0.375,0.5,0.625,0.75,0.875\}\), and sets

\[
s_n=rs,\qquad s_t=s\sqrt{\frac{3-r^2}{2}}.
\]

This keeps the squared step budget constant for every ratio:

\[
s_n^2+2s_t^2 = r^2s^2+2\left(\frac{3-r^2}{2}s^2\right)=3s^2.
\]

The theoretical per-step Euclidean rounding bound \(\sqrt{s_n^2+2s_t^2}/2\) therefore matches the equal-step variant's bound. Smaller \(r\) gives finer normal quantization while allowing coarser tangent quantization. This does not guarantee a better actual file size or accumulated mesh error; the predictor is recursive, so each candidate is measured and only a candidate meeting the baseline's conservative maximum-error bound is eligible for selection.

The v5 header stores the three local-frame steps and the chosen normal-step ratio; decoders continue to support v1–v4. The implementation is inspired by the paper's non-uniform local-coordinate quantization, but it is not a reproduction of their entropy coder or full rate-distortion optimizer. The auto selector tests all five normal-step ratios across source, BFS and Morton ordering, alongside the other in-house coders. The benchmark also reports reconstruction error projected onto the decoder's local normal and tangent axes, to test whether extra normal precision actually improves the targeted component.

### Adaptive size selection

The \`auto\` encoder tests all four available coders under source, BFS, and Morton traversal and emits the shortest serialized candidate. This makes the output no larger than any tested candidate for a given mesh and parameter setting, but requires up to 12 encodes. It is a rate-first option, not a fast default. It also does not prove superiority to Draco because the test candidates are our own methods and the current assets are geometry-only.

## Evaluation questions

- Does Prithvi reduce coordinate-stream and total-file size versus the absolute-coordinate baseline at equal position precision?
- How does vertex ordering affect size? The implementation now tests source order, deterministic BFS graph traversal, and 3D Morton/Z-order.
- Which mesh families benefit (grid-like surfaces, CAD parts, spheres, scans, irregular triangulations)?
- Is any improvement retained after accounting for the header, adjacency prediction costs, and decoder time?
- How does it compare with Google Draco when attributes, quantization and distortion constraints are matched?

## Failure modes and limitations

- Poor index order can make a vertex's chosen earlier neighbor geometrically distant, yielding large residuals.
- A varint+zlib residual stream may be larger than fixed-width quantized coordinates compressed by zlib.
- Triangle topology and vertex positions are preserved, but normals, UVs, colors, textures, materials, and source-file metadata are omitted.
- Synthetic fixtures do not establish broad performance claims.
- No claim is made that this codec beats Draco, LZ4, or any production codec.

## Next experiments

1. Extend the ratio-sweep benchmark to real-world CAD, scan, and robotics meshes with redistribution rights.
2. Optimize Python stencil construction, local-frame calculation and residual coding; the tangent variants may save bytes but are much slower on larger fixtures.
3. Evaluate angle-weighted prediction on boundary-heavy and irregular meshes; do not tune it only to our six synthetic fixtures.
4. Add a Draco baseline at comparable distortion and with the same attribute set.
5. Add perceptual and surface-distance metrics, and record peak memory.
6. Explore learned prediction or neural displacement fields only on a carefully chosen task: some recent methods compress many related models together or represent a surface implicitly, so their reported ratios are not directly comparable to our standalone per-mesh bitstreams.

## First vertex ordering results

The first hosted comparison is documented in [BASELINE_RESULTS.md](BASELINE_RESULTS.md) and the [machine-readable JSON](results/vertex_ordering_study_2026-10-25.json) / [CSV](results/vertex_ordering_study_2026-10-25.csv).

At 16 bits per axis over six deterministic synthetic meshes:

- Source order: 61,956 bytes for the absolute baseline and 47,436 bytes for Prithvi (23.4360% lower).
- BFS: 49,634 bytes for the baseline and 36,345 bytes for Prithvi (26.7740% lower than the same-order baseline).
- Morton: 79,687 bytes for the baseline and 69,734 bytes for Prithvi (12.4901% lower than the same-order baseline).

BFS + Prithvi was the smallest of these tested configurations, but it was slower than the matched baseline in the hosted run. Morton performed poorly on this fixture set. These results are exploratory and should not be treated as general conclusions about arbitrary meshes. All 18 mesh/ordering/method combinations passed topology and quantized-coordinate equivalence checks.


## Sanskrit combinatorics and the Chandas coding experiment (MO3D v6)

### Why Piṅgala, rather than claiming a ready-made “Vedic Mathematics” formula?

Jayant Shah's historical study *A History of Piṅgala's Combinatorics* says that the *Chandaḥśāstra* describes methods for listing and indexing metrical patterns and counting patterns with a fixed number of short syllables; the paper discusses the related binomial coefficients and how later interpretations of *meru-prastāra* have been debated. [University of Hyderabad PDF](https://sanskrit.uohyd.ac.in/Algorithms_in_Ancient_India/Material/Pingala.pdf).

The relevant design principle is **enumerate a pattern by its rank, then recover the pattern by unranking**. That has a direct modern analogue in enumerative coding. Fraenkel's 1989 *The use and usefulness of numeration systems* explicitly discusses compression of sparse binary strings using a suitable counting system ([Information and Computation](https://doi.org/10.1016/0890-5401(89)90028-X)). MO3D uses the connection as inspiration; the implementation is a modern combinatorial coder, not an assertion that the exact source algorithm occurs in an ancient text.

### Implemented hypothesis

MO3D v6 \`chandas_tangent\` combines the weighted tangent-space predictor with sparse enumerative coding of its integer stream:

1. The encoder predicts a vertex using a causal weighted-parallelogram stencil, expresses the residual in a local orthonormal frame, and quantizes it at the established conservative error budget.
2. Seed vertices contribute quantized absolute coordinate symbols; predicted vertices contribute signed residual symbols.
3. The flat symbol sequence is partitioned into blocks of 64. In each block, let the set of non-zero positions be \(S=\{s_0<\cdots<s_{k-1}\}\). The codec stores \(k\), the colexicographic combinatorial rank
   \[
   \operatorname{rank}(S)=\sum_{j=0}^{k-1}\binom{s_j}{j+1},
   \]
   and the signed non-zero values. All zero positions are implicit.
4. The rank is stored in the minimum whole number of bytes needed for the \(\binom{n}{k}\) possible subsets, with \(n\) the block length. The stream is then compressed with zlib.
5. The decoder un-ranks each pattern, fills omitted positions with zero, and reconstructs vertices using the same deterministic predictor.

This design is useful only when the non-zero pattern plus its rank costs less than a plain varint stream after compression. zlib already captures zero runs and repeated bytes, so a pattern-specific layer may be redundant. The benchmark is designed to reject the idea if the measured size or speed is worse.

### Other Sanskrit pattern inspiration

Vedānta Deśika's *Pādukā Sahasram* includes a *Citra Paddhati* whose verses are described as using pictorial or structured letter arrangements. A traditional community archive describes it as poetry whose arrangement itself forms a pattern ([Citra Paddhati discussion](https://ramanuja.org/sri/BhaktiListArchives/Article?p=jan2001%2F0197.html)). This is a poetic construction, not an established mesh-compression algorithm. A possible future experiment is to detect repeated local residual blocks or traversal motifs—similar in spirit to a pattern dictionary—but it must earn its place through a real benchmark. For this iteration, Piṅgala's ranking/unranking analogy is more directly expressible as a decoder-symmetric coding rule.

### Modern mesh-compression research used alongside this inspiration

Vaněček, Hácha and Váša (GRAPP 2024), *A Predictor for Triangle Mesh Compression Working in Tangent Space*, combine local coordinate residuals with valence-weighted parallelogram prediction and report improved rate–distortion performance over Draco on their test set ([paper record and abstract](https://dspace.zcu.cz/items/07738464-8ce9-403f-b870-5d6fb1bc3d93)). MO3D already implements exploratory versions of this idea as v3–v5; these versions are not a reproduction of the paper's full codec and do not automatically inherit its published results.

### Evaluation requirements

- Compare v6 against v4 weighted tangent at identical quantization/order and compare both against Draco at a matched maximum-error target.
- Require exact topology reconstruction and a bounded geometric error for every mesh/order/method candidate.
- Record per-mesh bytes and encode/decode times; aggregate results must not hide regressions on small or irregular meshes.
- Keep \`auto\` size-first selection separate from a fast single-method encode path, because evaluating many candidates adds encoding overhead.
- Use public, representative CAD, scanned-object and robotics meshes before making claims beyond the synthetic fixtures.


## Adaptive Chandas v7: fixed enumerative coding did not win, so add a per-block fallback

The first hosted v6 experiment showed that a fixed combinatorial mask is not a free win: across the 18 mesh/ordering combinations (six meshes × source/BFS/Morton), v6 used 174,559 bytes versus 172,180 bytes for weighted tangent (about 1.38% larger overall). It improved a few tiny box fixtures, but grew most larger meshes. This is a useful negative result: zlib and varints already capture many simple zero patterns, and a ranked mask costs metadata and rank bits.

V7 changes the experiment rather than hiding this outcome:

- Stores seed coordinates separately as unsigned quantized values.
- Stores only predictive residuals in the block-coding stream.
- Splits residuals into 64-symbol blocks and, for each block, compares direct signed zigzag-varints with enumerative coding of the non-zero position subset plus the non-zero magnitudes.
- Writes a one-byte block mode and chooses the shorter pre-zlib representation; zlib still compresses the complete stream.
- Uses a new MO3D v7 signature and retains decoders for earlier versions.

The comparison is a local byte-count decision, not a promise of a smaller total file: the new seed framing, residual count, mode flags, and zlib wrapper carry overhead. The hosted v7 benchmark must tell us whether the complete stream beats v4 on the mesh families we tested.

The next step is not automatically adding more Vedic analogies. It is to inspect which blocks choose enumerative mode, measure the share of residuals that are zero, compare v7 against v4 and Draco under the same error target, and then test on public, representative meshes. If the extra coding layer is not useful after overhead, we should drop it or reserve it only for meshes where it wins.


## Indian mathematical pattern traditions: what is grounded, what is analogy

### Piṅgala and enumerative coding

Jayant Shah's historical paper, *A History of Piṅgala's Combinatorics*, describes the *Chandaḥśāstra* as including procedures to list all forms of an n-syllable metre, recover a pattern from its serial position, determine a pattern's serial position, and count patterns with a fixed number of short syllables. It also notes a historiographical debate about attributing particular forms of *meru-prastāra* to Piṅgala. Source: [University of Hyderabad-hosted paper](https://sanskrit.uohyd.ac.in/Algorithms_in_Ancient_India/Material/Pingala.pdf).

The software connection is enumerative coding. A subset of \(k\) nonzero residual positions inside a block of \(n\) symbols has \(\binom{n}{k}\) possibilities, so a rank requires at least \(\lceil\log_2\binom{n}{k}\rceil\) bits in an ideal fixed-length representation. MO3D v6/v7 use a combinatorial-number-system rank for the nonzero positions, plus the nonzero residual values. This is a modern implementation inspired by ranking/unranking—not a claim that Piṅgala's text specifies this particular codec.

**Current empirical finding:** on the six synthetic meshes and three orderings in the archived extended run, fixed sparse enumeration v6 and the adaptive v7 variant did not beat weighted tangent coding in aggregate total size. v6 was about 1.4% larger; v7 was also slightly larger. Per-mesh exceptions exist, but we must not present the historical connection as a compression gain without evidence. The block coder may still be useful on different residual distributions.

### Śulbasūtras and geometry

The Śulbasūtras are a real source of geometric constructions, including right-triangle relations and transformations between shapes/areas. See S. G. Dani's [2024 historical review](https://doi.org/10.1007/978-3-031-40846-5_114) and Dani & Limaye's [2021 discussion](https://publications.azimpremjiuniversity.edu.in/2784/). The potential inspiration for MiddleOut-3D is to seek representations that preserve a clearly stated geometric invariant while changing coordinate systems. The tangent-space codec is a modern computer-graphics method; we do not claim it is derived from a Śulbasūtra.

### Vedānta Deśika and *Citra Paddhati*

The *Citra Paddhati* in *Pādukā Sahasram* is described in a Tirumala Tirupati Devasthanams publication as using patterned arrangements of verses. Source: [Vedantha Deshika publication](https://ebooks.tirumala.org/downloads/Vedantha%20Deshika.pdf). This is a literary pattern tradition, not evidence of a mesh-compression technique. A possible engineering analogy is that traversal order can be a designed path through a graph, but a Desika-inspired traversal must be evaluated like any other heuristic; no special historical claim is made.

### Modern papers that already outperform naive approaches

- Vaněček, Hácha and Váša, [*A Predictor for Triangle Mesh Compression Working in Tangent Space* (GRAPP 2024)](https://dspace.zcu.cz/items/07738464-8ce9-403f-b870-5d6fb1bc3d93), combines local-coordinate residuals with weighted parallelogram prediction and reports improved rate-distortion over Draco on its benchmark. Our tangent methods are exploratory adaptations, not an exact reproduction.
- Ren et al., [*Neural Compression for 3D Geometry Sets* (ICCV 2025)](https://openaccess.thecvf.com/content/ICCV2025/html/Ren_Neural_Compression_for_3D_Geometry_Sets_ICCV_2025_paper.html), uses a learned implicit representation and shared decoder weights to compress large sets of meshes. The reported up-to-900× figure concerns a particular collection-compression setup and is not directly comparable to one standalone geometry bitstream.

## New experiment: predictive-cost-guided vertex ordering

The original source/BFS/Morton experiment suggests the order in which a mesh is traversed can materially change residual and connectivity streams. The new \`predictive\` ordering is a greedy, encoder-side heuristic:

1. Start from a deterministic large-area seed triangle (fallbacks handle unreferenced vertices and disconnected pieces).
2. Maintain vertices whose candidate triangle stencils become available as earlier neighbors are visited.
3. Estimate residual-varint cost under a classic parallelogram predictor and a valence-weighted predictor.
4. Greedily visit the available candidate with the lowest estimated cost; ties break deterministically by error, predictor ID, and stencil.
5. Remap face indices consistently and benchmark it alongside source, BFS, and Morton orders under each codec and against Draco.

Unlike the historical text, this heuristic is modern graph traversal. The connection to the older pattern traditions is only the broad idea that an ordering can be designed rather than fixed. The key hypothesis is that cost-driven ordering will reduce the residual and face-index streams enough to offset its search overhead.

The current CI workflow is testing the new order on six synthetic meshes, 16 bits per axis, and five timed repetitions. Required acceptance checks are: permutation validity, topology equivalence after remapping, matching baseline/Prithvi quantized positions, geometry-error bounds for the tangent variants, and a Draco comparison at a measured error budget. The benchmark will decide whether this ordering should be kept or reverted.

## Historical note on “Vedic Mathematics”

The popular 16-sūtra system in Bharati Krishna Tirtha's modern book is not the same as a well-established corpus of algorithmic sutras in extant Vedic texts. S. G. Dani's *Vedic Mathematics in Perspective* discusses the weak documentary basis for attributing that system directly to an extant Atharvaveda appendix: [TIFR PDF](https://www.math.tifr.res.in/~dani/vmissc.pdf). For reproducible research, this project prioritizes identifiable sources such as Piṅgala's *Chandaḥśāstra* and the Śulbasūtras, and treats all modern analogies as hypotheses.


## Predictive-cost traversal: empirical result and rejection from auto-selection

The first predictive ordering assigned the next vertex by estimated signed-residual varint length to the latest visited adjacent vertex. The heuristic was changed to an O((V+E) log V) frontier traversal, then compared across six synthetic OBJ fixtures at 16-bit positions against source, BFS and Morton orderings, seven in-house coders, and a DracoPy 2.0.0 sweep. Full records: [JSON](results/predictive_ordering_study_2026-10-25.json), [CSV](results/predictive_ordering_study_2026-10-25.csv), [CI run](https://github.com/lalitkumar790/MiddleOut-3D/actions/runs/40195070244).

The result is negative. Predictive ordering increased aggregate bytes versus BFS for every in-house method: baseline +38.9%, Prithvi +45.9%, tangent +63.1%, weighted tangent +52.2%, normal-fine tangent +51.8%, Chandas +51.5%, and adaptive Chandas +50.0%. It was not the best method/order combination for any of the six fixtures. Baseline encoding took 411.06 ms summed across the six meshes versus 44.92 ms for BFS and 16.51 ms for source order; these are one-repeat CI timings without a separate warmup. The order is now available for experiments but excluded from the auto search.

The failure is informative: optimizing estimated coordinate residuals alone ignores the complete payload, particularly face-index deltas, traversal construction cost, and each coder's own prediction stencil. Any next traversal objective must optimize or approximate the *combined coordinate and connectivity stream*, then verify its total serialized size and speed.

## Relevant mesh-connectivity literature: next target

The current prototype serializes the face array as flat zigzag/varint index deltas followed by zlib. This is simple but leaves connectivity compression well behind established topology encoders.

- Rossignac and Szymczak's 1999 EdgeBreaker connectivity method encodes a triangulated planar graph using a short CLERS symbol stream; their follow-up reports entropy-coded lengths around 0.91–1.26 bits per triangle on their evaluated meshes ([Wrap&Zip / EdgeBreaker paper](https://www.sciencedirect.com/science/article/pii/S0925-7721(99)00028-0)). This is a connectivity-specific representation, not directly comparable to our complete bitstreams without a matched mesh corpus.
- Alliez and Desbrun's 2001 [Valence-Driven Connectivity Encoding for 3D Meshes](https://diglib.eg.org/items/5318ef03-07a9-4d30-9be5-d0adc309d75f) exploits vertex-valence patterns for lossless connectivity compression.
- Marais, Gain and Shreiner's 2007 [Distance-Ranked Connectivity Compression of Triangle Meshes](https://diglib.eg.org/items/57a65691-acc2-4d79-bdb4-0a53bf1d8011) traverses mesh edges and ranks candidate closing vertices by their distance to a predicted position. This is especially relevant to our next experiment: use geometry to choose among connectivity continuations, then code the small rank instead of writing every face index.

The next algorithm experiment should target face/connectivity coding rather than adding another coordinate predictor. A safe first version should add a new, opt-in connectivity stream (preserving triangle winding), round-trip it, and compare complete serialized sizes and decoding time against the current index-delta stream and Draco. The historic connection to *Citra Paddhati* remains analogy only; these connectivity algorithms are modern mesh-compression research.
