#!/usr/bin/env python3
"""Demo server: REST API + dashboard. Stdlib only.

    python3 server.py              # mock broker, http://localhost:8787
    BROKER=alpaca python3 server.py  # real Alpaca paper account

Routes
    GET  /                     dashboard
    GET  /api/portfolio        account + enriched positions
    GET  /api/analysis         full analytics (summary, concentration, flags)
    GET  /api/styles           all six style lenses
    GET  /api/styles/<id>      one lens
    GET  /api/orders           recent orders
    POST /api/orders           {"symbol","qty","side"} -> place a paper order
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import analysis
import broker as broker_mod
import styles

BROKER = broker_mod.get_broker()
HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("PORT", "8787"))


def snapshot():
    acct = BROKER.get_account()
    a = analysis.analyze(acct, BROKER.get_positions())
    a["account"] = acct
    a["broker"] = dict(name=BROKER.name, label=BROKER.label)
    return a


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("  %s\n" % (fmt % args))

    def _send(self, code, body, ctype="application/json"):
        if not isinstance(body, bytes):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, default=str), "application/json")

    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        try:
            if path == "/":
                with open(os.path.join(HERE, "static", "index.html"), "rb") as f:
                    return self._send(200, f.read(), "text/html; charset=utf-8")
            if path == "/api/portfolio":
                a = snapshot()
                return self._json(dict(broker=a["broker"], account=a["account"],
                                       positions=a["positions"],
                                       summary=a["summary"]))
            if path == "/api/analysis":
                return self._json(snapshot())
            if path == "/api/styles":
                return self._json(styles.evaluate(snapshot()))
            if path.startswith("/api/styles/"):
                sid = path.rsplit("/", 1)[-1]
                r = styles.evaluate(snapshot(), sid)
                if not r["styles"]:
                    return self._json(dict(error=f"unknown style '{sid}'"), 404)
                return self._json(r)
            if path == "/api/orders":
                return self._json(dict(orders=BROKER.get_orders()))
            return self._json(dict(error="not found", path=path), 404)
        except Exception as e:  # keep the demo alive on stage
            return self._json(dict(error=str(e), type=type(e).__name__), 500)

    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/")
        if path != "/api/orders":
            return self._json(dict(error="not found"), 404)
        try:
            n = int(self.headers.get("Content-Length") or 0)
            req = json.loads(self.rfile.read(n) or b"{}")
            order = BROKER.place_order(req["symbol"], req["qty"],
                                       req.get("side", "buy"))
            return self._json(dict(order=order, summary=snapshot()["summary"]))
        except KeyError as e:
            return self._json(dict(error=f"missing field {e}"), 400)
        except Exception as e:
            return self._json(dict(error=str(e)), 400)


if __name__ == "__main__":
    a = snapshot()
    print(f"\n  Broker : {BROKER.label}")
    print(f"  Account: {a['account']['account_number']}  "
          f"equity ${a['account']['equity']:,.2f}  "
          f"{a['summary']['position_count']} positions")
    print(f"  Flags  : {len(a['flags'])} observations\n")
    print(f"  ->  http://localhost:{PORT}\n")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
