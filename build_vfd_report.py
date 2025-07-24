#!/usr/bin/env python3
"""
SISL VFD Stock Report Generator

• Place exactly three CSVs in ./data/:
  1. Inventory        (has “Qty owned” & “Total cost” columns)
  2. 1.27 price list  (has a “1.27” column)
  3. List‑Price map   (ideally named VFD_Price_SISL_Final.csv)

• Excludes zero‑qty, FR‑S520SE‑0.2K‑19, and “PEC”
• Calculates COGS, COGS×1.75, List Price, 1.27 prices, discounts, GP %
• Sorts by capacity (0.4 K → 400 K) then D→E→F→A→HEL
• Outputs an A4‑portrait PDF (0.6″ margins) in ./pdf_reports/
  with auto‑incremented version tag.
"""

import os, re, glob
from datetime import datetime
import pandas as pd
from fpdf import FPDF

# ─── CONFIG ─────────────────────────────────────────────
DATA_DIR    = "data"
OUT_DIR     = "pdf_reports"
MARGIN_INCH = 0.6
ROW_H       = 5
HDR_FONT    = 7
BODY_FONT   = 7

# ─── UTIL ───────────────────────────────────────────────
def money(x):
    try:
        return f"{float(x):,.2f}"
    except:
        return ""

# ─── DETECT CSVs ────────────────────────────────────────
paths = glob.glob(os.path.join(DATA_DIR, "*.csv"))
inv_csv = price127_csv = listprice_csv = None

# Prefer explicit filename for list‑price
for p in paths:
    if os.path.basename(p).lower() == "vfd_price_sisl_final.csv":
        listprice_csv = p
        break

# Identify inventory and 1.27 files by header
for p in paths:
    hdr = pd.read_csv(p, nrows=0).columns.str.strip().tolist()
    if {"Qty owned", "Total cost"}.issubset(hdr):
        inv_csv = p
    elif "1.27" in hdr:
        price127_csv = p

# Fallback: the remaining file is list‑price
if not listprice_csv:
    leftovers = [p for p in paths if p not in (inv_csv, price127_csv)]
    if leftovers:
        listprice_csv = leftovers[0]

if not all((inv_csv, price127_csv, listprice_csv)):
    raise FileNotFoundError(f"Expected 3 CSVs in {DATA_DIR}, found: {paths}")

# ─── HELPERS ────────────────────────────────────────────
def parse_listprice(fp):
    df = pd.read_csv(fp, dtype=str, keep_default_na=False).applymap(str.strip)
    mp = {}
    for _, row in df.iterrows():
        cells = [c for c in row if c]
        for i, c in enumerate(cells):
            if c.startswith("FR-"):
                model = c.split()[0]
                for nxt in cells[i+1:]:
                    if re.fullmatch(r"[\d,]+(?:\.\d+)?", nxt):
                        mp[model] = float(nxt.replace(",", ""))
                        break
    return mp

def fallback127(model, lookup):
    m = re.search(r"-(?:H)?([\d.]+)K", model)
    if not m: return None
    cap = m.group(1)+"K"
    if "720" in model: return lookup.get(f"FR-E820-{cap}-1")
    if "740" in model: return lookup.get(f"FR-E840-{cap}-1")
    return None

def list_price(model, lp):
    if model in lp: return lp[model]
    m = re.search(r"-(?:H)?([\d.]+)K", model)
    if not m: return None
    cap = m.group(1)+"K"
    if any(t in model for t in ("D720","D720S","E720","E820")):
        return lp.get(f"FR-A820-{cap}-1") or lp.get(f"FR-E820-{cap}-1")
    if any(t in model for t in ("D740","E740","E840")):
        return lp.get(f"FR-A840-{cap}-1") or lp.get(f"FR-E840-{cap}-1")
    return None

def series_tag(model):
    m = re.match(r"FR-([A-Z]+?)-", model)
    if not m: return ""
    tag = m.group(1)
    return "H" if tag=="HEL" else tag[0]

def capacity_val(model):
    m = re.search(r"-(?:H)?([\d.]+)K", model)
    return float(m.group(1)) if m else 0.0

# ─── LOAD & PROCESS ────────────────────────────────────
lp_map = parse_listprice(listprice_csv)

inv = pd.read_csv(inv_csv)
inv.columns = inv.columns.str.strip()
col_src = "Name" if "Name" in inv.columns else "Model"
inv["Model"] = (
    inv[col_src].astype(str)
       .apply(lambda s: s.split("||")[-1].strip())
       .replace({"FR-D720S-025-NA": "FR-D720S-0.4K"})
)
inv = inv[(inv["Qty owned"]>0) & ~inv["Model"].isin({"FR-S520SE-0.2K-19","PEC"})]
inv["Qty"]       = inv["Qty owned"].astype(int)
inv["TotalCost"] = inv["Total cost"].str.replace(",","").astype(float)
inv["COGS"]      = inv["TotalCost"] / inv["Qty"]
inv["COGS_x1.75"]= inv["COGS"] * 1.75

