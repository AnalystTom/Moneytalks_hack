"""Plaid Sandbox over HTTP: /sandbox/public_token/create -> /item/public_token/exchange -> balances / transactions."""
import asyncio
import json
import re
from datetime import date, timedelta
from pathlib import Path

import httpx

from app.config import env

PERSONA_PATH = Path(env("PERSONA_PATH") or Path(__file__).resolve().parents[3] / "data" / "PERSONA.md")

HOST = "https://sandbox.plaid.com"
INSTITUTION = "ins_109508"  # First Platypus Bank; user_good / pass_good
STUB_BALANCES = {"cash": 4200.0, "accounts": [{"name": "Plaid Checking", "balance": 4200.0}]}


class PlaidError(Exception):
    def __init__(self, message: str, code: str = "", status: int = 502):
        super().__init__(message)
        self.code = code
        self.status = status


def configured() -> bool:
    return bool(env("PLAID_CLIENT_ID") and env("PLAID_SECRET"))


async def _post(client: httpx.AsyncClient, path: str, body: dict) -> dict:
    creds = {"client_id": env("PLAID_CLIENT_ID"), "secret": env("PLAID_SECRET")}
    try:
        r = await client.post(f"{HOST}{path}", json={**creds, **body})
    except httpx.HTTPError as e:
        raise PlaidError(f"Plaid could not be reached: {e}") from e
    data = r.json() if r.content else {}
    if r.status_code != 200:
        raise PlaidError(data.get("error_message") or f"Plaid returned HTTP {r.status_code}", data.get("error_code", ""), r.status_code)
    return data


# Bank-type rows of the persona's account table -> Plaid depository subtype.
SUBTYPES = (("checking", "checking"), ("savings", "savings"), ("money market", "money market"))

# Synthetic monthly activity (day of month, description, amount); Plaid amounts are positive for money out.
MONTHLY = (
    (1, "ACH Electronic Credit EMPLOYER PAYROLL", -9500.0),
    (3, "Austin Apartment Rent", 2600.0),
    (8, "H-E-B Groceries", 180.0),
    (14, "Austin Energy Utilities", 140.0),
    (21, "Uber Eats", 45.0),
    (26, "Netflix", 15.49),
)


def persona_bank_accounts(path: Path = PERSONA_PATH) -> list[dict]:
    """Checking, savings and money-market rows of the persona's account table: [{name, subtype, balance}]."""
    try:
        text = path.read_text()
    except OSError:
        return []
    accounts = []
    for line in text.splitlines():
        cells = [c.strip().strip("*").strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 4 or not cells[3].startswith("$"):
            continue
        label, institution, kind, balance = cells
        subtype = next((sub for key, sub in SUBTYPES if key in kind.lower()), None)
        if subtype:
            accounts.append({"name": f"{institution} {kind}", "subtype": subtype, "balance": float(re.sub(r"[^\d.]", "", balance))})
    return accounts


def _month_start(today: date, back: int) -> date:
    month = today.month - back
    return date(today.year + (month - 1) // 12, (month - 1) % 12 + 1, 1)


def _custom_user(accounts: list[dict]) -> dict:
    """Plaid custom sandbox user: every account ends at its persona balance; activity is booked on the first checking account."""
    today = date.today()
    activity = []
    for back in range(2):  # Plaid custom users only keep roughly the last 30 days
        start = _month_start(today, back)
        for day, description, amount in MONTHLY:
            d = start.replace(day=day)
            if d < today:
                activity.append({"date_transacted": d.isoformat(), "date_posted": d.isoformat(), "amount": amount, "description": description, "currency": "USD"})
    activity_account = next((a for a in accounts if a["subtype"] == "checking"), accounts[0])
    override = []
    for a in accounts:
        txns = activity if a is activity_account else []
        # Plaid reports starting_balance as the current balance; transactions don't move it
        override.append({
            "type": "depository", "subtype": a["subtype"],
            "starting_balance": a["balance"],
            "meta": {"name": a["name"], "official_name": a["name"]},
            "transactions": txns,
        })
    return {"override_accounts": override}


async def _access_token(client: httpx.AsyncClient) -> str:
    if not configured():
        raise PlaidError("PLAID_CLIENT_ID / PLAID_SECRET are not set", status=503)
    body = {"institution_id": INSTITUTION, "initial_products": ["transactions"]}
    accounts = persona_bank_accounts()
    if accounts:  # make the sandbox bank match the persona instead of Plaid's generic user
        body["options"] = {"override_username": "user_custom", "override_password": json.dumps(_custom_user(accounts))}
    created = await _post(client, "/sandbox/public_token/create", body)
    exchanged = await _post(client, "/item/public_token/exchange", {"public_token": created["public_token"]})
    return exchanged["access_token"]


async def sandbox_balances() -> dict:
    """Cash and per-account balances; falls back to canned data when Plaid credentials are not configured."""
    if not configured():
        return STUB_BALANCES
    async with httpx.AsyncClient(timeout=30) as client:
        access_token = await _access_token(client)
        data = await _post(client, "/accounts/balance/get", {"access_token": access_token})
    accounts, cash = [], 0.0
    for a in data["accounts"]:
        balance = float(a["balances"].get("available") or a["balances"].get("current") or 0)
        accounts.append({"name": a["name"], "balance": balance})
        if a.get("type") == "depository":
            cash += balance
    return {"cash": cash, "accounts": accounts}


async def get_transactions(days: int = 90) -> list[dict]:
    """Sandbox bank transactions for the last `days` days, newest first.

    Each item: {"id", "date", "name", "amount", "category", "account"}; Plaid amounts are positive for money out.
    """
    end = date.today()
    start = end - timedelta(days=days)
    async with httpx.AsyncClient(timeout=30) as client:
        access_token = await _access_token(client)
        body = {
            "access_token": access_token,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "options": {"count": 500},
        }
        for attempt in range(6):  # a fresh sandbox item needs a moment before its transactions are ready
            try:
                data = await _post(client, "/transactions/get", body)
                break
            except PlaidError as e:
                if e.code != "PRODUCT_NOT_READY" or attempt == 5:
                    raise
                await asyncio.sleep(1.5)
    names = {a["account_id"]: a["name"] for a in data["accounts"]}
    txns = [
        {
            "id": t["transaction_id"],
            "date": t["date"],
            "name": t.get("merchant_name") or t["name"],
            "amount": float(t["amount"]),
            "category": (t.get("personal_finance_category") or {}).get("primary", ""),
            "account": names.get(t["account_id"], ""),
        }
        for t in data["transactions"]
    ]
    return sorted(txns, key=lambda t: t["date"], reverse=True)
