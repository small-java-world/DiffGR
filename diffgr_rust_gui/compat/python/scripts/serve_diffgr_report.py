#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import threading
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from diffgr.html_report import render_group_diff_html  # noqa: E402
from diffgr.impact_merge import build_impact_preview_report, preview_impact_merge  # noqa: E402
from diffgr.review_state import (  # noqa: E402
    apply_review_state,
    build_review_state_diff_report,
    empty_review_state,
    extract_review_state,
    load_diffgr_document,
    load_review_state,
    normalize_review_state_payload,
    review_state_fingerprint,
    save_review_state,
)
from diffgr.viewer_core import load_json, print_error, validate_document, write_json  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve DiffGR HTML report with direct review save API.")
    parser.add_argument("--input", required=True, help="Input .diffgr.json path.")
    parser.add_argument("--state", help="Optional external state JSON path. If set, render/save uses this state file.")
    parser.add_argument("--impact-old", help="Optional old .diffgr.json path for Impact Preview.")
    parser.add_argument("--impact-state", help="Optional review state JSON path for Impact Preview.")
    parser.add_argument(
        "--group",
        default="all",
        help="Group selector. Use group id or exact group name. Default: all.",
    )
    parser.add_argument("--title", help="Optional custom report title.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind. Default: 127.0.0.1.")
    parser.add_argument("--port", type=int, default=8765, help="Port to bind. Default: 8765.")
    parser.add_argument("--open", action="store_true", help="Open in default browser.")
    return parser.parse_args(argv)


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _empty_review_state() -> dict[str, dict[str, Any]]:
    return empty_review_state()


def _normalize_state_payload(payload: Any) -> dict[str, dict[str, Any]]:
    return normalize_review_state_payload(payload)


def save_review_state_to_document(path: Path, state: dict[str, Any]) -> dict[str, Any]:
    doc = load_diffgr_document(path)
    review_state = normalize_review_state_payload(state)
    out = apply_review_state(doc, review_state)
    write_json(path, out)
    return {
        "savedTo": str(path),
        "savedAt": _iso_now(),
        "reviewChunkCount": len(review_state["reviews"]),
    }


def save_review_state_to_file(path: Path, state: dict[str, Any]) -> dict[str, Any]:
    review_state = save_review_state(path, state)
    return {
        "savedTo": str(path),
        "savedAt": _iso_now(),
        "reviewChunkCount": len(review_state["reviews"]),
    }


