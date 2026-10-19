"""Minimal KiCad s-expression reader/writer and symbol-library access."""
import os
import re

KICAD = os.path.expanduser(os.environ.get("KICAD_APP", "~/Applications/KiCad/KiCad.app"))
SHARED = os.path.join(KICAD, "Contents/SharedSupport")

_tok = re.compile(r'\(|\)|"(?:[^"\\]|\\.)*"|[^\s()]+')


class Sym(str):
    """Unquoted atom (keywords, numbers)."""


def parse(text: str):
    stack, cur = [], []
    for m in _tok.finditer(text):
        t = m.group(0)
        if t == "(":
            stack.append(cur); cur = []
        elif t == ")":
            done = cur; cur = stack.pop(); cur.append(done)
        elif t.startswith('"'):
            cur.append(t[1:-1].replace('\\"', '"').replace("\\\\", "\\"))
        else:
            cur.append(Sym(t))
    return cur[0]


def dump(e, indent=0) -> str:
    if isinstance(e, list):
        simple = all(not isinstance(x, list) for x in e)
        if simple:
            return "(" + " ".join(dump(x) for x in e) + ")"
        pad = "\t" * (indent + 1)
        return "(" + " ".join(dump(x) for x in e if not isinstance(x, list)) + "".join(
            "\n" + pad + dump(x, indent + 1) for x in e if isinstance(x, list)) + ")"
    if isinstance(e, Sym):
        return str(e)
    if isinstance(e, bool):
        return "yes" if e else "no"
    if isinstance(e, (int, float)):
        return f"{e:g}" if isinstance(e, float) else str(e)
    return '"' + str(e).replace("\\", "\\\\").replace('"', '\\"') + '"'


def find(e, key):
    return [x for x in e if isinstance(x, list) and x and x[0] == key]


def first(e, key):
    r = find(e, key)
    return r[0] if r else None


_libs: dict = {}


def library(name: str):
    if name not in _libs:
        _libs[name] = parse(open(os.path.join(SHARED, "symbols", name + ".kicad_sym")).read())
    return _libs[name]


def symbol(lib_id: str):
    """Library symbol (with 'extends' resolved), renamed to its lib_id, as used in a schematic's lib_symbols."""
    lib, name = lib_id.split(":")
    syms = {s[1]: s for s in find(library(lib), "symbol")}
    s = syms[name]
    ext = first(s, "extends")
    if ext:
        base = [x for x in syms[ext[1]]]
        props = {p[1]: p for p in find(s, "property")}
        out = [base[0], lib_id]
        for x in base[2:]:
            if isinstance(x, list) and x[0] == "property" and x[1] in props:
                out.append(props.pop(x[1]))
            elif isinstance(x, list) and x[0] == "symbol":
                out.append([x[0], x[1].replace(ext[1], name, 1)] + x[2:])
            else:
                out.append(x)
        out.extend(props.values())
        return out
    return [s[0], lib_id] + s[2:]


def pins(sym) -> list[dict]:
    """[{number, name, x, y, angle, length}] in symbol coordinates (y up), unit 0/1 only."""
    out = []
    for sub in find(sym, "symbol"):
        m = re.search(r"_(\d+)_(\d+)$", sub[1])
        if m and m.group(1) not in ("0", "1"):
            continue
        for p in find(sub, "pin"):
            at, ln = first(p, "at"), first(p, "length")
            out.append({"number": first(p, "number")[1], "name": first(p, "name")[1],
                        "x": float(at[1]), "y": float(at[2]), "angle": float(at[3]) if len(at) > 3 else 0.0,
                        "length": float(ln[1]), "type": p[1]})
    return out
