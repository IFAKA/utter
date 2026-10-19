"""JLCPCB parts library lookup (stock, basic/extended, price). Used to pick and re-verify BOM parts.

  python3 hardware/gen/jlc.py search "TPS7A2030"     # candidates
  python3 hardware/gen/jlc.py check C527440 C2913202  # verify exact codes
"""
import json
import sys
import urllib.request

API = "https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList"


def query(keyword: str, n: int = 10) -> list[dict]:
    body = json.dumps({"keyword": keyword, "currentPage": 1, "pageSize": n}).encode()
    req = urllib.request.Request(API, body, {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.load(r)
    out = []
    for c in (d.get("data") or {}).get("componentPageInfo", {}).get("list") or []:
        prices = c.get("componentPrices") or [{}]
        out.append({"lcsc": c.get("componentCode"), "mpn": c.get("componentModelEn"),
                    "pkg": c.get("componentSpecificationEn"), "type": c.get("componentLibraryType"),
                    "stock": c.get("stockCount"), "price": prices[0].get("productPrice"),
                    "preferred": bool(c.get("preferredComponentFlag")),  # preferred extended: no setup fee
                    "desc": (c.get("describe") or "")[:70]})
    return out


def check(code: str) -> dict | None:
    return next((c for c in query(code, 5) if c["lcsc"] == code), None)


if __name__ == "__main__":
    cmd, args = sys.argv[1], sys.argv[2:]
    for a in args:
        rows = query(a) if cmd == "search" else [check(a) or {"lcsc": a, "mpn": "NOT FOUND"}]
        for c in rows:
            print(f"{c['lcsc']:>10} {str(c.get('type')):6} stock={c.get('stock')!s:>7} ${c.get('price')!s:8} "
                  f"{c.get('mpn')!s:28} {c.get('pkg')!s:14} {c.get('desc', '')}")
        print()
