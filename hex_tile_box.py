#!/usr/bin/env python3
"""Generate hex tile box PDFs for Z-scale Tantrix layout modules.

Produces two separate PDF files for independent laser-cutting orders:
  hex_top.pdf   — Hexagonal top panel (×1 per tile)
  wall_rail.pdf — Universal chiral rail wall (one part; order ×6 per tile)

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
DOWEL_CUT_D = 3.7        # mm undersized cut; ream to 4.0 (H7) for a slip fit
DOWEL_X_INSET = 10.0     # mm from each end of panel
DOWEL_HEIGHT = 25.0      # mm from bottom edge
CLAMP_D = 3.5            # mm M3 clearance
CLAMP_HEIGHT = 25.0      # mm from bottom edge
NOTCH_W = 15.0           # mm cable notch width
NOTCH_H = 8.0            # mm cable notch height

# ── Track registration brackets ──────────────────────
TRACK_BASE_W = 11.8      # mm Märklin Z track base width (verify by caliper)
BRACKET_FINGER = 13.2    # mm rail-edge tab width (25.0 − TRACK_BASE_W)
BRACKET_SPACE = 11.8     # mm rail-edge notch width (= TRACK_BASE_W)
NIB_W = 2.0              # mm rail-catch nib width
NIB_H = 1.0              # mm rail-catch nib height (protrudes above deck)
# On a hex edge the bracket joint yields 5 tabs (indices 0..4) at rel-midpoint
# -50/-25/0/+25/+50 mm; the two rail bases drop into the notches at ±12.5.
# Nibs sit on the notch-facing corner(s) of the three center tabs to catch the
# base edges (≈±6.6 inner, ±18.4 outer).  'l'=left corner, 'r'=right, 'both'.
NIB_TABS = {1: 'r', 2: 'both', 3: 'l'}

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


def straight_specs():
    """Return straight double-track descriptors: (entry_x, entry_y, heading, length).

    Connects opposite faces (0,3), (1,4), (2,5) with the ±12.5 mm parallel pair.
    Each rail runs parallel to the face-to-face diameter, offset by C3/C4 along the
    face tangent, so it lands at the matching ±12.5 mm point on the opposite face.
    """
    specs = []
    length = 2 * APOTHEM            # face midpoint to opposite face midpoint
    for fa in (0, 1, 2):
        mx, my = face_midpoint(fa)
        tx, ty = face_tangent(fa)
        for d in (C3_OFFSET, C4_OFFSET):
            specs.append((mx + d * tx, my + d * ty, inward_heading(fa), length))
    return specs


# ════════════════════════════════════════════════════════
#  Custom edge: finger joint with rail-catch nibs
# ════════════════════════════════════════════════════════

class CatchFingerEdge(edges.FingerJointEdge):
    """Finger-joint edge with small rail-catch nibs on selected fingers' corners.

    Used only on a wall's top edge.  Keeps every structural finger flush (so the
    joint into the hex top is unchanged) and adds a NIB_W×NIB_H bump above the deck
    on the notch-facing corner(s) of the fingers named in NIB_TABS, catching the
    track base laterally.  The bump is the same kind of polyline excursion as the
    cable notch, anchored to the auto-generated tab so it stays in sync.
    """

    def __call__(self, length, **kw):
        self._fi = 0
        super().__call__(length, **kw)

    def draw_finger(self, f, h, style, positive=True, firsthalf=True):
        side = NIB_TABS.get(self._fi) if positive else None
        self._fi += 1
        if side is None or style != "rectangular":
            return super().draw_finger(f, h, style, positive, firsthalf)
        w, nh = NIB_W, NIB_H
        bump = [-90, nh, 90, w, 90, nh, -90]   # outward NIB_H, across NIB_W, back in
        if side == 'l':
            mid = [0, *bump, f - w]
        elif side == 'r':
            mid = [f - w, *bump, 0]
        else:  # 'both'
            mid = [0, *bump, f - 2 * w, *bump, 0]
        self.polyline(0, -90, h, 90, *mid, 90, h, -90)


def register_bracket_edges(box):
    """Register the bracket finger-joint edges on *box*.

    'j' — wall top edge (CatchFingerEdge, with rail-catch nibs).
    'J' — hex-top counterpart.
    Both share the same wider spacing (finger/space → period 25 mm, odd count)
    so the notches land on the ±12.5 mm rail centers and the two edges mate.
    """
    s = copy.deepcopy(box.edges["f"].settings)
    s.setValues(box.thickness, relative=False,
                finger=BRACKET_FINGER, space=BRACKET_SPACE, surroundingspaces=1)
    s.edgeObjects(box, chars="jJ")
    nibbed = CatchFingerEdge(box, s)
    nibbed.char = 'j'
    box.addPart(nibbed)


# ════════════════════════════════════════════════════════
#  Generator: hex_top.svg
# ════════════════════════════════════════════════════════

class HexTop(Boxes):
    """Hexagonal top panel with finger-joint edges and engraved track arcs."""

    def __init__(self):
        Boxes.__init__(self)
        self.addSettingsArgs(edges.FingerJointSettings, surroundingspaces=1)

    def render(self):
        register_bracket_edges(self)
        self.regularPolygonWall(
            corners=6, r=INNER_R, edges='J',
            callback=[self._engrave], move="right")

    def _engrave(self):
        self.ctx.stroke()
        self.set_source_color(Color.RED)

        # Curved tracks (face pairs 0/2, 0/4, 2/4)
        for ex, ey, hdg, turn, r in arc_specs():
            with self.saved_context():
                self.moveTo(ex, ey, hdg)
                self.corner(turn, r)

        # Straight tracks across opposite faces (0-3, 1-4, 2-5)
        for ex, ey, hdg, length in straight_specs():
            with self.saved_context():
                self.moveTo(ex, ey, hdg)
                self.edge(length)

        # Center cross (5 mm arms)
        for a in (0, 90, 180, 270):
            with self.saved_context():
                self.moveTo(0, 0, a)
                self.edge(5.0)

        self.ctx.stroke()


# ════════════════════════════════════════════════════════
#  Generator: wall_rail.svg  (one universal chiral wall ×6)
# ════════════════════════════════════════════════════════

class WallRail(Boxes):
    """Universal chiral rail wall (one part; order ×6 per tile).

    A single identical part: a flat 'g' finger edge on the right vertical and a
    stepped 'G' slot on the left, so fingers always meet slots around the hex
    ring (no separate male/female variants).  Carries dowel/clamp holes, a cable
    notch in the bottom edge, and the bracket top edge ('j') with rail-catch nibs.
    """

    def __init__(self):
        Boxes.__init__(self)
        self.addSettingsArgs(edges.FingerJointSettings, surroundingspaces=1)

    def render(self):
        t = self.thickness
        _, _, side = self.regularPolygon(6, radius=INNER_R)
        h = H_WALL

        # 60° corner finger joints (g flat / G stepped) for the hexagonal ring
        fjs = copy.deepcopy(self.edges["f"].settings)
        fjs.setValues(self.thickness, angle=CORNER_ANGLE)
        fjs.edgeObjects(self, chars="gGH")

        # Bracket top edge: 'j' (CatchFingerEdge) + 'J' counterpart
        register_bracket_edges(self)

        gap = side / 2 - NOTCH_W / 2
        borders = [
            # Bottom edge with centered cable notch (recessed into panel)
            gap, 90,  NOTCH_H, -90,  NOTCH_W, -90,  NOTCH_H, 90,  gap, 90,
            # Right side (flat, 'g' finger joint)
            0, 0,  h, 0,  0, 90,
            # Top edge (bracket 'j' into hex top, with rail-catch nibs)
            side, 90,
            # Left side (stepped, 'G' counterpart slot)
            0, -90,  t, 90,  h, 90,  t, -90,  0, 90,
        ]

        # One wall (order ×6 per tile)
        self.polygonWall(borders, edge='eeeeeegejeeGee',
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
    generate(WallRail, out / 'wall_rail.pdf', burn)
    print('Done.')


if __name__ == '__main__':
    main()
