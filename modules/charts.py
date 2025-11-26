import streamlit as st
import plotly.express as px
import pandas as pd
from datetime import datetime

# Common chart style to ensure black text
def _apply_chart_style(fig):
    fig.update_layout(
        font=dict(color="black"),
        title=dict(font=dict(color="black", size=18)),
        xaxis=dict(
            title_font=dict(color="black"),
            tickfont=dict(color="black"),
            showgrid=True,
            gridcolor="lightgray",
            gridwidth=1,
            zeroline=False
        ),
        yaxis=dict(
            title_font=dict(color="black"),
            tickfont=dict(color="black"),
            showgrid=True,
            gridcolor="lightgray",
            gridwidth=1,
            zeroline=False
        ),
        legend=dict(
            font=dict(color="black"),
            title_font=dict(color="black")
        ),
        plot_bgcolor="rgba(245,245,245,1)",
        paper_bgcolor="white",
        margin=dict(l=20, r=20, t=60, b=20),
        hoverlabel=dict(font_color="black", bgcolor="white")
    )
    return fig


def render_procurement_kpis(procurement_df):
    proc_table = procurement_df.groupby('RawMaterial_ID').agg(
        OrderType=('LotSizingModel_Used', lambda s: s.mode().iloc[0] if not s.mode().empty else s.iloc[0]),
        TotalQuantity=('Planned_Order_Qty', 'sum'),
        Members=('Planned_Order_Qty', 'count'),
        EarliestDate=('Planned_Order_ReceiptDate', 'min')
    ).reset_index().rename(columns={'RawMaterial_ID': 'Raw Material', 'OrderType': 'Order Type'})
    proc_table['EarliestDate'] = pd.to_datetime(proc_table['EarliestDate']).dt.date

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🧱 Total Unique Materials", f"{proc_table['Raw Material'].nunique()}")
    c2.metric("📦 Total Quantity Ordered", f"{int(proc_table['TotalQuantity'].sum()):,}")
    next_row = procurement_df.sort_values('Planned_Order_ReceiptDate').head(1)
    if not next_row.empty and pd.notna(next_row.iloc[0]['Planned_Order_ReceiptDate']):
        c3.metric("⏰ Next Procurement", f"{next_row.iloc[0]['RawMaterial_ID']} on {pd.to_datetime(next_row.iloc[0]['Planned_Order_ReceiptDate']).date()}")
    else:
        c3.metric("⏰ Next Procurement", "None planned")
    c4.metric("📄 Total Orders", f"{len(procurement_df)}")


def render_procurement_gantt(procurement_df):
    gantt_df = procurement_df.copy()
    gantt_df['Start'] = gantt_df['Requirement_Date'].fillna(gantt_df.get('Planned_Order_Release', pd.NaT))
    gantt_df['Start'] = pd.to_datetime(gantt_df['Start'])
    gantt_df['Finish'] = pd.to_datetime(gantt_df['Planned_Order_ReceiptDate']).fillna(gantt_df['Start'] + pd.Timedelta(days=1))
    gantt_df['SimpleType'] = gantt_df['LotSizingModel_Used'].astype(str).str.upper().apply(
        lambda x: 'POQ' if 'POQ' in x else ('EOQ' if 'EOQ' in x else ('LFL' if 'LFL' in x else 'OTHER'))
    )

    if gantt_df.empty:
        st.write("No procurement tasks to display.")
        return

    fig = px.timeline(
        gantt_df,
        x_start='Start',
        x_end='Finish',
        y='RawMaterial_ID',
        color='SimpleType',
        hover_data=['Planned_Order_Qty', 'Net_Requirement'],
        title="📊 Procurement Gantt Chart"
    )
    fig.update_yaxes(autorange='reversed')
    fig = _apply_chart_style(fig)
    st.plotly_chart(fig, use_container_width=True)