p127 = pd.read_csv(price127_csv)
p127_map = dict(zip(
    p127.iloc[:,0].str.strip(),
    p127.iloc[:,1].astype(str).str.replace(",","").astype(float)
))
inv["1.27"]     = inv["Model"].apply(lambda m: p127_map.get(m, fallback127(m,p127_map)))
inv["Series"]   = inv["Model"].apply(series_tag)
inv["ListPrice"]= inv["Model"].apply(lambda m: list_price(m, lp_map))

inv["Disc20"] = inv["ListPrice"] * 0.80
inv["Disc25"] = inv["ListPrice"] * 0.75
inv["Disc30"] = inv["ListPrice"] * 0.70
inv["GPpct"]  = (inv["ListPrice"] - inv["COGS"]) / inv["COGS"] * 100

inv["Capacity"]    = inv["Model"].apply(capacity_val)
order_map          = {"D":0,"E":1,"F":2,"A":3,"H":4}
inv["SeriesOrder"] = inv["Series"].map(order_map).fillna(99)
inv.sort_values(["Capacity","SeriesOrder"], inplace=True, ignore_index=True)
inv.insert(0, "SL", range(1, len(inv)+1))

# ─── PDF OUTPUT ─────────────────────────────────────────
class StockPDF(FPDF):
    def header(self):
        self.set_font("Arial","B",16)
        self.cell(0,8,"VFD STOCK LIST",0,1,'C'); self.ln(1)
        self.set_font("Arial",10)
        self.cell(0,5,datetime.now().strftime("Date: %d %B, %Y"),0,1,'C')
        self.cell(0,5,"Smart Industrial Solution Ltd.",0,1,'C'); self.ln(4)
    def footer(self):
        self.set_y(-12); self.set_font("Arial","I",8)
        self.cell(0,6,f"Page {self.page_no()}",0,0,'C')

cols = [
    ("SL",8,'C'),("Model",34,'L'),("Qty",8,'C'),
    ("List Price",17,'R'),("20% Disc",17,'R'),("25% Disc",17,'R'),
    ("30% Disc",17,'R'),("GP%",11,'R'),("COGS",17,'R'),
    ("COGS ×1.75",18,'R'),("1.27",17,'R')
]

pdf = StockPDF('P','mm','A4')
margin_mm = MARGIN_INCH * 25.4
pdf.set_margins(margin_mm,15,margin_mm)
pdf.set_auto_page_break(True,15)
pdf.add_page()

pdf.set_font("Arial","B",HDR_FONT)
for title,width,align in cols:
    pdf.cell(width,ROW_H,title,1,0,align)
pdf.ln()

pdf.set_font("Arial",size=BODY_FONT)
shade = False
for _, r in inv.iterrows():
    pdf.set_fill_color(242,242,242) if shade else pdf.set_fill_color(255,255,255)
    pdf.cell(cols[0][1],ROW_H,str(int(r["SL"])),1,0,'C',shade)
    pdf.cell(cols[1][1],ROW_H,r["Model"],1,0,'L',shade)
    pdf.cell(cols[2][1],ROW_H,str(int(r["Qty"])),1,0,'C',shade)
    pdf.cell(cols[3][1],ROW_H,money(r["ListPrice"]),1,0,'R',shade)
    pdf.cell(cols[4][1],ROW_H,money(r["Disc20"]),1,0,'R',shade)
    pdf.cell(cols[5][1],ROW_H,money(r["Disc25"]),1,0,'R',shade)
    pdf.cell(cols[6][1],ROW_H,money(r["Disc30"]),1,0,'R',shade)
    pdf.cell(cols[7][1],ROW_H,(f"{r['GPpct']:.2f}%" if pd.notna(r["GPpct"]) else ""),1,0,'R',shade)
    pdf.cell(cols[8][1],ROW_H,money(r["COGS"]),1,0,'R',shade)
    pdf.cell(cols[9][1],ROW_H,money(r["COGS_x1.75"]),1,0,'R',shade)
    pdf.cell(cols[10][1],ROW_H,money(r["1.27"]),1,0,'R',shade)
    pdf.ln()
    shade = not shade

pdf.set_font("Arial","B",BODY_FONT)
pdf.cell(cols[0][1]+cols[1][1],ROW_H,"Total",1,0,'R')
pdf.cell(cols[2][1],ROW_H,str(int(inv["Qty"].sum())),1,0,'C')
pdf.cell(sum(w for _,w,_ in cols[3:]),ROW_H,"",1,0)

os.makedirs(OUT_DIR, exist_ok=True)
tag = datetime.now().strftime("%y%m%d")
existing = glob.glob(f"{OUT_DIR}/SISL_VFD_PL_{tag}_V.*.pdf")
vers = [int(re.search(r"_V\\.(\\d{2})\\.pdf",f).group(1)) for f in existing] if existing else []
outfile = f"SISL_VFD_PL_{tag}_V.{(max(vers)+1 if vers else 5):02d}.pdf"
pdf.output(os.path.join(OUT_DIR, outfile))

print("Generated:", outfile)
