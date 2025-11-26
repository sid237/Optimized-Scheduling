# app.py
import streamlit as st
import pandas as pd
from io import BytesIO
from Modules.preprocessing import load_workbook
from Modules.mrp_core import run_mrp_and_return_results
from Modules.scheduling_core import run_scheduling_with_mrp_integration
from Modules.charts import (
    render_scheduling_kpis,
    render_procurement_kpis,
    render_procurement_gantt,
    render_procurement_table,
    render_scheduling_gantt,
    render_scheduling_table
)
from Modules.utils import write_results_to_excel

st.set_page_config(page_title="MRP + Scheduling", layout="wide")
st.title("📦 MRP & Scheduling")

st.markdown(
    "Upload a input excel file (sheets: product details, Bill of materials, "
    "raw material details , Machines, Eligibility)."
)

uploaded = st.file_uploader("Upload Excel", type=["xlsx"])

if uploaded is not None:
    try:
        bytes_data = uploaded.read()
        # 1) Preprocess / read workbook
        sheets = load_workbook(BytesIO(bytes_data))

        # 2) Run MRP
        mrp_results = run_mrp_and_return_results(sheets['products_df'], sheets['bom_df'], sheets['materials_df'])

        procurement_df = mrp_results['procurement_df']
        comparison_df = mrp_results['comparison_df']

        # 3) Show procurement outputs
        if procurement_df.empty:
            st.warning("MRP produced no procurement orders.")
        else:
            # normalize fields
            procurement_df['Planned_Order_ReceiptDate'] = (
                pd.to_datetime(procurement_df.get('Planned_Order_ReceiptDate', pd.NaT))
            )
            procurement_df['Requirement_Date'] = (
                pd.to_datetime(procurement_df.get('Requirement_Date', pd.NaT))
            )

            st.markdown("### 📈 Procurement Summary")
            render_procurement_kpis(procurement_df)

            st.markdown("---")
            st.markdown("### 🗓️ Procurement Gantt (Raw Material vs Dates)")
            render_procurement_gantt(procurement_df)

            st.markdown("---")
            st.markdown("### 📋 Procurement Table")
            render_procurement_table(procurement_df)

        # 4) Run Scheduling (pass raw file sheets for Machines and Eligibility)
        sched_results = run_scheduling_with_mrp_integration(
            mrp_results,
            sheets['machines_df'],
            sheets['eligibility_df']
        )

        gantt_tasks_df = sched_results['gantt_tasks_df']
        milp_prod_df = sched_results['milp_prod_df']

        st.markdown("---")
        st.markdown("### 🏭 Machine Scheduling Gantt")
        if gantt_tasks_df.empty:
            st.write("No scheduling tasks produced by MILP.")
        else:
            # st.markdown("### 📈 Scheduling Summary")
            # render_scheduling_kpis(gantt_tasks_df)
            render_scheduling_gantt(gantt_tasks_df)
            st.markdown("**Notes:** duration for each product = production cycles × cycle time per batch + maintenance time (if any).")
            render_scheduling_table(gantt_tasks_df)

        # 5) Download combined excel
        towrite = write_results_to_excel(
            procurement_df=procurement_df,
            procurement_summary=comparison_df,
            machine_gantt=gantt_tasks_df,
            milp_prod=milp_prod_df
        )
        towrite.seek(0)
        st.download_button(
            "⬇️ Download results (Excel)",
            towrite,
            file_name="trimmed_mrp_scheduling_output_modular.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    except Exception as e:
        st.error(f"Processing error: {e}")
else:
    st.info("Upload an Excel input file to generate the trimmed report.")
