#!/usr/bin/env python3
"""Turn a flow diagram file into a plain graph (nodes + labelled edges) for chatbot flow design.

    python extract_diagram.py <file> [--json graph.json]

Supported: Mermaid flowcharts (.mmd, .mermaid, or a ```mermaid block in .md), draw.io / diagrams.net
(.drawio, .xml, including the compressed form), BPMN 2.0 (.bpmn, .xml). Images and PDFs are not parsed:
look at those directly and write the graph by hand in the same shape.

Output is a markdown summary on stdout (every node with its shape and outgoing edges) and, with --json,
{"nodes": [{"id", "label", "shape"}], "edges": [{"from", "to", "label"}]}.
"""
import argparse
import base64
import html
import json
import re
import sys
import urllib.parse
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path


def clean(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"<br\s*/?>|</p>|</div>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip().strip('"')


# ---------------------------------------------------------------- mermaid

# Order matters: longest delimiters first.
SHAPES = [
    (r"\(\[(.+?)\]\)", "terminator"),
    (r"\(\((.+?)\)\)", "circle"),
    (r"\[\[(.+?)\]\]", "subroutine"),
    (r"\[\((.+?)\)\]", "database"),
    (r"\{\{(.+?)\}\}", "hexagon"),
    (r"\[/(.+?)/\]", "input"),
    (r"\[\\(.+?)\\\]", "input"),
    (r"\[/(.+?)\\\]", "manual"),
    (r"\{(.+?)\}", "decision"),
    (r"\((.+?)\)", "rounded"),
    (r">(.+?)\]", "flag"),
    (r"\[(.+?)\]", "process"),
]
NODE = re.compile(r"^\s*([A-Za-z_][\w-]*)\s*(.*)$", re.S)
EDGE = re.compile(r"(<?(?:-{2,}|={2,}|-\.+-|-\.-)>?|--[xo])(?:\|([^|]*)\|)?")


def parse_mermaid(text: str):
    block = re.search(r"```mermaid\s*(.*?)```", text, re.S)
    if block:
        text = block.group(1)
    nodes, edges = {}, []

    def declare(token: str):
        m = NODE.match(token)
        if not m:
            return None
        nid, rest = m.group(1), m.group(2).strip()
        shape, label = None, None
        for pattern, name in SHAPES:
            sm = re.fullmatch(pattern, rest, re.S)
            if sm:
                shape, label = name, clean(sm.group(1))
                break
        if nid not in nodes:
            nodes[nid] = {"id": nid, "label": label or nid, "shape": shape or "process"}
        elif label:
            nodes[nid].update(label=label, shape=shape)
        return nid

    for raw in re.split(r"[\n;]", text):
        line = raw.strip()
        if not line or line.startswith(("%%", "flowchart", "graph", "subgraph", "end", "classDef", "class ", "style ", "linkStyle", "click ", "direction")):
            continue
        # "A -- text --> B" form: turn the text into |text|
        line = re.sub(r"--\s+([^->|]+?)\s+-->", r"-->|\1|", line)
        line = re.sub(r"==\s+([^=>|]+?)\s+==>", r"==>|\1|", line)
        pieces, labels, pos = [], [], 0
        for m in EDGE.finditer(line):
            if m.start() < pos:
                continue
            pieces.append(line[pos:m.start()])
            labels.append(clean(m.group(2) or ""))
            pos = m.end()
        pieces.append(line[pos:])
        ids = []
        for piece in pieces:
            # "A & B" fan-in/out
            group = [declare(p) for p in re.split(r"\s&\s", piece.strip()) if p.strip()]
            ids.append([g for g in group if g])
        for i, label in enumerate(labels):
            if i + 1 < len(ids):
                for a in ids[i]:
                    for b in ids[i + 1]:
                        edges.append({"from": a, "to": b, "label": label})
    return list(nodes.values()), edges


# ---------------------------------------------------------------- draw.io

def drawio_cells(root: ET.Element):
    if root.tag == "mxfile":
        out = []
        for diagram in root.iter("diagram"):
            inner = diagram.find("mxGraphModel")
            if inner is not None:
                out.append(inner)
                continue
            payload = (diagram.text or "").strip()
            if payload:
                try:
                    raw = zlib.decompress(base64.b64decode(payload), -15).decode("utf-8")
                    out.append(ET.fromstring(urllib.parse.unquote(raw)))
                except Exception:  # noqa: BLE001 - report and carry on with other pages
                    print("warning: could not decode a compressed diagram page", file=sys.stderr)
        return out
    return [root]


def parse_drawio(root: ET.Element):
    nodes, edges = {}, []
    for model in drawio_cells(root):
        cells = list(model.iter("mxCell"))
        # draw.io puts custom labels on <object label=".."> wrappers around the cell
        wrappers = {o.get("id"): o for o in model.iter("object")}
        for cell in cells:
            cid = cell.get("id")
            wrap = wrappers.get(cid)
            value = clean((wrap.get("label") if wrap is not None else cell.get("value")) or "")
            style = cell.get("style") or ""
            if cell.get("edge") == "1":
                continue
            if cell.get("vertex") == "1":
                shape = ("decision" if "rhombus" in style else "terminator" if "ellipse" in style or "terminator" in style
                         else "input" if "parallelogram" in style else "subroutine" if "process" in style
                         else "database" if "cylinder" in style else "document" if "document" in style else "process")
                nodes[cid] = {"id": cid, "label": value or cid, "shape": shape}
        for cell in cells:
            if cell.get("edge") == "1" and cell.get("source") and cell.get("target"):
                wrap = wrappers.get(cell.get("id"))
                label = clean((wrap.get("label") if wrap is not None else cell.get("value")) or "")
                edges.append({"from": cell.get("source"), "to": cell.get("target"), "label": label})
        # edge labels are sometimes separate text cells whose parent is the edge
        by_id = {c.get("id"): c for c in cells}
        for cell in cells:
            parent = by_id.get(cell.get("parent"))
            if parent is not None and parent.get("edge") == "1" and cell.get("vertex") == "1" and cell.get("id") in nodes:
                label = nodes.pop(cell.get("id"))["label"]
                for e in edges:
                    if e["from"] == parent.get("source") and e["to"] == parent.get("target") and not e["label"]:
                        e["label"] = label
    edges = [e for e in edges if e["from"] in nodes and e["to"] in nodes]
    return list(nodes.values()), edges


# ---------------------------------------------------------------- bpmn

def parse_bpmn(root: ET.Element):
    def local(tag):
        return tag.split("}")[-1]

    kinds = {"startEvent": "terminator", "endEvent": "terminator", "task": "process", "userTask": "input",
             "serviceTask": "process", "scriptTask": "process", "sendTask": "process", "receiveTask": "input",
             "exclusiveGateway": "decision", "inclusiveGateway": "decision", "parallelGateway": "decision",
             "callActivity": "subroutine", "subProcess": "subroutine", "manualTask": "manual"}
    nodes, edges = {}, []
    for el in root.iter():
        name = local(el.tag)
        if name in kinds:
            nodes[el.get("id")] = {"id": el.get("id"), "label": clean(el.get("name") or el.get("id")), "shape": kinds[name],
                                   "bpmn": name}
        elif name == "sequenceFlow":
            edges.append({"from": el.get("sourceRef"), "to": el.get("targetRef"), "label": clean(el.get("name") or "")})
    return list(nodes.values()), edges


# ---------------------------------------------------------------- main

def load(path: Path):
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    suffix = path.suffix.lower()
    if suffix in (".mmd", ".mermaid") or (suffix == ".md" and "```mermaid" in text) or text.lstrip().startswith(("flowchart", "graph ")):
        return parse_mermaid(text)
    try:
        root = ET.fromstring(text)
    except ET.ParseError as ex:
        raise SystemExit(f"cannot read {path.name} as Mermaid, draw.io or BPMN: {ex}")
    tag = root.tag.split("}")[-1]
    if tag == "definitions" or suffix == ".bpmn":
        return parse_bpmn(root)
    return parse_drawio(root)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file")
    parser.add_argument("--json")
    args = parser.parse_args()
    path = Path(args.file)
    if path.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".vsdx", ".fig"):
        print(f"{path.suffix} is not parsed. View the file directly and write the graph by hand.", file=sys.stderr)
        return 2
    nodes, edges = load(path)
    if not nodes:
        print("no nodes found", file=sys.stderr)
        return 1
    if args.json:
        Path(args.json).write_text(json.dumps({"nodes": nodes, "edges": edges}, indent=2), encoding="utf-8")
    ids = {n["id"] for n in nodes}
    incoming = {e["to"] for e in edges}
    out = [f"# {path.name}: {len(nodes)} nodes, {len(edges)} edges", ""]
    starts = [n["id"] for n in nodes if n["id"] not in incoming]
    out.append(f"Entry candidates (no incoming edge): {starts or 'none (cycle?)'}")
    dangling = [e for e in edges if e["from"] not in ids or e["to"] not in ids]
    if dangling:
        out.append(f"Edges pointing at unknown nodes: {len(dangling)}")
    out.append("")
    for n in nodes:
        outs = [e for e in edges if e["from"] == n["id"]]
        out.append(f"- [{n['shape']}] {n['id']}: {n['label']}")
        for e in outs:
            label = f" ({e['label']})" if e["label"] else ""
            target = next((x["label"] for x in nodes if x["id"] == e["to"]), e["to"])
            out.append(f"    -> {e['to']}{label}: {target}")
        if not outs:
            out.append("    (end)")
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
