#!/usr/bin/env python3
"""
SISL VFD STOCK LIST generator  • version 0.6  (2025‑07‑24)

Repo layout
-----------
project‑root/
├─ data/
│   ├─ VFD_PRICE_LAST.csv         # inventory  (Qty owned, Total cost)
│   ├─ VFD_PRICE_JULY_2025.csv    # July‑25 “1.27” price list   (1.27 column)
│   └─ VFD_Price_SISL_Final.csv   # master list‑price map
└─ pdf_reports/                   # output PDFs

Key rules
---------
•  Skip rows with Qty = 0, the model “FR‑S520SE‑0.2K‑19”, or any model containing “PEC”.
•  Calculate COGS, COGS×1.75, List Price, 1.27 Price, 20 / 25 / 30 % discounts, GP %.
•  Sort by capacity (0.4 K → 400 K) then series D → E → F → A → HEL.
•  List‑price lookup cascade:
     1) exact match
     2) D/E “720 / 740” → A “820 / 840” equivalent
     3) any other series with the same capacity
•  Output A4‑portrait PDF (0.6″ margins) named
     SISL_VFD_PL_<YYMMDD>_V.<nn>.pdf   (nn auto‑increments per day)
"""

import os, re, glob
from datetime import datetime
from pathlib import Path

import pandas as pd
from dateutil import tz
from fpdf import FPDF


# ───────────────────────────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────────────────────────
def series_tag(model: str) -> str:
    if re.search(r"FR-HEL", model, re.I):
        return "H"
    m = re.match(r"FR-([A-Z])", model, re.I)
    return m.group(1).upper() if m else ""


ORDER_MAP = {"D": 0, "E": 1, "F": 2, "A": 3, "H": 4}


def capacity_val(model: str) -> float:
    """
    Returns numeric capacity in kW (e.g. 'FR-F840-37K-1' → 37.0).
    """
    m = re.search(r"-(?:H)?([\d.]+)K", model, re.I)
    return float(m.group(1)) if m else 0.0


def alt_models(model: str) -> list[str]:
    """
    Generate fallback model names for list‑price lookup.

    1. D/E 720 / 740  ⟷ A 820 / 840 (same capacity)
    2. Cross‑series same capacity (family swap)
    """
    alts: list[str] = []
    cap = f"{capacity_val(model):.0f}K"
    # 720 / 820 mapping
    subs = {
        r"FR-D720": "FR-A820",
        r"FR-E720": "FR-A820",
        r"FR-D740": "FR-A840",
        r"FR-E740": "FR-A840",
        r"FR-A820": "FR-D720",
        r"FR-A840": "FR-D740",
    }
    for patt, repl in subs.items():
        if re.match(patt, model, re.I):
            alt = re.sub(patt, repl, model, flags=re.I)
            # Ensure trailing '-1' for A/HEL series
            if "-1" not in alt and re.match(r"FR-A8", alt, re.I):
                alt += "-1"
            alts.append(alt)
    # Cross‑series same capacity F⇄A⇄E⇄D
    series_order = ["D", "E", "F", "A"]
    cur_tag = series_tag(model)
    base = re.sub(r"FR-[A-Z]", "FR-X", model, flags=re.I)  # placeholder
    for s in series_order:
        if s == cur_tag:
            continue
        alt = re.sub(r"FR-X", f"FR-{s}", base, flags=re.I)
        alts.append(alt)
    return list(dict.fromkeys(alts))  # preserve order, drop dups


def money(v: float | int | pd.NA) -> str:
    return f"{v:,.0f}" if pd.notna(v) else ""


# ───────────────────────────────────────────────────────────────────────────────
# Load data
# ───────────────────────────────────────────────────────────────────────────────
DATA_DIR = Path(__file__).parent / "data"
INV_CSV = DATA_DIR / "VFD_PRICE_LAST.csv"
P127_CSV = DATA_DIR / "VFD_PRICE_JULY_2025.csv"
LIST_CSV = DATA_DIR / "VFD_Price_SISL_Final.csv"

