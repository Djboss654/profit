import streamlit as st
import pandas as pd
import requests
import json
import base64
import os
import uuid
from datetime import datetime, date

# ==========================================
# PAGE CONFIGURATION
# ==========================================
st.set_page_config(page_title="Simple Partner Hisab", page_icon="💰", layout="wide")

LOCAL_FILE = "accounting_data.json"
PARTNERSHIPS = {
    "Sandeep & Harshal": "Harshal",
    "Sandeep & Vishnu": "Vishnu"
}

# ==========================================
# GITHUB & LOCAL STORAGE FUNCTIONS
# ==========================================
def get_empty_data():
    """Returns the default empty data structure for both partnerships."""
    return {
        "Sandeep & Harshal": {"expenses": [], "settlements": [], "payouts": []},
        "Sandeep & Vishnu": {"expenses": [], "settlements": [], "payouts": []}
    }

def is_github_configured():
    """Checks if GitHub secrets are configured in Streamlit."""
    try:
        return bool(st.secrets.get("GITHUB_TOKEN") and st.secrets.get("GITHUB_REPO"))
    except Exception:
        return False

def get_github_config():
    """Reads GitHub API configuration from Streamlit secrets."""
    token = st.secrets["GITHUB_TOKEN"].strip()
    repo = st.secrets["GITHUB_REPO"].strip()
    # Clean full GitHub URLs if pasted instead of username/repo
    repo = repo.replace("https://github.com/", "").replace("http://github.com/", "").strip("/")
    if repo.endswith(".git"):
        repo = repo[:-4]
    file_path = st.secrets.get("GITHUB_FILE_PATH", "accounting_data.json").strip()
    branch = st.secrets.get("GITHUB_BRANCH", "main").strip()
    url = f"https://api.github.com/repos/{repo}/contents/{file_path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    return url, headers, branch

