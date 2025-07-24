#!/usr/bin/env python3
"""
SISL VFD STOCK LIST generator  • version 0.7  (2025‑07‑24)

Repo layout
-----------
project‑root/
├─ data/
│   ├─ VFD_PRICE_LAST.csv         # inventory  (Qty owned, Total cost)
│   ├─ VFD_PRICE_JULY_2025.csv    # July‑25 “1.27” price list   (1.27 column)
│   └─ VFD_Price_SISL_Final.csv   # master list‑price map
└─ pdf_reports/                   # output PDFs

Rules
-----
• Skip rows with Qty = 0, the model “FR‑S520SE‑0.2K‑19”, or any model containing “PEC”.
• Calculate COGS, COGS×1.75, List Price, 1.27 Price, 20 / 25 / 30 % discounts, GP %.
• Sort by capacity (0.4 K → 400 K) then series D → E → F → A → HEL.
• List‑price lookup cascade:
    1. exact match
    2. D/E 720 / 740 ↔ A 820 / 840 equivalent
    3. cross‑series same capacity (A ⇆ E ⇆ F ⇆ D)
• Output A4‑portrait PDF (0.6″ margins) named
    SISL_VFD_PL_<YYMMDD>_V.<nn>.pdf   (auto‑increment <nn> per day)
"""

import glob
import os
import re
from datetime import datetime
from pathlib import Path

import pandas as pd
from dateutil import tz
from fpdf import FPDF


# ───────────────────────────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────────────────────────
def series_tag(model: str) -> str:
    """Return one‑letter series tag D/E/F/A/H for a model name."""
    if re.search(r"FR-HEL", model, re.I):
        return "H"
    m = re.match(r"FR-([A-Z])", model, re.I)
    return m.group(1).upper() if m else ""


ORDER_MAP = {"D": 0, "E": 1, "F": 2, "A": 3, "H": 4}


def capacity_val(model: str) -> float:
    """Extract capacity in kW (as float) from model string."""
    m = re.search(r"-(?:H)?([\d.]+)K", model, re.I)
    return float(m.group(1)) if m else 0.0


def alt_models(model: str) -> list[str]:
    """
    Generate fallback model names for list‑price lookup.

    1. D/E “720 / 740” ⟷ A “820 / 840” (same capacity)
    2. Cross‑series same capacity (F⇄A⇄E⇄D)
    """
    alts: list[str] = []
    # 720 / 820 mapping
    mapping = {
        r"FR-D720": "FR-A820",
        r"FR-E720": "FR-A820",
        r"FR-D740": "FR-A840",
        r"FR-E740": "FR-A840",
        r"FR-A820": "FR-D720",
        r"FR-A840": "FR-D740",
    }
    for patt, repl in mapping.items():
        if re.match(patt, model, re.I):
            alt = re.sub(patt, repl, model, flags=re.I)
            # ensure trailing “-1” for A‑series
            if "-1" not in alt and re.match(r"FR-A8", alt, re.I):
                alt += "-1"
            alts.append(alt)

    # Cross‑series swap
    series_cycle = ["D", "E", "F", "A"]
    cur = series_tag(model)
    base = re.sub(r"FR-[A-Z]", "FR-X", model, flags=re.I)
    for s in series_cycle:
        if s == cur:
            continue
        alt = re.sub(r"FR-X", f"FR-{s}", base, flags=re.I)
        alts.append(alt)
    return list(dict.fromkeys(alts))  # preserve order, drop duplicates


def money(v) -> str:
    """Thousands‑sep. numbers; blank for NaN / None."""
    return f"{v:,.0f}" if pd.notna(v) else ""


# ───────────────────────────────────────────────────────────────────────────────
# Load data
# ───────────────────────────────────────────────────────────────────────────────
DATA_DIR = Path(__file__).parent / "data"
INV_CSV = DATA_DIR / "VFD_PRICE_LAST.csv"
P127_CSV = DATA_DIR / "VFD_PRICE_JULY_2025.csv"
LIST_CSV = DATA_DIR / "VFD_Price_SISL_Final.csv"

inv_df = pd.read_csv(INV_CSV).rename(columns=lambda c: c.strip().title().replace(" ", ""))
price127_df = pd.read_csv(P127_CSV).rename(columns=lambda c: c.strip())
list_df = pd.read_csv(LIST_CSV).rename(columns=lambda c: c.strip())

price127_map = dict(zip(price127_df["Material Name"], price127_df["1.27"]))
list_price_map = dict(zip(list_df["Model"], list_df["List Price"]))

