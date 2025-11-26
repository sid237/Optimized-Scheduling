# modules/scheduling_core.py
import pandas as pd
import math
import pulp
from collections import defaultdict
from datetime import datetime

def run_scheduling_with_mrp_integration(mrp_results, machines_df, eligibility_df):
    products_df = mrp_results['products_df']
    bom_df = mrp_results['bom_df']
    materials_df = mrp_results['materials_df']

    # product metadata
    products = products_df['Product_ID'].tolist()
    product_data = {}
    for _, row in products_df.iterrows():
        pid = row['Product_ID']
        if 'Days from Today' in row and not pd.isna(row['Days from Today']):
            due_days = float(row['Days from Today'])
        else:
            due_days = (pd.to_datetime(row['Due Date']).date() - datetime.today().date()).days
            if due_days < 0: due_days = 0.0
        product_data[pid] = {
            'demand': float(row.get('Units to Delivered', 0)),
            'due_date_hours': due_days * 24,
            'penalty_per_hour': float(row.get('Penalty Per Day[Rs]', 0)) / 24.0 if 'Penalty Per Day[Rs]' in row else 0.0
        }

    # machine metadata
    machines = machines_df['Machine / Vessel ID'].tolist()
    machine_data = {}
    for _, row in machines_df.iterrows():
        mid = row['Machine / Vessel ID']
        machine_data[mid] = {
            'op_cost_per_hour': float(row.get('Running Cost Per Hour in Rs', 0)),
            'cycle_time_hours': float(row.get('Cycle Time in Hours Per Batch', 0)) if not pd.isna(row.get('Cycle Time in Hours Per Batch', 0)) else 0.0,
            'capacity_units': float(row.get('Volume[Capacity] in Units Per batch', 0)) if not pd.isna(row.get('Volume[Capacity] in Units Per batch', 0)) else 0.0,
            'pre_maintenance_hours': float(row.get('PreMaintenanceHours', 0)) if 'PreMaintenanceHours' in row else 0.0,
            'post_maintenance_hours': float(row.get('PostMaintenanceHours', 0)) if 'PostMaintenanceHours' in row else 0.0
        }
        machine_data[mid]['total_maintenance_hours'] = machine_data[mid]['pre_maintenance_hours'] + machine_data[mid]['post_maintenance_hours']

    eligibility_df = eligibility_df.set_index('Product_ID') if not eligibility_df.empty else eligibility_df
    eligibility = eligibility_df.to_dict('index') if not eligibility_df.empty else {}

    # Build material_ready & product_material_ready_hours
    mat_ready = mrp_results['material_earliest_receipt']
    product_material_ready_hours = {}
    for _, prod in products_df.iterrows():
        pid = prod['Product_ID']
        prod_bom = bom_df[bom_df['Parent'] == pid]
        latest_date = None
        for _, comp in prod_bom.iterrows():
            mat = comp['Item']
            mat_date = mat_ready.get(mat)
            if mat_date is None:
                mat_row = materials_df.set_index('Raw materials').to_dict('index').get(mat, {})
                if float(mat_row.get('OnHand', 0)) > 0:
                    mat_date = pd.Timestamp(datetime.today().date())
                else:
                    mat_date = pd.Timestamp(datetime.today().date()) + pd.Timedelta(days=365)
            if latest_date is None or mat_date > latest_date:
                latest_date = mat_date
        if latest_date is None:
            latest_date = pd.Timestamp(datetime.today().date())
        hours_from_today = max(0.0, (pd.to_datetime(latest_date).date() - datetime.today().date()).days * 24.0)
        product_material_ready_hours[pid] = hours_from_today

    # Build MILP
    model = pulp.LpProblem("Integrated_MRP_Scheduling", pulp.LpMinimize)
    x = pulp.LpVariable.dicts("x", ((i, m) for i in products for m in machines), lowBound=0, cat='Continuous')
    z = pulp.LpVariable.dicts("z", ((i, m) for i in products for m in machines), cat='Binary')
    u = pulp.LpVariable.dicts("u", ((i, m) for i in products for m in machines), lowBound=0, cat='Integer')
    L = pulp.LpVariable.dicts("L", (i for i in products), lowBound=0, cat='Continuous')
    CT = pulp.LpVariable.dicts("CT", (i for i in products), lowBound=0, cat='Continuous')

    # Big-Ms
    M_cycles = {}
    for i in products:
        for m in machines:
            cap = machine_data[m]['capacity_units']
            if cap > 0:
                M_cycles[(i, m)] = math.ceil(max(0.0, product_data[i]['demand']) / cap)
            else:
                M_cycles[(i, m)] = 0
    M_time = {}
    for m in machines:
        cyc_sum = sum(M_cycles[(j, m)] * machine_data[m]['cycle_time_hours'] for j in products)
        maint_sum = len(products) * machine_data[m]['total_maintenance_hours']
        M_time[m] = cyc_sum + maint_sum + 1.0

    operating_cost = pulp.lpSum(
        machine_data[m]['op_cost_per_hour'] * machine_data[m]['cycle_time_hours'] * u[i, m]
        for i in products for m in machines
    )
    penalty_cost = pulp.lpSum(product_data[i]['penalty_per_hour'] * L[i] for i in products)
    model += operating_cost + penalty_cost

    for i in products:
        model += pulp.lpSum(x[i, m] for m in machines) >= product_data[i]['demand']
        model += L[i] >= CT[i] - product_data[i]['due_date_hours']
        mat_ready_hours = product_material_ready_hours.get(i, 0.0)
        model += CT[i] >= mat_ready_hours
        for m in machines:
            cap = machine_data[m]['capacity_units']
            model += x[i, m] <= cap * u[i, m]
            model += u[i, m] <= M_cycles[(i, m)] * z[i, m]
            if i in eligibility and m in eligibility[i]:
                try:
                    allowed = bool(eligibility[i][m])
                except Exception:
                    allowed = eligibility[i].get(m, 1)
                model += z[i, m] <= (1 if allowed else 0)
            total_machine_time = (
                pulp.lpSum(machine_data[m]['cycle_time_hours'] * u[j, m] for j in products)
                + pulp.lpSum(machine_data[m]['total_maintenance_hours'] * z[j, m] for j in products)
            )
            model += CT[i] >= total_machine_time - M_time[m] * (1 - z[i, m])

    model.solve()

    milp_prod_rows = []
    product_CT = {}
    product_L = {}
    for i in products:
        for m in machines:
            xi = pulp.value(x[i, m])
            ui = pulp.value(u[i, m])
            if xi is not None and xi > 1e-6:
                milp_prod_rows.append({
                    'Product_ID': i,
                    'Machine_ID': m,
                    'Units_Produced_MILP': round(xi),
                    'Production_Cycles_MILP': int(round(ui)) if ui is not None else 0
                })
        product_CT[i] = pulp.value(CT[i]) if pulp.value(CT[i]) is not None else 0.0
        product_L[i] = pulp.value(L[i]) if pulp.value(L[i]) is not None else 0.0

    milp_prod_df = pd.DataFrame(milp_prod_rows)

    # Build EDD-like sequences (simple simulation for gantt)
    gantt_tasks = []
    for m in machines:
        assigned = [r for r in milp_prod_rows if r['Machine_ID'] == m]
        assigned = sorted(assigned, key=lambda r: product_data.get(r['Product_ID'], {}).get('due_date_hours', 0))
        current_time = 0.0
        for r in assigned:
            prod = r['Product_ID']
            cycles = r.get('Production_Cycles_MILP', 0)
            cyc_time = machine_data[m]['cycle_time_hours']
            maint = machine_data[m].get('total_maintenance_hours', 0.0)
            task_time = cycles * cyc_time + maint
            start_hr = current_time
            end_hr = current_time + task_time
            gantt_tasks.append({
                'Machine_ID': m,
                'Product_ID': prod,
                'Start_Hours': start_hr,
                'Finish_Hours': end_hr,
                'Duration_Hours': task_time
            })
            current_time = end_hr

    gantt_tasks_df = pd.DataFrame(gantt_tasks)

    return {
        'milp_prod_df': milp_prod_df,
        'gantt_tasks_df': gantt_tasks_df
    }
