#!/usr/bin/env python3
"""Generate hex tile box PDFs for Z-scale Tantrix layout modules.

Produces three separate PDF files for independent laser-cutting orders:
  hex_top.pdf    — Hexagonal top panel (×1 per tile)
  wall_blind.pdf — Blind side wall    (×3 per tile)
  wall_rail.pdf  — Rail side wall     (×3 per tile)

Usage: python hex_tile_box.py [burn_mm]
"""

import copy
import math
import sys
from pathlib import Path

from boxes import Boxes, edges
from boxes.Color import Color

# ── Geometry ─────────────────────────────────────────
S = 415.0 / 3.0          # outer circumradius ≈ 138.333 mm
H_OUTSIDE = 56.0         # mm total outside height
THICKNESS = 6.0          # mm birch plywood
H_WALL = H_OUTSIDE - THICKNESS  # = 50.0 mm wall height
INNER_R = S - THICKNESS / math.cos(math.radians(30))  # ≈ 131.405 mm

# ── Track reference arcs ─────────────────────────────
C4_OFFSET = +12.5        # mm from face midpoint (outer track position)
C3_OFFSET = -12.5        # mm (inner track position)
R_C3 = 195.0             # mm Märklin 8591 curve radius
R_C4 = 220.0             # mm Märklin 8590 curve radius

# ── Rail panel hardware ──────────────────────────────
DOWEL_CUT_D = 3.9        # mm  (ream to 4.0 after cutting)
DOWEL_X_INSET = 10.0     # mm from each end of panel
DOWEL_HEIGHT = 25.0      # mm from bottom edge
CLAMP_D = 3.5            # mm M3 clearance
CLAMP_HEIGHT = 25.0      # mm from bottom edge
NOTCH_W = 15.0           # mm cable notch width
NOTCH_H = 8.0            # mm cable notch height

# ── Laser ────────────────────────────────────────────
BURN = 0.1               # mm default kerf compensation
CORNER_ANGLE = 60.0      # degrees between adjacent hex walls


# ════════════════════════════════════════════════════════
#  Hex face geometry (math coords: origin at center, y-up)
# ════════════════════════════════════════════════════════

APOTHEM = S * math.cos(math.radians(30))  # outer apothem = panel edge


def face_midpoint(i):
    a = math.radians(90 - i * 60)
    return APOTHEM * math.cos(a), APOTHEM * math.sin(a)


def face_tangent(i):
    a = math.radians(-i * 60)
    return math.cos(a), math.sin(a)


def face_normal(i):
    a = math.radians(90 - i * 60)
    return math.cos(a), math.sin(a)


def inward_heading(i):
    """Turtle heading (degrees, boxes.py convention) for inward perpendicular."""
    return (270 - i * 60) % 360


# ════════════════════════════════════════════════════════
#  Track arc computation
# ════════════════════════════════════════════════════════

def arc_specs():
    """Return 6 arc descriptors: (entry_x, entry_y, heading_deg, turn_deg, radius).

    Face pairs (0,2), (0,4), (2,4).  Two arcs per pair (R_C3 and R_C4).
    For LEFT  turn: entry offset d = (3S/2 − R) on face_a.
    For RIGHT turn: entry offset d = (R − 3S/2) on face_a.
    Exit offset is always −d (lands at ±12.5 mm from face_b midpoint).
    """
    pairs = [
        (0, 2, +1),   # left turn
        (0, 4, -1),   # right turn
        (2, 4, +1),   # left turn
    ]
    arcs = []
    for fa, _fb, sign in pairs:
        for R in (R_C3, R_C4):
            d = (1.5 * S - R) * sign
            mx, my = face_midpoint(fa)
            tx, ty = face_tangent(fa)
            arcs.append((mx + d * tx, my + d * ty,
                         inward_heading(fa), 60 * sign, R))
            assert abs(abs(d) - 12.5) < 0.01, f"offset {d} != ±12.5"
    return arcs


# ════════════════════════════════════════════════════════
#  Generator: hex_top.svg
# ════════════════════════════════════════════════════════

class HexTop(Boxes):
    """Hexagonal top panel with finger-joint edges and engraved track arcs."""

    def __init__(self):
        Boxes.__init__(self)
        self.addSettingsArgs(edges.FingerJointSettings, surroundingspaces=1)

    def render(self):
        self.regularPolygonWall(
            corners=6, r=INNER_R, edges='F',
            callback=[self._engrave], move="right")

    def _engrave(self):
        self.ctx.stroke()
        self.set_source_color(Color.RED)

        for ex, ey, hdg, turn, r in arc_specs():
            with self.saved_context():
                self.moveTo(ex, ey, hdg)
                self.corner(turn, r)

        # Center cross (5 mm arms)
        for a in (0, 90, 180, 270):
            with self.saved_context():
                self.moveTo(0, 0, a)
                self.edge(5.0)

        self.ctx.stroke()


