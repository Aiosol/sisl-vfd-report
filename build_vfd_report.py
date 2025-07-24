#!/usr/bin/env python3
"""
SISL VFD STOCK LIST generator  • version 0.8  (2025-07-24)

Changes in v0.8
---------------
• List-price CSV may label its columns differently (“Material Name”, “Model Name”,
  “Item”, etc.).  The script now auto-detects the *model* and *list-price* columns
  instead of assuming exact names (“Model”, “List Price”).
• No other logic changed.

Repo layout (unchanged)
-----------------------
project-root/
├─ data/
│   ├─ VFD_PRICE_LAST.csv         # inventory  (Qty owned, Total cost)
│   ├─ VFD_PRICE_JULY_2025.csv    # July-25 “1.27” price list   (1.27 column)
│   └─ VFD_Price_SISL_Final.csv   # master list-price map   ← can have flexible headers
└─ pdf_reports/                   # output PDFs
"""

import glob
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
    if re.search(r"FR-HEL", model, re.I):
        return "H"
    m = re.match(r"FR-([A-Z])", model, re.I)
    return m.group(1).upper() if m else ""


ORDER_MAP = {"D": 0, "E": 1, "F": 2, "A": 3, "H": 4}


def capacity_val(model: str) -> float:
    m = re.search(r"-(?:H)?([\d.]+)K", model, re.I)
    return float(m.group(1)) if m else 0.0


def alt_models(model: str) -> list[str]:
    alts: list[str] = []
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
            if "-1" not in alt and re.match(r"FR-A8", alt, re.I):
                alt += "-1"
            alts.append(alt)

    for s in ["D", "E", "F", "A"]:
        if s == series_tag(model):
            continue
        base = re.sub(r"FR-[A-Z]", "FR-X", model, flags=re.I)
        alts.append(re.sub(r"FR-X", f"FR-{s}", base, flags=re.I))
    return list(dict.fromkeys(alts))


def money(v) -> str:
    return f"{v:,.0f}" if pd.notna(v) else ""


# ───────────────────────────────────────────────────────────────────────────────
# Load CSVs
# ───────────────────────────────────────────────────────────────────────────────
DATA_DIR = Path(__file__).parent / "data"
inv_df = pd.read_csv(DATA_DIR / "VFD_PRICE_LAST.csv").rename(
    columns=lambda c: c.strip().title().replace(" ", "")
)
price127_df = pd.read_csv(DATA_DIR / "VFD_PRICE_JULY_2025.csv").rename(
    columns=lambda c: c.strip()
)
list_df = pd.read_csv(DATA_DIR / "VFD_Price_SISL_Final.csv").rename(
    columns=lambda c: c.strip()
)

# ── Detect column names in list-price CSV ─────────────────────────────────────
model_col = next(
    (
        c
        for c in list_df.columns
        if c.lower()
        in ["model", "model name", "material name", "item", "item name", "material"]
    ),
    None,
)
price_col = next(
    (
        c
        for c in list_df.columns
        if "list" in c.lower() and "price" in c.lower()
        or c.lower() in ["price", "price (bdt)"]
    ),
    None,
)
if model_col is None or price_col is None:
    raise ValueError(
        "Cannot locate model / price columns in VFD_Price_SISL_Final.csv. "
        "Please ensure it has headers like ‘Model’, ‘Material Name’, ‘List Price’, etc."
    )

price127_map = dict(zip(price127_df["Material Name"], price127_df["1.27"]))
list_price_map = dict(zip(list_df[model_col], list_df[price_col]))

# ───────────────────────────────────────────────────────────────────────────────
# Assemble report rows
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

    cogs = r["Totalcost"] / qty if qty else 0.0
    lp = list_price_map.get(model)
    if lp is None:
        for alt in alt_models(model):
            lp = list_price_map.get(alt)
            if lp is not None:
                break

    p127 = price127_map.get(model)
    discs = {d: lp * (1 - d / 100) if lp else None for d in (20, 25, 30)}
    gp_pct = round((lp - cogs) / lp * 100, 2) if lp and cogs else None

    rows.append(
        dict(
            Model=model,
            Qty=qty,
            ListPrice=lp,
            **{f"{d}%": discs[d] for d in (20, 25, 30)},
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
    0,
    5,
    datetime.now(tz.gettz("Asia/Dhaka")).strftime("%d %b %Y"),
    ln=1,
    align="C",
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
        val = row[col]
        txt = (
            f"{val:,.2f}%"
            if col == "GP%" and pd.notna(val)
            else money(val)
            if col != "Model"
            else row["Model"]
        )
        pdf.cell(w, 5, txt, 1, 0, "C" if col != "Model" else "L", fill=fill)
    pdf.ln()
    fill = not fill

# ───────────────────────────────────────────────────────────────────────────────
# Save PDF (auto-increment version per day)
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
