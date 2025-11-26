# modules/preprocessing.py
import pandas as pd
from io import BytesIO

def _safe_read_excel(file_like, sheet_name, parse_dates=None):
    try:
        return pd.read_excel(file_like, sheet_name=sheet_name, parse_dates=parse_dates)
    except Exception:
        # return empty DF with no error (caller should handle)
        return pd.DataFrame()

def load_workbook(file_like):
    """
    Read the required sheets and perform basic cleanup/normalization.
    Returns dict with products_df, bom_df, materials_df, machines_df, eligibility_df
    """
    # We use BytesIO so pandas can read multiple times
    if isinstance(file_like, BytesIO):
        buffer = file_like
    else:
        buffer = BytesIO(file_like.read()) if hasattr(file_like, "read") else BytesIO(file_like)

    # Read sheets
    products_df = _safe_read_excel(buffer, sheet_name='product details', parse_dates=['Due Date'])
    # reset buffer pointer for next read
    buffer.seek(0)
    bom_df = _safe_read_excel(buffer, sheet_name='Bill of materials')
    buffer.seek(0)
    temp_materials_df = _safe_read_excel(buffer, sheet_name='raw material details ')
    buffer.seek(0)
    parse_dates_flag = ['PlannedOrderReceiptDate'] if 'PlannedOrderReceiptDate' in temp_materials_df.columns else False
    materials_df = _safe_read_excel(buffer, sheet_name='raw material details ', parse_dates=parse_dates_flag)
    buffer.seek(0)
    machines_df = _safe_read_excel(buffer, sheet_name='Machines')
    buffer.seek(0)
    eligibility_df = _safe_read_excel(buffer, sheet_name='Eligibility')

    # Basic cleanup same as original
    for df, cols in [(products_df, ['Product_ID']), (bom_df, ['Parent', 'Item']), (materials_df, ['Raw materials'])]:
        for col in cols:
            if col in df.columns and df[col].dtype == object:
                df[col] = df[col].str.strip()

    # Numeric coercions used downstream
    if 'PlannedOrderRelease' in products_df.columns:
        products_df['PlannedOrderRelease'] = pd.to_numeric(products_df.get('PlannedOrderRelease', 0), errors='coerce').fillna(0)
    else:
        products_df['PlannedOrderRelease'] = 0

    products_df['Units to Delivered'] = pd.to_numeric(products_df.get('Units to Delivered', 0), errors='coerce').fillna(0)
    products_df['OnHand'] = pd.to_numeric(products_df.get('OnHand', 0), errors='coerce').fillna(0)

    return {
        'products_df': products_df,
        'bom_df': bom_df,
        'materials_df': materials_df,
        'machines_df': machines_df,
        'eligibility_df': eligibility_df
    }
