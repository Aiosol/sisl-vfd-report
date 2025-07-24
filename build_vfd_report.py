#!/usr/bin/env python3
"""
SISL VFD Stock Report Generator v0.5
• Filters: zero‑Qty, FR‑S520SE‑0.2K‑19, 'PEC'
• Computes COGS, COGS×1.75, ListPrice, 1.27, 20/25/30 % discounts, GP %
• Sorts Capacity (0.4→400 K) then Series (D,E,F,A,HEL)
• Outputs A4‑portrait PDF (0.6″ margins) with versioned filename
"""

import os, re, sys
import pandas as pd
from fpdf import FPDF
from datetime import datetime

# ──────────────────────────────────────
# 1. Paths & constants
# ──────────────────────────────────────
DATA_DIR      = 'data'
PDF_DIR       = 'pdf_reports'
VERSION       = '0.5'
INVENTORY_CSV = os.path.join(DATA_DIR, 'VFD_PRICE_LAST.csv')
PRICE127_CSV  = os.path.join(DATA_DIR, 'VFD_PRICE_JULY_2025.csv')
MASTER_CSV    = os.path.join(DATA_DIR, 'VFD_Price_SISL_Final.csv')

# ──────────────────────────────────────
# 2. Load CSVs
# ──────────────────────────────────────
df_inv    = pd.read_csv(INVENTORY_CSV)
df_127    = pd.read_csv(PRICE127_CSV)
df_master = pd.read_csv(MASTER_CSV)

for df in (df_inv, df_127, df_master):
    df.columns = df.columns.str.strip()

# ──────────────────────────────────────
# 3. Detect & rename key columns
# ──────────────────────────────────────
# ---- Inventory (model / qty / cost) ----
model_col = next((c for c in df_inv.columns
                  if re.search(r'(model|material.*name)', c, re.I)), None)
if not model_col:                                   # fall back to first col
    model_col = df_inv.columns[0]
df_inv.rename(columns={model_col:'Model'}, inplace=True)

qty_col = next((c for c in df_inv.columns if re.search(r'qty', c, re.I)), None)
if not qty_col:
    sys.exit(f"❌ No quantity column found in {INVENTORY_CSV}. "
             f"Columns are: {', '.join(df_inv.columns)}")
df_inv.rename(columns={qty_col:'Qty'}, inplace=True)

cost_col = next((c for c in df_inv.columns
                 if re.search(r'(total).*cost', c, re.I)), None)
if not cost_col:
    sys.exit(f"❌ No total‑cost column found in {INVENTORY_CSV}. "
             f"Columns are: {', '.join(df_inv.columns)}")
df_inv.rename(columns={cost_col:'TotalCost'}, inplace=True)

# ---- Price‑1.27 ----
df_127.rename(columns={df_127.columns[0]:'Model'}, inplace=True)
col_127 = next((c for c in df_127.columns if '1.27' in c), None)
if not col_127:
    sys.exit(f"❌ 1.27 column not found in {PRICE127_CSV}. "
             f"Columns are: {', '.join(df_127.columns)}")
df_127.rename(columns={col_127:'Price127'}, inplace=True)

# ---- Master list price ----
df_master.rename(columns={df_master.columns[0]:'Model'}, inplace=True)
price_candidates = [c for c in df_master.columns
                    if re.search(r'price', c, re.I) and '1.27' not in c]
if not price_candidates:
    sys.exit(f"❌ No list‑price column found in {MASTER_CSV}. "
             f"Columns are: {', '.join(df_master.columns)}")
df_master.rename(columns={price_candidates[0]:'ListPrice'}, inplace=True)

# ──────────────────────────────────────
# 4. Merge & filter
# ──────────────────────────────────────
df = (df_inv[['Model','Qty','TotalCost']]
      .merge(df_master[['Model','ListPrice']], how='left')
      .merge(df_127[['Model','Price127']], how='left'))

df = df[(df.Qty > 0) &
        (df.Model != 'FR-S520SE-0.2K-19') &
        (~df.Model.str.contains('PEC', na=False))].copy()

# ──────────────────────────────────────
# 5. Calculations
# ──────────────────────────────────────
df['COGS']     = df.TotalCost / df.Qty
df['COGS175']  = df.COGS * 1.75
df['Disc20']   = df.ListPrice * 0.80
df['Disc25']   = df.ListPrice * 0.75
df['Disc30']   = df.ListPrice * 0.70
df['GP_pct']   = (df.ListPrice - df.COGS) / df.ListPrice * 100

df['Capacity'] = df.Model.str.extract(r'-(\d+\.?\d*)K').astype(float)
df['Series']   = df.Model.str.extract(r'FR-([A-Z]+)\d')
order_map      = {'D':0,'E':1,'F':2,'A':3,'HEL':4}
df['SeriesOrder'] = df.Series.map(order_map).fillna(5)
df.sort_values(['Capacity','SeriesOrder'], inplace=True)

# ──────────────────────────────────────
# 6. PDF output
# ──────────────────────────────────────
os.makedirs(PDF_DIR, exist_ok=True)
today = datetime.now().strftime('%Y%m%d')
out   = os.path.join(PDF_DIR,
         f'SISL_VFD_Stock_Report_v{VERSION}_{today}.pdf')

pdf = FPDF('P','in','A4')
pdf.set_margins(0.6,0.6,0.6)
pdf.set_auto_page_break(True,0.6)
pdf.add_page()

pdf.set_font('Arial','B',12)
pdf.cell(0,0.3,f'SISL VFD Stock Report v{VERSION} – {datetime.now():%Y-%m-%d}',
         ln=1,align='C')
pdf.ln(0.2)

headers = ['SL','Model','Qty','COGS','COGS×1.75','ListPrice',
           '1.27','20%','25%','30%','GP%']
widths  = [0.4,1.8,0.5,0.7,0.8,0.8,0.8,0.8,0.8,0.8,0.6]

pdf.set_font('Arial','B',10)
for h,w in zip(headers,widths):
    pdf.cell(w,0.3,h,1,0,'C')
pdf.ln()

pdf.set_font('Arial','',9)
for i,row in enumerate(df.itertuples(index=False),1):
    pdf.cell(widths[0],0.25,str(i),1,0,'C')
    pdf.cell(widths[1],0.25,row.Model,1,0,'L')
    pdf.cell(widths[2],0.25,f'{int(row.Qty)}',1,0,'C')
    pdf.cell(widths[3],0.25,f'{row.COGS:,.2f}',1,0,'R')
    pdf.cell(widths[4],0.25,f'{row.COGS175:,.2f}',1,0,'R')
    pdf.cell(widths[5],0.25,f'{row.ListPrice:,.2f}',1,0,'R')
    pdf.cell(widths[6],0.25,f'{row.Price127 if pd.notna(row.Price127) else 0:,.2f}',1,0,'R')
    pdf.cell(widths[7],0.25,f'{row.Disc20:,.2f}',1,0,'R')
    pdf.cell(widths[8],0.25,f'{row.Disc25:,.2f}',1,0,'R')
    pdf.cell(widths[9],0.25,f'{row.Disc30:,.2f}',1,0,'R')
    pdf.cell(widths[10],0.25,f'{row.GP_pct:,.2f}%',1,0,'R')
    pdf.ln()

pdf.output(out)
print("✅ PDF generated:", out)
