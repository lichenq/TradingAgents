#!/usr/bin/env python3
"""Lightweight zero-dependency web server for dynamically rendering TradingAgents debate rooms.

Supports opening:
  http://localhost:8000/?ticker=301308&date=2026-05-27

Debate content is loaded from SQLite via debate_canvas.load_debate_payload (not from .md files).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict

current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.storage import init_db
from scripts.debate_canvas import HTML_TEMPLATE, load_debate_payload

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("debate_server")


def resolve_results_root() -> Path:
    env = (os.environ.get("TRADINGAGENTS_RESULTS_DIR") or "").strip()
    if env:
        return Path(env).expanduser().resolve()
    cwd_results = Path.cwd() / "results"
    if cwd_results.is_dir():
        return cwd_results.resolve()
    return Path(DEFAULT_CONFIG["results_dir"]).expanduser().resolve()


class DebateRoomHTTPHandler(BaseHTTPRequestHandler):
    """Serve debate SPA shell and /api/report backed by SQLite."""

    results_dir: Path

    def do_GET(self) -> None:
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        query_params = urllib.parse.parse_qs(parsed_url.query)

        if path == "/api/report":
            self.handle_api_report(query_params)
            return
        if path in ("/", "/index.html"):
            self.handle_web_root()
            return
        self.send_error_response(404, "Page Not Found")

    def handle_web_root(self) -> None:
        try:
            html_content = HTML_TEMPLATE.format(
                title="TradingAgents 智能体投研辩论",
                ticker="UNKNOWN",
                date="",
                rating="HOLD",
                messages_json="[]",
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(html_content.encode("utf-8"))
        except Exception as e:
            logger.error("Failed to serve index page: %s", e, exc_info=True)
            self.send_error_response(500, f"Internal Server Error: {e}")

    def handle_api_report(self, params: Dict[str, list[str]]) -> None:
        ticker = params.get("ticker", [""])[0].strip()
        date = params.get("date", [""])[0].strip()
        logger.info("Querying debate from SQLite for %s on %s", ticker, date)

        payload = load_debate_payload(self.results_dir, ticker, date)
        if not payload.get("ok"):
            status = 400 if "invalid" in payload.get("error", "").lower() else 404
            self.send_json_response(payload, status_code=status)
            return
        self.send_json_response(payload)

    def send_json_response(self, data: Dict[str, Any], status_code: int = 200) -> None:
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def send_error_response(self, status_code: int, message: str) -> None:
        self.send_response(status_code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(message.encode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve dynamic debate canvas (SQLite-backed)")
    parser.add_argument("--port", type=int, default=8000, help="Local server port (default: 8000)")
    parser.add_argument("--host", default="localhost", help="Local server host (default: localhost)")
    parser.add_argument(
        "--results-dir",
        default="",
        help="Results directory containing trading_agents.db (default: TRADINGAGENTS_RESULTS_DIR or ./results)",
    )
    args = parser.parse_args()

    results_dir = Path(args.results_dir).expanduser().resolve() if args.results_dir else resolve_results_root()
    init_db(results_dir)

    handler = type(
        "ConfiguredDebateHandler",
        (DebateRoomHTTPHandler,),
        {"results_dir": results_dir},
    )

    server_address = (args.host, args.port)
    httpd = HTTPServer(server_address, handler)

    logger.info("=" * 60)
    logger.info("SQLite database: %s", results_dir / "trading_agents.db")
    logger.info("Debate server: http://%s:%s/?ticker=601138&date=2026-05-27", args.host, args.port)
    logger.info("=" * 60)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("\nServer stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
