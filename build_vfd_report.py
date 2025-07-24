#!/usr/bin/env python3
"""
SISL VFD Stock Report Generator

• Drop exactly three CSVs into ./data/:
  - Inventory (contains “Qty owned” & “Total cost”)
  - 1.27 price sheet (contains a “1.27” column)
  - Master List‐Price table (contains “List Price” or “ListPrice” header)
• Excludes zero‑qty, FR‑S520SE‑0.2K‑19, and “PEC” entries
• Calculates COGS, COGS×1.75, attaches official List Price, 1.27 prices,
  discounts (20/25/30%), and GP%
• Orders by capacity (0.4→400 K) then series D→E→F→A→HEL
• Generates A4‑portrait PDF with 0.6″ margins
• Auto‑increments V.xx in filename
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

# ─── AUTO‑DETECT CSVs ───────────────────────────────────
paths = glob.glob(os.path.join(DATA_DIR, "*.csv"))
inv_csv = price127_csv = listprice_csv = None

for p in paths:
    head = pd.read_csv(p, nrows=0).columns.str.strip().tolist()
    if "Qty owned" in head and "Total cost" in head:
        inv_csv = p
    elif "1.27" in head:
        price127_csv = p

# pick the List‑Price CSV by header
for p in paths:
    if p not in (inv_csv, price127_csv):
        head = pd.read_csv(p, nrows=0).columns.str.strip().tolist()
        # look for “List Price” or “ListPrice” in any column
        if any(c in head for c in ("List Price","ListPrice")):
            listprice_csv = p

if not all([inv_csv, price127_csv, listprice_csv]):
    raise FileNotFoundError(f"Expected 3 CSVs in {DATA_DIR}, found: {paths}")

# ─── HELPERS ────────────────────────────────────────────
def money(x):
    return f"{x:,.2f}" if pd.notna(x) else ""

def parse_listprice(path):
    df = pd.read_csv(path, dtype=str, keep_default_na=False).applymap(str.strip)
    mp = {}
    for _, row in df.iterrows():
        cells = [c for c in row.values if c]
        for i, c in enumerate(cells):
            if c.startswith("FR-"):
                mdl = c.split()[0]
                for nxt in cells[i+1:]:
                    if re.fullmatch(r"[\d,]+(?:\.\d+)?", nxt):
                        mp[mdl] = float(nxt.replace(",", ""))
                        break
    return mp

def fallback127(m, lookup):
    mm = re.search(r"-(?:H)?([\d.]+)K", m)
    if not mm: return None
    cap = mm.group(1)+"K"
    if "720" in m: return lookup.get(f"FR-E820-{cap}-1")
    if "740" in m: return lookup.get(f"FR-E840-{cap}-1")
    return None

def list_price(m, lp_map):
    if m in lp_map:
        return lp_map[m]
    mm = re.search(r"-(?:H)?([\d.]+)K", m)
    if not mm: return None
    cap = mm.group(1)+"K"
    # D720/E720 fallback → A820/E820
    if any(t in m for t in ("D720","D720S","E720","E820")):
        return lp_map.get(f"FR-A820-{cap}-1") or lp_map.get(f"FR-E820-{cap}-1")
    # D740/E740 fallback → A840/E840
    if any(t in m for t in ("D740","E740","E840")):
        return lp_map.get(f"FR-A840-{cap}-1") or lp_map.get(f"FR-E840-{cap}-1")
    return None

def get_series(m):
    mt = re.match(r"FR-([A-Z]+?)-", m)
    if not mt: return ""
    tag = mt.group(1)
    return "H" if tag=="HEL" else tag[0]

def get_capacity(m):
    mm = re.search(r"-(?:H)?([\d.]+)K", m)
    return float(mm.group(1)) if mm else 0.0

# ─── LOAD & PROCESS ─────────────────────────────────────
# Master List‐Price
lp_map = parse_listprice(listprice_csv)

# Inventory
inv = pd.read_csv(inv_csv)
inv.columns = inv.columns.str.strip()
inv["Model"] = (
    inv["Name"].str.split("||").str[-1].str.strip()
       .replace({"FR-D720S-025-NA":"FR-D720S-0.4K"})
)
inv = inv[(inv["Qty owned"]>0) & ~inv["Model"].isin({"FR-S520SE-0.2K-19","PEC"})]

inv["Qty"]       = inv["Qty owned"].astype(int)
inv["TotalCost"] = inv["Total cost"].astype(str).str.replace(",","").astype(float)
inv["COGS"]      = inv["TotalCost"] / inv["Qty"]
inv["COGS_x1.75"]= inv["COGS"] * 1.75

# 1.27 prices
p127 = pd.read_csv(price127_csv)
p127_map = dict(zip(
    p127.iloc[:,0].str.strip(),
    p127.iloc[:,1].astype(str).str.replace(",","").astype(float)
))
inv["1.27"] = inv["Model"].apply(lambda m: p127_map.get(m, fallback127(m,p127_map)))

# Attach List Price + discounts + GP%
inv["Series"]    = inv["Model"].apply(get_series)
inv["IsHEL"]     = inv["Series"]=="H"
inv["ListPrice"] = inv["Model"].apply(lambda m: None if m.startswith("HEL") else list_price(m,lp_map))
inv.loc[inv["IsHEL"], "ListPrice"] = None

inv["Disc20"] = inv["ListPrice"] * 0.80
inv["Disc25"] = inv["ListPrice"] * 0.75
inv["Disc30"] = inv["ListPrice"] * 0.70
inv["GPpct"]  = (inv["ListPrice"] - inv["COGS"]) / inv["COGS"] * 100

# Sort
inv["Capacity"]    = inv["Model"].apply(get_capacity)
order_map         = {"D":0,"E":1,"F":2,"A":3,"H":4}
inv["SeriesOrder"] = inv["Series"].map(order_map).fillna(99)
inv.sort_values(["Capacity","SeriesOrder"], inplace=True, ignore_index=True)
inv.insert(0, "SL", range(1, len(inv)+1))

# ─── PDF OUTPUT ─────────────────────────────────────────
class StockPDF(FPDF):
    def header(self):
        self.set_font("Arial","B",16)
        self.cell(0,8,"VFD STOCK LIST",0,1,'C'); self.ln(1)
        self.set_font("Arial",size=10)
        self.cell(0,5,f"Date: {datetime.now():%d %B, %Y}",0,1,'C')
        self.cell(0,5,"Smart Industrial Solution Ltd.",0,1,'C'); self.ln(4)
    def footer(self):
        self.set_y(-12); self.set_font("Arial","I",8)
        self.cell(0,6,f"Page {self.page_no()}",0,0,'C')

cols = [
    ("SL",8,'C'),("Model",34,'L'),("Qty",8,'C'),("List Price",17,'R'),
    ("20% Disc",17,'R'),("25% Disc",17,'R'),("30% Disc",17,'R'),
    ("GP%",11,'R'),("COGS",17,'R'),("COGS ×1.75",18,'R'),("1.27",17,'R')
]

pdf = StockPDF('P','mm','A4')
m = MARGIN_INCH * 25.4
pdf.set_margins(m,15,m)
pdf.set_auto_page_break(True,15)
pdf.add_page()

# Header row
pdf.set_font("Arial","B",HDR_FONT)
for t,w,a in cols: pdf.cell(w,ROW_H,t,1,0,a)
pdf.ln()

# Body rows
pdf.set_font("Arial",size=BODY_FONT)
fill=False
for _,r in inv.iterrows():
    pdf.set_fill_color(242,242,242) if fill else pdf.set_fill_color(255,255,255)
    for key,w,a in cols:
        v = r.get(key, None)
        txt = f"{v:,.2f}%" if key=="GP%" and pd.notna(v) else money(v)
        pdf.cell(w,ROW_H,txt,1,0,a,fill)
    pdf.ln(); fill = not fill

# Total
pdf.set_font("Arial","B",BODY_FONT)
pdf.cell(cols[0][1]+cols[1][1],ROW_H,"Total",1,0,'R')
pdf.cell(cols[2][1],ROW_H,str(inv["Qty"].sum()),1,0,'C')
pdf.cell(sum(w for _,w,_ in cols[3:]),ROW_H,"",1,0)

os.makedirs(OUT_DIR, exist_ok=True)
tag = datetime.now().strftime("%y%m%d")
existing = glob.glob(f"{OUT_DIR}/SISL_VFD_PL_{tag}_V.*.pdf")
vers     = [int(re.search(r"_V\.(\d{2})\.pdf",f).group(1)) for f in existing] if existing else []
next_v   = max(vers)+1 if vers else 5
outfile  = f"SISL_VFD_PL_{tag}_V.{next_v:02d}.pdf"
pdf.output(os.path.join(OUT_DIR, outfile))
print("Generated:", outfile)