def load_data():
    """Loads data from GitHub if configured, otherwise from a local JSON file."""
    if is_github_configured():
        try:
            url, headers, branch = get_github_config()
            resp = requests.get(f"{url}?ref={branch}", headers=headers, timeout=10)
            if resp.status_code == 200:
                content = resp.json()
                decoded = base64.b64decode(content["content"]).decode("utf-8")
                data = json.loads(decoded)
                for p in PARTNERSHIPS:
                    if p not in data:
                        data[p] = {"expenses": [], "settlements": [], "payouts": []}
                return data
            elif resp.status_code == 404:
                return get_empty_data()
            else:
                st.error(f"GitHub load error ({resp.status_code}): {resp.text}")
        except Exception as e:
            st.error(f"Could not connect to GitHub: {e}")

    # Fallback to local JSON file
    if os.path.exists(LOCAL_FILE):
        try:
            with open(LOCAL_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            for p in PARTNERSHIPS:
                if p not in data:
                    data[p] = {"expenses": [], "settlements": [], "payouts": []}
            return data
        except Exception:
            pass
    return get_empty_data()

def save_data(data):
    """Saves data to GitHub (if configured) and also writes a local backup copy."""
    try:
        with open(LOCAL_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass

    if is_github_configured():
        try:
            url, headers, branch = get_github_config()
            sha = None
            get_resp = requests.get(f"{url}?ref={branch}", headers=headers, timeout=10)
            if get_resp.status_code == 200:
                sha = get_resp.json().get("sha")

            encoded_content = base64.b64encode(
                json.dumps(data, indent=2).encode("utf-8")
            ).decode("utf-8")

            payload = {
                "message": f"Update accounting data - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                "content": encoded_content,
                "branch": branch
            }
            if sha:
                payload["sha"] = sha

            put_resp = requests.put(url, headers=headers, json=payload, timeout=15)
            if put_resp.status_code in (200, 201):
                return True, "Saved to GitHub!"
            else:
                return False, f"GitHub save failed ({put_resp.status_code}): {put_resp.text}"
        except Exception as e:
            return False, f"GitHub connection error: {e}"
    return True, "Saved locally (configure GitHub Secrets to save permanently)."

# ==========================================
# HELPER & CALCULATION LOGIC
# ==========================================
def fmt(amount):
    """Formats a number in Indian Rupees."""
    return f"₹ {amount:,.2f}"

def calculate_summary(pdata, partner_name):
    """
    Calculates all pending expenses, 50-50 shares, profit, and final cash settlement
    for a single partnership (Sandeep & Partner).
    """
    expenses = pdata.get("expenses", [])
    settlements = pdata.get("settlements", [])
    payouts = pdata.get("payouts", [])

    # 1. Separate Expenses
    sandeep_number_purchase = sum(e["amount"] for e in expenses if e["paid_by"] == "Sandeep")
    partner_order_payment = sum(e["amount"] for e in expenses if e["paid_by"] == partner_name)

    # Sandeep's Number Purchase is split 50-50 -> Partner owes 50% to Sandeep
    sandeep_50_share = sandeep_number_purchase / 2.0

    # 2. Manual Payouts Tracking (No auto-reimbursement)
    partner_expense_paid_back = sum(
        p["amount"] for p in payouts if p["purpose"] == "Partner Order Expense"
    )
    sandeep_50_paid_back = sum(
        p["amount"] for p in payouts if p["purpose"] == "Sandeep 50% Number Purchase"
    )

    pending_partner_expense = partner_order_payment - partner_expense_paid_back
    pending_sandeep_50 = sandeep_50_share - sandeep_50_paid_back

    # 3. Settlements Received
    settle_in_partner_bank = sum(s["amount"] for s in settlements if s["received_by"] == partner_name)
    settle_in_sandeep_bank = sum(s["amount"] for s in settlements if s["received_by"] == "Sandeep")
    total_settlement = settle_in_partner_bank + settle_in_sandeep_bank

    # 4. Leftover Profit Calculation
    total_expenses = sandeep_number_purchase + partner_order_payment
    net_profit = total_settlement - total_expenses
    sandeep_profit = net_profit / 2.0
    partner_profit = net_profit / 2.0

    # 5. Final Cash-in-Hand vs Rightful Total Cut
    sandeep_should_have = sandeep_number_purchase + sandeep_profit
    partner_should_have = partner_order_payment + partner_profit

    cash_sandeep_to_partner = sum(
        p["amount"] for p in payouts if p["paid_from"] == "Sandeep" and p["paid_to"] == partner_name
    )
    cash_partner_to_sandeep = sum(
        p["amount"] for p in payouts if p["paid_from"] == partner_name and p["paid_to"] == "Sandeep"
    )

    sandeep_cash_now = settle_in_sandeep_bank - cash_sandeep_to_partner + cash_partner_to_sandeep
    partner_cash_now = settle_in_partner_bank - cash_partner_to_sandeep + cash_sandeep_to_partner

    partner_to_give_sandeep = partner_cash_now - partner_should_have

    return {
        "sandeep_number_purchase": sandeep_number_purchase,
        "sandeep_50_share": sandeep_50_share,
        "sandeep_50_paid_back": sandeep_50_paid_back,
        "pending_sandeep_50": pending_sandeep_50,
        "partner_order_payment": partner_order_payment,
        "partner_expense_paid_back": partner_expense_paid_back,
        "pending_partner_expense": pending_partner_expense,
        "settle_in_partner_bank": settle_in_partner_bank,
        "settle_in_sandeep_bank": settle_in_sandeep_bank,
        "total_settlement": total_settlement,
        "total_expenses": total_expenses,
        "net_profit": net_profit,
        "sandeep_profit": sandeep_profit,
        "partner_profit": partner_profit,
        "sandeep_should_have": sandeep_should_have,
        "partner_should_have": partner_should_have,
        "sandeep_cash_now": sandeep_cash_now,
        "partner_cash_now": partner_cash_now,
        "partner_to_give_sandeep": partner_to_give_sandeep,
    }

# ==========================================
# MAIN APP UI
# ==========================================
def main():
    if "db_data" not in st.session_state:
        st.session_state.db_data = load_data()

    st.sidebar.title("💰 Partner Hisab")
    partnership = st.sidebar.radio(
        "Select Partnership",
        list(PARTNERSHIPS.keys())
    )
    partner_name = PARTNERSHIPS[partnership]

    st.sidebar.markdown("---")
    if is_github_configured():
        st.sidebar.success("☁️ GitHub Auto-Save: ON")
    else:
        st.sidebar.warning("⚠️ Local Mode (GitHub not linked)")
        with st.sidebar.expander("How to Save on GitHub"):
            st.markdown("""
            Add these 3 lines in **Streamlit Cloud → Settings → Secrets**:
            ```toml
            GITHUB_TOKEN = "your_github_token"
            GITHUB_REPO = "Djboss654/profit"
            GITHUB_BRANCH = "main"
            ```
            """)

    if st.sidebar.button("🔄 Refresh from GitHub"):
        st.session_state.db_data = load_data()
        st.rerun()

    pdata = st.session_state.db_data[partnership]
    s = calculate_summary(pdata, partner_name)

    st.title(f"📘 {partnership}")

    tab1, tab2, tab3, tab4 = st.tabs([
        "📊 Summary (Hisab)",
        "➕ Add Entry",
        "💸 Manual Payouts",
        "📋 History"
    ])

    # ------------------------------------------
    # TAB 1: SUMMARY (HISAB)
    # ------------------------------------------
    with tab1:
        st.subheader("1. Pending Expenses (Manual Settlement)")
        c1, c2 = st.columns(2)

        with c1:
            st.info(f"**{partner_name} — Order Place Payment**")
            st.write(f"Total Spent by {partner_name}: **{fmt(s['partner_order_payment'])}**")
            st.write(f"Already Paid Back (Manual): **{fmt(s['partner_expense_paid_back'])}**")
            st.metric(f"Pending Expense to Pay {partner_name}", fmt(s['pending_partner_expense']))

        with c2:
            st.info("**Sandeep — Number Purchase (50-50)**")
            st.write(f"Total Spent by Sandeep: **{fmt(s['sandeep_number_purchase'])}**")
            st.write(f"50% Share ({partner_name} has to give Sandeep): **{fmt(s['sandeep_50_share'])}**")
            st.write(f"Already Received (Manual): **{fmt(s['sandeep_50_paid_back'])}**")
            st.metric("Pending 50% Amount to Sandeep", fmt(s['pending_sandeep_50']))

        st.markdown("---")
        st.subheader("2. Bank Settlement & Profit Split (50-50)")

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Settlement Received", fmt(s['total_settlement']))
        m2.metric("Total Expenses (Both)", fmt(s['total_expenses']))
        m3.metric("Leftover Net Profit", fmt(s['net_profit']))
        m4.metric("Each Partner 50% Profit", fmt(s['sandeep_profit']))

        st.caption(
            f"Settlements in {partner_name}'s Bank: {fmt(s['settle_in_partner_bank'])}  |  "
            f"Settlements in Sandeep's Bank: {fmt(s['settle_in_sandeep_bank'])}"
        )

        st.markdown("---")
        st.subheader("3. Final Cash Settlement (Who Gives Whom)")

        if s['total_settlement'] == 0:
            st.warning(
                f"No bank settlement recorded yet. Right now, **{partner_name}** has spent "
                f"**{fmt(s['partner_order_payment'])}** (Order Place) and owes Sandeep "
                f"**{fmt(s['pending_sandeep_50'])}** (50% of Number Purchase)."
            )
        else:
            b1, b2 = st.columns(2)
            with b1:
                st.write(f"**Sandeep's Total Share:** {fmt(s['sandeep_should_have'])} *(Number Purchase + 50% Profit)*")
                st.write(f"**Cash Currently with Sandeep:** {fmt(s['sandeep_cash_now'])}")
            with b2:
                st.write(f"**{partner_name}'s Total Share:** {fmt(s['partner_should_have'])} *(Order Payment + 50% Profit)*")
                st.write(f"**Cash Currently with {partner_name}:** {fmt(s['partner_cash_now'])}")

            diff = s['partner_to_give_sandeep']
            if diff > 0.01:
                st.error(f"👉 **{partner_name}** needs to give **{fmt(abs(diff))}** to **Sandeep**.")
            elif diff < -0.01:
                st.error(f"👉 **Sandeep** needs to give **{fmt(abs(diff))}** to **{partner_name}**.")
            else:
                st.success("✅ All settled! Nobody owes anything.")

    # ------------------------------------------
    # TAB 2: ADD ENTRY (EXPENSES & SETTLEMENTS)
    # ------------------------------------------
    with tab2:
        entry_type = st.radio(
            "What do you want to add?",
            [
                f"{partner_name} Expense (Order Place Payment)",
                "Sandeep Expense (Number Purchase)",
                "Bank Settlement Received"
            ],
            horizontal=True
        )

        st.markdown("---")

        if entry_type == f"{partner_name} Expense (Order Place Payment)":
            with st.form("partner_exp_form", clear_on_submit=True):
                st.subheader(f"Add {partner_name}'s Order Place Payment")
                col1, col2 = st.columns(2)
                e_date = col1.date_input("Date", date.today())
                e_amt = col2.number_input("Amount (₹)", min_value=0.0, step=100.0)
                e_note = st.text_input("Note (Optional)", placeholder="e.g., 50 orders payment")

                if st.form_submit_button(f"Save {partner_name}'s Expense", type="primary"):
                    if e_amt <= 0:
                        st.error("Please enter an amount greater than 0.")
                    else:
                        pdata["expenses"].append({
                            "id": str(uuid.uuid4())[:8],
                            "date": e_date.strftime("%Y-%m-%d"),
                            "paid_by": partner_name,
                            "type": "Order Place Payment",
                            "amount": float(e_amt),
                            "note": e_note
                        })
                        ok, msg = save_data(st.session_state.db_data)
                        if ok:
                            st.success(f"Added! {msg}")
                            st.rerun()
                        else:
                            st.error(msg)

        elif entry_type == "Sandeep Expense (Number Purchase)":
            with st.form("sandeep_exp_form", clear_on_submit=True):
                st.subheader("Add Sandeep's Number Purchase")
                col1, col2 = st.columns(2)
                e_date = col1.date_input("Date", date.today())
                e_amt = col2.number_input("Total Amount Paid by Sandeep (₹)", min_value=0.0, step=50.0)
                e_note = st.text_input("Note (Optional)", placeholder="e.g., 50 numbers purchased")

                if st.form_submit_button("Save Sandeep's Expense", type="primary"):
                    if e_amt <= 0:
                        st.error("Please enter an amount greater than 0.")
                    else:
                        pdata["expenses"].append({
                            "id": str(uuid.uuid4())[:8],
                            "date": e_date.strftime("%Y-%m-%d"),
                            "paid_by": "Sandeep",
                            "type": "Number Purchase",
                            "amount": float(e_amt),
                            "note": e_note
                        })
                        ok, msg = save_data(st.session_state.db_data)
                        if ok:
                            st.success(f"Added! 50% share ({fmt(e_amt/2)}) added to pending. {msg}")
                            st.rerun()
                        else:
                            st.error(msg)

        else:
            with st.form("settlement_form", clear_on_submit=True):
                st.subheader("Add Bank Settlement Received")
                col1, col2, col3 = st.columns(3)
                s_date = col1.date_input("Received Date", date.today())
                s_amt = col2.number_input("Amount Received (₹)", min_value=0.0, step=500.0)
                s_rec = col3.selectbox("Received In Account Of", [partner_name, "Sandeep"])
                s_note = st.text_input("Note / Bank Ref (Optional)", placeholder="e.g., Settlement received")

                if st.form_submit_button("Save Settlement", type="primary"):
                    if s_amt <= 0:
                        st.error("Please enter an amount greater than 0.")
                    else:
                        pdata["settlements"].append({
                            "id": str(uuid.uuid4())[:8],
                            "date": s_date.strftime("%Y-%m-%d"),
                            "received_by": s_rec,
                            "amount": float(s_amt),
                            "note": s_note
                        })
                        ok, msg = save_data(st.session_state.db_data)
                        if ok:
                            st.success(f"Settlement saved! {msg}")
                            st.rerun()
                        else:
                            st.error(msg)

    # ------------------------------------------
    # TAB 3: MANUAL PAYOUTS
    # ------------------------------------------
    with tab3:
        st.subheader("Record Manual Payment / Expense Reimbursement")
        st.caption("Nothing is auto-reimbursed. Use this form when you manually pay back an expense or transfer cash.")

        with st.form("payout_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            p_date = col1.date_input("Date", date.today())
            p_purpose = col2.selectbox(
                "Payment Purpose",
                [
                    "Partner Order Expense",
                    "Sandeep 50% Number Purchase",
                    "Profit / Cash Transfer"
                ],
                format_func=lambda x: {
                    "Partner Order Expense": f"Pay {partner_name}'s Pending Order Expense",
                    "Sandeep 50% Number Purchase": "Pay Sandeep's 50% Number Purchase",
                    "Profit / Cash Transfer": "Profit / General Cash Transfer"
                }[x]
            )

            c3, c4, c5 = st.columns(3)
            p_from = c3.selectbox("Paid From (Bank/Hand)", [partner_name, "Sandeep"])
            p_to = c4.selectbox("Paid To", ["Sandeep", partner_name])
            p_amt = c5.number_input("Amount (₹)", min_value=0.0, step=100.0)
            p_note = st.text_input("Note (Optional)", placeholder="e.g., Paid via UPI")

            if st.form_submit_button("Save Manual Payout", type="primary"):
                if p_amt <= 0:
                    st.error("Please enter an amount greater than 0.")
                else:
                    pdata["payouts"].append({
                        "id": str(uuid.uuid4())[:8],
                        "date": p_date.strftime("%Y-%m-%d"),
                        "purpose": p_purpose,
                        "paid_from": p_from,
                        "paid_to": p_to,
                        "amount": float(p_amt),
                        "note": p_note
                    })
                    ok, msg = save_data(st.session_state.db_data)
                    if ok:
                        st.success(f"Payout recorded! {msg}")
                        st.rerun()
                    else:
                        st.error(msg)

    # ------------------------------------------
    # TAB 4: HISTORY & DELETE
    # ------------------------------------------
    with tab4:
        st.subheader(f"All Records ({partnership})")

        st.markdown("#### 🧾 Expenses")
        if pdata["expenses"]:
            df_exp = pd.DataFrame(pdata["expenses"]).sort_values(by="date", ascending=False)
            st.dataframe(df_exp, use_container_width=True, hide_index=True)
            del_exp_id = st.selectbox("Select Expense ID to Delete", ["None"] + df_exp["id"].tolist(), key="del_exp")
            if del_exp_id != "None" and st.button("🗑️ Delete Selected Expense"):
                pdata["expenses"] = [x for x in pdata["expenses"] if x["id"] != del_exp_id]
                save_data(st.session_state.db_data)
                st.rerun()
        else:
            st.info("No expenses added yet.")

        st.markdown("---")

        st.markdown("#### 🏦 Bank Settlements")
        if pdata["settlements"]:
            df_set = pd.DataFrame(pdata["settlements"]).sort_values(by="date", ascending=False)
            st.dataframe(df_set, use_container_width=True, hide_index=True)
            del_set_id = st.selectbox("Select Settlement ID to Delete", ["None"] + df_set["id"].tolist(), key="del_set")
            if del_set_id != "None" and st.button("🗑️ Delete Selected Settlement"):
                pdata["settlements"] = [x for x in pdata["settlements"] if x["id"] != del_set_id]
                save_data(st.session_state.db_data)
                st.rerun()
        else:
            st.info("No settlements recorded yet.")

        st.markdown("---")

        st.markdown("#### 💸 Manual Payouts")
        if pdata["payouts"]:
            df_pay = pd.DataFrame(pdata["payouts"]).sort_values(by="date", ascending=False)
            st.dataframe(df_pay, use_container_width=True, hide_index=True)
            del_pay_id = st.selectbox("Select Payout ID to Delete", ["None"] + df_pay["id"].tolist(), key="del_pay")
            if del_pay_id != "None" and st.button("🗑️ Delete Selected Payout"):
                pdata["payouts"] = [x for x in pdata["payouts"] if x["id"] != del_pay_id]
                save_data(st.session_state.db_data)
                st.rerun()
        else:
            st.info("No manual payouts recorded yet.")

if __name__ == "__main__":
    main()
