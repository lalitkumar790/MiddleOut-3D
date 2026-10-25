import json
import struct
import unittest
import numpy as np
import trimesh

from middleout3d.codec import CodecError, decode_mesh, encode_mesh, reorder_mesh, vertex_order_for_mesh


class CodecTests(unittest.TestCase):
    def setUp(self):
        mesh = trimesh.creation.icosphere(subdivisions=2)
        self.vertices = np.asarray(mesh.vertices, dtype=np.float64)
        self.faces = np.asarray(mesh.faces, dtype=np.int64)

    def test_roundtrip_topology_is_exact_and_positions_are_bounded(self):
        bits = 16
        payload = encode_mesh(self.vertices, self.faces, bits=bits)
        vertices, faces, header = decode_mesh(payload)
        self.assertTrue(np.array_equal(faces, self.faces))
        self.assertEqual(len(vertices), len(self.vertices))
        max_error = np.linalg.norm(vertices - self.vertices, axis=1).max()
        half_step = (self.vertices.max(axis=0) - self.vertices.min(axis=0)) / (2 * ((1 << bits) - 1))
        self.assertLessEqual(max_error, np.linalg.norm(half_step) + 1e-12)
        self.assertEqual(header["version"], 1)

    def test_higher_precision_is_no_worse_than_lower_precision(self):
        low, _, _ = decode_mesh(encode_mesh(self.vertices, self.faces, bits=8))
        high, _, _ = decode_mesh(encode_mesh(self.vertices, self.faces, bits=16))
        low_err = np.linalg.norm(low - self.vertices, axis=1).max()
        high_err = np.linalg.norm(high - self.vertices, axis=1).max()
        self.assertLessEqual(high_err, low_err)


    def test_prithvi_predictor_roundtrip_matches_baseline_quantization(self):
        baseline_payload = encode_mesh(self.vertices, self.faces, bits=16, method="baseline")
        prithvi_payload = encode_mesh(self.vertices, self.faces, bits=16, method="prithvi")
        baseline_vertices, baseline_faces, _ = decode_mesh(baseline_payload)
        vertices, faces, header = decode_mesh(prithvi_payload)

        self.assertTrue(np.array_equal(faces, self.faces))
        self.assertTrue(np.array_equal(faces, baseline_faces))
        self.assertTrue(np.array_equal(vertices, baseline_vertices))
        self.assertIn("prithvi", header["coordinate_coder"])
        self.assertEqual(header["version"], 2)
        self.assertEqual(prithvi_payload[:5], bytes([77, 79, 51, 68, 2]))
        self.assertEqual(baseline_payload[:5], bytes([77, 79, 51, 68, 1]))
        self.assertLessEqual(
            np.linalg.norm(vertices - self.vertices, axis=1).max(),
            np.linalg.norm(
                (self.vertices.max(axis=0) - self.vertices.min(axis=0))
                / (2 * ((1 << 16) - 1))
            ) + 1e-12,
        )

    def test_prithvi_rejects_unsupported_method(self):
        with self.assertRaises(CodecError):
            encode_mesh(self.vertices, self.faces, method="magic")

    def test_bfs_and_morton_are_valid_permutations_and_preserve_face_mapping(self):
        for ordering in ("source", "bfs", "morton"):
            with self.subTest(ordering=ordering):
                order = vertex_order_for_mesh(self.vertices, self.faces, ordering)
                self.assertEqual(len(order), len(self.vertices))
                self.assertTrue(np.array_equal(np.sort(order), np.arange(len(self.vertices))))
                reordered_vertices, reordered_faces, returned_order = reorder_mesh(
                    self.vertices, self.faces, ordering
                )
                self.assertTrue(np.array_equal(order, returned_order))
                self.assertTrue(np.array_equal(reordered_vertices, self.vertices[order]))
                self.assertTrue(np.array_equal(order[reordered_faces], self.faces))
                self.assertTrue(np.all(reordered_faces >= 0))
                self.assertTrue(np.all(reordered_faces < len(self.vertices)))

    def test_all_orderings_roundtrip_baseline_and_prithvi(self):
        for ordering in ("source", "bfs", "morton"):
            order = vertex_order_for_mesh(self.vertices, self.faces, ordering)
            for method in ("baseline", "prithvi"):
                with self.subTest(ordering=ordering, method=method):
                    payload = encode_mesh(
                        self.vertices, self.faces, bits=16, method=method, ordering=ordering
                    )
                    decoded_vertices, decoded_faces, header = decode_mesh(payload)
                    restored_vertices = np.empty_like(decoded_vertices)
                    restored_vertices[order] = decoded_vertices
                    restored_faces = order[decoded_faces]
                    self.assertTrue(np.array_equal(restored_faces, self.faces))
                    self.assertTrue(np.allclose(restored_vertices, self.vertices, atol=1e-4))
                    self.assertEqual(header["vertex_ordering"], ordering)

    def test_prithvi_and_baseline_positions_equal_for_each_ordering(self):
        for ordering in ("source", "bfs", "morton"):
            with self.subTest(ordering=ordering):
                base, _, _ = decode_mesh(encode_mesh(
                    self.vertices, self.faces, bits=16, method="baseline", ordering=ordering
                ))
                predicted, _, _ = decode_mesh(encode_mesh(
                    self.vertices, self.faces, bits=16, method="prithvi", ordering=ordering
                ))
                self.assertTrue(np.array_equal(base, predicted))

    def test_tangent_codec_roundtrip_and_error_bound_across_orderings(self):
        levels = (1 << 16) - 1
        diagonal = np.linalg.norm(self.vertices.max(axis=0) - self.vertices.min(axis=0))
        error_bound = diagonal / (2 * levels)
        for ordering in ("source", "bfs", "morton"):
            with self.subTest(ordering=ordering):
                order = vertex_order_for_mesh(self.vertices, self.faces, ordering)
                payload = encode_mesh(
                    self.vertices, self.faces, bits=16, method="tangent", ordering=ordering
                )
                vertices, faces, header = decode_mesh(payload)
                restored_vertices = np.empty_like(vertices)
                restored_vertices[order] = vertices
                restored_faces = order[faces]
                errors = np.linalg.norm(restored_vertices - self.vertices, axis=1)

                self.assertEqual(header["version"], 3)
                self.assertEqual(header["coordinate_coder"], "tangent-parallelogram-residual-varint-zlib")
                self.assertEqual(payload[:5], bytes([77, 79, 51, 68, 3]))
                self.assertGreaterEqual(header["tangent_predictive_vertices"], 0)
                self.assertTrue(np.array_equal(restored_faces, self.faces))
                self.assertLessEqual(float(errors.max()), error_bound * 1.0001 + 1e-12)

    def test_tangent_mode_rejects_zero_extent_mesh(self):
        vertices = np.zeros((3, 3), dtype=np.float64)
        faces = np.array([[0, 1, 2]], dtype=np.int64)
        with self.assertRaises(CodecError):
            encode_mesh(vertices, faces, method="tangent")

    def test_normal_fine_tangent_precision_across_orderings(self):
        levels = (1 << 16) - 1
        diagonal = np.linalg.norm(self.vertices.max(axis=0) - self.vertices.min(axis=0))
        error_bound = diagonal / (2 * levels)
        for ordering in ("source", "bfs", "morton"):
            with self.subTest(ordering=ordering):
                order = vertex_order_for_mesh(self.vertices, self.faces, ordering)
                payload = encode_mesh(
                    self.vertices, self.faces, bits=16,
                    method="normal_fine_tangent", ordering=ordering
                )
                vertices, faces, header = decode_mesh(payload)
                restored_vertices = np.empty_like(vertices)
                restored_vertices[order] = vertices
                restored_faces = order[faces]
                errors = np.linalg.norm(restored_vertices - self.vertices, axis=1)

                self.assertEqual(header["version"], 5)
                self.assertEqual(
                    header["coordinate_coder"],
                    "normal-fine-weighted-tangent-parallelogram-residual-varint-zlib",
                )
                self.assertEqual(payload[:5], bytes([77, 79, 51, 68, 5]))
                steps = np.asarray(header["tangent_residual_steps"], dtype=np.float64)
                self.assertEqual(steps.shape, (3,))
                self.assertTrue(np.all(steps > 0))
                # First component (local surface normal) receives finer precision.
                self.assertLess(steps[0], steps[1])
                self.assertAlmostEqual(float(np.sum(steps ** 2)), float(3 * (diagonal / (np.sqrt(3) * levels)) ** 2))
                self.assertTrue(np.array_equal(restored_faces, self.faces))
                self.assertLessEqual(float(errors.max()), error_bound * 1.0001 + 1e-12)

    def test_weighted_tangent_roundtrip_across_orderings(self):
        levels = (1 << 16) - 1
        diagonal = np.linalg.norm(self.vertices.max(axis=0) - self.vertices.min(axis=0))
        error_bound = diagonal / (2 * levels)
        for ordering in ("source", "bfs", "morton"):
            with self.subTest(ordering=ordering):
                order = vertex_order_for_mesh(self.vertices, self.faces, ordering)
                payload = encode_mesh(
                    self.vertices, self.faces, bits=16, method="weighted_tangent", ordering=ordering
                )
                vertices, faces, header = decode_mesh(payload)
                restored_vertices = np.empty_like(vertices)
                restored_vertices[order] = vertices
                restored_faces = order[faces]
                errors = np.linalg.norm(restored_vertices - self.vertices, axis=1)

                self.assertEqual(header["version"], 4)
                self.assertEqual(header["coordinate_coder"], "weighted-tangent-parallelogram-residual-varint-zlib")
                self.assertEqual(payload[:5], bytes([77, 79, 51, 68, 4]))
                self.assertTrue(np.array_equal(restored_faces, self.faces))
                self.assertLessEqual(float(errors.max()), error_bound * 1.0001 + 1e-12)

    def test_auto_mode_selects_smallest_of_all_coder_ordering_candidates(self):
        bits = 16
        candidates = [
            encode_mesh(self.vertices, self.faces, bits=bits, method=method, ordering=ordering)
            for ordering in ("source", "bfs", "morton")
            for method in ("baseline", "prithvi", "tangent", "weighted_tangent")
        ] + [
            encode_mesh(
                self.vertices, self.faces, bits=bits, method="normal_fine_tangent",
                ordering=ordering, normal_step_ratio=ratio
            )
            for ordering in ("source", "bfs", "morton")
            for ratio in (0.375, 0.5, 0.625, 0.75, 0.875)
        ]
        automatic = encode_mesh(self.vertices, self.faces, bits=bits, method="auto")
        vertices, faces, header = decode_mesh(automatic)
        self.assertEqual(len(automatic), min(len(payload) for payload in candidates))
        self.assertTrue(np.array_equal(faces.shape, np.asarray(self.faces.shape)))
        self.assertIn(header["vertex_ordering"], ("source", "bfs", "morton"))
        if header["coordinate_coder"] == "normal-fine-weighted-tangent-parallelogram-residual-varint-zlib":
            self.assertIn(header["normal_step_ratio"], (0.375, 0.5, 0.625, 0.75, 0.875))
        self.assertIn(
            header["coordinate_coder"],
            (
                "absolute-fixed-width-zlib",
                "prithvi-mesh-adjacency-residual-varint-zlib",
                "tangent-parallelogram-residual-varint-zlib",
                "weighted-tangent-parallelogram-residual-varint-zlib",
                "normal-fine-weighted-tangent-parallelogram-residual-varint-zlib",
            ),
        )
        self.assertEqual(len(vertices), len(self.vertices))

    def test_auto_mode_falls_back_when_predictive_methods_are_not_applicable(self):
        vertices = np.zeros((3, 3), dtype=np.float64)
        faces = np.array([[0, 1, 2]], dtype=np.int64)
        payload = encode_mesh(vertices, faces, method="auto")
        _, _, header = decode_mesh(payload)
        self.assertEqual(header["coordinate_coder"], "absolute-fixed-width-zlib")

    def test_legacy_v1_header_without_new_coder_fields_still_decodes(self):
        payload = encode_mesh(self.vertices, self.faces, bits=16, method="baseline")
        header_length = struct.unpack(">I", payload[5:9])[0]
        old_header = json.loads(payload[9:9 + header_length].decode("utf-8"))
        old_header.pop("coordinate_coder", None)
        old_header.pop("method_note", None)
        legacy_header_bytes = json.dumps(old_header, separators=(",", ":"), allow_nan=False).encode("utf-8")
        legacy_payload = (
            payload[:5]
            + struct.pack(">I", len(legacy_header_bytes))
            + legacy_header_bytes
            + payload[9 + header_length:]
        )
        _, faces, header = decode_mesh(legacy_payload)
        self.assertTrue(np.array_equal(faces, self.faces))
        self.assertEqual(header["version"], 1)

    def test_mismatched_magic_and_header_versions_are_rejected(self):
        payload = bytearray(encode_mesh(self.vertices, self.faces, bits=16, method="prithvi"))
        payload[4] = 1
        with self.assertRaises(CodecError):
            decode_mesh(payload)

    def test_bad_magic_rejected(self):
        with self.assertRaises(CodecError):
            decode_mesh(b"not a MO3D file")

    def test_invalid_bits_rejected(self):
        with self.assertRaises(CodecError):
            encode_mesh(self.vertices, self.faces, bits=7)

    def test_corrupt_payload_rejected(self):
        payload = encode_mesh(self.vertices, self.faces)
        with self.assertRaises(CodecError):
            decode_mesh(payload[:-3])


if __name__ == "__main__":
    unittest.main(verbosity=2)
