# modules/mrp_core.py
import pandas as pd
import numpy as np
import math
from collections import defaultdict
from datetime import datetime

def calculate_day_by_day_plan(material_details, time_phased_reqs, lot_sizing_logic):
    ordering_cost = float(material_details.get('OrderingCost', 0))
    holding_cost_per_day = float(material_details.get('HoldingCostPerDay', 0))
    lead_time = pd.to_timedelta(int(material_details.get('LeadTime', 0)), unit='d')
    safety_stock = float(material_details.get('SafetyStock', 0))
    backorder_cost_per_unit_per_day = float(material_details.get(
        'BackorderCostPerUnitPerDay',
        material_details.get('BackorderCostPerUnit', 0)
    ))

    planning_horizon_dates = sorted(time_phased_reqs.keys())
    if not planning_horizon_dates:
        return [], {'ordering_cost': 0, 'holding_cost': 0, 'backorder_cost': 0, 'total_cost': 0}

    start_date, end_date = planning_horizon_dates[0], planning_horizon_dates[-1]
    simulation_dates = pd.date_range(start=start_date, end=end_date, freq='D')

    on_hand_inventory = float(material_details.get('OnHand', material_details.get('ScheduledReceipts', 0)))

    scheduled_receipts = defaultdict(float)
    if 'PlannedOrderReceiptDate' in material_details and pd.notna(material_details.get('PlannedOrderReceiptDate', None)):
        try:
            receipt_date = pd.to_datetime(material_details.get('PlannedOrderReceiptDate'))
            receipt_qty = float(material_details.get('ScheduledReceipts', 0))
            scheduled_receipts[receipt_date] += receipt_qty
            on_hand_inventory = float(material_details.get('OnHand', 0))
        except Exception:
            pass

    total_holding_cost = 0.0
    orders_placed_count = 0
    total_backorder_cost = 0.0
    backorder_units = 0.0
    plan = []
    all_reqs = {pd.to_datetime(d): float(q) for d, q in time_phased_reqs.items()}

    for current_date in simulation_dates:
        if current_date in scheduled_receipts and scheduled_receipts[current_date] > 0:
            qty_arriving = scheduled_receipts[current_date]
            if backorder_units > 0:
                fulfill = min(qty_arriving, backorder_units)
                backorder_units -= fulfill
                qty_arriving -= fulfill
            on_hand_inventory += qty_arriving
            scheduled_receipts[current_date] = 0.0

        gross_req = float(all_reqs.get(current_date, 0.0))
        demand_during_lead_time = 0.0
        if lead_time.days > 0:
            lt_end_date = current_date + lead_time
            for d, q in all_reqs.items():
                if current_date < d <= lt_end_date:
                    demand_during_lead_time += q
        target_on_hand_needed = safety_stock + demand_during_lead_time

        if on_hand_inventory < target_on_hand_needed:
            net_req = max(0.0, target_on_hand_needed - on_hand_inventory)
            order_qty = float(lot_sizing_logic(current_date, net_req, all_reqs))
            if order_qty > 0:
                receipt_date = current_date + lead_time
                scheduled_receipts[receipt_date] += order_qty
                orders_placed_count += 1
                plan.append({
                    'Requirement_Date': current_date,
                    'Net_Requirement': net_req,
                    'Planned_Order_Qty': order_qty,
                    'Planned_Order_Release': current_date,
                    'Planned_Order_ReceiptDate': receipt_date
                })

        if on_hand_inventory >= gross_req:
            on_hand_inventory -= gross_req
        else:
            shortage = gross_req - on_hand_inventory
            on_hand_inventory = 0.0
            backorder_units += shortage

        if on_hand_inventory > 0:
            total_holding_cost += on_hand_inventory * holding_cost_per_day
        if backorder_units > 0 and backorder_cost_per_unit_per_day > 0:
            total_backorder_cost += backorder_units * backorder_cost_per_unit_per_day

    total_ordering_cost = orders_placed_count * ordering_cost
    total_cost = total_ordering_cost + total_holding_cost + total_backorder_cost
    costs = {
        'ordering_cost': total_ordering_cost,
        'holding_cost': total_holding_cost,
        'backorder_cost': total_backorder_cost,
        'total_cost': total_cost
    }
    return plan, costs

