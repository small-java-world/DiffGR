from __future__ import annotations

from html import escape
from typing import Any


def _resolve_group(doc: dict[str, Any], selector: str | None) -> tuple[str | None, str]:
    groups = [group for group in (doc.get("groups") or []) if isinstance(group, dict)]
    by_id = {str(group.get("id", "")): group for group in groups}

    if not selector or selector.lower() == "all":
        return None, "All Groups"
    if selector.lower() in {"unassigned", "__unassigned__"}:
        return "__unassigned__", "Unassigned"

    if selector in by_id:
        group_name = str(by_id[selector].get("name", selector))
        return selector, group_name

    matched = [group for group in groups if str(group.get("name", "")) == selector]
    if len(matched) == 1:
        group = matched[0]
        group_id = str(group.get("id", ""))
        group_name = str(group.get("name", group_id))
        return group_id, group_name
    if len(matched) > 1:
        ids = ", ".join(str(group.get("id", "")) for group in matched)
        raise RuntimeError(f"Group name is ambiguous: {selector} (matched ids: {ids})")

    raise RuntimeError(f"Group not found: {selector}")


def _collect_chunks_for_group(doc: dict[str, Any], group_id: str | None) -> list[dict[str, Any]]:
    chunks = [chunk for chunk in (doc.get("chunks") or []) if isinstance(chunk, dict)]
    chunk_map = {str(chunk.get("id", "")): chunk for chunk in chunks}
    assignments = doc.get("assignments") or {}

    if group_id is None:
        selected = list(chunk_map.values())
    elif group_id == "__unassigned__":
        assigned_ids: set[str] = set()
        if isinstance(assignments, dict):
            for values in assignments.values():
                if isinstance(values, list):
                    assigned_ids.update(str(value) for value in values)
        selected = [chunk for chunk_id, chunk in chunk_map.items() if chunk_id not in assigned_ids]
    else:
        assigned_ids = assignments.get(group_id, [])
        if not isinstance(assigned_ids, list):
            assigned_ids = []
        selected = [chunk_map[cid] for cid in assigned_ids if cid in chunk_map]

    return sorted(
        selected,
        key=lambda chunk: (
            str(chunk.get("filePath", "")),
            int((chunk.get("old") or {}).get("start", 0)),
            str(chunk.get("id", "")),
        ),
    )


def _line_kind_stats(chunks: list[dict[str, Any]]) -> dict[str, int]:
    stats = {"add": 0, "delete": 0, "context": 0}
    for chunk in chunks:
        for line in chunk.get("lines") or []:
            kind = str(line.get("kind", ""))
            if kind in stats:
                stats[kind] += 1
    return stats


def _anchor_id_from_file(file_path: str, index: int) -> str:
    safe = "".join(ch if ch.isalnum() else "-" for ch in file_path).strip("-").lower()
    safe = "-".join(part for part in safe.split("-") if part)
    if not safe:
        safe = "file"
    return f"file-{index}-{safe}"


def _render_diff_rows(chunk: dict[str, Any]) -> str:
    rows: list[str] = []
    for line in chunk.get("lines") or []:
        kind = str(line.get("kind", "context"))
        old_line = "" if line.get("oldLine") is None else str(line.get("oldLine"))
        new_line = "" if line.get("newLine") is None else str(line.get("newLine"))
        text = str(line.get("text", ""))

        if kind == "add":
            old_text = ""
            new_text = text
            row_class = "add"
        elif kind == "delete":
            old_text = text
            new_text = ""
            row_class = "delete"
        elif kind == "context":
            old_text = text
            new_text = text
            row_class = "context"
        else:
            old_text = text
            new_text = text
            row_class = "meta"

        rows.append(
            "<tr class='row-{row_class}'>"
            "<td class='num'>{old_line}</td>"
            "<td class='code old'>{old_text}</td>"
            "<td class='num'>{new_line}</td>"
            "<td class='code new'>{new_text}</td>"
            "</tr>".format(
                row_class=escape(row_class),
                old_line=escape(old_line),
                old_text=escape(old_text),
                new_line=escape(new_line),
                new_text=escape(new_text),
            )
        )
    return "\n".join(rows)


