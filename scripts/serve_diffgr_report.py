#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import threading
import webbrowser
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from diffgr.html_report import render_group_diff_html  # noqa: E402
from diffgr.viewer_core import load_json, validate_document  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve DiffGR HTML report with direct review save API.")
    parser.add_argument("--input", required=True, help="Input .diffgr.json path.")
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


def _normalize_reviews_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise RuntimeError("Request payload must be a JSON object.")
    candidate = payload.get("reviews", payload)
    if not isinstance(candidate, dict):
        raise RuntimeError("`reviews` must be a JSON object.")
    return candidate


def save_reviews_to_document(path: Path, reviews: dict[str, Any]) -> dict[str, Any]:
    doc = load_json(path)
    validate_document(doc)
    doc["reviews"] = reviews
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "savedTo": str(path),
        "reviewChunkCount": len(reviews),
        "savedAt": _iso_now(),
    }


@dataclass
class ServerState:
    source_path: Path
    group_selector: str
    report_title: str | None
    lock: threading.Lock

    def render_html(self) -> str:
        doc = load_json(self.source_path)
        validate_document(doc)
        return render_group_diff_html(
            doc,
            group_selector=self.group_selector,
            report_title=self.report_title,
            save_reviews_url="/api/reviews",
            save_reviews_label="Save to App",
        )

    def save_reviews(self, reviews: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            return save_reviews_to_document(self.source_path, reviews)


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
            if path != "/api/reviews":
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
                reviews = _normalize_reviews_payload(payload)
                result = state.save_reviews(reviews)
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

    if not source_path.exists():
        print(f"[error] File not found: {source_path}", file=sys.stderr)
        return 1

    try:
        doc = load_json(source_path)
        validate_document(doc)
    except Exception as error:  # noqa: BLE001
        print(f"[error] {error}", file=sys.stderr)
        return 1

    state = ServerState(
        source_path=source_path,
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
