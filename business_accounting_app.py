"""
Simple Two-Partner Business Hisab App (Sandeep & Harshal / Sandeep & Vishnu)
---------------------------------------------------------------------------
Key Rules Implemented:
1. Two completely separate partnerships:
   - Sandeep & Harshal
   - Sandeep & Vishnu
2. Order Payments (by Harshal / Vishnu) = Business Investment:
   - Tracks total number of orders placed and total amount paid.
   - At every settlement, you manually decide how much invested amount to pay back.
3. Number Purchase (by Sandeep) = Business Expense:
   - Paid back to Sandeep from settlement before dividing profit.
4. Settlements:
   - Tracks number of orders settled, total settlement amount received,
     who received the money in their bank, how much investment is returned
     to the partner from that settlement, and how much expense is paid to Sandeep.
5. Profit Split:
   - After Number Purchase expense and Order Investment, remaining profit is split 50-50.
6. Persistence:
   - Automatically saves and loads `accounting_data.json` from GitHub via Streamlit Secrets,
     with automatic fallback to a local JSON file if secrets are not configured.
"""

import base64
import json
import os
import uuid
from datetime import date, datetime

import pandas as pd
import requests
import streamlit as st

# ============================================================================
# 1. PAGE CONFIG & CLEAN STYLING
# ============================================================================
st.set_page_config(
    page_title="Simple Partnership Hisab",
    page_icon="📒",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
        .block-container {
            padding-top: 1.4rem;
            padding-bottom: 2.5rem;
        }
        .hisab-card {
            background-color: var(--secondary-background-color);
            border: 1px solid rgba(128, 128, 128, 0.2);
            border-radius: 12px;
            padding: 16px 18px;
            margin-bottom: 12px;
        }
        .hisab-title {
            font-size: 0.9rem;
            opacity: 0.78;
            margin-bottom: 4px;
            font-weight: 500;
        }
        .hisab-value {
            font-size: 1.55rem;
            font-weight: 700;
            margin: 0;
        }
        .hisab-sub {
            font-size: 0.82rem;
            opacity: 0.75;
            margin-top: 4px;
        }
        .step-box {
            border-left: 4px solid #2e7d32;
            background-color: var(--secondary-background-color);
            padding: 14px 16px;
            border-radius: 8px;
            margin-bottom: 12px;
        }
        .step-box-blue {
            border-left: 4px solid #1565c0;
            background-color: var(--secondary-background-color);
            padding: 14px 16px;
            border-radius: 8px;
            margin-bottom: 12px;
        }
        .step-box-amber {
            border-left: 4px solid #ef6c00;
            background-color: var(--secondary-background-color);
            padding: 14px 16px;
            border-radius: 8px;
            margin-bottom: 12px;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

# ============================================================================
# 2. CONSTANTS & HELPER FUNCTIONS
# ============================================================================
PARTNERSHIPS = {
    "Sandeep & Harshal": "Harshal",
    "Sandeep & Vishnu": "Vishnu",
}
LOCAL_DATA_FILE = "accounting_data.json"
GITHUB_DATA_PATH = "accounting_data.json"


def format_inr(amount: float) -> str:
    """Format a number in Indian Rupee style (e.g., ₹ 1,25,000.00)."""
    try:
        val = float(amount)
    except (TypeError, ValueError):
        val = 0.0
    sign = "-" if val < 0 else ""
    val = abs(val)
    integer_part, decimal_part = f"{val:.2f}".split(".")
    if len(integer_part) > 3:
        last_three = integer_part[-3:]
        rest = integer_part[:-3]
        parts = []
        while len(rest) > 2:
            parts.append(rest[-2:])
            rest = rest[:-2]
        if rest:
            parts.append(rest)
        formatted_int = ",".join(reversed(parts)) + "," + last_three
    else:
        formatted_int = integer_part
    return f"{sign}₹ {formatted_int}.{decimal_part}"


def empty_partnership_data() -> dict:
    """Return a clean empty structure for one partnership."""
    return {
        "orders": [],        # Partner investment: orders placed & amount paid
        "expenses": [],      # Sandeep's expense: number purchase
        "settlements": [],   # Settlement received + decided investment/expense payouts
        "payouts": [],       # Extra manual payouts (investment, expense, or profit)
    }


def default_root_data() -> dict:
    """Return default root JSON structure containing both partnerships."""
    return {
        "Sandeep & Harshal": empty_partnership_data(),
        "Sandeep & Vishnu": empty_partnership_data(),
    }


def ensure_data_schema(raw: dict) -> dict:
    """Guarantee both partnerships and all required lists exist (backward-compatible)."""
    data = default_root_data()
    if not isinstance(raw, dict):
        return data
    for p_key in PARTNERSHIPS:
        if isinstance(raw.get(p_key), dict):
            for section in ("orders", "expenses", "settlements", "payouts"):
                items = raw[p_key].get(section, [])
                if isinstance(items, list):
                    data[p_key][section] = items
    return data


# ============================================================================
# 3. GITHUB & LOCAL STORAGE LAYER
# ============================================================================
def get_github_config() -> tuple:
    """
    Read GitHub credentials from Streamlit Secrets.
    Supports full repo URLs (e.g., https://github.com/user/repo) or 'user/repo'.
    """
    try:
        token = st.secrets.get("GITHUB_TOKEN", "").strip()
        repo = st.secrets.get("GITHUB_REPO", "").strip()
        branch = st.secrets.get("GITHUB_BRANCH", "main").strip() or "main"
    except Exception:
        return "", "", "main"

    if repo:
        repo = repo.replace("https://github.com/", "").replace("http://github.com/", "")
        repo = repo.rstrip("/")
        if repo.endswith(".git"):
            repo = repo[:-4]
    return token, repo, branch


def github_headers(token: str) -> dict:
    """Return auth headers compatible with both classic and fine-grained GitHub PATs."""
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def load_data() -> tuple[dict, str, str]:
    """
    Load accounting data from GitHub if configured, otherwise from local JSON.
    Returns: (data_dict, storage_mode_label, error_message)
    """
    token, repo, branch = get_github_config()
    if token and repo:
        url = f"https://api.github.com/repos/{repo}/contents/{GITHUB_DATA_PATH}"
        try:
            resp = requests.get(
                url,
                headers=github_headers(token),
                params={"ref": branch},
                timeout=12,
            )
            if resp.status_code == 200:
                payload = resp.json()
                st.session_state["github_sha"] = payload.get("sha")
                decoded = base64.b64decode(payload["content"]).decode("utf-8")
                return ensure_data_schema(json.loads(decoded)), f"GitHub ({repo})", ""
            elif resp.status_code == 404:
                st.session_state["github_sha"] = None
                return default_root_data(), f"GitHub ({repo})", ""
            else:
                err = f"GitHub Load Error ({resp.status_code}): {resp.text[:160]}"
        except Exception as exc:
            err = f"GitHub Connection Error: {exc}"
    else:
        err = ""

    # Fallback to local JSON file
    if os.path.exists(LOCAL_DATA_FILE):
        try:
            with open(LOCAL_DATA_FILE, "r", encoding="utf-8") as f:
                return ensure_data_schema(json.load(f)), "Local File", err
        except Exception as exc:
            return default_root_data(), "Local File", f"Local Read Error: {exc}"
    return default_root_data(), "Local File", err


def save_data(data: dict) -> tuple[bool, str]:
    """
    Persist accounting data to GitHub (if configured) and always mirror locally.
    Returns: (success, status_message)
    """
    # Always write local copy as fast fallback
    try:
        with open(LOCAL_DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

    token, repo, branch = get_github_config()
    if not (token and repo):
        return True, "Saved locally (Add GitHub Secrets in Streamlit Cloud for permanent cloud save)."

    url = f"https://api.github.com/repos/{repo}/contents/{GITHUB_DATA_PATH}"
    headers = github_headers(token)

    try:
        # Fetch latest SHA to prevent conflict errors on concurrent updates
        sha = st.session_state.get("github_sha")
        check_resp = requests.get(url, headers=headers, params={"ref": branch}, timeout=10)
        if check_resp.status_code == 200:
            sha = check_resp.json().get("sha")
        elif check_resp.status_code == 404:
            sha = None

        content_str = json.dumps(data, indent=2, ensure_ascii=False)
        encoded_content = base64.b64encode(content_str.encode("utf-8")).decode("utf-8")

        body = {
            "message": f"Update hisab data ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})",
            "content": encoded_content,
            "branch": branch,
        }
        if sha:
            body["sha"] = sha

        put_resp = requests.put(url, headers=headers, json=body, timeout=15)
        if put_resp.status_code in (200, 201):
            new_sha = put_resp.json().get("content", {}).get("sha")
            if new_sha:
                st.session_state["github_sha"] = new_sha
            st.session_state["storage_label"] = f"GitHub ({repo})"
            return True, "Saved to GitHub successfully!"
        if put_resp.status_code == 401:
            return False, "GitHub Error 401: Token is invalid or expired. Generate a new token and update Streamlit Secrets."
        if put_resp.status_code == 403:
            return False, "GitHub Error 403: Permission denied. Set 'Contents' permission to 'Read and write' on your token."
        if put_resp.status_code == 404:
            return False, f"GitHub Error 404: Repo '{repo}' or branch '{branch}' not found (or token lacks access to this repo)."
        return False, f"GitHub Save Error ({put_resp.status_code}): {put_resp.text[:180]}"
    except Exception as exc:
        return False, f"GitHub Save Exception: {exc}"


# ============================================================================
# 4. CORE HISAB CALCULATION ENGINE
# ============================================================================
def calculate_hisab(pdata: dict, partner_name: str) -> dict:
    """
    Compute all clear, simple metrics for the active partnership.

    Rules:
    - Order Payments (Harshal / Vishnu) = Business Investment.
    - Number Purchase (Sandeep) = Business Expense (paid back to Sandeep first).
    - Settlements record:
        * orders_settled
        * amount (total settlement received)
        * received_by (who got the bank transfer)
        * investment_paid_to_partner (decided manually at each settlement)
        * expense_paid_to_sandeep (number purchase amount paid back to Sandeep)
    - Extra Manual Payouts can also pay back Investment, Expense, or Profit.
    """
    orders = pdata.get("orders", [])
    expenses = pdata.get("expenses", [])
    settlements = pdata.get("settlements", [])
    payouts = pdata.get("payouts", [])

    # 1. Orders & Partner Investment
    total_orders_placed = sum(int(o.get("orders_count", 0)) for o in orders)
    total_investment = sum(float(o.get("amount", 0.0)) for o in orders)

    # 2. Sandeep's Number Purchase Expense
    total_numbers_bought = sum(int(e.get("count", 0)) for e in expenses)
    total_number_expense = sum(float(e.get("amount", 0.0)) for e in expenses)

    # 3. Settlements Received
    total_orders_settled = sum(int(s.get("orders_settled", 0)) for s in settlements)
    pending_orders = max(0, total_orders_placed - total_orders_settled)
    total_settlement = sum(float(s.get("amount", 0.0)) for s in settlements)

    settlement_in_partner_bank = sum(
        float(s.get("amount", 0.0))
        for s in settlements
        if s.get("received_by") == partner_name
    )
    settlement_in_sandeep_bank = sum(
        float(s.get("amount", 0.0))
        for s in settlements
        if s.get("received_by") == "Sandeep"
    )

    # 4. Investment Returned to Partner (from settlements + extra manual payouts)
    inv_returned_in_settlements = sum(
        float(s.get("investment_paid_to_partner", 0.0)) for s in settlements
    )
    inv_returned_manual = sum(
        float(p.get("amount", 0.0))
        for p in payouts
        if p.get("payout_type") == "Investment Return to Partner"
    )
    total_investment_returned = inv_returned_in_settlements + inv_returned_manual
    pending_investment = total_investment - total_investment_returned

    # 5. Number Purchase Expense Paid to Sandeep (from settlements + extra manual payouts)
    exp_paid_in_settlements = sum(
        float(s.get("expense_paid_to_sandeep", 0.0)) for s in settlements
    )
    exp_paid_manual = sum(
        float(p.get("amount", 0.0))
        for p in payouts
        if p.get("payout_type") == "Number Expense to Sandeep"
    )
    total_expense_paid_to_sandeep = exp_paid_in_settlements + exp_paid_manual
    pending_expense_to_sandeep = total_number_expense - total_expense_paid_to_sandeep

    # 6. Profit Calculation
    # A) Cash-Pool Distributable Profit (based on what you actually decided to return from settlements):
    #    Total Settlement - Investment Returned - Number Expense Paid to Sandeep
    cash_left_for_profit = (
        total_settlement - total_investment_returned - total_expense_paid_to_sandeep
    )
    cash_profit_each = cash_left_for_profit / 2.0

    # B) True Overall Business Profit (after ALL investments + ALL number expenses):
    true_net_profit = total_settlement - total_investment - total_number_expense
    true_profit_each = true_net_profit / 2.0

    # 7. Profit Payouts already taken
    sandeep_profit_taken = sum(
        float(p.get("amount", 0.0))
        for p in payouts
        if p.get("payout_type") == "Profit Share Paid" and p.get("partner") == "Sandeep"
    )
    partner_profit_taken = sum(
        float(p.get("amount", 0.0))
        for p in payouts
        if p.get("payout_type") == "Profit Share Paid" and p.get("partner") == partner_name
    )

    sandeep_pending_profit = cash_profit_each - sandeep_profit_taken
    partner_pending_profit = cash_profit_each - partner_profit_taken

    return {
        "total_orders_placed": total_orders_placed,
        "total_orders_settled": total_orders_settled,
        "pending_orders": pending_orders,
        "total_investment": total_investment,
        "total_investment_returned": total_investment_returned,
        "pending_investment": pending_investment,
        "total_numbers_bought": total_numbers_bought,
        "total_number_expense": total_number_expense,
        "total_expense_paid_to_sandeep": total_expense_paid_to_sandeep,
        "pending_expense_to_sandeep": pending_expense_to_sandeep,
        "total_settlement": total_settlement,
        "settlement_in_partner_bank": settlement_in_partner_bank,
        "settlement_in_sandeep_bank": settlement_in_sandeep_bank,
        "cash_left_for_profit": cash_left_for_profit,
        "cash_profit_each": cash_profit_each,
        "true_net_profit": true_net_profit,
        "true_profit_each": true_profit_each,
        "sandeep_profit_taken": sandeep_profit_taken,
        "partner_profit_taken": partner_profit_taken,
        "sandeep_pending_profit": sandeep_pending_profit,
        "partner_pending_profit": partner_pending_profit,
    }


def render_card(title: str, value: str, subtitle: str = ""):
    """Render a clean KPI card."""
    sub_html = f'<div class="hisab-sub">{subtitle}</div>' if subtitle else ""
    st.markdown(
        f"""
        <div class="hisab-card">
            <div class="hisab-title">{title}</div>
            <div class="hisab-value">{value}</div>
            {sub_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


# ============================================================================
# 5. INITIALIZE SESSION STATE
# ============================================================================
if "data" not in st.session_state:
    loaded_data, storage_label, load_err = load_data()
    st.session_state["data"] = loaded_data
    st.session_state["storage_label"] = storage_label
    st.session_state["load_err"] = load_err


# ============================================================================
# 6. SIDEBAR NAVIGATION & PARTNERSHIP SWITCHER
# ============================================================================
with st.sidebar:
    st.title("📒 Partnership Hisab")

    active_partnership = st.selectbox(
        "Select Partnership",
        options=list(PARTNERSHIPS.keys()),
        index=0,
    )
    partner_name = PARTNERSHIPS[active_partnership]

    st.divider()
    page = st.radio(
        "Menu",
        options=[
            "📊 Summary (Hisab)",
            "➕ Add Entry",
            "💸 Extra Payouts",
            "📜 History & Delete",
        ],
        index=0,
    )

    st.divider()
    storage_label = st.session_state.get("storage_label", "Local File")
    if storage_label.startswith("GitHub"):
        st.success(f"☁️ Auto-Save: {storage_label}")
    else:
        st.warning("💾 Local Save Only (Add GitHub Secrets for cloud save)")

    if st.session_state.get("load_err"):
        st.error(st.session_state["load_err"])

    if st.button("🔄 Reload from GitHub", use_container_width=True):
        loaded_data, storage_label, load_err = load_data()
        st.session_state["data"] = loaded_data
        st.session_state["storage_label"] = storage_label
        st.session_state["load_err"] = load_err
        st.rerun()

    if st.button("☁️ Test & Save File to GitHub Now", use_container_width=True):
        ok, msg = save_data(st.session_state["data"])
        if ok:
            st.success(msg)
        else:
            st.error(msg)

# Active partnership data & calculations
pdata = st.session_state["data"][active_partnership]
hisab = calculate_hisab(pdata, partner_name)


# ============================================================================
# 7. PAGE 1: SUMMARY (HISAB)
# ============================================================================
if page == "📊 Summary (Hisab)":
    st.header(f"📊 {active_partnership} — Simple Hisab")

    # Top Row: Orders & Settlement Overview
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        render_card(
            "Total Orders Placed",
            f"{hisab['total_orders_placed']:,}",
            f"Settled: {hisab['total_orders_settled']:,} | Pending: {hisab['pending_orders']:,}",
        )
    with c2:
        render_card(
            f"{partner_name}'s Order Investment",
            format_inr(hisab["total_investment"]),
            f"Returned: {format_inr(hisab['total_investment_returned'])}",
        )
    with c3:
        render_card(
            "Sandeep's Number Expense",
            format_inr(hisab["total_number_expense"]),
            f"Paid to Sandeep: {format_inr(hisab['total_expense_paid_to_sandeep'])}",
        )
    with c4:
        render_card(
            "Total Settlement Received",
            format_inr(hisab["total_settlement"]),
            f"{partner_name} Bank: {format_inr(hisab['settlement_in_partner_bank'])} | Sandeep Bank: {format_inr(hisab['settlement_in_sandeep_bank'])}",
        )

    st.subheader("Step-by-Step Settlement & Profit Division")

    # Step 1: Partner Investment
    st.markdown(
        f"""
        <div class="step-box-blue">
            <strong>Step 1 — {partner_name}'s Investment (Order Payments)</strong><br>
            Total Invested: <strong>{format_inr(hisab['total_investment'])}</strong>
            &nbsp;|&nbsp; Paid Back So Far: <strong>{format_inr(hisab['total_investment_returned'])}</strong>
            &nbsp;|&nbsp; Pending Investment Balance: <strong>{format_inr(hisab['pending_investment'])}</strong><br>
            <span style="font-size:0.86rem; opacity:0.8;">
                You decide how much of this investment to pay back to {partner_name} at every settlement.
            </span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Step 2: Sandeep's Number Purchase Expense
    st.markdown(
        f"""
        <div class="step-box-amber">
            <strong>Step 2 — Sandeep's Business Expense (Number Purchase)</strong><br>
            Total Number Expense: <strong>{format_inr(hisab['total_number_expense'])}</strong>
            &nbsp;|&nbsp; Paid to Sandeep: <strong>{format_inr(hisab['total_expense_paid_to_sandeep'])}</strong>
            &nbsp;|&nbsp; Pending to Pay Sandeep: <strong>{format_inr(hisab['pending_expense_to_sandeep'])}</strong><br>
            <span style="font-size:0.86rem; opacity:0.8;">
                Number purchase is a business expense and is paid back to Sandeep before dividing profit.
            </span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Step 3: Profit Split (50-50)
    st.markdown(
        f"""
        <div class="step-box">
            <strong>Step 3 — Remaining Cash to Divide 50-50 (Profit Pool)</strong><br>
            Settlement ({format_inr(hisab['total_settlement'])})
            − Investment Paid ({format_inr(hisab['total_investment_returned'])})
            − Number Expense Paid ({format_inr(hisab['total_expense_paid_to_sandeep'])})
            = <strong>{format_inr(hisab['cash_left_for_profit'])}</strong><br>
            <strong>Sandeep's 50% Share:</strong> {format_inr(hisab['cash_profit_each'])}
            (Taken: {format_inr(hisab['sandeep_profit_taken'])} | Pending: <strong>{format_inr(hisab['sandeep_pending_profit'])}</strong>)<br>
            <strong>{partner_name}'s 50% Share:</strong> {format_inr(hisab['cash_profit_each'])}
            (Taken: {format_inr(hisab['partner_profit_taken'])} | Pending: <strong>{format_inr(hisab['partner_pending_profit'])}</strong>)
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Overall True Net Profit Note
    st.divider()
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("#### 📌 What Sandeep Needs to Receive")
        sandeep_total_pending = (
            max(0.0, hisab["pending_expense_to_sandeep"])
            + max(0.0, hisab["sandeep_pending_profit"])
        )
        st.info(
            f"**Pending Number Expense:** {format_inr(hisab['pending_expense_to_sandeep'])}\n\n"
            f"**Pending 50% Profit Share:** {format_inr(hisab['sandeep_pending_profit'])}\n\n"
            f"**Total Pending for Sandeep:** {format_inr(sandeep_total_pending)}"
        )

    with col_b:
        st.markdown(f"#### 📌 What {partner_name} Needs to Receive")
        partner_total_pending = (
            max(0.0, hisab["pending_investment"])
            + max(0.0, hisab["partner_pending_profit"])
        )
        st.info(
            f"**Pending Order Investment:** {format_inr(hisab['pending_investment'])}\n\n"
            f"**Pending 50% Profit Share:** {format_inr(hisab['partner_pending_profit'])}\n\n"
            f"**Total Pending for {partner_name}:** {format_inr(partner_total_pending)}"
        )

    # True Profit Check (after 100% of all investments & expenses)
    if hisab["true_net_profit"] >= 0:
        st.success(
            f"📈 **Overall Net Business Profit (after 100% Investment + Number Expense):** "
            f"{format_inr(hisab['true_net_profit'])} "
            f"(Each Partner's True 50% Profit: {format_inr(hisab['true_profit_each'])})"
        )
    else:
        st.warning(
            f"⏳ **Recovery Status:** Total Settlement ({format_inr(hisab['total_settlement'])}) is currently "
            f"{format_inr(abs(hisab['true_net_profit']))} below Total Investment + Number Expense "
            f"({format_inr(hisab['total_investment'] + hisab['total_number_expense'])}). "
            f"You have **{hisab['pending_orders']} pending orders** awaiting settlement."
        )


# ============================================================================
# 8. PAGE 2: ADD ENTRY (ORDERS / NUMBER PURCHASE / SETTLEMENT)
# ============================================================================
elif page == "➕ Add Entry":
    st.header(f"➕ Add Entry — {active_partnership}")

    tab_order, tab_expense, tab_settlement = st.tabs(
        [
            f"🛒 1. Order Placed ({partner_name} Investment)",
            "📱 2. Number Purchase (Sandeep Expense)",
            "🏦 3. Settlement Received",
        ]
    )

    # --- TAB 1: ORDER PLACED (PARTNER INVESTMENT) ---
    with tab_order:
        st.subheader(f"Order Place Payment by {partner_name} (Investment)")
        with st.form("add_order_form", clear_on_submit=True):
            col1, col2, col3 = st.columns(3)
            with col1:
                o_date = st.date_input("Date", value=date.today(), key="order_date")
            with col2:
                o_count = st.number_input(
                    "Total Orders Placed", min_value=1, step=1, value=10
                )
            with col3:
                o_amount = st.number_input(
                    "Total Amount Paid (₹)", min_value=0.0, step=100.0, value=0.0
                )

            o_notes = st.text_input("Notes (Optional)", placeholder="e.g., Today's orders placed")
            submitted_order = st.form_submit_button("💾 Save Order Investment", use_container_width=True)

            if submitted_order:
                if o_amount <= 0:
                    st.error("Please enter an amount greater than 0.")
                else:
                    entry = {
                        "id": str(uuid.uuid4())[:8],
                        "date": str(o_date),
                        "partner": partner_name,
                        "orders_count": int(o_count),
                        "amount": round(float(o_amount), 2),
                        "notes": o_notes.strip(),
                        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    }
                    pdata["orders"].append(entry)
                    ok, msg = save_data(st.session_state["data"])
                    if ok:
                        st.success(f"✅ Saved {o_count} orders ({format_inr(o_amount)}). {msg}")
                    else:
                        st.error(msg)

    # --- TAB 2: NUMBER PURCHASE (SANDEEP EXPENSE) ---
    with tab_expense:
        st.subheader("Number Purchase by Sandeep (Business Expense)")
        with st.form("add_expense_form", clear_on_submit=True):
            col1, col2, col3 = st.columns(3)
            with col1:
                e_date = st.date_input("Date", value=date.today(), key="exp_date")
            with col2:
                e_count = st.number_input(
                    "Numbers / Accounts Bought (Optional)", min_value=0, step=1, value=0
                )
            with col3:
                e_amount = st.number_input(
                    "Total Amount Paid by Sandeep (₹)", min_value=0.0, step=50.0, value=0.0
                )

            e_notes = st.text_input("Notes (Optional)", placeholder="e.g., Purchased 50 numbers @ ₹15")
            submitted_exp = st.form_submit_button("💾 Save Number Expense", use_container_width=True)

            if submitted_exp:
                if e_amount <= 0:
                    st.error("Please enter an amount greater than 0.")
                else:
                    entry = {
                        "id": str(uuid.uuid4())[:8],
                        "date": str(e_date),
                        "paid_by": "Sandeep",
                        "count": int(e_count),
                        "amount": round(float(e_amount), 2),
                        "notes": e_notes.strip(),
                        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    }
                    pdata["expenses"].append(entry)
                    ok, msg = save_data(st.session_state["data"])
                    if ok:
                        st.success(f"✅ Saved Number Purchase expense ({format_inr(e_amount)}). {msg}")
                    else:
                        st.error(msg)

    # --- TAB 3: SETTLEMENT RECEIVED ---
    with tab_settlement:
        st.subheader("Record Bank Settlement & Decide Payouts")
        st.caption(
            f"Current Pending Investment ({partner_name}): **{format_inr(hisab['pending_investment'])}** "
            f"| Current Pending Number Expense (Sandeep): **{format_inr(hisab['pending_expense_to_sandeep'])}** "
            f"| Pending Orders: **{hisab['pending_orders']}**"
        )

        # Live inputs outside form so user sees instant profit division preview before saving
        col1, col2 = st.columns(2)
        with col1:
            s_date = st.date_input("Settlement Received Date", value=date.today(), key="set_date")
            s_orders = st.number_input(
                "Number of Orders Received in Settlement",
                min_value=0,
                step=1,
                value=0,
                key="set_orders",
            )
        with col2:
            s_received_by = st.selectbox(
                "Received in Which Partner's Account?",
                options=[partner_name, "Sandeep"],
                key="set_rec_by",
            )
            s_amount = st.number_input(
                "Total Settlement Amount Received (₹)",
                min_value=0.0,
                step=100.0,
                value=0.0,
                key="set_amount",
            )

        st.markdown("##### Decide Amounts to Pay from This Settlement:")
        col3, col4 = st.columns(2)
        with col3:
            s_exp_to_sandeep = st.number_input(
                "1. Number Purchase Expense Paid to Sandeep (₹)",
                min_value=0.0,
                step=50.0,
                value=max(0.0, round(float(hisab["pending_expense_to_sandeep"]), 2)),
                help="Sandeep's number purchase expense to recover from this settlement.",
                key="set_exp_sandeep",
            )
        with col4:
            s_inv_to_partner = st.number_input(
                f"2. Investment Amount Paid to {partner_name} (₹)",
                min_value=0.0,
                step=100.0,
                value=0.0,
                help=f"Decide how much of {partner_name}'s invested money to return from this settlement.",
                key="set_inv_partner",
            )

        # Live preview calculation
        preview_left = s_amount - s_exp_to_sandeep - s_inv_to_partner
        preview_each = preview_left / 2.0

        st.info(
            f"**Live Settlement Preview:**\n\n"
            f"- Settlement Received: **{format_inr(s_amount)}** ({s_orders} orders)\n"
            f"- Paid to Sandeep (Number Expense): **{format_inr(s_exp_to_sandeep)}**\n"
            f"- Paid to {partner_name} (Investment Return): **{format_inr(s_inv_to_partner)}**\n"
            f"- **Remaining Amount to Divide 50-50:** **{format_inr(preview_left)}** "
            f"→ Sandeep: **{format_inr(preview_each)}** | {partner_name}: **{format_inr(preview_each)}**"
        )

        s_notes = st.text_input("Notes (Optional)", placeholder="e.g., Bank UTR / settlement remark", key="set_notes")

        if st.button("💾 Save Settlement", type="primary", use_container_width=True):
            if s_amount <= 0:
                st.error("Please enter a Settlement Amount greater than 0.")
            else:
                entry = {
                    "id": str(uuid.uuid4())[:8],
                    "date": str(s_date),
                    "orders_settled": int(s_orders),
                    "amount": round(float(s_amount), 2),
                    "received_by": s_received_by,
                    "expense_paid_to_sandeep": round(float(s_exp_to_sandeep), 2),
                    "investment_paid_to_partner": round(float(s_inv_to_partner), 2),
                    "profit_pool": round(float(preview_left), 2),
                    "profit_each": round(float(preview_each), 2),
                    "notes": s_notes.strip(),
                    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                }
                pdata["settlements"].append(entry)
                ok, msg = save_data(st.session_state["data"])
                if ok:
                    st.success(f"✅ Settlement of {format_inr(s_amount)} saved! {msg}")
                    st.rerun()
                else:
                    st.error(msg)


# ============================================================================
# 9. PAGE 3: EXTRA MANUAL PAYOUTS
# ============================================================================
elif page == "💸 Extra Payouts":
    st.header(f"💸 Extra Manual Payouts — {active_partnership}")
    st.write(
        "Use this page whenever you manually pay out **Profit Share**, return extra **Investment**, "
        "or pay **Number Expense** outside of a settlement entry."
    )

    c1, c2, c3 = st.columns(3)
    with c1:
        render_card(f"Pending Investment ({partner_name})", format_inr(hisab["pending_investment"]))
    with c2:
        render_card("Pending Number Expense (Sandeep)", format_inr(hisab["pending_expense_to_sandeep"]))
    with c3:
        render_card(
            "Pending Profit Share",
            f"S: {format_inr(hisab['sandeep_pending_profit'])}",
            f"{partner_name}: {format_inr(hisab['partner_pending_profit'])}",
        )

    with st.form("manual_payout_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            p_date = st.date_input("Date", value=date.today())
            p_type = st.selectbox(
                "Payout Type",
                options=[
                    "Profit Share Paid",
                    "Investment Return to Partner",
                    "Number Expense to Sandeep",
                ],
            )
        with col2:
            p_partner = st.selectbox(
                "Paid To",
                options=["Sandeep", partner_name],
                help="For 'Investment Return to Partner' it applies to your partner; for 'Number Expense' it applies to Sandeep.",
            )
            p_amount = st.number_input("Amount Paid (₹)", min_value=0.0, step=100.0, value=0.0)

        p_notes = st.text_input("Notes (Optional)", placeholder="e.g., UPI / Cash paid")
        submitted_payout = st.form_submit_button("💾 Save Manual Payout", use_container_width=True)

        if submitted_payout:
            if p_amount <= 0:
                st.error("Please enter an amount greater than 0.")
            else:
                # Enforce exact recipient for Investment / Expense types
                final_partner = p_partner
                if p_type == "Investment Return to Partner":
                    final_partner = partner_name
                elif p_type == "Number Expense to Sandeep":
                    final_partner = "Sandeep"

                entry = {
                    "id": str(uuid.uuid4())[:8],
                    "date": str(p_date),
                    "payout_type": p_type,
                    "partner": final_partner,
                    "amount": round(float(p_amount), 2),
                    "notes": p_notes.strip(),
                    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                }
                pdata["payouts"].append(entry)
                ok, msg = save_data(st.session_state["data"])
                if ok:
                    st.success(f"✅ Recorded {p_type} ({format_inr(p_amount)}) to {final_partner}. {msg}")
                else:
                    st.error(msg)


# ============================================================================
# 10. PAGE 4: HISTORY & DELETE
# ============================================================================
elif page == "📜 History & Delete":
    st.header(f"📜 History — {active_partnership}")

    t1, t2, t3, t4 = st.tabs(
        [
            f"🛒 Orders Placed ({len(pdata['orders'])})",
            f"📱 Number Purchases ({len(pdata['expenses'])})",
            f"🏦 Settlements ({len(pdata['settlements'])})",
            f"💸 Extra Payouts ({len(pdata['payouts'])})",
        ]
    )

    def render_history_section(items: list, section_key: str, columns_map: dict):
        if not items:
            st.info("No records yet.")
            return

        df = pd.DataFrame(items)
        display_cols = [c for c in columns_map.keys() if c in df.columns]
        df_show = df[display_cols].rename(columns=columns_map)
        st.dataframe(df_show, use_container_width=True, hide_index=True)

        st.markdown("##### Delete a Record")
        options = {
            f"{item.get('id')} | {item.get('date')} | {format_inr(item.get('amount', 0))} | {item.get('notes', '')}": item.get("id")
            for item in reversed(items)
        }
        selected_label = st.selectbox(
            "Select record to delete",
            options=list(options.keys()),
            key=f"del_select_{section_key}",
        )
        confirm_del = st.checkbox(
            "Confirm delete this record",
            key=f"del_confirm_{section_key}",
        )
        if st.button("🗑️ Delete Selected Record", key=f"del_btn_{section_key}", disabled=not confirm_del):
            target_id = options[selected_label]
            pdata[section_key] = [x for x in items if x.get("id") != target_id]
            ok, msg = save_data(st.session_state["data"])
            if ok:
                st.success(f"Deleted record {target_id}. {msg}")
                st.rerun()
            else:
                st.error(msg)

    with t1:
        render_history_section(
            pdata["orders"],
            "orders",
            {
                "id": "ID",
                "date": "Date",
                "partner": "Partner",
                "orders_count": "Orders Placed",
                "amount": "Investment Paid (₹)",
                "notes": "Notes",
            },
        )

    with t2:
        render_history_section(
            pdata["expenses"],
            "expenses",
            {
                "id": "ID",
                "date": "Date",
                "paid_by": "Paid By",
                "count": "Numbers Bought",
                "amount": "Expense Amount (₹)",
                "notes": "Notes",
            },
        )

    with t3:
        render_history_section(
            pdata["settlements"],
            "settlements",
            {
                "id": "ID",
                "date": "Date",
                "orders_settled": "Orders Settled",
                "amount": "Total Settlement (₹)",
                "received_by": "Received By",
                "expense_paid_to_sandeep": "Sandeep Expense Paid (₹)",
                "investment_paid_to_partner": f"{partner_name} Investment Paid (₹)",
                "profit_each": "50% Profit Each (₹)",
                "notes": "Notes",
            },
        )

    with t4:
        render_history_section(
            pdata["payouts"],
            "payouts",
            {
                "id": "ID",
                "date": "Date",
                "payout_type": "Type",
                "partner": "Paid To",
                "amount": "Amount (₹)",
                "notes": "Notes",
            },
        )