def render_group_diff_html(
    doc: dict[str, Any],
    *,
    group_selector: str | None,
    report_title: str | None = None,
) -> str:
    group_id, group_name = _resolve_group(doc, group_selector)
    chunks = _collect_chunks_for_group(doc, group_id)
    stats = _line_kind_stats(chunks)

    chunks_by_file: dict[str, list[dict[str, Any]]] = {}
    for chunk in chunks:
        file_path = str(chunk.get("filePath", "(unknown)"))
        chunks_by_file.setdefault(file_path, []).append(chunk)

    page_title = report_title or f"DiffGR Group Report - {group_name}"
    source = doc.get("meta", {}).get("source", {}) if isinstance(doc.get("meta"), dict) else {}
    base = str(source.get("base", "-"))
    head = str(source.get("head", "-"))

    file_nav: list[str] = []
    file_sections: list[str] = []
    for index, (file_path, file_chunks) in enumerate(chunks_by_file.items(), start=1):
        anchor = _anchor_id_from_file(file_path, index)
        add_count = 0
        del_count = 0
        for chunk in file_chunks:
            for line in chunk.get("lines") or []:
                kind = str(line.get("kind", ""))
                if kind == "add":
                    add_count += 1
                elif kind == "delete":
                    del_count += 1

        file_nav.append(
            "<li><a href='#{anchor}'>{file_path}</a> "
            "<span class='file-stats'>chunks {chunks} / +{adds} -{deletes}</span></li>".format(
                anchor=escape(anchor),
                file_path=escape(file_path),
                chunks=len(file_chunks),
                adds=add_count,
                deletes=del_count,
            )
        )

        chunk_blocks: list[str] = []
        for chunk in file_chunks:
            chunk_id = str(chunk.get("id", ""))
            old = chunk.get("old") or {}
            new = chunk.get("new") or {}
            header = str(chunk.get("header", ""))
            chunk_blocks.append(
                "<section class='chunk'>"
                "<div class='chunk-header'>"
                "<span class='chunk-id'>{chunk_id}</span>"
                "<span class='chunk-range'>old {old_start},{old_count} -> new {new_start},{new_count}</span>"
                "<span class='chunk-title'>{header}</span>"
                "</div>"
                "<table class='diff-table'>"
                "<thead><tr><th>Old#</th><th>Old</th><th>New#</th><th>New</th></tr></thead>"
                "<tbody>{rows}</tbody>"
                "</table>"
                "</section>".format(
                    chunk_id=escape(chunk_id),
                    old_start=escape(str(old.get("start", "?"))),
                    old_count=escape(str(old.get("count", "?"))),
                    new_start=escape(str(new.get("start", "?"))),
                    new_count=escape(str(new.get("count", "?"))),
                    header=escape(header),
                    rows=_render_diff_rows(chunk),
                )
            )

        file_sections.append(
            "<section id='{anchor}' class='file-section'>"
            "<h2>{file_path}</h2>"
            "<p class='file-summary'>chunks {chunks} / +{adds} -{deletes}</p>"
            "{chunk_blocks}"
            "</section>".format(
                anchor=escape(anchor),
                file_path=escape(file_path),
                chunks=len(file_chunks),
                adds=add_count,
                deletes=del_count,
                chunk_blocks="\n".join(chunk_blocks),
            )
        )

    if not file_sections:
        file_sections.append("<section class='file-section'><p>No chunks found for selected group.</p></section>")

    return """<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{page_title}</title>
  <style>
    :root {{
      --bg: #0b0d11;
      --panel: #121722;
      --panel2: #0f1420;
      --line: #243041;
      --text: #e8edf5;
      --muted: #9aabc1;
      --add-bg: #0f2a1f;
      --add-line: #1f6e48;
      --del-bg: #34171a;
      --del-line: #7d2c35;
      --ctx-bg: #121722;
      --meta-bg: #1b2232;
      --accent: #5ea3ff;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: "Segoe UI", "Yu Gothic UI", "Meiryo", sans-serif;
    }}
    a {{ color: var(--accent); text-decoration: none; }}
    .layout {{
      display: grid;
      grid-template-columns: 320px 1fr;
      min-height: 100vh;
    }}
    .sidebar {{
      position: sticky;
      top: 0;
      height: 100vh;
      overflow: auto;
      background: var(--panel);
      border-right: 1px solid var(--line);
      padding: 16px;
    }}
    .main {{
      padding: 18px;
      overflow: auto;
    }}
    h1 {{
      margin: 0 0 10px;
      font-size: 20px;
    }}
    h2 {{
      margin: 0 0 8px;
      font-size: 18px;
      color: #c8d8ef;
    }}
    .meta {{
      margin: 0 0 10px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.5;
    }}
    .stats {{
      margin: 0 0 14px;
      color: var(--muted);
      font-size: 13px;
    }}
    .file-list {{
      margin: 0;
      padding-left: 18px;
      line-height: 1.6;
      font-size: 13px;
    }}
    .file-stats {{ color: var(--muted); }}
    .file-section {{
      margin-bottom: 28px;
      border: 1px solid var(--line);
      border-radius: 10px;
      background: var(--panel);
      padding: 14px;
    }}
    .file-summary {{
      margin: 0 0 10px;
      color: var(--muted);
      font-size: 13px;
    }}
    .chunk {{
      border: 1px solid var(--line);
      border-radius: 8px;
      margin-bottom: 14px;
      overflow: hidden;
      background: var(--panel2);
    }}
    .chunk-header {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      padding: 8px 10px;
      border-bottom: 1px solid var(--line);
      font-size: 12px;
      background: #1a2233;
    }}
    .chunk-id {{ color: #9bc0ff; font-weight: 600; }}
    .chunk-range {{ color: #b6c5dc; }}
    .chunk-title {{ color: #d2def0; }}
    .diff-table {{
      width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
      font-family: Consolas, "Courier New", monospace;
      font-size: 12px;
    }}
    .diff-table th {{
      text-align: left;
      padding: 6px 8px;
      border-bottom: 1px solid var(--line);
      color: #c5d4eb;
      background: #151c2b;
      position: sticky;
      top: 0;
      z-index: 1;
    }}
    .diff-table td {{
      border-bottom: 1px solid #1a2232;
      vertical-align: top;
      white-space: pre-wrap;
      word-break: break-word;
    }}
    .diff-table td.num {{
      width: 68px;
      text-align: right;
      padding: 4px 8px;
      color: var(--muted);
      background: #101624;
    }}
    .diff-table td.code {{
      padding: 4px 8px;
    }}
    .row-context td.code {{ background: var(--ctx-bg); }}
    .row-add td.code {{
      background: var(--add-bg);
      border-left: 2px solid var(--add-line);
    }}
    .row-delete td.code {{
      background: var(--del-bg);
      border-left: 2px solid var(--del-line);
    }}
    .row-meta td.code {{ background: var(--meta-bg); color: #c7d2e8; }}
    @media (max-width: 1024px) {{
      .layout {{ grid-template-columns: 1fr; }}
      .sidebar {{
        position: static;
        height: auto;
        border-right: none;
        border-bottom: 1px solid var(--line);
      }}
    }}
  </style>
</head>
<body>
  <div class="layout">
    <aside class="sidebar">
      <h1>{title}</h1>
      <p class="meta">
        Group: <b>{group_name}</b><br>
        Selector: {selector}<br>
        Source: {base} -> {head}
      </p>
      <p class="stats">
        chunks {chunk_count} / files {file_count}<br>
        +{adds}  -{deletes}  context {contexts}
      </p>
      <ol class="file-list">
        {file_nav}
      </ol>
    </aside>
    <main class="main">
      {file_sections}
    </main>
  </div>
</body>
</html>
""".format(
        page_title=escape(page_title),
        title=escape(page_title),
        group_name=escape(group_name),
        selector=escape(group_selector or "all"),
        base=escape(base),
        head=escape(head),
        chunk_count=len(chunks),
        file_count=len(chunks_by_file),
        adds=stats["add"],
        deletes=stats["delete"],
        contexts=stats["context"],
        file_nav="\n".join(file_nav) if file_nav else "<li>(no files)</li>",
        file_sections="\n".join(file_sections),
    )
