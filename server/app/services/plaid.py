# Stub: swap for Plaid Sandbox over HTTP (/sandbox/public_token/create -> /item/public_token/exchange -> balances).
async def sandbox_balances() -> dict:
    return {"cash": 4200.0, "accounts": [{"name": "Plaid Checking", "balance": 4200.0}]}
