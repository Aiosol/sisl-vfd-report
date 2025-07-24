#!/usr/bin/env python3
"""
SISL VFD Stock Report Generator · v0.5

• Place exactly three CSVs in ./data/:
  1. VFD_PRICE_LAST.csv        # inventory  (has “Qty owned” & “Total cost” columns)
  2. VFD_PRICE_JULY_2025.csv   # July-2025 price list (has “1.27” column)
  3. VFD_Price_SISL_Final.csv  # master list-price map (Model, ListPrice)

• Excludes zero-qty, FR-S520SE-0.2K-19, and any model containing “PEC”
• Calculates COGS, COGS×1.75, ListPrice lookup cascade, 1.27 price, discounts, GP%
• Sorts by capacity (0.4K → 400K) then series D→E→F→A→HEL
• Outputs A4 portrait PDF (0.6" margins) to ./pdf_reports/ with filename SISL_VFD_PL_<YYMMDD>_V.<nn>.pdf
"""
import os
import re
import glob
from datetime import datetime
timport pandas as pd
from dateutil import parser
tfrom fpdf import FPDF

# ─── CONFIG ─────────────────────────────────────────────────────────
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
OUT_DIR = os.path.join(os.path.dirname(__file__), "pdf_reports")
VERSION_TAG = "0.5"
MARGIN_INCH = 0.6  # inch
PAGE_WIDTH_MM = 210
PAGE_HEIGHT_MM = 297
ROW_H = 6

# Column widths (mm)
COL_WIDTHS = {
    'SL': 8, 'Model': 34, 'Qty': 8,
    'List': 17, '20%': 17, '25%': 17, '30%': 17,
    'GP%': 11, 'COGS': 17, 'COGS×1.75': 18, '1.27': 17
}

# Helper functions
MODEL_SKIP = re.compile(r'FR-S520SE-0\.2K-19', re.I)
PEC_SKIP = re.compile(r'PEC', re.I)


def series_tag(model):
    if re.search(r'FR-HEL', model, re.I):
        return 'H'
    m = re.match(r'FR-([A-Z])', model)
    return m.group(1) if m else ''

order_map = {'D': 0, 'E': 1, 'F': 2, 'A': 3, 'H': 4}


def capacity_val(model):
    m = re.search(r'-(?:H)?([\d.]+)K', model)
    return float(m.group(1)) if m else 0.0


def money(v):
    try:
        return f"{float(v):,.2f}"
    except:
        return ""


# Load data
inv_df = pd.read_csv(os.path.join(DATA_DIR, 'VFD_PRICE_LAST.csv'))
price127_df = pd.read_csv(os.path.join(DATA_DIR, 'VFD_PRICE_JULY_2025.csv'))
master_df = pd.read_csv(os.path.join(DATA_DIR, 'VFD_Price_SISL_Final.csv'))

# Normalize column names
inv_df.rename(columns={col: col.strip() for col in inv_df.columns}, inplace=True)
price127_df.rename(columns={col: col.strip(): col.replace(' ', '') for col in price127_df.columns}, inplace=True)
master_df.rename(columns={col: col.strip() for col in master_df.columns}, inplace=True)

# Filters
df = inv_df.copy()
mask_valid = (
    df['Qty owned'] > 0) &
    ~df['Model'].str.match(MODEL_SKIP) &
    ~df['Model'].str.contains(PEC_SKIP)
)
df = df[mask_valid]

# Merge 1.27 data
df = df.merge(price127_df[['Model', '1.27']], on='Model', how='left')

# Cascade lookup for ListPrice
list_map = master_df.set_index('Model')['ListPrice'].to_dict()

# capacity-series groups map
series_groups = {}
for model in df['Model']:
    cap = capacity_val(model)
    series_groups.setdefault(cap, []).append(model)

# For each capacity fill list price
for cap, models in series_groups.items():
    # cross-series fallback order
    fallback_order = ['A', 'E', 'F', 'D']
    for m in models:
        if pd.notna(df.loc[df['Model'] == m, 'ListPrice']).bool():
            continue
        # exact
        if m in list_map:
            df.loc[df['Model'] == m, 'ListPrice'] = list_map[m]
            continue
        # 720/740 to A820/A840 fallback
        base = re.sub(r'-[EDFA]?[78]?(20|40)K', '-A' + str(cap).replace('.', '') + 'K-1', m)
        if base in list_map:
            df.loc[df['Model'] == m, 'ListPrice'] = list_map[base]
            continue
        # generic cross-series
        for s in fallback_order:
            alt = re.sub(r'^FR-[A-Z]', f'FR-{s}', m)
            if alt in list_map:
                df.loc[df['Model'] == m, 'ListPrice'] = list_map[alt]
                break

# Calculate fields
df['COGS'] = df['Total cost'] / df['Qty owned']
df['COGS×1.75'] = df['COGS'] * 1.75
# 1.27 fallback to ListPrice if missing
df['1.27'] = df.apply(lambda x: x['1.27'] if pd.notna(x['1.27']) else x['ListPrice'], axis=1)
# Discounts
for d in [20, 25, 30]:
    df[f'{d}%'] = df['ListPrice'] * (1 - d / 100)
# GP%
df['GP%'] = (df['ListPrice'] - df['COGS']) / df['ListPrice'] * 100

# Sorting
df['capacity'] = df['Model'].apply(capacity_val)
df['series'] = df['Model'].apply(series_tag)
df['series_order'] = df['series'].map(order_map)
df.sort_values(['capacity', 'series_order'], inplace=True)

# PDF generation
if not os.path.exists(OUT_DIR): os.makedirs(OUT_DIR)

# Filename increment
today = datetime.now().strftime('%y%m%d')
pattern = os.path.join(OUT_DIR, f'SISL_VFD_PL_{today}_V.*.pdf')
existing = glob.glob(pattern)
idx = len(existing) + 1
filename = os.path.join(OUT_DIR, f'SISL_VFD_PL_{today}_V.{idx:02d}.pdf')

pdf = FPDF(format='A4', unit='mm')
pdf.set_auto_page_break(False)
pdf.add_page()
# Margins
pdf.set_margins(MARGIN_INCH*25.4, MARGIN_INCH*25.4)

# Header
pdf.set_font('Arial', 'B', 16)
pdf.cell(0, 10, 'VFD STOCK LIST', ln=True, align='C')
pdf.set_font('Arial', '', 12)
pdf.cell(0, 8, 'Date: ' + datetime.now().strftime('%d %B, %Y'), ln=True, align='C')
pdf.cell(0, 8, 'Smart Industrial Solution Ltd.', ln=True, align='C')
pdf.ln(4)

# Table header
pdf.set_font('Arial', 'B', 8)
for col, w in COL_WIDTHS.items():
    pdf.cell(w, ROW_H, col, 1, 0, 'C')
pdf.ln(ROW_H)

# Table rows
pdf.set_font('Arial', '', 8)
for i, row in df.iterrows():
    txts = [
        str(i+1), row['Model'],
        str(int(row['Qty owned'])),
        money(row['ListPrice']),
        money(row['20%']), money(row['25%']), money(row['30%']),
        f"{row['GP%']:.2f}%",
        money(row['COGS']), money(row['COGS×1.75']), money(row['1.27'])
    ]
    for (col, w), txt in zip(COL_WIDTHS.items(), txts):
        align = 'R' if col not in ['Model'] else 'L'
        pdf.cell(w, ROW_H, txt, 1, 0, align)
    pdf.ln(ROW_H)

# Output
pdf.output(filename)
print(f"Report generated: {filename}")
