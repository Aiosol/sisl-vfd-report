#!/usr/bin/env python3
"""
SISL VFD STOCK LIST generator  • v0.9  (2025‑07‑24)

What’s new
----------
✓ Auto‑detects *all* critical columns (“Model”, “Qty”, “Total Cost”, “List Price”,
  “1.27”) across every CSV, so the script works even if headers vary
  (“Material Name”, “Item”, “Qty owned”, etc.).
✓ No other logic changed (filters, cascade, sorting, PDF, filename).

Repo layout unchanged
---------------------
project‑root/
├─ data/
│   ├─ VFD_PRICE_LAST.csv
│   ├─ VFD_PRICE_JULY_2025.csv
│   └─ VFD_Price_SISL_Final.csv
└─ pdf_reports/
"""

import glob
import re
from datetime import datetime
from pathlib import Path

import pandas as pd
from dateutil import tz
from fpdf import FPDF


# ───────────────────────────────────────────────────────────────────────────────
# Helper functions
# ───────────────────────────────────────────────────────────────────────────────
def find_col(df: pd.DataFrame, aliases: list[str]) -> str | None:
    """Return first column whose lowercase header matches any alias substr."""
    for a in aliases:
        for c in df.columns:
            if a in c.lower():
                return c
    return None


def series_tag(model: str) -> str:
    if re.search(r"fr-hel", model, re.I):
        return "H"
    m = re.match(r"fr-([a-z])", model, re.I)
    return m.group(1).upper() if m else ""


ORDER_MAP = {"D": 0, "E": 1, "F": 2, "A": 3, "H": 4}


def capacity_val(model: str) -> float:
    m = re.search(r"-(?:h)?([\d.]+)k", model, re.I)
    return float(m.group(1)) if m else 0.0


def alt_models(model: str) -> list[str]:
    alts: list[str] = []
    mapping = {
        r"fr-d720": "FR-A820",
        r"fr-e720": "FR-A820",
        r"fr-d740": "FR-A840",
        r"fr-e740": "FR-A840",
        r"fr-a820": "FR-D720",
        r"fr-a840": "FR-D740",
    }
    for patt, repl in mapping.items():
        if re.match(patt, model, re.I):
            alt = re.sub(patt, repl, model, flags=re.I)
            if "-1" not in alt and re.match(r"fr-a8", alt, re.I):
                alt += "-1"
            alts.append(alt)

    for s in ["D", "E", "F", "A"]:
        if s == series_tag(model):
            continue
        base = re.sub(r"fr-[a-z]", "FR-X", model, flags=re.I)
        alts.append(re.sub(r"FR-X", f"FR-{s}", base, flags=re.I))
    return list(dict.fromkeys(alts))


def money(v) -> str:
    return f"{v:,.0f}" if pd.notna(v) else ""


# ───────────────────────────────────────────────────────────────────────────────
# Load & harmonise CSVs
# ───────────────────────────────────────────────────────────────────────────────
DATA = Path(__file__).parent / "data"

inv_df = pd.read_csv(DATA / "VFD_PRICE_LAST.csv").rename(
    columns=lambda c: c.strip()
)
p127_df = pd.read_csv(DATA / "VFD_PRICE_JULY_2025.csv").rename(
    columns=lambda c: c.strip()
)
list_df = pd.read_csv(DATA / "VFD_Price_SISL_Final.csv").rename(
    columns=lambda c: c.strip()
)

# Detect inventory columns
inv_model = find_col(inv_df, ["model", "material", "item"])
inv_qty = find_col(inv_df, ["qty"])
inv_cost = find_col(inv_df, ["total cost", "totalcost", "cost"])

if None in (inv_model, inv_qty, inv_cost):
    raise ValueError(
        "Inventory CSV is missing a Model, Qty, or Total Cost column. "
        "Please check headers."
    )

inv_df = inv_df.rename(
    columns={inv_model: "Model", inv_qty: "Qty", inv_cost: "TotalCost"}
)

