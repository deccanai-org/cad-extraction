"""Focused regression tests for SDS2 built-up section decoding and outlines."""

import struct
import unittest
import numpy as np

from sds2job import Member, Shape, _read_shapes_archive
from to_step import profile, solid_for
from to_step2 import rolled_local, bolt_stacks, piece_instance_label
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps


def polygon_area(loop):
    return abs(sum(loop[i][0] * loop[(i + 1) % len(loop)][1]
                   - loop[(i + 1) % len(loop)][0] * loop[i][1]
                   for i in range(len(loop))) / 2)


def section_area(outlines):
    return polygon_area(outlines[0]) - sum(polygon_area(loop) for loop in outlines[1:])


class BuiltUpProfileTest(unittest.TestCase):
    def test_7425_wbx_extra_fields(self):
        # Real 7.425 WBX24x143 field layout: ordinary bf=1 is not its width.
        record = bytearray(160)
        record[:4] = struct.pack("<I", 23)
        record[4:13] = b"WBX24x143"
        record[27] = 28
        record[32:80] = struct.pack("<6d", 24, 1, 1, .5, 8, 143)
        record[96:128] = struct.pack("<4d", 10, 1, 10, 1)
        sh = _read_shapes_archive(bytes(record))[1]
        self.assertEqual((sh.bf_top, sh.tf_top, sh.bf_bot, sh.tf_bot), (10, 1, 10, 1))
        self.assertAlmostEqual(section_area(profile(sh)), 42)

    def test_plate_girder_uses_real_flange_fields(self):
        sh = Shape(1, "PLG42x22/0.75/3", 42, 22, 3, .75, 0, 541.04, 22, 3, 22, 3)
        self.assertAlmostEqual(section_area(profile(sh)), 159)

    def test_asymmetric_wps(self):
        sh = Shape(1, "WPS24x105", 24, 12, 1, .5, 0, 105, 8, 1, 12, 1)
        loops = profile(sh)
        self.assertAlmostEqual(section_area(loops), 31)
        self.assertEqual(max(v for _, v in loops[0]), 6)
        self.assertEqual(min(v for _, v in loops[0]), -6)

    def test_wbx_is_hollow_box_not_i_profile(self):
        sh = Shape(1, "WBX24x143", 24, 10, 1, .5, 0, 143, 10, 1, 10, 1)
        loops = profile(sh)
        self.assertEqual(len(loops), 2)
        self.assertAlmostEqual(section_area(loops), 42)

    def test_named_plg_with_placeholder_source_weight(self):
        sh = Shape(1, "PLG36x24/2/4", 36, 24, 4, 2, 0, 92, 24, 4, 24, 4)
        self.assertAlmostEqual(section_area(profile(sh)), 248)

    def test_rejects_unvalidated_builtin_family(self):
        sh = Shape(1, "WPS24x105", 24, 12, 1, .5, 0, 92, 8, 1, 12, 1)
        with self.assertRaises(ValueError):
            profile(sh)

    def test_rolled_w_stays_unchanged(self):
        sh = Shape(1, "W10x49", 10, 8, .5, .3, 0, 49)
        loops = profile(sh)
        self.assertEqual(len(loops), 1)
        self.assertAlmostEqual(section_area(loops), 2 * 8 * .5 + (10 - 1) * .3)

    def test_unequal_angle_follows_piece_vertex_axes(self):
        sh = Shape(1, "L8x4x1", 8, 4, 1, 1, 0, 37.4)
        # A real Binney angle of this section has local y=4, z=8. Both
        # extruded end faces should retain those axes, not become y=8,z=4.
        yz = np.array([(0, 0), (4, 0), (4, 1), (1, 1), (1, 8), (0, 8)])
        vertices = np.array([[x, y, z] for x in (0, 25.125) for y, z in yz])
        loop, _, holes = rolled_local(vertices, sh, 25.125)
        self.assertTrue(np.allclose(np.ptp(np.array(loop)[:, 1:], axis=0), [4, 8]))
        self.assertEqual(holes, [])

    def test_hollow_section_inner_loop_survives_stage2_fit(self):
        sh = Shape(1, "HSS10x6x1/2", 10, 6, .5, .5, 0, 89)
        vertices = np.array([[x, y, z] for x in (0, 100) for y in (-5, 5) for z in (-3, 3)])
        _, _, holes = rolled_local(vertices, sh, 100)
        self.assertEqual(len(holes), 1)
        self.assertTrue(np.allclose(np.ptp(np.array(holes[0])[:, 1:], axis=0), [9, 5]))

    def test_corrupt_hole_coordinate_does_not_abort_step_export(self):
        c = np.array([[0., 0., 0.], [0., 0., 0.], [1e200, 0., 0.]])
        a = np.array([[0., 0., 1.]] * 3)
        result = bolt_stacks(c, a, np.array([1., 1., 1.]), np.array([.875] * 3), np.array([1, 2, 3]))
        self.assertEqual(len(result), 1)

    def test_stage1_round_pipe_is_hollow_not_two_added_discs(self):
        sh = Shape(1, "PIPE 10 STD", 10.8, 10.8, .365, .365, 0, 40.5)
        member = Member(1, "COLUMN", (0., 0., 0.), (100., 0., 0.), sh, 0.)
        solid = solid_for(member, "X", 0)
        props = GProp_GProps()
        BRepGProp.VolumeProperties_s(solid, props)
        area = props.Mass() / 25.4 ** 3 / 100
        self.assertAlmostEqual(area, section_area(profile(sh)), places=4)

    def test_round_hss_uses_wall_matching_recorded_weight(self):
        # Actual 50 Binney record: stored design wall .465, nominal name .500,
        # but the SDS2 source weight is based on the nominal gauge.
        sh = Shape(1, "HSS20x.500", 20, 20, .465, .465, 0, 104)
        area = section_area(profile(sh))
        self.assertLess(abs(area * 3.4032 / sh.weight - 1), .02)

    def test_repeated_piece_instances_have_distinct_names(self):
        first = piece_instance_label("BEAM", 42, "L4x4x1/4", 812, 1)
        second = piece_instance_label("BEAM", 42, "L4x4x1/4", 812, 2)
        self.assertNotEqual(first, second)
        self.assertIn("(piece 812, inst 2)", second)


if __name__ == "__main__":
    unittest.main()