# ════════════════════════════════════════════════════════
#  Generator: wall_blind.svg
# ════════════════════════════════════════════════════════

class WallBlind(Boxes):
    """Blind side wall — stepped profile for corner finger joints."""

    def __init__(self):
        Boxes.__init__(self)
        self.addSettingsArgs(edges.FingerJointSettings, surroundingspaces=1)

    def render(self):
        t = self.thickness
        _, _, side = self.regularPolygon(6, radius=INNER_R)
        h = H_WALL

        # Corner finger joints at 60° for hexagonal inter-wall connections
        fjs = copy.deepcopy(self.edges["f"].settings)
        fjs.setValues(self.thickness, angle=CORNER_ANGLE)
        fjs.edgeObjects(self, chars="gGH")

        # Stepped profile: tabs extend on both vertical sides
        # (mates with adjacent flat/rail panels' 'g' finger edges)
        borders = [
            side, 90,  0, -90,  t, 90,  h, 90,  t, -90,  0, 90,
            side, 90,  0, -90,  t, 90,  h, 90,  t, -90,  0, 90,
        ]
        self.polygonWall(borders, edge='eeeGeefeeGee',
                         correct_corners=False, move="right")


# ════════════════════════════════════════════════════════
#  Generator: wall_rail.svg
# ════════════════════════════════════════════════════════

class WallRail(Boxes):
    """Rail side wall — flat profile, dowel holes, clamp hole, cable notch."""

    def __init__(self):
        Boxes.__init__(self)
        self.addSettingsArgs(edges.FingerJointSettings, surroundingspaces=1)

    def render(self):
        _, _, side = self.regularPolygon(6, radius=INNER_R)
        h = H_WALL

        # Corner finger joints at 60°
        fjs = copy.deepcopy(self.edges["f"].settings)
        fjs.setValues(self.thickness, angle=CORNER_ANGLE)
        fjs.edgeObjects(self, chars="gGH")

        # Flat profile with cable notch cut into bottom edge
        gap = side / 2 - NOTCH_W / 2
        borders = [
            # Bottom edge with centered cable notch (recessed into panel)
            gap, 90,  NOTCH_H, -90,  NOTCH_W, -90,  NOTCH_H, 90,  gap, 90,
            # Right side (flat, 'g' finger joint)
            0, 0,  h, 0,  0, 90,
            # Top edge ('f' finger joint into hex top)
            side, 90,
            # Left side (flat, 'g' finger joint)
            0, 0,  h, 0,  0, 90,
        ]

        self.polygonWall(borders, edge='eeeeeegefege',
                         correct_corners=False,
                         callback=[self._add_holes], move="right")

    def _add_holes(self):
        _, _, side = self.regularPolygon(6, radius=INNER_R)
        self.hole(DOWEL_X_INSET, DOWEL_HEIGHT, d=DOWEL_CUT_D,
                  color=Color.BLUE)
        self.hole(side - DOWEL_X_INSET, DOWEL_HEIGHT, d=DOWEL_CUT_D,
                  color=Color.BLUE)
        self.hole(side / 2, CLAMP_HEIGHT, d=CLAMP_D,
                  color=Color.BLUE)


# ════════════════════════════════════════════════════════
#  Output
# ════════════════════════════════════════════════════════

def generate(cls, path, burn):
    b = cls()
    b.parseArgs([
        f'--thickness={THICKNESS}',
        f'--burn={burn}',
        f'--output={path}',
        '--format=pdf',
        '--reference=0',
        '--labels=0',
    ])
    b.open()
    b.set_source_color(Color.BLUE)
    b.render()
    data = b.close()
    if data:
        with open(path, 'wb') as f:
            f.write(data.getvalue())
        print(f'  {path}')


def main():
    burn = float(sys.argv[1]) if len(sys.argv) > 1 else BURN
    out = Path('.')
    print(f'Generating hex tile box PDFs (burn={burn} mm):')
    generate(HexTop, out / 'hex_top.pdf', burn)
    generate(WallBlind, out / 'wall_blind.pdf', burn)
    generate(WallRail, out / 'wall_rail.pdf', burn)
    print('Done.')


if __name__ == '__main__':
    main()