# Detect price‑list columns (master List Price map)
list_model = find_col(list_df, ["model", "material", "item"])
list_price = find_col(list_df, ["list price", "price"])

if None in (list_model, list_price):
    raise ValueError(
        "VFD_Price_SISL_Final.csv lacks a Model or List Price column."
    )

# Detect 1.27 list columns
p127_model = find_col(p127_df, ["model", "material", "item"])
p127_price = find_col(p127_df, ["1.27", "1_27", "1-27"])

if None in (p127_model, p127_price):
    raise ValueError(
        "VFD_PRICE_JULY_2025.csv lacks a Model or 1.27 column."
    )

# Build fast look‑ups
list_price_map = dict(zip(list_df[list_model], list_df[list_price]))
p127_map = dict(zip(p127_df[p127_model], p127_df[p127_price]))

# ───────────────────────────────────────────────────────────────────────────────
# Assemble report rows
# ───────────────────────────────────────────────────────────────────────────────
rows = []
for _, r in inv_df.iterrows():
    model = str(r["Model"]).strip()
    qty = r["Qty"]

    if qty == 0 or model.upper() == "FR-S520SE-0.2K-19" or "PEC" in model.upper():
        continue

    cogs = r["TotalCost"] / qty if qty else 0.0
    lp = list_price_map.get(model)
    if lp is None:
        for alt in alt_models(model):
            lp = list_price_map.get(alt)
            if lp is not None:
                break

    p127 = p127_map.get(model)
    disc20, disc25, disc30 = (lp * x if lp else None for x in (0.8, 0.75, 0.7))
    gp_pct = round((lp - cogs) / lp * 100, 2) if lp and cogs else None

    rows.append(
        dict(
            Model=model,
            Qty=qty,
            ListPrice=lp,
            **{"20%": disc20, "25%": disc25, "30%": disc30},
            **{"GP%": gp_pct, "COGS": cogs, "COGSx1.75": cogs * 1.75, "1.27": p127},
        )
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

pdf = FPDF("P", "mm", "A4")
pdf.set_margins(15.24, 15.24, 15.24)  # 0.6"
pdf.add_page()
pdf.set_auto_page_break(True, 15)

pdf.set_font("Helvetica", "B", 14)
pdf.cell(0, 8, "VFD STOCK LIST", ln=1, align="C")
pdf.set_font("Helvetica", "", 10)
pdf.cell(
    0, 5, datetime.now(tz.gettz("Asia/Dhaka")).strftime("%d %b %Y"), ln=1, align="C"
)
pdf.cell(0, 5, "Smart Industrial Solution Ltd.", ln=1, align="C")
pdf.ln(3)

pdf.set_font("Helvetica", "B", 7)
for col, w in COLS:
    pdf.cell(w, 6, col, 1, 0, "C")
pdf.ln()

pdf.set_font("Helvetica", "", 7)
fill = False
for _, row in df.iterrows():
    for col, w in COLS:
        v = row[col]
        txt = (
            f"{v:,.2f}%"
            if col == "GP%" and pd.notna(v)
            else money(v)
            if col != "Model"
            else row["Model"]
        )
        pdf.cell(w, 5, txt, 1, 0, "C" if col != "Model" else "L", fill=fill)
    pdf.ln()
    fill = not fill

# ───────────────────────────────────────────────────────────────────────────────
# Save PDF (auto‑increment per day)
# ───────────────────────────────────────────────────────────────────────────────
PDF_DIR = Path(__file__).parent / "pdf_reports"
PDF_DIR.mkdir(exist_ok=True)
date_tag = datetime.now(tz.gettz("Asia/Dhaka")).strftime("%y%m%d")
existing = sorted(glob.glob(str(PDF_DIR / f"SISL_VFD_PL_{date_tag}_V.*.pdf")))
ver = int(re.search(r"_V\.(\d+)\.pdf$", existing[-1]).group(1)) + 1 if existing else 1
outfile = PDF_DIR / f"SISL_VFD_PL_{date_tag}_V.{ver:02d}.pdf"
pdf.output(outfile)
print("✓ Report saved to:", outfile)