def render_procurement_table(procurement_df):
    proc_table = procurement_df.groupby('RawMaterial_ID').agg(
        OrderType=('LotSizingModel_Used', lambda s: s.mode().iloc[0] if not s.mode().empty else s.iloc[0]),
        TotalQuantity=('Planned_Order_Qty', 'sum'),
        Members=('Planned_Order_Qty', 'count'),
        EarliestDate=('Planned_Order_ReceiptDate', 'min')
    ).reset_index().rename(columns={'RawMaterial_ID': 'Raw Material', 'OrderType': 'Order Type'})
    proc_table['EarliestDate'] = pd.to_datetime(proc_table['EarliestDate']).dt.date

    st.dataframe(proc_table[['Raw Material', 'Order Type', 'TotalQuantity', 'Members', 'EarliestDate']].rename(
        columns={'TotalQuantity': 'Total Quantity', 'Members': 'Members', 'EarliestDate': 'Order Date'}
    ), use_container_width=True)


def render_scheduling_gantt(gantt_tasks_df):
    baseline = pd.Timestamp(datetime.today().date())
    gantt = gantt_tasks_df.copy()
    gantt['Start_dt'] = gantt['Start_Hours'].apply(lambda h: baseline + pd.Timedelta(hours=float(h)))
    gantt['Finish_dt'] = gantt['Finish_Hours'].apply(lambda h: baseline + pd.Timedelta(hours=float(h)))

    fig2 = px.timeline(
        gantt,
        x_start='Start_dt',
        x_end='Finish_dt',
        y='Machine_ID',
        color='Product_ID',
        hover_data=['Duration_Hours'],
        title="🏭 Machine Scheduling Gantt Chart"
    )
    fig2.update_yaxes(autorange='reversed')
    fig2 = _apply_chart_style(fig2)
    st.plotly_chart(fig2, use_container_width=True)


def render_scheduling_table(gantt_tasks_df):
    baseline = pd.Timestamp(datetime.today().date())
    gantt = gantt_tasks_df.copy()
    gantt['Start_dt'] = gantt['Start_Hours'].apply(lambda h: baseline + pd.Timedelta(hours=float(h)))
    gantt['Finish_dt'] = gantt['Finish_Hours'].apply(lambda h: baseline + pd.Timedelta(hours=float(h)))
    st.dataframe(gantt[['Machine_ID', 'Product_ID', 'Start_dt', 'Finish_dt', 'Duration_Hours']].rename(
        columns={'Machine_ID':'Machine','Product_ID':'Product','Start_dt':'Start','Finish_dt':'Finish','Duration_Hours':'Hours'}
    ), use_container_width=True)

def render_scheduling_kpis(gantt_tasks_df):
    if gantt_tasks_df is None or gantt_tasks_df.empty:
        st.warning("No scheduling data available to summarize.")
        return

    # Compute total operation time
    total_operation_time = gantt_tasks_df['Duration_Hours'].sum() if 'Duration_Hours' in gantt_tasks_df.columns else 0

    # Total cycles = total unique combinations of Machine & Product
    total_cycles = gantt_tasks_df.groupby(['Machine_ID', 'Product_ID']).size().sum()

    # Total quantity if available
    if 'Quantity' in gantt_tasks_df.columns:
        total_quantity = gantt_tasks_df['Quantity'].sum()
    else:
        total_quantity = total_cycles  # fallback approximation

    # EOQ total cost if available
    if 'EOQ_Cost' in gantt_tasks_df.columns:
        eoq_total_cost = gantt_tasks_df['EOQ_Cost'].sum()
    else:
        eoq_total_cost = 0

    # Display metrics summary
    st.markdown("### 🏭 Machine Scheduling Summary")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("⚙️ Total Operation Time (hrs)", f"{total_operation_time:,.2f}")
    c2.metric("🔁 Total Cycles Produced", f"{int(total_cycles):,}")
    c3.metric("📦 Total Quantity Produced", f"{int(total_quantity):,}")
    c4.metric("💰 EOQ Total Cost", f"{eoq_total_cost:,.2f}")
