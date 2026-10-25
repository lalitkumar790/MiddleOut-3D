# Geometry-conditioned distance-ranked connectivity — experiment E000

Branch: research/distance-ranked-connectivity
Status: code and tests prepared for CI; benchmark results pending.

## Hypothesis and algorithm

The prototype changes topology representation while keeping the geometry stream fixed to absolute quantized XYZ. It starts from the first triangle and maintains a deterministic queue of directed gate edges. For a gate u→v in a decoded triangle whose opposite vertex is w, predict the new closing vertex as p-hat = p_u + p_v - p_w. Sort all vertex IDs except u,v by (squared Euclidean distance to p-hat, vertex ID). The encoder writes 0 when the gate is a boundary edge; otherwise it writes 1 + rank(x) for the adjacent triangle's opposite vertex x. The decoder selects that rank and appends (v,u,x), preserving orientation.

The ranking uses reconstructed, quantized positions so the encoder and decoder produce the same candidate ordering, including ties. Already-closed edges (two incident decoded triangles) are inferred from edge counts and need no coded symbol. The stream has a DRC1 signature and is wrapped in zlib; a v9 header identifies the connectivity coder separately from the geometry coder.

This is not a reimplementation of Marais, Gain and Shreiner (2007), nor Dvořák et al.'s priority-based encoder. It is a testable adaptation with a deliberately broad candidate set (all vertices except the gate endpoints); candidate-set cost and prediction quality may be poor. The implementation rejects non-manifold edges, duplicate/degenerate faces, inconsistent shared-edge winding and disconnected face components. It supports boundaries.

## Experimental controls

- Compare baseline and distance_ranked_connectivity at the same 16-bit per-axis quantization, same vertex ordering and the same coordinate coder.
- Use six deterministic synthetic fixtures and source/BFS/Morton vertex orderings, with three encode/decode repeats.
- Record complete payload bytes, coordinate and connectivity substream bytes, median encode/decode times, maximum vertex error, RMSE, winding-preserving topology equality, and the common error-budget check.
- Record unsupported cases rather than quietly treating them as successes. A positive result on these fixtures is not a general claim and does not establish superiority to Draco, whose connectivity stream may use EdgeBreaker/valence modes and whose attribute settings must be controlled in a fair full-codec comparison.

## Source material

- Marais, Gain and Shreiner (2007), Distance-Ranked Connectivity Compression of Triangle Meshes: https://diglib.eg.org/items/57a65691-acc2-4d79-bdb4-0a53bf1d8011 — separate topology coding for connected 2-manifold triangle meshes using geometric prediction and distance ranks; reported gains for regular triangulations and caveats for irregular/sliver-heavy data.
- Dvořák, Káčereková, Vaněček and Váša (2023), Priority-based encoding of triangle mesh connectivity for a known geometry: https://diglib.eg.org/items/2b0e5b8d-8052-4fc0-b70f-4d28da9a0598 — prioritize gates with more confident predictions.
- Google Draco bitstream specification: https://google.github.io/draco/spec/ — describes connectivity and geometry coding modes.

The codec uses an idea from modern published research. No claim is made that distance-ranked mesh coding occurs in Piṅgala's Chandaḥśāstra, the Śulbasūtras or Vedānta Deśika's Citra Paddhati.
