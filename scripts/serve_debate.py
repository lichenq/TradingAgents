#!/usr/bin/env python3
"""Lightweight zero-dependency web server for dynamically rendering TradingAgents debate rooms.

Supports opening:
  http://localhost:8000/?ticker=301308&date=2026-05-27
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
from typing import Any, Dict, Optional

# Adjust sys.path to find tradingagents and scripts
current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.storage import query_report, init_db
from scripts.generate_live_html import HTML_TEMPLATE, parse_markdown_debate, extract_meta

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("debate_server")


def find_report_on_filesystem(results_dir: Path, ticker: str, date: str) -> Optional[str]:
    """Fallback search in filesystem results directory if SQLite record is missing."""
    clean_ticker = ticker.strip().upper()
    # Normalize ticker (e.g. SZ301308 -> 301308)
    numeric_ticker = "".join(ch for ch in clean_ticker if ch.isdigit())
    if not numeric_ticker:
        numeric_ticker = clean_ticker
        
    date_str = date.strip()
    
    # Try searching for directory matching pattern *numeric_ticker-date_str
    patterns = [
        f"*-{numeric_ticker}-{date_str}",
        f"*-{clean_ticker}-{date_str}",
        f"{numeric_ticker}-{numeric_ticker}-{date_str}"
    ]
    
    for pattern in patterns:
        for p in results_dir.glob(pattern):
            report_file = p / "complete_report.md"
            if report_file.is_file():
                logger.info(f"Found report complete_report.md via filesystem fallback: {report_file}")
                return report_file.read_text(encoding="utf-8")
                
    return None


class DebateRoomHTTPHandler(BaseHTTPRequestHandler):
    """Custom HTTP request handler to serve the dynamic debate canvas and report API."""

    def do_GET(self) -> None:
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        query_params = urllib.parse.parse_qs(parsed_url.query)

        # 1. API Endpoint: Fetch parsed report JSON
        if path == "/api/report":
            self.handle_api_report(query_params)
            return

        # 2. Web interface root / index.html
        if path in ("/", "/index.html"):
            self.handle_web_root()
            return

        # 3. Fallback 404
        self.send_error_response(404, "Page Not Found")

    def handle_web_root(self) -> None:
        """Serve the dynamic HTML Debate Canvas SPA."""
        try:
            # Generate HTML page with dynamic/empty template placeholders
            html_content = HTML_TEMPLATE.format(
                title="TradingAgents 智能体投研辩论",
                ticker="UNKNOWN",
                date="",
                rating="HOLD",
                messages_json="[]"
            )
            
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(html_content.encode("utf-8"))
        except Exception as e:
            logger.error(f"Failed to serve index page: {e}", exc_info=True)
            self.send_error_response(500, f"Internal Server Error: {e}")

    def handle_api_report(self, params: Dict[str, list[str]]) -> None:
        """Query report from SQLite or filesystem and return structural JSON."""
        ticker = params.get("ticker", [""])[0].strip()
        date = params.get("date", [""])[0].strip()

        if not ticker or not date:
            self.send_json_response({
                "ok": False,
                "error": "Missing required parameters: 'ticker' and 'date'"
            }, status_code=400)
            return

        results_dir_str = DEFAULT_CONFIG.get("results_dir", "results")
        results_dir = Path(results_dir_str)
        
        logger.info(f"Querying debate report for {ticker} on {date}")
        md_text = None

        # Try SQLite query first
        try:
            # Check SQLite
            report = query_report(results_dir, ticker, date)
            if report and report.get("complete_report"):
                md_text = report["complete_report"]
                logger.info(f"Successfully retrieved report for {ticker} on {date} from SQLite")
        except Exception as e:
            logger.warning(f"Failed SQLite query, falling back to filesystem: {e}")

        # Try Filesystem query fallback
        if not md_text:
            try:
                md_text = find_report_on_filesystem(results_dir, ticker, date)
            except Exception as e:
                logger.error(f"Failed filesystem query fallback: {e}")

        if not md_text:
            self.send_json_response({
                "ok": False,
                "error": f"No debate report found for ticker '{ticker}' on date '{date}' in SQLite or filesystem"
            }, status_code=404)
            return

        # Parse report markdown into dialogue flow structures
        try:
            meta = extract_meta(md_text)
            messages = parse_markdown_debate(md_text)
            
            self.send_json_response({
                "ok": True,
                "title": meta["title"],
                "ticker": meta["ticker"],
                "date": meta["date"],
                "rating": meta["rating"],
                "messages": messages
            })
        except Exception as e:
            logger.error(f"Failed to parse report: {e}", exc_info=True)
            self.send_json_response({
                "ok": False,
                "error": f"Failed to parse report markdown: {e}"
            }, status_code=500)

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
    parser = argparse.ArgumentParser(description="Serve the dynamic interactive debate canvas locally")
    parser.add_argument("--port", type=int, default=8000, help="Local server port (default: 8000)")
    parser.add_argument("--host", default="localhost", help="Local server host (default: localhost)")
    args = parser.parse_args()

    results_dir_str = DEFAULT_CONFIG.get("results_dir", "results")
    init_db(results_dir_str)

    server_address = (args.host, args.port)
    httpd = HTTPServer(server_address, DebateRoomHTTPHandler)
    
    logger.info("=" * 60)
    logger.info(f"TradingAgents Dynamic Debate Server started at: http://{args.host}:{args.port}/")
    logger.info("Open the following link format in your browser to view debates:")
    logger.info(f"  http://{args.host}:{args.port}/?ticker=301308&date=2026-05-27")
    logger.info("=" * 60)
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("\nServer stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
