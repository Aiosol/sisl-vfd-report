#!/usr/bin/env python3
"""
SISL VFD Stock Report Generator v0.5

Generates an A4-portrait PDF (0.6" margins) listing VFD inventory with costs,
list prices, discounts, and gross profit margin, sorted by capacity and series.
"""

import os
import re
import pandas as pd
from fpdf import FPDF
from datetime import datetime

# --- Configuration ---
DATA_DIR      = 'data'
PDF_DIR       = 'pdf_reports'
VERSION       = '0.5'
INVENTORY_CSV = os.path.join(DATA_DIR, 'VFD_PRICE_LAST.csv')
PRICE127_CSV  = os.path.join(DATA_DIR, 'VFD_PRICE_JULY_2025.csv')
MASTER_CSV    = os.path.join(DATA_DIR, 'VFD_Price_SISL_Final.csv')

# --- Load CSVs ---
df_inv    = pd.read_csv(INVENTORY_CSV)
df_127    = pd.read_csv(PRICE127_CSV)
df_master = pd.read_csv(MASTER_CSV)

# --- Normalize column names ---
df_inv.columns    = df_inv.columns.str.strip()
df_127.columns    = df_127.columns.str.strip()
df_master.columns = df_master.columns.str.strip()

# --- Identify and rename key columns ---
# Inventory: Model, Qty owned, Total cost
df_inv.rename(columns={'Qty owned': 'Qty', 'Total cost': 'TotalCost'}, inplace=True)
# Price127: rename first column to Model, find the '1.27' column
df_127.rename(columns={df_127.columns[0]: 'Model'}, inplace=True)
col_127 = next(c for c in df_127.columns if '1.27' in c)
df_127.rename(columns={col_127: 'Price127'}, inplace=True)
# Master: rename first column to Model, find list-price column
df_master.rename(columns={df_master.columns[0]: 'Model'}, inplace=True)
col_list = next(c for c in df_master.columns if 'List' in c)
df_master.rename(columns={col_list: 'ListPrice'}, inplace=True)

# --- Merge dataframes ---
df = (
    df_inv[['Model', 'Qty', 'TotalCost']]
    .merge(df_master[['Model', 'ListPrice']], on='Model', how='left')
    .merge(df_127[['Model', 'Price127']], on='Model', how='left')
)

# --- Apply filters ---
mask = (
    (df['Qty'] > 0)
    & (df['Model'] != 'FR-S520SE-0.2K-19')
    & (~df['Model'].str.contains('PEC', na=False))
)
df = df.loc[mask].copy()

# --- Calculations ---
df['COGS']    = df['TotalCost'] / df['Qty']
df['COGS175'] = df['COGS'] * 1.75
df['Disc20']  = df['ListPrice'] * 0.80
df['Disc25']  = df['ListPrice'] * 0.75
df['Disc30']  = df['ListPrice'] * 0.70
df['GP_pct']  = (df['ListPrice'] - df['COGS']) / df['ListPrice'] * 100

# --- Extract sort keys: capacity and series ---
def extract_capacity(m):
    found = re.search(r'-(\d+\.?\d*)K', m)
    return float(found.group(1)) if found else 0.0

def extract_series(m):
    found = re.match(r'FR-([A-Z]+)\d', m)
    return found.group(1) if found else ''

df['Capacity']    = df['Model'].apply(extract_capacity)
df['Series']      = df['Model'].apply(extract_series)
order_map = {'D': 0, 'E': 1, 'F': 2, 'A': 3, 'HEL': 4}
df['SeriesOrder'] = df['Series'].map(order_map).fillna(5)

# --- Sort dataframe ---
df.sort_values(['Capacity','SeriesOrder'], inplace=True)

# --- Prepare PDF output ---
os.makedirs(PDF_DIR, exist_ok=True)
today_str   = datetime.now().strftime('%Y%m%d')
output_file = f'SISL_VFD_Stock_Report_v{VERSION}_{today_str}.pdf'
output_path = os.path.join(PDF_DIR, output_file)

pdf = FPDF(orientation='P', unit='in', format='A4')
pdf.set_margins(0.6, 0.6, 0.6)
pdf.set_auto_page_break(auto=True, margin=0.6)
pdf.add_page()

# --- Header ---
pdf.set_font('Arial','B',12)
pdf.cell(0, 0.3, f'SISL VFD Stock Report v{VERSION} – {datetime.now():%Y-%m-%d}', ln=True, align='C')
pdf.ln(0.2)

# --- Table header ---
pdf.set_font('Arial','B',10)
headers = ['SL','Model','Qty','COGS','COGS×1.75','ListPrice','1.27','20% Disc','25% Disc','30% Disc','GP%']
col_widths = [0.4, 1.8, 0.5, 0.7, 0.8, 0.8, 0.8, 0.8, 0.8, 0.8, 0.6]
for h,w in zip(headers, col_widths):
    pdf.cell(w, 0.3, h, border=1, align='C')
pdf.ln()

# --- Table rows ---
pdf.set_font('Arial','',9)
for i, row in enumerate(df.itertuples(index=False), start=1):
    pdf.cell(col_widths[0], 0.25, str(i), 1, 0, 'C')
    pdf.cell(col_widths[1], 0.25, row.Model, 1, 0, 'L')
    pdf.cell(col_widths[2], 0.25, f'{int(row.Qty)}', 1, 0, 'C')
    pdf.cell(col_widths[3], 0.25, f'{row.COGS:,.2f}', 1, 0, 'R')
    pdf.cell(col_widths[4], 0.25, f'{row.COGS175:,.2f}', 1, 0, 'R')
    pdf.cell(col_widths[5], 0.25, f'{row.ListPrice:,.2f}', 1, 0, 'R')
    pdf.cell(col_widths[6], 0.25, f'{(row.Price127 if pd.notna(row.Price127) else 0):,.2f}', 1, 0, 'R')
    pdf.cell(col_widths[7], 0.25, f'{row.Disc20:,.2f}', 1, 0, 'R')
    pdf.cell(col_widths[8], 0.25, f'{row.Disc25:,.2f}', 1, 0, 'R')
    pdf.cell(col_widths[9], 0.25, f'{row.Disc30:,.2f}', 1, 0, 'R')
    pdf.cell(col_widths[10], 0.25, f'{row.GP_pct:,.2f}%', 1, 0, 'R')
    pdf.ln()

# --- Save PDF ---
pdf.output(output_path)
print(f"Generated PDF: {output_path}")
