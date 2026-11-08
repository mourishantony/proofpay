"""Generate synthetic (fictional) steel shop drawings for the demo.

samples/beam_B12_rev_A_fail.pdf - outdated revision, missing CHECKED BY, open TBD note,
                                  BOM/callout mismatches  -> agent requests revision
samples/beam_B12_rev_B_pass.pdf - clean revision B        -> agent approves / releases
"""
from pathlib import Path

import pymupdf as fitz

OUT = Path(__file__).resolve().parents[1] / "samples"


def draw_sheet(path: Path, *, rev: str, checked_by: str | None, notes: list[str], callouts: list[str], bom: list[tuple]):
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)  # A4 landscape
    blue, black = (0.1, 0.25, 0.6), (0, 0, 0)

    page.draw_rect(fitz.Rect(20, 20, 822, 575), color=black, width=1.5)
    # beam elevation
    page.draw_rect(fitz.Rect(80, 150, 560, 190), color=black, width=1.2)
    for x in (80, 560):
        page.draw_rect(fitz.Rect(x - 10, 120, x + 10, 220), color=black, width=1)
    page.insert_text((250, 140), "BEAM B12 - ELEVATION", fontsize=11, color=black)
    page.insert_text((290, 215), "W12x26 x 6000 LG", fontsize=9, color=black)
    # callouts
    for i, mark in enumerate(callouts):
        x = 90 + i * 130
        page.draw_line((x + 15, 240), (x + 15, 192), color=blue, width=0.6)
        page.draw_circle((x + 15, 252), 12, color=blue, width=0.8)
        page.insert_text((x + 3, 256), mark, fontsize=8, color=blue)
    # notes
    y = 320
    page.insert_text((60, y), "GENERAL NOTES", fontsize=10, color=black)
    for i, note in enumerate(notes, 1):
        page.insert_text((60, y + 16 * i), f"{i}. {note}", fontsize=8, color=black)

    # BOM
    page.draw_rect(fitz.Rect(600, 40, 810, 70 + 14 * len(bom)), color=black, width=0.8)
    page.insert_text((610, 55), "BILL OF MATERIALS", fontsize=9, color=black)
    page.insert_text((610, 68), "MARK  QTY  DESCRIPTION", fontsize=7, color=black)
    for i, (mark, qty, desc) in enumerate(bom):
        page.insert_text((610, 82 + 14 * i), f"{mark}  {qty}  {desc}", fontsize=7, color=black)

    # title block
    tb = fitz.Rect(600, 430, 810, 565)
    page.draw_rect(tb, color=black, width=1)
    lines = ["PROJECT: DEMO WAREHOUSE (FICTIONAL)", "DRAWING NO: SD-1012", f"REV: {rev}",
             "DATE: 2026-11-05", "DRAWN BY: MAC"]
    if checked_by:
        lines.append(f"CHECKED BY: {checked_by}")
    lines.append("SCALE: 1:20")
    for i, txt in enumerate(lines):
        page.insert_text((610, 448 + 16 * i), txt, fontsize=8, color=black)

    OUT.mkdir(exist_ok=True)
    doc.save(path)
    doc.close()
    print("wrote", path)


if __name__ == "__main__":
    draw_sheet(
        OUT / "beam_B12_rev_A_fail.pdf", rev="A", checked_by=None,
        notes=["ALL BOLTS A325-N UNLESS NOTED.", "END CONNECTION DETAIL TBD - AWAITING RFI-014.",
               "PAINT: SHOP PRIMER."],
        callouts=["P101", "P102", "C201"],
        bom=[("B012", 1, "W12x26 x 6000"), ("P101", 2, "PL 10x150x200"), ("P102", 2, "PL 10x100x150"),
             ("A103", 4, "L 75x75x8 x 150")],
    )
    draw_sheet(
        OUT / "beam_B12_rev_B_pass.pdf", rev="B", checked_by="SRK",
        notes=["ALL BOLTS A325-N UNLESS NOTED.", "END CONNECTION PER RFI-014 RESPONSE.", "PAINT: SHOP PRIMER."],
        callouts=["B012", "P101", "P102", "A103"],
        bom=[("B012", 1, "W12x26 x 6000"), ("P101", 2, "PL 10x150x200"), ("P102", 2, "PL 10x100x150"),
             ("A103", 4, "L 75x75x8 x 150")],
    )