def run_mrp_and_return_results(products_df, bom_df, materials_df):
    """
    Inputs: dataframes (clean) for products_df, bom_df, materials_df
    Returns: dict with procurement_df, comparison_df, material_earliest_receipt, and original dfs
    """
    # Build materials dict
    materials_dict = materials_df.set_index('Raw materials').to_dict('index')

    gross_reqs = defaultdict(lambda: defaultdict(float))
    products_df['NetRequirement'] = products_df['Units to Delivered'] - products_df['OnHand']

    for _, product in products_df[products_df['NetRequirement'] > 0].iterrows():
        materials_needed_by_date = product['Due Date'] - pd.to_timedelta(int(product['PlannedOrderRelease']), unit='d')
        product_bom = bom_df[bom_df['Parent'] == product['Product_ID']]
        for _, component in product_bom.iterrows():
            gross_reqs[component['Item']][materials_needed_by_date] += float(product['NetRequirement']) * float(component['REQUIREMENTS'])

    all_materials_comparison = []
    final_plan_records = []
    material_earliest_receipt = {}

    for material_id, time_phased_reqs in gross_reqs.items():
        material_details = materials_dict.get(material_id)
        if material_details is None:
            continue

        # LFL
        lfl_logic = lambda date, net_req, all_reqs: net_req
        lfl_plan, lfl_costs = calculate_day_by_day_plan(material_details, time_phased_reqs, lfl_logic)

        # POQ - search a small window (3..21)
        best_poq_costs = {'total_cost': float('inf')}
        best_period = 0
        for period in range(3, 22):
            def make_poq_logic(p):
                def poq_logic(current_date, net_req, all_reqs):
                    period_end = current_date + pd.to_timedelta(p - 1, unit='d')
                    return sum(q for d, q in all_reqs.items() if current_date <= d <= period_end)
                return poq_logic
            _, current_poq_costs = calculate_day_by_day_plan(material_details, time_phased_reqs, make_poq_logic(period))
            if current_poq_costs['total_cost'] < best_poq_costs['total_cost']:
                best_poq_costs = current_poq_costs
                best_period = period

        def final_poq_logic(current_date, net_req, all_reqs):
            period_end = current_date + pd.to_timedelta(max(1, best_period) - 1, unit='d')
            return sum(q for d, q in all_reqs.items() if current_date <= d <= period_end)
        best_poq_plan, _ = calculate_day_by_day_plan(material_details, time_phased_reqs, final_poq_logic)

        # EOQ
        total_horizon_demand = sum(time_phased_reqs.values())
        annual_demand = float(material_details.get('AnnualDemand', np.nan))
        if np.isnan(annual_demand) or annual_demand <= 0:
            horizon_days = (max(time_phased_reqs.keys()) - min(time_phased_reqs.keys())).days + 1
            if horizon_days > 0:
                annual_demand = (total_horizon_demand / max(1, horizon_days)) * 365
            else:
                annual_demand = total_horizon_demand * 12
        ordering_cost = float(material_details.get('OrderingCost', 0))
        annual_holding_cost = float(material_details.get('HoldingCostPerDay', 0)) * 365
        eoq_qty = 0.0
        if ordering_cost > 0 and annual_holding_cost > 0 and annual_demand > 0:
            eoq_qty = np.sqrt((2.0 * annual_demand * ordering_cost) / annual_holding_cost)
            eoq_qty = float(max(1.0, round(eoq_qty)))
        eoq_logic = lambda date, net_req, all_reqs: eoq_qty if eoq_qty > 0 else net_req
        eoq_plan, eoq_costs = calculate_day_by_day_plan(material_details, time_phased_reqs, eoq_logic)

        models = {
            'LFL': lfl_costs,
            f'POQ (P={best_period} days)': best_poq_costs,
            f'EOQ (Order Qty={eoq_qty:.0f})': eoq_costs
        }
        winner_name = min(models, key=lambda k: models[k]['total_cost'])
        if 'LFL' in winner_name:
            recommended_plan = lfl_plan
        elif 'POQ' in winner_name:
            recommended_plan = best_poq_plan
        else:
            recommended_plan = eoq_plan

        earliest = None
        for ord_rec in recommended_plan:
            rd = ord_rec.get('Planned_Order_ReceiptDate')
            if pd.notna(rd):
                if earliest is None or rd < earliest:
                    earliest = pd.to_datetime(rd)
        if earliest is not None:
            material_earliest_receipt[material_id] = earliest
        else:
            on_hand = float(material_details.get('OnHand', 0))
            if on_hand > 0:
                material_earliest_receipt[material_id] = pd.Timestamp(datetime.today().date())
            else:
                material_earliest_receipt[material_id] = max(time_phased_reqs.keys()) + pd.Timedelta(days=365)

        all_materials_comparison.append({
            'RawMaterial_ID': material_id,
            'LFL_Total_Cost': lfl_costs['total_cost'],
            'POQ_Total_Cost': best_poq_costs['total_cost'],
            'EOQ_Total_Cost': eoq_costs['total_cost'],
            'Recommended_Model': winner_name,
            'Winner_Total_Cost': models[winner_name]['total_cost']
        })

        for order in recommended_plan:
            final_plan_records.append({
                **order,
                'RawMaterial_ID': material_id,
                'LotSizingModel_Used': winner_name
            })

    procurement_df = pd.DataFrame(final_plan_records)
    comparison_df = pd.DataFrame(all_materials_comparison).round(2)

    return {
        'procurement_df': procurement_df,
        'comparison_df': comparison_df,
        'material_earliest_receipt': material_earliest_receipt,
        'products_df': products_df,
        'bom_df': bom_df,
        'materials_df': materials_df
    }
