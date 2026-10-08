"""steelstd - the BLUE standards library of the partial-tier completion (complete/standards/).

Deterministic builders that return {geometry (GEOM, world mm, complete/INTERFACES.md 2.4), colour (BLUE | AMBER),
provenance {what, standard, basis?, evidence}, part fields, target {volume_mm3, bbox}}; the GEOM -> build123d solid
reference builder is geom.to_shape (tests). Tables and their citations: tables.py.

  fasteners: bolt_assembly (ASTM F3125 heavy hex / A307 hex + A563 nut + F436 washers, RCSC grip rule),
             hole_dims (AISC J3.3), headed_stud (AWS D1.1), anchor_rod (F1554 + AISC Table 14-2)
  members:   hss_member / hss_profile (AISC A500 radii, catalogue override), rebar (ASTM A615, ACI 318 bends)
  joists:    joist (SJI K / KCS / LH / DLH; always AMBER: SJI fixes depth + seat, not chords / webs)
  grating:   grating_panel (NAAMM MBG 531)
"""
from . import tables, geom, core, fasteners, members, joists, grating  # noqa: F401

__version__ = 'steelstd-1.0 (2026-10-07)'
