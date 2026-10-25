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

Let \(s=D/(\sqrt{3}L)\), where \(D\) is the mesh bounding-box diagonal and \(L=2^B-1\). In the local frame, the first residual component is normal to the base triangle and the remaining two are tangential. MO3D v5 sets

\[
s_n=s/2,\qquad s_t=s\sqrt{11/8}.
\]

This keeps the total squared step budget constant:

\[
s_n^2+2s_t^2 = s^2/4 + 2(11s^2/8)=3s^2.
\]

So its theoretical per-step Euclidean rounding bound \(\sqrt{s_n^2+2s_t^2}/2\) matches the equal-step variant's bound. The normal component gets twice the quantization density while the tangential steps become larger. This does not guarantee a better actual file size or accumulated mesh error; the predictor is recursive, so the implementation still measures each decoded mesh's maximum vertex error and RMSE.

The variant is versioned as MO3D v5. It writes the three local-frame steps to the header so the decoder reproduces them exactly. The older v1–v4 streams remain supported. This is inspired by the non-uniform local-coordinate quantization explored in the tangent-space paper, but it is not a reproduction of their entropy coder or full rate-distortion optimization.

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

1. Extend the five-coder/order study to real-world CAD, scan, and robotics meshes with redistribution rights.
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
