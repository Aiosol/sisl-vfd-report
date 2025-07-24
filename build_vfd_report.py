#!/usr/bin/env python3
"""
build_vfd_report.py  (version 0.5)

Generates a VFD STOCK LIST PDF for Smart Industrial Solution Ltd.

Folder layout (relative to this script):
project-root/
├─ data/
│   ├─ VFD_PRICE_LAST.csv        # inventory  (Qty owned, Total cost)
│   ├─ VFD_PRICE_JULY_2025.csv   # 1.27 price list (column “1.27”)
│   └─ VFD_Price_SISL_Final.csv  # master list‑price map
├─ pdf_reports/                  # output PDFs
└─ requirements.txt              # dependencies

Requirements
------------
pandas>=2.2
fpdf2==2.7.8
python-dateutil
"""

from __future__ import annotations

import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd
from dateutil.tz import tzlocal
from fpdf import FPDF

# ──────────────────────────────────────────────────────────
# CONFIGURATION
# ──────────────────────────────────────────────────────────
DATA_DIR = Path(__file__).resolve().parent / "data"
PDF_DIR = Path(__file__).resolve().parent / "pdf_reports"
PDF_DIR.mkdir(exist_ok=True)

MARGIN_INCH = 0.6            # inches
MARGIN_MM = MARGIN_INCH * 25.4

# Column widths (mm) in the PDF, matching spec
COLS = [
    ("SL", 8, "C"),
    ("Model", 34, "L"),
    ("Qty", 8, "C"),
    ("ListPrice", 17, "R"),
    ("20% Disc", 17, "R"),
    ("25% Disc", 17, "R"),
    ("30% Disc", 17, "R"),
    ("GP%", 11, "R"),
    ("COGS", 17, "R"),
    ("COGS×1.75", 18, "R"),
    ("1.27", 17, "R"),
]

SKIP_MODEL_EXACT = {"FR-S520SE-0.2K-19"}
SKIP_MODEL_CONTAINS = "PEC"

SERIES_ORDER = {"D": 0, "E": 1, "F": 2, "A": 3, "HEL": 4}

DATE_STR = datetime.now(tzlocal()).strftime("%y%m%d")

CANDIDATE_MODEL_COLS = [
    "Model",
    "Material Name",
    "Description",
    "Model Name",
    "Material",
    "Part",
    "Product",
    "Item",
    "Model_Name",
]


# ──────────────────────────────────────────────────────────
# HELPER FUNCTIONS
# ──────────────────────────────────────────────────────────
def money(x: Any) -> str:
    """Format numbers with comma separator; blanks for NaN/None."""
    if pd.isna(x):
        return ""
    return f"{float(x):,.2f}"


def percent(x: Any) -> str:
    if pd.isna(x):
        return ""
    return f"{float(x):,.2f}%"


def extract_capacity_kw(model: str) -> float:
    """
    Extract numeric capacity in kW from model strings (e.g., 55K, 1.5K, H75K).
    Returns float for proper sorting; if missing, returns a large number.
    """
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*K", model, flags=re.I)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    # HEL variants like H75K, H110K etc.
    m2 = re.search(r"H([0-9]+(?:\.[0-9]+)?)\s*K", model, flags=re.I)
    if m2:
        try:
            return float(m2.group(1))
        except ValueError:
            pass
    return float("inf")


def series_rank(model: str) -> int:
    """Return ordering key based on series letter in model."""
    m = re.search(r"FR-([A-Z]+)", model)
    series = m.group(1) if m else ""
    # Map HEL separately, else first char
    if series.startswith("HEL"):
        return SERIES_ORDER["HEL"]
    key = series[0] if series else ""
    return SERIES_ORDER.get(key, 99)


def find_price127(model: str, price127_map: dict[str, float]) -> Optional[float]:
    """
    Retrieve 1.27 price with fallback:
      – Direct match.
      – Replace 720→820 or 740→840 (any series).
    Returns None if not found.
    """
    if model in price127_map:
        return price127_map[model]

    # fallback logic
    fallback = (
        model.replace("720", "820", 1)
        if "720" in model
        else model.replace("740", "840", 1)
        if "740" in model
        else None
    )
    if fallback and fallback in price127_map:
        return price127_map[fallback]
    return None


def next_pdf_filename() -> Path:
    """Compute next incremental filename for today's date."""
    pattern = re.compile(rf"^SISL_VFD_PL_{DATE_STR}_V\.(\d+)\.pdf$")
    versions = [
        int(m.group(1))
        for f in PDF_DIR.iterdir()
        if (m := pattern.match(f.name))
    ]
    ver = max(versions) + 1 if versions else 1
    return PDF_DIR / f"SISL_VFD_PL_{DATE_STR}_V.{ver:02d}.pdf"