# ───────────────────────────────────────────────────────────────────────────────
# Build report rows
# ───────────────────────────────────────────────────────────────────────────────
rows = []
for _, r in inv_df.iterrows():
    model = str(r["Model"]).strip()
    qty = r["Qty"]
    if (
        qty == 0
        or model.upper() == "FR-S520SE-0.2K-19".upper()
        or "PEC" in model.upper()
    ):
        continue

    unit_cogs = r["Totalcost"] / qty if qty else 0.0

    # List price cascade
    lp = list_price_map.get(model)
    if lp is None:
        for alt in alt_models(model):
            lp = list_price_map.get(alt)
            if lp is not None:
                break

    p127 = price127_map.get(model)
    disc20 = lp * 0.8 if lp else None
    disc25 = lp * 0.75 if lp else None
    disc30 = lp * 0.7 if lp else None
    gp_pct = round((lp - unit_cogs) / lp * 100, 2) if lp and unit_cogs else None

    rows.append(
        {
            "Model": model,
            "Qty": qty,
            "ListPrice": lp,
            "20%": disc20,
            "25%": disc25,
            "30%": disc30,
            "GP%": gp_pct,
            "COGS": unit_cogs,
            "COGSx1.75": unit_cogs * 1.75 if unit_cogs else None,
            "1.27": p127,
        }
    )

df = pd.DataFrame(rows)
df["CapVal"] = df["Model"].apply(capacity_val)
df["SeriesOrd"] = df["Model"].apply(lambda m: ORDER_MAP.get(series_tag(m), 99))
df = df.sort_values(["CapVal", "SeriesOrd"]).reset_index(drop=True)
df["SL"] = df.index + 1

# ───────────────────────────────────────────────────────────────────────────────
# PDF generation
# ───────────────────────────────────────────────────────────────────────────────
COLS = [
    ("SL", 8),
    ("Model", 34),
    ("Qty", 8),
    ("ListPrice", 17),
    ("20%", 17),
    ("25%", 17),
    ("30%", 17),
    ("GP%", 11),
    ("COGS", 17),
    ("COGSx1.75", 18),
    ("1.27", 17),
]

pdf = FPDF(orientation="P", unit="mm", format="A4")
pdf.set_margins(15.24, 15.24, 15.24)  # 0.6″
pdf.add_page()
pdf.set_auto_page_break(auto=True, margin=15)

# Header
pdf.set_font("Helvetica", "B", 14)
pdf.cell(0, 8, "VFD STOCK LIST", ln=1, align="C")
pdf.set_font("Helvetica", "", 10)
today = datetime.now(tz.gettz("Asia/Dhaka")).strftime("%d %b %Y")
pdf.cell(0, 5, today, ln=1, align="C")
pdf.cell(0, 5, "Smart Industrial Solution Ltd.", ln=1, align="C")
pdf.ln(3)

# Table header
pdf.set_font("Helvetica", "B", 7)
for col, w in COLS:
    pdf.cell(w, 6, col, 1, 0, "C")
pdf.ln()

# Table body
pdf.set_font("Helvetica", "", 7)
ROW_H, fill = 5, False
for _, r in df.iterrows():
    for col, w in COLS:
        val = r[col]
        txt = (
            f"{val:,.2f}%"
            if col == "GP%" and pd.notna(val)
            else money(val)
            if col != "Model"
            else r["Model"]
        )
        align = "C" if col != "Model" else "L"
        pdf.cell(w, ROW_H, txt, 1, 0, align, fill=fill)
    pdf.ln()
    fill = not fill

# ───────────────────────────────────────────────────────────────────────────────
# Save PDF with auto‑incremented version tag
# ───────────────────────────────────────────────────────────────────────────────
PDF_DIR = Path(__file__).parent / "pdf_reports"
PDF_DIR.mkdir(exist_ok=True)

date_tag = datetime.now(tz.gettz("Asia/Dhaka")).strftime("%y%m%d")
existing = sorted(glob.glob(str(PDF_DIR / f"SISL_VFD_PL_{date_tag}_V.*.pdf")))
next_ver = (
    int(re.search(r"_V\.(\d+)\.pdf$", existing[-1]).group(1)) + 1 if existing else 1
)

outfile = PDF_DIR / f"SISL_VFD_PL_{date_tag}_V.{next_ver:02d}.pdf"
pdf.output(outfile)

print("✓ Report saved to:", outfile)
