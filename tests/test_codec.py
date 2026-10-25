import unittest
import numpy as np
import trimesh

from middleout3d.codec import CodecError, decode_mesh, encode_mesh


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
