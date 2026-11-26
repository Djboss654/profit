"""
Simple Two-Partner Business Hisab App (Sandeep & Harshal / Sandeep & Vishnu)
---------------------------------------------------------------------------
Exact Workflow:
1. Two completely separate partnerships:
   - Sandeep & Harshal
   - Sandeep & Vishnu
2. Daily Work Entry (per date):
   - Number of Orders
   - Order Price per order (paid by Partner: Harshal / Vishnu)
   - Number Rate per order (paid by Sandeep)
3. Settlement Entry (always received in Partner's bank):
   - Settlement Date, Total Settlement Amount, Number of Orders Settled
   - Links to a Work Date (auto-fills that day's Order Price & Number Rate, or custom)
   - Automatically calculates:
       * Partner's Invested Amount for those orders (Order Price × Orders Settled)
       * Sandeep's Number Amount for those orders (Number Rate × Orders Settled)
       * Remaining Profit = Settlement Amount − Partner Invested − Sandeep Number Cost
       * 50-50 Profit Share = Remaining Profit / 2
       * Partner's Share (keeps in bank) = Partner Invested + 50% Profit
       * Sandeep's Share (to take from Partner) = Sandeep Number Cost + 50% Profit
4. Payment Received from Partner:
   - Record cash/UPI received by Sandeep from Harshal/Vishnu to track exact pending balance.
5. GitHub Auto-Save:
   - Saves and loads `accounting_data.json` on GitHub via Streamlit Secrets (with local fallback).
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
# 1. PAGE CONFIG & STYLING
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
            border: 1px solid rgba(128, 128, 128, 0.22);
            border-radius: 12px;
            padding: 16px 18px;
            margin-bottom: 12px;
        }
        .hisab-title {
            font-size: 0.88rem;
            opacity: 0.78;
            margin-bottom: 4px;
            font-weight: 500;
        }
        .hisab-value {
            font-size: 1.5rem;
            font-weight: 700;
            margin: 0;
        }
        .hisab-sub {
            font-size: 0.82rem;
            opacity: 0.75;
            margin-top: 4px;
        }
        .take-banner {
            background: linear-gradient(135deg, rgba(46, 125, 50, 0.16), rgba(46, 125, 50, 0.05));
            border-left: 5px solid #2e7d32;
            border-radius: 10px;
            padding: 18px 20px;
            margin-bottom: 16px;
        }
        .partner-banner {
            background: linear-gradient(135deg, rgba(21, 101, 192, 0.14), rgba(21, 101, 192, 0.04));
            border-left: 5px solid #1565c0;
            border-radius: 10px;
            padding: 18px 20px;
            margin-bottom: 16px;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

# ============================================================================
# 2. CONSTANTS & HELPERS
# ============================================================================
PARTNERSHIPS = {
    "Sandeep & Harshal": "Harshal",
    "Sandeep & Vishnu": "Vishnu",
}
LOCAL_DATA_FILE = "accounting_data.json"
GITHUB_DATA_PATH = "accounting_data.json"


def format_inr(amount: float) -> str:
    """Format a number in Indian Rupee format (e.g., ₹ 1,25,000.00)."""
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
    """Return clean empty data structure for one partnership."""
    return {
        "daily_work": [],            # Each date: orders_count, order_price, number_rate
        "settlements": [],           # Each settlement: date, orders_settled, amount, rates & shares
        "received_from_partner": [], # Money Partner actually paid to Sandeep
    }


def default_root_data() -> dict:
    """Return root JSON structure containing both partnerships."""
    return {
        "Sandeep & Harshal": empty_partnership_data(),
        "Sandeep & Vishnu": empty_partnership_data(),
    }


def ensure_data_schema(raw: dict) -> dict:
    """Guarantee all required keys exist without crashing on older data files."""
    data = default_root_data()
    if not isinstance(raw, dict):
        return data
    for p_key in PARTNERSHIPS:
        if isinstance(raw.get(p_key), dict):
            for section in ("daily_work", "settlements", "received_from_partner"):
                items = raw[p_key].get(section, [])
                if isinstance(items, list):
                    data[p_key][section] = items
    return data


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
# 3. GITHUB & LOCAL STORAGE LAYER
# ============================================================================
def get_github_config() -> tuple:
    """Read GitHub credentials from Streamlit Secrets."""
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
    """Return GitHub API headers compatible with fine-grained and classic PATs."""
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def load_data() -> tuple:
    """Load data from GitHub if configured, otherwise fallback to local JSON."""
    token, repo, branch = get_github_config()
    err = ""
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

    if os.path.exists(LOCAL_DATA_FILE):
        try:
            with open(LOCAL_DATA_FILE, "r", encoding="utf-8") as f:
                return ensure_data_schema(json.load(f)), "Local File", err
        except Exception as exc:
            return default_root_data(), "Local File", f"Local Read Error: {exc}"
    return default_root_data(), "Local File", err


def save_data(data: dict) -> tuple:
    """Save data to local JSON and push to GitHub if secrets are configured."""
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
            return False, "GitHub Error 401: Invalid or expired token. Generate a new token and update Streamlit Secrets."
        if put_resp.status_code == 403:
            return False, "GitHub Error 403: Permission denied. Ensure token has 'Contents: Read and write' permission."
        if put_resp.status_code == 404:
            return False, f"GitHub Error 404: Repo '{repo}' or branch '{branch}' not found."
        return False, f"GitHub Save Error ({put_resp.status_code}): {put_resp.text[:180]}"
    except Exception as exc:
        return False, f"GitHub Save Exception: {exc}"


# ============================================================================
# 4. CORE CALCULATION ENGINE
# ============================================================================
def calculate_summary(pdata: dict) -> dict:
    """
    Calculate clear totals across all daily work, settlements, and payments received.
    Remember: Settlement money ALWAYS arrives in the Partner's bank account.
    """
    daily_work = pdata.get("daily_work", [])
    settlements = pdata.get("settlements", [])
    received = pdata.get("received_from_partner", [])

    # Daily Work Totals
    total_orders_placed = sum(int(w.get("orders_count", 0)) for w in daily_work)
    total_partner_order_paid = sum(float(w.get("partner_total", 0.0)) for w in daily_work)
    total_sandeep_number_paid = sum(float(w.get("sandeep_total", 0.0)) for w in daily_work)

    # Settlement Totals
    total_orders_settled = sum(int(s.get("orders_settled", 0)) for s in settlements)
    pending_orders = max(0, total_orders_placed - total_orders_settled)
    total_settlement_received = sum(float(s.get("settlement_amount", 0.0)) for s in settlements)

    # Breakdown from Settled Batches
    settled_partner_investment = sum(float(s.get("partner_invested", 0.0)) for s in settlements)
    settled_sandeep_number = sum(float(s.get("sandeep_invested", 0.0)) for s in settlements)
    total_net_profit = sum(float(s.get("net_profit", 0.0)) for s in settlements)
    total_profit_each = sum(float(s.get("profit_each", 0.0)) for s in settlements)

    # Shares (Settlements arrive in Partner's bank)
    total_partner_share = sum(float(s.get("partner_total_share", 0.0)) for s in settlements)
    total_sandeep_share = sum(float(s.get("sandeep_total_share", 0.0)) for s in settlements)

    # Money already transferred from Partner to Sandeep
    already_received_by_sandeep = sum(float(r.get("amount", 0.0)) for r in received)
    pending_to_take_from_partner = total_sandeep_share - already_received_by_sandeep

    # Track settled orders per work_id so dropdown shows remaining unsettled orders
    settled_by_work_id = {}
    for s in settlements:
        wid = s.get("work_id")
        if wid:
            settled_by_work_id[wid] = settled_by_work_id.get(wid, 0) + int(s.get("orders_settled", 0))

    return {
        "total_orders_placed": total_orders_placed,
        "total_orders_settled": total_orders_settled,
        "pending_orders": pending_orders,
        "total_partner_order_paid": total_partner_order_paid,
        "total_sandeep_number_paid": total_sandeep_number_paid,
        "total_settlement_received": total_settlement_received,
        "settled_partner_investment": settled_partner_investment,
        "settled_sandeep_number": settled_sandeep_number,
        "total_net_profit": total_net_profit,
        "total_profit_each": total_profit_each,
        "total_partner_share": total_partner_share,
        "total_sandeep_share": total_sandeep_share,
        "already_received_by_sandeep": already_received_by_sandeep,
        "pending_to_take_from_partner": pending_to_take_from_partner,
        "settled_by_work_id": settled_by_work_id,
    }


# ============================================================================
# 5. INITIALIZE SESSION STATE
# ============================================================================
if "data" not in st.session_state:
    loaded_data, storage_label, load_err = load_data()
    st.session_state["data"] = loaded_data
    st.session_state["storage_label"] = storage_label
    st.session_state["load_err"] = load_err


# ============================================================================
# 6. SIDEBAR NAVIGATION
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
            "📅 1. Daily Order & Number Entry",
            "🏦 2. Add Settlement",
            "💵 3. Payment Received",
            "📜 History & Delete",
        ],
        index=0,
    )

    st.divider()
    storage_label = st.session_state.get("storage_label", "Local File")
    if storage_label.startswith("GitHub"):
        st.success(f"☁️ Auto-Save: {storage_label}")
    else:
        st.warning("💾 Local Save Only (Add GitHub Secrets)")

    if st.session_state.get("load_err"):
        st.error(st.session_state["load_err"])

    if st.button("🔄 Reload from GitHub", use_container_width=True):
        loaded_data, storage_label, load_err = load_data()
        st.session_state["data"] = loaded_data
        st.session_state["storage_label"] = storage_label
        st.session_state["load_err"] = load_err
        st.rerun()

    if st.button("☁️ Test & Save File to GitHub", use_container_width=True):
        ok, msg = save_data(st.session_state["data"])
        if ok:
            st.success(msg)
        else:
            st.error(msg)

pdata = st.session_state["data"][active_partnership]
summary = calculate_summary(pdata)


# ============================================================================
# 7. PAGE 1: SUMMARY (HISAB)
# ============================================================================
if page == "📊 Summary (Hisab)":
    st.header(f"📊 {active_partnership} — Hisab Summary")
    st.caption(f"All settlements arrive in **{partner_name}'s bank account**.")

    # Main Action Banners: Exact Amount Sandeep Has to Take vs Partner's Share
    b1, b2 = st.columns(2)
    with b1:
        pending_take = summary["pending_to_take_from_partner"]
        st.markdown(
            f"""
            <div class="take-banner">
                <div style="font-size:0.95rem; font-weight:600; opacity:0.85;">
                    💰 AMOUNT SANDEEP HAS TO TAKE FROM {partner_name.upper()}
                </div>
                <div style="font-size:2.1rem; font-weight:800; margin:6px 0;">
                    {format_inr(pending_take)}
                </div>
                <div style="font-size:0.88rem; opacity:0.85;">
                    Total Sandeep Share: <strong>{format_inr(summary['total_sandeep_share'])}</strong>
                    (Number Cost: {format_inr(summary['settled_sandeep_number'])} + 50% Profit: {format_inr(summary['total_profit_each'])})<br>
                    Already Received from {partner_name}: <strong>{format_inr(summary['already_received_by_sandeep'])}</strong>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with b2:
        st.markdown(
            f"""
            <div class="partner-banner">
                <div style="font-size:0.95rem; font-weight:600; opacity:0.85;">
                    🏦 {partner_name.upper()}'S TOTAL SHARE (KEEPS FROM SETTLEMENT)
                </div>
                <div style="font-size:2.1rem; font-weight:800; margin:6px 0;">
                    {format_inr(summary['total_partner_share'])}
                </div>
                <div style="font-size:0.88rem; opacity:0.85;">
                    Order Investment Back: <strong>{format_inr(summary['settled_partner_investment'])}</strong><br>
                    + 50% Profit Share: <strong>{format_inr(summary['total_profit_each'])}</strong>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # KPI Row
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        render_card(
            "Orders Overview",
            f"{summary['total_orders_placed']:,}",
            f"Settled: {summary['total_orders_settled']:,} | Pending: {summary['pending_orders']:,}",
        )
    with c2:
        render_card(
            f"Total Settlement ({partner_name} Bank)",
            format_inr(summary["total_settlement_received"]),
            f"Net Profit: {format_inr(summary['total_net_profit'])}",
        )
    with c3:
        render_card(
            f"{partner_name}'s Total Order Paid",
            format_inr(summary["total_partner_order_paid"]),
            f"Settled Back: {format_inr(summary['settled_partner_investment'])}",
        )
    with c4:
        render_card(
            "Sandeep's Total Number Paid",
            format_inr(summary["total_sandeep_number_paid"]),
            f"Settled Back: {format_inr(summary['settled_sandeep_number'])}",
        )

    # Recent Settlements Table
    st.subheader("🏦 Settlement-Wise Share Breakdown")
    if pdata["settlements"]:
        rows = []
        for s in reversed(pdata["settlements"]):
            rows.append(
                {
                    "Settlement Date": s.get("date"),
                    "Work Date": s.get("work_date", "Custom"),
                    "Orders": s.get("orders_settled", 0),
                    "Settlement (₹)": s.get("settlement_amount", 0.0),
                    f"{partner_name} Inv. (₹)": s.get("partner_invested", 0.0),
                    "Sandeep Num. (₹)": s.get("sandeep_invested", 0.0),
                    "50% Profit Each (₹)": s.get("profit_each", 0.0),
                    f"{partner_name} Share (₹)": s.get("partner_total_share", 0.0),
                    "Take by Sandeep (₹)": s.get("sandeep_total_share", 0.0),
                }
            )
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("No settlements added yet. Go to **📅 1. Daily Order & Number Entry** first, then **🏦 2. Add Settlement**.")


# ============================================================================
# 8. PAGE 2: DAILY ORDER & NUMBER ENTRY
# ============================================================================
elif page == "📅 1. Daily Order & Number Entry":
    st.header(f"📅 Daily Order & Number Entry — {active_partnership}")
    st.write(
        f"Enter each date's **Order Price** (paid by **{partner_name}**) and "
        f"**Number Rate** (paid by **Sandeep**)."
    )

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        w_date = st.date_input("Work Date", value=date.today(), key="w_date")
    with col2:
        w_orders = st.number_input("Number of Orders", min_value=1, step=1, value=50, key="w_orders")
    with col3:
        w_order_price = st.number_input(
            f"Order Price / Order (₹) — {partner_name}",
            min_value=0.0,
            step=1.0,
            value=124.0,
            key="w_order_price",
        )
    with col4:
        w_number_rate = st.number_input(
            "Number Rate / Order (₹) — Sandeep",
            min_value=0.0,
            step=1.0,
            value=15.0,
            key="w_number_rate",
        )

    partner_total = round(w_orders * w_order_price, 2)
    sandeep_total = round(w_orders * w_number_rate, 2)

    st.info(
        f"**Live Daily Cost Preview for {w_orders} Orders on {w_date}:**\n\n"
        f"- **{partner_name} Pays (Orders):** {w_orders} × {format_inr(w_order_price)} = **{format_inr(partner_total)}**\n"
        f"- **Sandeep Pays (Numbers):** {w_orders} × {format_inr(w_number_rate)} = **{format_inr(sandeep_total)}**\n"
        f"- **Total Daily Investment:** **{format_inr(partner_total + sandeep_total)}**"
    )

    w_notes = st.text_input("Notes (Optional)", placeholder="e.g., Today's batch", key="w_notes")

    if st.button("💾 Save Daily Entry", type="primary", use_container_width=True):
        entry = {
            "id": str(uuid.uuid4())[:8],
            "date": str(w_date),
            "orders_count": int(w_orders),
            "order_price": round(float(w_order_price), 2),
            "number_rate": round(float(w_number_rate), 2),
            "partner_total": partner_total,
            "sandeep_total": sandeep_total,
            "notes": w_notes.strip(),
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        pdata["daily_work"].append(entry)
        ok, msg = save_data(st.session_state["data"])
        if ok:
            st.success(f"✅ Saved {w_orders} orders for {w_date}. {msg}")
            st.rerun()
        else:
            st.error(msg)

    # Show recent daily entries below
    if pdata["daily_work"]:
        st.divider()
        st.subheader("Recent Daily Entries")
        settled_map = summary["settled_by_work_id"]
        rows = []
        for w in reversed(pdata["daily_work"]):
            settled_cnt = settled_map.get(w["id"], 0)
            rem_cnt = max(0, int(w.get("orders_count", 0)) - settled_cnt)
            rows.append(
                {
                    "Work Date": w.get("date"),
                    "Orders": w.get("orders_count"),
                    "Settled": settled_cnt,
                    "Pending": rem_cnt,
                    f"Order Price ({partner_name})": w.get("order_price"),
                    f"{partner_name} Paid (₹)": w.get("partner_total"),
                    "Number Rate (Sandeep)": w.get("number_rate"),
                    "Sandeep Paid (₹)": w.get("sandeep_total"),
                    "Notes": w.get("notes", ""),
                }
            )
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ============================================================================
# 9. PAGE 3: ADD SETTLEMENT (ALWAYS RECEIVED IN PARTNER'S BANK)
# ============================================================================
elif page == "🏦 2. Add Settlement":
    st.header(f"🏦 Add Settlement — {active_partnership}")
    st.caption(
        f"Settlement money is received in **{partner_name}'s bank**. "
        f"Select the work date (or custom rate), enter orders received & settlement amount, "
        f"and see the exact share for **{partner_name}** and **Sandeep**."
    )

    settled_map = summary["settled_by_work_id"]

    # Build work date selector options
    work_options = {"Custom Rate / Unknown Work Date": None}
    for w in reversed(pdata["daily_work"]):
        wid = w["id"]
        total_o = int(w.get("orders_count", 0))
        done_o = settled_map.get(wid, 0)
        rem_o = max(0, total_o - done_o)
        label = (
            f"{w['date']} | {total_o} Orders (Pending: {rem_o}) | "
            f"Order ₹{w['order_price']} | Number ₹{w['number_rate']}"
        )
        work_options[label] = w

    selected_work_label = st.selectbox(
        "Which Work Date is this Settlement For?",
        options=list(work_options.keys()),
    )
    selected_work = work_options[selected_work_label]

    # Default rates and order count from selected work date
    if selected_work is not None:
        wid = selected_work["id"]
        rem_orders = max(1, int(selected_work["orders_count"]) - settled_map.get(wid, 0))
        default_order_price = float(selected_work["order_price"])
        default_number_rate = float(selected_work["number_rate"])
        work_date_str = selected_work["date"]
        work_id_str = wid
    else:
        rem_orders = 10
        default_order_price = 124.0
        default_number_rate = 15.0
        work_date_str = "Custom / Unknown"
        work_id_str = ""

    col1, col2, col3 = st.columns(3)
    with col1:
        s_date = st.date_input("Settlement Received Date", value=date.today(), key="s_date")
    with col2:
        s_orders = st.number_input(
            "Number of Orders Received in Settlement",
            min_value=1,
            step=1,
            value=int(rem_orders),
            key=f"s_orders_{work_id_str}",
        )
    with col3:
        s_amount = st.number_input(
            f"Settlement Amount Received in {partner_name}'s Bank (₹)",
            min_value=0.0,
            step=100.0,
            value=0.0,
            key="s_amount",
        )

    # Rate inputs (auto-filled from chosen Work Date, editable if needed)
    r1, r2 = st.columns(2)
    with r1:
        used_order_price = st.number_input(
            f"Order Price Applied ({partner_name}) (₹ / order)",
            min_value=0.0,
            step=1.0,
            value=default_order_price,
            key=f"used_op_{work_id_str}",
        )
    with r2:
        used_number_rate = st.number_input(
            "Number Rate Applied (Sandeep) (₹ / order)",
            min_value=0.0,
            step=1.0,
            value=default_number_rate,
            key=f"used_nr_{work_id_str}",
        )

    # Exact Live Settlement Calculation
    partner_invested = round(s_orders * used_order_price, 2)
    sandeep_invested = round(s_orders * used_number_rate, 2)
    net_profit = round(s_amount - partner_invested - sandeep_invested, 2)
    profit_each = round(net_profit / 2.0, 2)

    partner_total_share = round(partner_invested + profit_each, 2)
    sandeep_total_share = round(sandeep_invested + profit_each, 2)

    st.divider()
    st.subheader("Live Settlement Split Preview")

    p_col1, p_col2 = st.columns(2)
    with p_col1:
        st.markdown(
            f"""
            <div class="take-banner">
                <div style="font-size:0.9rem; font-weight:600;">
                    👉 TAKE FROM {partner_name.upper()} (SANDEEP'S SHARE)
                </div>
                <div style="font-size:1.9rem; font-weight:800; margin:4px 0;">
                    {format_inr(sandeep_total_share)}
                </div>
                <div style="font-size:0.86rem;">
                    1. Sandeep's Number Cost ({s_orders} × ₹{used_number_rate:g}): <strong>{format_inr(sandeep_invested)}</strong><br>
                    2. Sandeep's 50% Profit Share: <strong>{format_inr(profit_each)}</strong>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with p_col2:
        st.markdown(
            f"""
            <div class="partner-banner">
                <div style="font-size:0.9rem; font-weight:600;">
                    🏦 {partner_name.upper()}'S SHARE (KEEPS IN BANK)
                </div>
                <div style="font-size:1.9rem; font-weight:800; margin:4px 0;">
                    {format_inr(partner_total_share)}
                </div>
                <div style="font-size:0.86rem;">
                    1. {partner_name}'s Order Cost ({s_orders} × ₹{used_order_price:g}): <strong>{format_inr(partner_invested)}</strong><br>
                    2. {partner_name}'s 50% Profit Share: <strong>{format_inr(profit_each)}</strong>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.caption(
        f"Check: Settlement ({format_inr(s_amount)}) = "
        f"{partner_name}'s Share ({format_inr(partner_total_share)}) + "
        f"Sandeep's Share ({format_inr(sandeep_total_share)}) | "
        f"Total Net Profit = {format_inr(net_profit)}"
    )

    s_notes = st.text_input("Notes (Optional)", placeholder="e.g., Bank UTR / settlement note", key="s_notes")

    if st.button("💾 Save Settlement", type="primary", use_container_width=True):
        if s_amount <= 0:
            st.error("Please enter a Settlement Amount greater than 0.")
        else:
            entry = {
                "id": str(uuid.uuid4())[:8],
                "date": str(s_date),
                "work_id": work_id_str,
                "work_date": work_date_str,
                "orders_settled": int(s_orders),
                "settlement_amount": round(float(s_amount), 2),
                "order_price": round(float(used_order_price), 2),
                "number_rate": round(float(used_number_rate), 2),
                "partner_invested": partner_invested,
                "sandeep_invested": sandeep_invested,
                "net_profit": net_profit,
                "profit_each": profit_each,
                "partner_total_share": partner_total_share,
                "sandeep_total_share": sandeep_total_share,
                "notes": s_notes.strip(),
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            }
            pdata["settlements"].append(entry)
            ok, msg = save_data(st.session_state["data"])
            if ok:
                st.success(
                    f"✅ Saved settlement of {format_inr(s_amount)}! "
                    f"Sandeep takes {format_inr(sandeep_total_share)} from {partner_name}. {msg}"
                )
                st.rerun()
            else:
                st.error(msg)


# ============================================================================
# 10. PAGE 4: PAYMENT RECEIVED FROM PARTNER
# ============================================================================
elif page == "💵 3. Payment Received":
    st.header(f"💵 Payment Received from {partner_name}")
    st.write(
        f"Record whenever **{partner_name}** transfers money to **Sandeep** "
        f"(UPI / Bank / Cash) to clear Sandeep's pending share."
    )

    c1, c2, c3 = st.columns(3)
    with c1:
        render_card("Total Sandeep Share (All Settlements)", format_inr(summary["total_sandeep_share"]))
    with c2:
        render_card(f"Already Received from {partner_name}", format_inr(summary["already_received_by_sandeep"]))
    with c3:
        render_card(
            f"Still Pending to Take from {partner_name}",
            format_inr(summary["pending_to_take_from_partner"]),
        )

    with st.form("received_payment_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            r_date = st.date_input("Payment Date", value=date.today())
        with col2:
            default_amt = max(0.0, round(float(summary["pending_to_take_from_partner"]), 2))
            r_amount = st.number_input(
                f"Amount Received from {partner_name} (₹)",
                min_value=0.0,
                step=100.0,
                value=default_amt,
            )
        r_notes = st.text_input("Notes (Optional)", placeholder="e.g., GPay / PhonePe / Cash")
        submitted = st.form_submit_button("💾 Save Payment Received", use_container_width=True)

        if submitted:
            if r_amount <= 0:
                st.error("Please enter an amount greater than 0.")
            else:
                entry = {
                    "id": str(uuid.uuid4())[:8],
                    "date": str(r_date),
                    "from_partner": partner_name,
                    "amount": round(float(r_amount), 2),
                    "notes": r_notes.strip(),
                    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                }
                pdata["received_from_partner"].append(entry)
                ok, msg = save_data(st.session_state["data"])
                if ok:
                    st.success(f"✅ Recorded {format_inr(r_amount)} received from {partner_name}. {msg}")
                    st.rerun()
                else:
                    st.error(msg)


# ============================================================================
# 11. PAGE 5: HISTORY & DELETE
# ============================================================================
elif page == "📜 History & Delete":
    st.header(f"📜 History & Delete — {active_partnership}")

    t1, t2, t3 = st.tabs(
        [
            f"📅 Daily Work ({len(pdata['daily_work'])})",
            f"🏦 Settlements ({len(pdata['settlements'])})",
            f"💵 Payments Received ({len(pdata['received_from_partner'])})",
        ]
    )

    def render_history_tab(items: list, section_key: str, columns_map: dict, amount_field: str):
        if not items:
            st.info("No records yet.")
            return

        df = pd.DataFrame(items)
        display_cols = [c for c in columns_map.keys() if c in df.columns]
        st.dataframe(
            df[display_cols].rename(columns=columns_map),
            use_container_width=True,
            hide_index=True,
        )

        st.markdown("##### Delete a Record")
        options = {
            f"{item.get('id')} | {item.get('date')} | {format_inr(item.get(amount_field, 0))} | {item.get('notes', '')}": item.get("id")
            for item in reversed(items)
        }
        selected = st.selectbox(
            "Select record to delete",
            options=list(options.keys()),
            key=f"del_sel_{section_key}",
        )
        confirm = st.checkbox("Confirm delete this record", key=f"del_chk_{section_key}")
        if st.button("🗑️ Delete Selected Record", key=f"del_btn_{section_key}", disabled=not confirm):
            target_id = options[selected]
            pdata[section_key] = [x for x in items if x.get("id") != target_id]
            ok, msg = save_data(st.session_state["data"])
            if ok:
                st.success(f"Deleted record {target_id}. {msg}")
                st.rerun()
            else:
                st.error(msg)

    with t1:
        render_history_tab(
            pdata["daily_work"],
            "daily_work",
            {
                "id": "ID",
                "date": "Work Date",
                "orders_count": "Orders",
                "order_price": f"Order Price ({partner_name})",
                "partner_total": f"{partner_name} Paid (₹)",
                "number_rate": "Number Rate (Sandeep)",
                "sandeep_total": "Sandeep Paid (₹)",
                "notes": "Notes",
            },
            "partner_total",
        )

    with t2:
        render_history_tab(
            pdata["settlements"],
            "settlements",
            {
                "id": "ID",
                "date": "Settlement Date",
                "work_date": "Work Date",
                "orders_settled": "Orders",
                "settlement_amount": "Settlement (₹)",
                "partner_invested": f"{partner_name} Inv. (₹)",
                "sandeep_invested": "Sandeep Num. (₹)",
                "profit_each": "50% Profit Each (₹)",
                "partner_total_share": f"{partner_name} Share (₹)",
                "sandeep_total_share": "Sandeep Takes (₹)",
                "notes": "Notes",
            },
            "settlement_amount",
        )

    with t3:
        render_history_tab(
            pdata["received_from_partner"],
            "received_from_partner",
            {
                "id": "ID",
                "date": "Date",
                "from_partner": "From Partner",
                "amount": "Amount Received (₹)",
                "notes": "Notes",
            },
            "amount",
        )