inv_df = pd.read_csv(INV_CSV).rename(
    columns=lambda c: c.strip().title().replace(" ", "")
)  # normalize headers
price127_df = pd.read_csv(P127_CSV)
list_df = pd.read_csv(LIST_CSV)

# Standardize column names we’ll use
inv_df = inv_df.rename(columns={"Qtyowned": "Qty", "Totalcost": "TotalCost"})
price127_df = price127_df.rename(columns=lambda c: c.strip())
list_df = list_df.rename(columns=lambda c: c.strip())

# Build fast look‑ups
price127_map = dict(zip(price127_df["Material Name"], price127_df["1.27"]))
list_price_map = dict(zip(list_df["Model"], list_df["List Price"]))

# ───────────────────────────────────────────────────────────────────────────────
# Construct report DataFrame
# ───────────────────────────────────────────────────────────────────────────────
rows = []
for _, row in inv_df.iterrows():
    model = str(row["Model"]).strip()
    qty = row["Qty"]
    cogs = row["TotalCost"] / qty if qty else 0  # unit COGS

    # Skip rules ---------------------------------------------------------------
    if (
        qty == 0
        or model.upper() == "FR-S520SE-0.2K-19".upper()
        or "PEC" in model.upper()
    ):
        continue

    # List‑price lookup cascade -------------------------------------------------
    list_price = list_price_map.get(model)
    if list_price is None:
        for alt in alt_models(model):
            list_price = list_price_map.get(alt)
            if list_price is not None:
                break

    # 1.27 price
    price127 = price127_map.get(model)

    # Discounts
    disc20 = list_price * 0.8 if list_price else None
    disc25 = list_price * 0.75 if list_price else None
    disc30 = list_price * 0.7 if list_price else None

    # GP%
    gp_pct = None
    if list_price and cogs:
        gp_pct = round((list_price - cogs) / list_price * 100, 2)

    # Build row
    rows.append(
        {
            "Model": model,
            "Qty": qty,
            "ListPrice": list_price,
            "20%": disc20,
            "25%": disc25,
            "30%": disc30,
            "GP%": gp_pct,
            "COGS": cogs,
            "COGSx1.75": cogs * 1.75 if cogs else None,
            "1.27": price127,
        }
    )

df = pd.DataFrame(rows)

# Sorting ----------------------------------------------------------------------
df["CapVal"] = df["Model"].apply(capacity_val)
df["SeriesOrd"] = df["Model"].apply(lambda m: ORDER_MAP.get(series_tag(m), 99))
df = df.sort_values(["CapVal", "SeriesOrd"]).reset_index(drop=True)
df["SL"] = df.index + 1  # serial column

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
pdf.set_auto_page_break(auto=True, margin=15)
pdf.set_margins(15.24, 15.24, 15.24)  # 0.6" = 15.24 mm
pdf.add_page()

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
ROW_H = 5
fill = False
for _, r in df.iterrows():
    for col, w in COLS:
        key = col if col != "COGSx1.75" else "COGSx1.75"
        v = r[key]
        txt = (
            f"{v:,.2f}%" if key == "GP%" and pd.notna(v) else money(v)
            if key != "Model"
            else r["Model"]
        )
        pdf.cell(w, ROW_H, txt, 1, 0, "C" if col != "Model" else "L", fill=fill)
    pdf.ln()
    fill = not fill

# ───────────────────────────────────────────────────────────────────────────────
# Save PDF with auto‑increment version
# ───────────────────────────────────────────────────────────────────────────────
PDF_DIR = Path(__file__).parent / "pdf_reports"
PDF_DIR.mkdir(exist_ok=True)

date_tag = datetime.now(tz.gettz("Asia/Dhaka")).strftime("%y%m%d")
pattern = str(PDF_DIR / f"SISL_VFD_PL_{date_tag}_V.*.pdf")
existing = sorted(glob.glob(pattern))
next_ver = (
    int(re.search(r"_V\.(\d+)\.pdf$", existing[-1]).group(1)) + 1
    if existing
    else 1
)
outfile = PDF_DIR / f"SISL_VFD_PL_{date_tag}_V.{next_ver:02d}.pdf"
pdf.output(outfile)
print("✓ Report saved to:", outfile)
