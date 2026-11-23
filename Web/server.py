"""
Simplest Sudoku website server (no installs needed - Python standard library only).

The server only hands out the web pages and new puzzles.
Login happens in the browser: login.html talks directly to Supabase.

Run:
    python3 server.py
Then open http://localhost:8080
"""

import importlib
import json
import os
import sys
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "sudokuMain"))
generator = importlib.import_module("sudoku-generator")

PORT = 8080

# The only files the browser may load: web address -> (file, content type).
# Anything else (server.py, supabase.env, ...) gets a 404.
FILES = {
    "/":                   ("index.html", "text/html; charset=utf-8"),
    "/index.html":         ("index.html", "text/html; charset=utf-8"),
    "/login":              ("login.html", "text/html; charset=utf-8"),
    "/login.html":         ("login.html", "text/html; charset=utf-8"),
    "/supabase-config.js": ("supabase-config.js", "text/javascript; charset=utf-8"),
    "/vendor/supabase.js": ("node_modules/@supabase/supabase-js/dist/umd/supabase.js",
                            "text/javascript; charset=utf-8"),
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urlparse(self.path)

        if url.path == "/api/puzzle":
            difficulty = parse_qs(url.query).get("difficulty", ["medium"])[0]
            if difficulty not in generator.DIFFICULTY_CLUES:
                difficulty = "medium"
            self.send(json.dumps(generator.generate(difficulty)).encode(), "application/json")

        elif url.path in FILES:
            filename, content_type = FILES[url.path]
            # The Supabase library never changes, so let the browser keep it for a day
            # instead of downloading 220 KB on every page.
            cache = "public, max-age=86400" if url.path.startswith("/vendor/") else "no-cache"
            try:
                with open(os.path.join(HERE, filename), "rb") as f:
                    self.send(f.read(), content_type, cache)
            except FileNotFoundError:
                self.send_error(404, f"{filename} is missing")

        else:
            self.send_error(404)

    def send(self, body, content_type, cache="no-cache"):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", cache)
        # Security headers:
        #  - CSP: scripts only from this site, network calls only to this site and
        #    Supabase, and no other website may show our pages in a frame
        #    (stops "clickjacking" tricks on the login page).
        #  - nosniff: the browser must trust our Content-Type.
        #  - Referrer-Policy: don't leak full URLs to other sites.
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                         "style-src 'self' 'unsafe-inline'; "
                         "connect-src 'self' https://*.supabase.co wss://*.supabase.co; "
                         "frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    print(f"Sudoku running at http://localhost:{PORT}  (Ctrl+C to stop)")
    # 127.0.0.1 = only this computer can connect. Use "" to allow other
    # devices on your network (e.g. to test on your phone).
    # Threading: each browser connection gets its own thread, so one idle
    # connection (browsers open spare ones) can't block every other request.
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
