# modules/utils.py
from io import BytesIO
import pandas as pd

def write_results_to_excel(procurement_df=None, procurement_summary=None, machine_gantt=None, milp_prod=None):
    """
    Returns BytesIO with an excel workbook containing provided DataFrames.
    """
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        if procurement_df is not None and not procurement_df.empty:
            procurement_df.to_excel(writer, sheet_name='Optimized_Procurement_Plan', index=False)
        else:
            pd.DataFrame().to_excel(writer, sheet_name='Optimized_Procurement_Plan', index=False)

        if procurement_summary is not None and not procurement_summary.empty:
            procurement_summary.to_excel(writer, sheet_name='Procurement_Summary_Table', index=False)
        else:
            pd.DataFrame().to_excel(writer, sheet_name='Procurement_Summary_Table', index=False)

        if machine_gantt is not None and not machine_gantt.empty:
            machine_gantt.to_excel(writer, sheet_name='Machine_Gantt_Tasks', index=False)
        else:
            pd.DataFrame().to_excel(writer, sheet_name='Machine_Gantt_Tasks', index=False)

        if milp_prod is not None and not milp_prod.empty:
            milp_prod.to_excel(writer, sheet_name='MILP_Production', index=False)
        else:
            pd.DataFrame().to_excel(writer, sheet_name='MILP_Production', index=False)

    output.seek(0)
    return output