def ensure_model_col(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure a 'Model' column exists by renaming compatible headers."""
    df.rename(columns=lambda c: c.strip(), inplace=True)
    for cand in CANDIDATE_MODEL_COLS:
        if cand in df.columns:
            if cand != "Model":
                df.rename(columns={cand: "Model"}, inplace=True)
            break
    else:
        raise ValueError("CSV missing a recognisable 'Model' column.")
    df["Model"] = df["Model"].astype(str).str.strip()
    return df


# ──────────────────────────────────────────────────────────
# LOAD DATA
# ──────────────────────────────────────────────────────────
try:
    inv_df = pd.read_csv(DATA_DIR / "VFD_PRICE_LAST.csv")
    price127_df = pd.read_csv(DATA_DIR / "VFD_PRICE_JULY_2025.csv")
    master_df = pd.read_csv(DATA_DIR / "VFD_Price_SISL_Final.csv")
except Exception as e:
    sys.exit(f"ERROR reading CSVs: {e}")

# Ensure model columns present & cleaned
inv_df = ensure_model_col(inv_df)
price127_df = ensure_model_col(price127_df)
master_df = ensure_model_col(master_df)

# Normalise inventory Quantity column name
if "Qty owned" in inv_df.columns and "Qty" not in inv_df.columns:
    inv_df.rename(columns={"Qty owned": "Qty"}, inplace=True)

# Mandatory columns check
if "Qty" not in inv_df.columns or "Total cost" not in inv_df.columns:
    sys.exit("Inventory CSV must have 'Qty' and 'Total cost' columns.")
if "1.27" not in price127_df.columns:
    sys.exit("Price list CSV must contain '1.27' column.")

# Build lookup maps
price127_map = dict(
    zip(price127_df["Model"], price127_df["1.27"].astype(float, errors="ignore"))
)

if "List Price" in master_df.columns:
    listprice_map = dict(
        zip(master_df["Model"], master_df["List Price"].astype(float, errors="ignore"))
    )
else:
    # Assume the column immediately after 'Model' holds list price
    lp_col_idx = master_df.columns.get_loc("Model") + 1
    lp_series = master_df.iloc[:, lp_col_idx].astype(float, errors="ignore")
    listprice_map = dict(zip(master_df["Model"], lp_series))

# ──────────────────────────────────────────────────────────
# TRANSFORM
# ──────────────────────────────────────────────────────────
records = []
for _, row in inv_df.iterrows():
    model = str(row["Model"]).strip()

    qty = row["Qty"]
    if pd.isna(qty) or qty == 0:
        continue

    if model in SKIP_MODEL_EXACT or (SKIP_MODEL_CONTAINS.lower() in model.lower()):
        continue

    total_cost = row["Total cost"]
    cogs = None
    if pd.notna(total_cost) and qty:
        cogs = float(total_cost) / float(qty)

    cogs_x175 = cogs * 1.75 if cogs is not None else None
    list_price = listprice_map.get(model)
    price127 = find_price127(model, price127_map)

    disc20 = list_price * 0.80 if list_price else None
    disc25 = list_price * 0.75 if list_price else None
    disc30 = list_price * 0.70 if list_price else None

    gp_percent = (
        ((list_price - cogs) / list_price) * 100
        if list_price and cogs is not None
        else None
    )

    records.append(
        {
            "Model": model,
            "Qty": qty,
            "ListPrice": list_price,
            "20% Disc": disc20,
            "25% Disc": disc25,
            "30% Disc": disc30,
            "GP%": gp_percent,
            "COGS": cogs,
            "COGS×1.75": cogs_x175,
            "1.27": price127,
        }
    )

df = pd.DataFrame(records)

# Sorting
df["CapacityKW"] = df["Model"].apply(extract_capacity_kw)
df["SeriesRank"] = df["Model"].apply(series_rank)
df.sort_values(["CapacityKW", "SeriesRank"], inplace=True, ignore_index=True)

# Add SL column
df.insert(0, "SL", range(1, len(df) + 1))

# ──────────────────────────────────────────────────────────
# PDF GENERATION
# ──────────────────────────────────────────────────────────
pdf = FPDF(unit="mm", format="A4")
pdf.set_auto_page_break(auto=True, margin=MARGIN_MM)
pdf.set_margins(MARGIN_MM, MARGIN_MM, MARGIN_MM)
pdf.add_page()

pdf.set_font("Arial", "B", 14)
pdf.cell(0, 10, "VFD STOCK LIST", 0, 1, "C")
pdf.ln(2)

# Table header
pdf.set_font("Arial", "B", 8)
for col_name, col_width, align in COLS:
    pdf.cell(col_width, 6, col_name, border=1, align=align)
pdf.ln()

# Table rows
pdf.set_font("Arial", "", 7)
row_h = 5
for _, record in df.iterrows():
    for (col_name, col_width, align) in COLS:
        val = record.get(col_name, "")
        if col_name in {
            "ListPrice",
            "20% Disc",
            "25% Disc",
            "30% Disc",
            "COGS",
            "COGS×1.75",
            "1.27",
        }:
            txt = money(val)
        elif col_name == "GP%":
            txt = percent(val)
        else:
            txt = str(val)
        pdf.cell(col_width, row_h, txt, border=1, align=align)
    pdf.ln()

# Save PDF
filename = next_pdf_filename()
pdf.output(str(filename))
print(f"PDF generated: {filename.relative_to(Path.cwd())}")
