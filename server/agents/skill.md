# Council tools

Every worker is given these tools and nothing else. Call them before you decide; a verdict that cites
nothing the tools returned is not allowed. Never invent a number, price, quote or URL: if a tool does not
return it, you do not have it.

## portfolio_lookup

Holdings of the client you are advising, from the portfolio snapshot (`data/portfolio.json`) merged with the
holdings they submitted. Per position: ticker, name, sector, shares, cost basis, current price, weight %,
P&L %, beta, dividend yield, 52-week high/low. Also returns the account summary (cash, invested %, portfolio
beta, winners/losers).

- `ticker` (optional): one symbol. Omit it for the whole portfolio.

## persona_profile

The client's own profile (`data/PERSONA.md`, or the `persona.md` they uploaded): age, goals, horizon, risk
tolerance, where their money is held. Advice that ignores it is wrong advice.

- no arguments.

## specialist_row

The specialist sheet row (`data/specialist.csv`) for a council member: style, philosophy, what they would
flag. Use it to check your own lens, or to see what another member will say before you dissent.

- `persona` (optional): member name, e.g. "Michael Burry". Omit it for your own row.

## web_search

Live web search through Anchor. Only present when `ANCHOR_API_KEY` is set; when it is absent the tool is
simply not offered, and you must reason from the portfolio, profile and specialist sheet alone and say so.
Every result you use must be cited in `sources`, with the URL and a quote the page actually contained.

- `query`: what to look up (ticker + topic works best).
