import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, date
import io

# ==========================================
# CONFIGURATION & INITIALIZATION
# ==========================================
st.set_page_config(page_title="Partnership Accounting App", page_icon="💰", layout="wide")

DB_FILE = 'accounting.db'

def init_db():
    """Initializes the SQLite database with required tables."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # Create partners table
    c.execute('''CREATE TABLE IF NOT EXISTS partners (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 name TEXT UNIQUE,
                 profit_share REAL)''')
    
    # Ensure default partners exist
    c.execute("INSERT OR IGNORE INTO partners (name, profit_share) VALUES ('Partner 1', 50.0)")
    c.execute("INSERT OR IGNORE INTO partners (name, profit_share) VALUES ('Partner 2', 50.0)")
    
    # Create daily batches (slots) table
    c.execute('''CREATE TABLE IF NOT EXISTS batches (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 work_date TEXT,
                 total_slots INTEGER,
                 cancelled_slots INTEGER DEFAULT 0,
                 p1_rate REAL DEFAULT 15.0,
                 p2_rate REAL DEFAULT 124.0,
                 settlement_rate REAL DEFAULT 200.0,
                 notes TEXT,
                 cancellation_reason TEXT,
                 created_at TEXT)''')
                 
    # Create expenses table
    c.execute('''CREATE TABLE IF NOT EXISTS expenses (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 expense_date TEXT,
                 name TEXT,
                 category TEXT,
                 amount REAL,
                 paid_by TEXT,
                 description TEXT,
                 notes TEXT,
                 ref_number TEXT,
                 created_at TEXT)''')
                 
    # Create settlements table
    c.execute('''CREATE TABLE IF NOT EXISTS settlements (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 received_date TEXT,
                 amount REAL,
                 received_by TEXT,
                 bank_ref TEXT,
                 batch_id INTEGER,
                 notes TEXT,
                 created_at TEXT)''')

    # Create withdrawals table (for partner payouts)
    c.execute('''CREATE TABLE IF NOT EXISTS withdrawals (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 withdrawal_date TEXT,
                 partner TEXT,
                 amount REAL,
                 notes TEXT,
                 created_at TEXT)''')

    # --- NEW MIGRATION FOR MULTI-PARTNERSHIP ---
    tables = ['batches', 'expenses', 'settlements', 'withdrawals']
    for tbl in tables:
        try:
            c.execute(f"ALTER TABLE {tbl} ADD COLUMN partnership TEXT DEFAULT 'Sandeep & Harshal'")
        except sqlite3.OperationalError:
            pass

    # Update old generic records to specific names
    c.execute("UPDATE expenses SET paid_by = 'Sandeep' WHERE paid_by = 'Partner 1'")
    c.execute("UPDATE expenses SET paid_by = 'Harshal' WHERE paid_by = 'Partner 2'")
    c.execute("UPDATE settlements SET received_by = 'Sandeep' WHERE received_by = 'Partner 1'")
    c.execute("UPDATE settlements SET received_by = 'Harshal' WHERE received_by = 'Partner 2'")
    c.execute("UPDATE withdrawals SET partner = 'Sandeep' WHERE partner = 'Partner 1'")
    c.execute("UPDATE withdrawals SET partner = 'Harshal' WHERE partner = 'Partner 2'")

    conn.commit()
    conn.close()

# Initialize database on app startup
init_db()

# ==========================================
# HELPER FUNCTIONS
# ==========================================
def format_currency(amount):
    """Formats a number as Indian Rupees."""
    return f"₹ {amount:,.2f}"

def execute_query(query, params=()):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(query, params)
    conn.commit()
    conn.close()

def fetch_data(query, params=()):
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df

# ==========================================
# ACCOUNTING LOGIC & CALCULATIONS
# ==========================================
def calculate_financials(partnership, p1_name, p2_name):
    """Calculates all master financials based on the accounting rules."""
    # 1. Slot Calculations
    batches_df = fetch_data("SELECT * FROM batches WHERE partnership=?", (partnership,))
    if not batches_df.empty:
        batches_df['active_slots'] = batches_df['total_slots'] - batches_df['cancelled_slots']
        batches_df['p1_cost'] = batches_df['active_slots'] * batches_df['p1_rate']
        batches_df['p2_cost'] = batches_df['active_slots'] * batches_df['p2_rate']
        batches_df['expected_settlement'] = batches_df['active_slots'] * batches_df['settlement_rate']
        
        total_p1_slot_cost = batches_df['p1_cost'].sum()
        total_p2_slot_cost = batches_df['p2_cost'].sum()
        total_expected_settlement = batches_df['expected_settlement'].sum()
        total_active_slots = batches_df['active_slots'].sum()
    else:
        total_p1_slot_cost = total_p2_slot_cost = total_expected_settlement = total_active_slots = 0.0

    # 2. General Expenses
    expenses_df = fetch_data("SELECT * FROM expenses WHERE partnership=?", (partnership,))
    if not expenses_df.empty:
        p1_expenses = expenses_df[expenses_df['paid_by'] == p1_name]['amount'].sum()
        p2_expenses = expenses_df[expenses_df['paid_by'] == p2_name]['amount'].sum()
    else:
        p1_expenses = p2_expenses = 0.0

    # Total expenses paid by each partner (Slot Costs + Manual Expenses)
    total_paid_by_p1 = total_p1_slot_cost + p1_expenses
    total_paid_by_p2 = total_p2_slot_cost + p2_expenses
    total_business_expenses = total_paid_by_p1 + total_paid_by_p2

    # 3. Settlements Received
    settlements_df = fetch_data("SELECT * FROM settlements WHERE partnership=?", (partnership,))
    if not settlements_df.empty:
        received_by_p1 = settlements_df[settlements_df['received_by'] == p1_name]['amount'].sum()
        received_by_p2 = settlements_df[settlements_df['received_by'] == p2_name]['amount'].sum()
        total_received_settlement = settlements_df['amount'].sum()
    else:
        received_by_p1 = received_by_p2 = total_received_settlement = 0.0

    # 4. Withdrawals
    withdrawals_df = fetch_data("SELECT * FROM withdrawals WHERE partnership=?", (partnership,))
    if not withdrawals_df.empty:
        withdrawn_p1 = withdrawals_df[withdrawals_df['partner'] == p1_name]['amount'].sum()
        withdrawn_p2 = withdrawals_df[withdrawals_df['partner'] == p2_name]['amount'].sum()
    else:
        withdrawn_p1 = withdrawn_p2 = 0.0

    # 5. Profit & Balances Calculation
    # Rule: Net Profit = Actual recognized revenue - Actual business expenses
    realized_net_profit = total_received_settlement - total_business_expenses
    pending_settlement = total_expected_settlement - total_received_settlement
    
    # Partner Shares (50:50 default)
    p1_share_pct = 0.50
    p2_share_pct = 0.50

    p1_profit_share = realized_net_profit * p1_share_pct
    p2_profit_share = realized_net_profit * p2_share_pct

    # Entitlement = Reimbursable expenses + Profit Share - Settlements Held - Withdrawals
    p1_balance = total_paid_by_p1 + p1_profit_share - received_by_p1 - withdrawn_p1
    p2_balance = total_paid_by_p2 + p2_profit_share - received_by_p2 - withdrawn_p2

    return {
        'active_slots': total_active_slots,
        'expected_settlement': total_expected_settlement,
        'received_settlement': total_received_settlement,
        'pending_settlement': max(0, pending_settlement), # Prevent negative if over-settled
        'business_expenses': total_business_expenses,
        'p1_contribution': total_paid_by_p1,
        'p2_contribution': total_paid_by_p2,
        'realized_net_profit': realized_net_profit,
        'p1_balance': p1_balance,
        'p2_balance': p2_balance,
        'p1_profit_share': p1_profit_share,
        'p2_profit_share': p2_profit_share,
        'received_by_p1': received_by_p1,
        'received_by_p2': received_by_p2,
        'withdrawn_p1': withdrawn_p1,
        'withdrawn_p2': withdrawn_p2,
        'batches_df': batches_df,
        'expenses_df': expenses_df,
        'settlements_df': settlements_df
    }


# ==========================================
# UI COMPONENTS (PAGES)
# ==========================================
def render_dashboard(data, partnership, p1_name, p2_name):
    st.title(f"📊 Dashboard: {partnership}")
    st.markdown("Overview of the Partnership's Financial Health")

    # Top Metrics
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Active Slots", f"{data['active_slots']:,.0f}")
    col2.metric("Expected Earnings", format_currency(data['expected_settlement']))
    col3.metric("Settlement Received", format_currency(data['received_settlement']))
    col4.metric("Pending Settlement", format_currency(data['pending_settlement']))

    col5, col6, col7, col8 = st.columns(4)
    col5.metric("Total Expenses", format_currency(data['business_expenses']))
    col6.metric(f"Net Profit ({partnership})", format_currency(data['realized_net_profit']))
    
    # Simpler Partner Status Calculations
    p1_rightful = data['p1_contribution'] + data['p1_profit_share']
    p1_holds = data['received_by_p1'] - data['withdrawn_p1']
    p1_diff = p1_holds - p1_rightful # Positive = Holds extra (needs to pay)
    
    p2_rightful = data['p2_contribution'] + data['p2_profit_share']
    p2_holds = data['received_by_p2'] - data['withdrawn_p2']
    p2_diff = p2_holds - p2_rightful # Positive = Holds extra (needs to pay)

    if p1_diff > 0:
        col7.metric(f"{p1_name} Needs to GIVE", format_currency(abs(p1_diff)))
    else:
        col7.metric(f"{p1_name} Needs to TAKE", format_currency(abs(p1_diff)))

    if p2_diff > 0:
        col8.metric(f"{p2_name} Needs to GIVE", format_currency(abs(p2_diff)))
    else:
        col8.metric(f"{p2_name} Needs to TAKE", format_currency(abs(p2_diff)))

    st.markdown("---")
    
    # Clear settlement instructions
    st.info(f"💡 **Simple Account Settlement:**")
    if p1_diff > 0:
        st.error(f"💸 **{p1_name}** is holding extra money. {p1_name} must pay **{p2_name}** exactly **{format_currency(abs(p1_diff))}** to settle accounts.")
    elif p2_diff > 0:
        st.error(f"💸 **{p2_name}** is holding extra money. {p2_name} must pay **{p1_name}** exactly **{format_currency(abs(p2_diff))}** to settle accounts.")
    else:
        st.success("✅ All accounts are perfectly settled. Nobody owes anyone.")

    st.markdown("---")

    # Charts
    st.subheader("📈 Financial Visualizations")
    chart_col1, chart_col2 = st.columns(2)
    
    with chart_col1:
        # Expected vs Received Donut
        fig1 = px.pie(
            names=['Received Settlement', 'Pending Settlement'], 
            values=[data['received_settlement'], data['pending_settlement']],
            title="Settlement Status", hole=0.4,
            color_discrete_sequence=['#2ecc71', '#e74c3c']
        )
        st.plotly_chart(fig1, use_container_width=True)

    with chart_col2:
        # Partner Contributions Bar
        fig2 = go.Figure(data=[
            go.Bar(name='Contributions (Expenses)', x=[p1_name, p2_name], y=[data['p1_contribution'], data['p2_contribution']], marker_color='#3498db'),
            go.Bar(name='Profit Share', x=[p1_name, p2_name], y=[data['p1_profit_share'], data['p2_profit_share']], marker_color='#9b59b6')
        ])
        fig2.update_layout(barmode='group', title="Partner Financial Breakdown")
        st.plotly_chart(fig2, use_container_width=True)

def render_slots_management(partnership, p1_name, p2_name):
    st.title(f"🎰 Slot Management ({partnership})")
    
    tab1, tab2 = st.tabs(["Add New Slots", "Manage / Cancel Slots"])
    
    with tab1:
        st.subheader("Record New Working Batch")
        with st.form("add_batch_form"):
            col1, col2 = st.columns(2)
            with col1:
                work_date = st.date_input("Work Date", date.today())
                total_slots = st.number_input("Number of Slots", min_value=1, step=1, value=50)
                notes = st.text_area("Notes / Message", placeholder="e.g., Slots purchased for today's work.")
            with col2:
                p1_rate = st.number_input(f"{p1_name} Purchase Rate (₹)", value=15.0)
                p2_rate = st.number_input(f"{p2_name} Payment Rate (₹)", value=124.0)
                settlement_rate = st.number_input("Expected Settlement Rate (₹)", value=200.0)
            
            submitted = st.form_submit_button("Record Batch")
            if submitted:
                execute_query('''
                    INSERT INTO batches (work_date, total_slots, p1_rate, p2_rate, settlement_rate, notes, created_at, partnership)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (work_date.strftime("%Y-%m-%d"), total_slots, p1_rate, p2_rate, settlement_rate, notes, datetime.now().isoformat(), partnership))
                st.success("Batch recorded successfully!")
                st.rerun()
                
    with tab2:
        st.subheader("Existing Batches")
        batches_df = fetch_data("SELECT * FROM batches WHERE partnership=? ORDER BY work_date DESC", (partnership,))
        if not batches_df.empty:
            batches_df['Active Slots'] = batches_df['total_slots'] - batches_df['cancelled_slots']
            batches_df['Expected ($)'] = batches_df['Active Slots'] * batches_df['settlement_rate']
            
            # Display summary table
            display_cols = ['id', 'work_date', 'total_slots', 'cancelled_slots', 'Active Slots', 'Expected ($)', 'notes']
            st.dataframe(batches_df[display_cols], use_container_width=True, hide_index=True)
            
            st.markdown("#### Cancel Slots")
            col1, col2, col3 = st.columns([1, 1, 2])
            with col1:
                batch_id_to_cancel = st.selectbox("Select Batch ID", batches_df['id'].tolist())
            with col2:
                cancel_count = st.number_input("Slots to Cancel", min_value=1, step=1)
            with col3:
                cancel_reason = st.text_input("Cancellation Reason")
                
            if st.button("Apply Cancellation", type="primary"):
                current_cancelled = int(batches_df[batches_df['id'] == batch_id_to_cancel]['cancelled_slots'].values[0])
                total_in_batch = int(batches_df[batches_df['id'] == batch_id_to_cancel]['total_slots'].values[0])
                
                new_cancelled = current_cancelled + cancel_count
                if new_cancelled > total_in_batch:
                    st.error("Cannot cancel more slots than the total slots in the batch!")
                else:
                    execute_query('''
                        UPDATE batches SET cancelled_slots = ?, cancellation_reason = ? WHERE id = ?
                    ''', (new_cancelled, cancel_reason, batch_id_to_cancel))
                    st.success("Cancellation applied successfully. Expectations automatically recalculated.")
                    st.rerun()
        else:
            st.info("No slot batches found. Add one in the other tab.")

def render_expenses(partnership, p1_name, p2_name):
    st.title(f"💸 Expense Management ({partnership})")
    
    tab1, tab2 = st.tabs(["Add Expense", "Expense History"])
    
    categories = ["Internet", "Travel", "Miscellaneous", "Refund", "Cancellation", "Other business expenses"]
    
    with tab1:
        with st.form("expense_form"):
            col1, col2 = st.columns(2)
            with col1:
                exp_date = st.date_input("Expense Date", date.today())
                name = st.text_input("Expense Name")
                category = st.selectbox("Category", categories)
                paid_by = st.radio("Paid By (Select Partner)", [p1_name, p2_name])
            with col2:
                amount = st.number_input("Amount (₹)", min_value=0.0, step=10.0)
                ref_number = st.text_input("Reference Number (Optional)")
                notes = st.text_area("Notes")
                
            if st.form_submit_button("Log Expense"):
                execute_query('''
                    INSERT INTO expenses (expense_date, name, category, amount, paid_by, notes, ref_number, created_at, partnership)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (exp_date.strftime("%Y-%m-%d"), name, category, amount, paid_by, notes, ref_number, datetime.now().isoformat(), partnership))
                st.success("Expense logged successfully!")
                st.rerun()
                
    with tab2:
        df_exp = fetch_data("SELECT expense_date, name, category, amount, paid_by, notes FROM expenses WHERE partnership=? ORDER BY expense_date DESC", (partnership,))
        if not df_exp.empty:
            st.dataframe(df_exp, use_container_width=True, hide_index=True)
        else:
            st.info("No expenses logged yet.")

def render_settlements(partnership, p1_name, p2_name):
    st.title(f"🏦 Settlement Management ({partnership})")
    
    tab1, tab2 = st.tabs(["Record Settlement", "Settlement History"])
    
    with tab1:
        st.info("💡 **Accounting Rule:** Never assume the settlement belongs to the current day. Allow it to remain unallocated if unknown.")
        with st.form("settlement_form"):
            col1, col2 = st.columns(2)
            with col1:
                rec_date = st.date_input("Actual Received Date", date.today())
                amount = st.number_input("Amount Received (₹)", min_value=0.0, step=100.0)
                received_by = st.radio("Received In Account Of", [p2_name, p1_name], index=0) 
            with col2:
                bank_ref = st.text_input("Bank Transaction Reference")
                
                # Option to link batch
                batches = fetch_data("SELECT id, work_date, total_slots FROM batches WHERE partnership=?", (partnership,))
                batch_options = {"None (Unallocated)": None}
                for _, r in batches.iterrows():
                    batch_options[f"Batch {r['id']} ({r['work_date']}) - {r['total_slots']} slots"] = r['id']
                
                selected_batch = st.selectbox("Link to Work Batch (Optional)", list(batch_options.keys()))
                batch_id = batch_options[selected_batch]
                
                notes = st.text_area("Notes", placeholder="e.g., Combined settlement covering multiple days.")
                
            if st.form_submit_button("Record Settlement"):
                execute_query('''
                    INSERT INTO settlements (received_date, amount, received_by, bank_ref, batch_id, notes, created_at, partnership)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (rec_date.strftime("%Y-%m-%d"), amount, received_by, bank_ref, batch_id, notes, datetime.now().isoformat(), partnership))
                st.success("Settlement recorded successfully!")
                st.rerun()
                
    with tab2:
        df_settle = fetch_data("SELECT received_date, amount, received_by, bank_ref, batch_id, notes FROM settlements WHERE partnership=? ORDER BY received_date DESC", (partnership,))
        if not df_settle.empty:
            st.dataframe(df_settle, use_container_width=True, hide_index=True)
        else:
            st.info("No settlements recorded yet.")

def render_partner_balance(data, partnership, p1_name, p2_name):
    st.title(f"⚖️ Simple Partner Accounting ({partnership})")
    
    st.markdown(f"""
    **How we calculate this easily:**
    1. We calculate how much money you **SHOULD HAVE** (Money you invested + Your half of the profit).
    2. We check how much money you **CURRENTLY HOLD** (Settlements in your bank - Money you gave out).
    3. If you hold more than you should, you give the extra to your partner. If you hold less, you take it from them.
    """)
    
    total_received = data['received_settlement']
    total_invested = data['business_expenses']
    profit_or_loss = data['realized_net_profit']

    st.info(f"**Overall Business Status:** Total Settlement Received: **{format_currency(total_received)}** | Total Investments Made: **{format_currency(total_invested)}**")

    if profit_or_loss < 0:
        st.warning(f"⚠️ **Pending Settlements Needed:** The business has not received enough settlements yet. Loss right now: {format_currency(abs(profit_or_loss))}.")
    else:
        st.success(f"🎉 **Profitable!** All investments recovered. Total Profit: {format_currency(profit_or_loss)} to be split 50-50.")

    st.markdown("---")
    
    # Logical calculations
    p1_rightful = data['p1_contribution'] + data['p1_profit_share']
    p1_holds = data['received_by_p1'] - data['withdrawn_p1']
    p1_diff = p1_holds - p1_rightful 
    
    p2_rightful = data['p2_contribution'] + data['p2_profit_share']
    p2_holds = data['received_by_p2'] - data['withdrawn_p2']
    p2_diff = p2_holds - p2_rightful

    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader(f"👤 {p1_name}'s Summary")
        st.write(f"1. Money Invested (To get back): **{format_currency(data['p1_contribution'])}**")
        st.write(f"2. Profit Share (50%): **{format_currency(data['p1_profit_share'])}**")
        st.markdown(f"#### 💰 {p1_name} SHOULD HAVE: {format_currency(p1_rightful)}")
        st.markdown("---")
        st.write(f"Settlements in {p1_name}'s Bank: **{format_currency(data['received_by_p1'])}**")
        st.write(f"Minus Payments Given Out: **{format_currency(data['withdrawn_p1'])}**")
        st.markdown(f"#### 🏦 {p1_name} CURRENTLY HOLDS: {format_currency(p1_holds)}")
        st.markdown("---")
        
        if p1_diff > 0:
            st.error(f"🔴 {p1_name} holds {format_currency(abs(p1_diff))} EXTRA. Needs to GIVE to {p2_name}.")
        elif p1_diff < 0:
            st.success(f"🟢 {p1_name} is SHORT by {format_currency(abs(p1_diff))}. Needs to TAKE from {p2_name}.")
        else:
            st.info("Settled")
            
    with col2:
        st.subheader(f"👤 {p2_name}'s Summary")
        st.write(f"1. Money Invested (To get back): **{format_currency(data['p2_contribution'])}**")
        st.write(f"2. Profit Share (50%): **{format_currency(data['p2_profit_share'])}**")
        st.markdown(f"#### 💰 {p2_name} SHOULD HAVE: {format_currency(p2_rightful)}")
        st.markdown("---")
        st.write(f"Settlements in {p2_name}'s Bank: **{format_currency(data['received_by_p2'])}**")
        st.write(f"Minus Payments Given Out: **{format_currency(data['withdrawn_p2'])}**")
        st.markdown(f"#### 🏦 {p2_name} CURRENTLY HOLDS: {format_currency(p2_holds)}")
        st.markdown("---")
        
        if p2_diff > 0:
            st.error(f"🔴 {p2_name} holds {format_currency(abs(p2_diff))} EXTRA. Needs to GIVE to {p1_name}.")
        elif p2_diff < 0:
            st.success(f"🟢 {p2_name} is SHORT by {format_currency(abs(p2_diff))}. Needs to TAKE from {p1_name}.")
        else:
            st.info("Settled")

    st.markdown("---")
    st.subheader("💸 Make a Payment / Settlement")
    st.write("Use this form when one partner actually pays the other partner to clear the accounts.")
    
    with st.form("withdrawal_form"):
        c1, c2, c3 = st.columns(3)
        with c1:
            w_date = st.date_input("Payment Date", date.today())
        with c2:
            w_partner = st.selectbox("Who is sending the money?", [p1_name, p2_name])
        with c3:
            w_amount = st.number_input("Amount (₹)", min_value=0.0, step=100.0)
        
        w_notes = st.text_input("Notes", value="Settling account balance")
        
        if st.form_submit_button("Record Payment"):
            execute_query("INSERT INTO withdrawals (withdrawal_date, partner, amount, notes, created_at, partnership) VALUES (?, ?, ?, ?, ?, ?)",
                          (w_date.strftime("%Y-%m-%d"), w_partner, w_amount, w_notes, datetime.now().isoformat(), partnership))
            st.success("Payment recorded successfully! Balances updated.")
            st.rerun()

def render_transaction_history(partnership):
    st.title(f"📜 Transaction Master Ledger ({partnership})")
    
    # Combine datasets for a master ledger
    queries = [
        f"SELECT created_at as timestamp, 'Batch Record' as type, total_slots || ' slots' as description, 0 as amount, 'System' as partner, notes FROM batches WHERE partnership='{partnership}'",
        f"SELECT created_at as timestamp, 'Expense' as type, category || ': ' || name as description, amount, paid_by as partner, notes FROM expenses WHERE partnership='{partnership}'",
        f"SELECT created_at as timestamp, 'Settlement' as type, 'Bank Ref: ' || ifnull(bank_ref, 'N/A') as description, amount, received_by as partner, notes FROM settlements WHERE partnership='{partnership}'",
        f"SELECT created_at as timestamp, 'Withdrawal' as type, 'Balance Settlement' as description, amount, partner, notes FROM withdrawals WHERE partnership='{partnership}'"
    ]
    
    ledger_df = pd.DataFrame()
    for q in queries:
        df = fetch_data(q)
        ledger_df = pd.concat([ledger_df, df])
        
    if not ledger_df.empty:
        ledger_df = ledger_df.sort_values(by='timestamp', ascending=False).reset_index(drop=True)
        
        # Filtering
        col1, col2 = st.columns(2)
        with col1:
            type_filter = st.multiselect("Filter by Type", ledger_df['type'].unique(), default=ledger_df['type'].unique())
        with col2:
            partner_filter = st.multiselect("Filter by Partner", ledger_df['partner'].unique(), default=ledger_df['partner'].unique())
            
        filtered_df = ledger_df[(ledger_df['type'].isin(type_filter)) & (ledger_df['partner'].isin(partner_filter))]
        
        st.dataframe(filtered_df, use_container_width=True)
        
        # CSV Export
        csv = filtered_df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Download Ledger as CSV",
            data=csv,
            file_name='accounting_ledger.csv',
            mime='text/csv',
        )
    else:
        st.info("No transactions found.")

def render_database_management():
    st.title("💾 Data Backup & Restore")
    
    st.warning("""
    **CRITICAL WARNING FOR STREAMLIT CLOUD USERS:**
    Streamlit Community Cloud automatically resets its file system occasionally. 
    To avoid losing your accounting data, **Download your database** regularly. 
    If the app resets, you can use the **Restore** function below to upload your saved database file.
    """)
    
    st.markdown("### 1. Backup Database")
    with open(DB_FILE, "rb") as fp:
        btn = st.download_button(
            label="📥 Download Database File (accounting.db)",
            data=fp,
            file_name=f"accounting_backup_{date.today().strftime('%Y%m%d')}.db",
            mime="application/octet-stream"
        )
        
    st.markdown("### 2. Restore Database")
    uploaded_file = st.file_uploader("Upload a previously downloaded accounting.db file", type="db")
    if uploaded_file is not None:
        if st.button("⚠️ Restore Database (Overwrites Current Data)", type="primary"):
            with open(DB_FILE, "wb") as f:
                f.write(uploaded_file.getbuffer())
            st.success("Database restored successfully! Reloading...")
            st.rerun()

# ==========================================
# MAIN APP ROUTING
# ==========================================
def main():
    # Sidebar Navigation
    st.sidebar.title("🏢 Partnership App")
    
    # --- NEW: Select Partnership ---
    partnership = st.sidebar.selectbox("🤝 Select Active Partnership", ["Sandeep & Harshal", "Sandeep & Vishnu"])
    p1_name = "Sandeep"
    p2_name = "Harshal" if "Harshal" in partnership else "Vishnu"
    
    st.sidebar.markdown("---")
    
    menu = ["Dashboard", "Slot Management", "Expenses", "Settlements", "Partner Balance", "Transaction History", "Data Backup (Important)"]
    choice = st.sidebar.radio("Navigation", menu)
    
    st.sidebar.markdown("---")
    st.sidebar.info("Calculates real-time P&L and exact amounts partners need to take or give.")
    
    # Pre-calculate financials for global use
    financial_data = calculate_financials(partnership, p1_name, p2_name)

    # Routing
    if choice == "Dashboard":
        render_dashboard(financial_data, partnership, p1_name, p2_name)
    elif choice == "Slot Management":
        render_slots_management(partnership, p1_name, p2_name)
    elif choice == "Expenses":
        render_expenses(partnership, p1_name, p2_name)
    elif choice == "Settlements":
        render_settlements(partnership, p1_name, p2_name)
    elif choice == "Partner Balance":
        render_partner_balance(financial_data, partnership, p1_name, p2_name)
    elif choice == "Transaction History":
        render_transaction_history(partnership)
    elif choice == "Data Backup (Important)":
        render_database_management()

if __name__ == '__main__':
    main()