@dataclass
class ServerState:
    source_path: Path
    state_path: Path | None = None
    impact_old_path: Path | None = None
    impact_state_path: Path | None = None
    group_selector: str = "all"
    report_title: str | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)

    def render_html(self) -> str:
        if (
            self.state_path is not None
            and self.impact_state_path is not None
            and self.state_path.resolve() != self.impact_state_path.resolve()
        ):
            raise RuntimeError("--state and --impact-state must point to the same state file.")
        doc = load_json(self.source_path)
        validate_document(doc)
        impact_preview_payload = None
        impact_preview_report = None
        impact_preview_label = None
        impact_state_fingerprint = None
        if self.impact_old_path is not None and self.impact_state_path is not None:
            old_doc = load_json(self.impact_old_path)
            validate_document(old_doc)
            impact_state = load_review_state(self.impact_state_path)
            impact_preview_payload = preview_impact_merge(
                old_doc=old_doc,
                new_doc=doc,
                state=impact_state,
            )
            impact_preview_label = (
                f"{self.impact_old_path.name} -> {self.source_path.name} using {self.impact_state_path.name}"
            )
            impact_preview_report = build_impact_preview_report(
                impact_preview_payload,
                old_label=self.impact_old_path.name,
                new_label=self.source_path.name,
                state_label=self.impact_state_path.name,
            )
            impact_state_fingerprint = review_state_fingerprint(impact_state)
        state_diff_report = None
        if self.state_path is not None and self.state_path.exists():
            imported_state = load_review_state(self.state_path)
            base_state = extract_review_state(doc)
            doc = apply_review_state(doc, imported_state)
            state_diff_report = build_review_state_diff_report(
                base_state,
                imported_state,
                source_label=str(self.state_path.name),
            )
        return render_group_diff_html(
            doc,
            group_selector=self.group_selector,
            report_title=self.report_title,
            save_state_url="/api/state",
            save_state_label="Save State",
            state_source_label=str(self.state_path.name) if self.state_path is not None else None,
            state_diff_report=state_diff_report,
            impact_preview_payload=impact_preview_payload,
            impact_preview_report=impact_preview_report,
            impact_preview_label=impact_preview_label,
            impact_state_label=str(self.impact_state_path.name) if self.impact_state_path is not None else None,
            impact_state_fingerprint=impact_state_fingerprint,
        )

    def save_state(self, state: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            if self.state_path is not None:
                return save_review_state_to_file(self.state_path, state)
            return save_review_state_to_document(self.source_path, state)


def _handler_factory(state: ServerState) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "DiffgrReviewServer/1.0"

        def _send_common_headers(self) -> None:
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

        def _write_json(self, status: int, payload: dict[str, Any]) -> None:
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self._send_common_headers()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _write_html(self, html: str) -> None:
            raw = html.encode("utf-8")
            self.send_response(200)
            self._send_common_headers()
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(204)
            self._send_common_headers()
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path in {"/", "/index.html"}:
                try:
                    self._write_html(state.render_html())
                except Exception as error:  # noqa: BLE001
                    self._write_json(500, {"ok": False, "error": str(error)})
                return
            if path == "/api/health":
                self._write_json(
                    200,
                    {
                        "ok": True,
                        "sourcePath": str(state.source_path),
                        "group": state.group_selector,
                        "time": _iso_now(),
                    },
                )
                return
            self._write_json(404, {"ok": False, "error": f"Not found: {path}"})

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path != "/api/state":
                self._write_json(404, {"ok": False, "error": f"Not found: {path}"})
                return
            try:
                length_raw = self.headers.get("Content-Length", "0")
                length = int(length_raw)
            except ValueError:
                self._write_json(400, {"ok": False, "error": "Invalid Content-Length header."})
                return
            if length <= 0:
                self._write_json(400, {"ok": False, "error": "Request body is required."})
                return
            if length > 20 * 1024 * 1024:
                self._write_json(413, {"ok": False, "error": "Request body too large."})
                return
            raw = self.rfile.read(length)
            try:
                payload = json.loads(raw.decode("utf-8"))
                review_state = _normalize_state_payload(payload)
                result = state.save_state(review_state)
            except Exception as error:  # noqa: BLE001
                self._write_json(400, {"ok": False, "error": str(error)})
                return
            self._write_json(200, {"ok": True, **result})

        def log_message(self, fmt: str, *args: Any) -> None:
            message = fmt % args
            print(f"[http] {self.address_string()} {message}")

    return Handler


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    source_path = Path(args.input)
    if not source_path.is_absolute():
        source_path = ROOT / source_path
    source_path = source_path.resolve()
    state_path = Path(args.state) if args.state else None
    if state_path is not None and not state_path.is_absolute():
        state_path = ROOT / state_path
    if state_path is not None:
        state_path = state_path.resolve()
    impact_old_path = Path(args.impact_old) if args.impact_old else None
    if impact_old_path is not None and not impact_old_path.is_absolute():
        impact_old_path = ROOT / impact_old_path
    if impact_old_path is not None:
        impact_old_path = impact_old_path.resolve()
    impact_state_path = Path(args.impact_state) if args.impact_state else None
    if impact_state_path is not None and not impact_state_path.is_absolute():
        impact_state_path = ROOT / impact_state_path
    if impact_state_path is not None:
        impact_state_path = impact_state_path.resolve()

    if not source_path.exists():
        print(f"[error] File not found: {source_path}", file=sys.stderr)
        return 1
    if bool(impact_old_path) != bool(impact_state_path):
        print("[error] --impact-old and --impact-state must be provided together.", file=sys.stderr)
        return 1
    if state_path is not None and impact_state_path is not None and state_path.resolve() != impact_state_path.resolve():
        print("[error] --state and --impact-state must point to the same state file.", file=sys.stderr)
        return 1

    try:
        doc = load_json(source_path)
        validate_document(doc)
        if impact_old_path is not None:
            old_doc = load_json(impact_old_path)
            validate_document(old_doc)
            load_review_state(impact_state_path)  # type: ignore[arg-type]
    except Exception as error:  # noqa: BLE001
        print_error(error)
        return 1

    state = ServerState(
        source_path=source_path,
        state_path=state_path,
        impact_old_path=impact_old_path,
        impact_state_path=impact_state_path,
        group_selector=args.group,
        report_title=args.title,
        lock=threading.Lock(),
    )
    handler = _handler_factory(state)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    base_url = f"http://{args.host}:{args.port}/"

    print(f"Serving: {base_url}")
    print(f"Source : {source_path}")
    print(f"Group  : {args.group}")
    if args.open:
        webbrowser.open(base_url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
