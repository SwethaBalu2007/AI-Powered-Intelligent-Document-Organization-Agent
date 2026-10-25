"""
Desktop Application Launcher for AI-Powered Intelligent Document Organization Agent.
Starts local agent backend and launches desktop dashboard.
"""

import os
import sys
import webbrowser
import threading
import time
import socket

try:
    import uvicorn
except ImportError:
    print("Error: uvicorn is not installed. Please run: pip install uvicorn")
    sys.exit(1)


def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0


def find_free_port(start_port: int = 8000) -> int:
    port = start_port
    while is_port_in_use(port):
        port += 1
    return port


def main():
    port = find_free_port(8000)
    url = f"http://127.0.0.1:{port}"

    print("=" * 70)
    print(" 📁 AI-POWERED INTELLIGENT DOCUMENT ORGANIZATION AGENT")
    print(" Local-First Desktop Agent | Human-in-the-Loop Safe Architecture")
    print("=" * 70)
    print(f" [+] Server initializing at: {url}")
    print(" [+] Mode: Security-Enforced (Read-Only Scan by default)")
    print(" [+] SQLite Database: backend/document_ledger.db")
    print("=" * 70)

    def open_browser():
        time.sleep(1.2)
        print(f" [+] Opening desktop dashboard in browser: {url}")
        webbrowser.open(url)

    threading.Thread(target=open_browser, daemon=True).start()

    # Run Uvicorn server
    uvicorn.run("backend.main:app", host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    main()
