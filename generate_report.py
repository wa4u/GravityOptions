#!/usr/bin/env python3
"""
GravityOptions - Report Generator CLI
Builds and views the interactive Daily, Weekly, Monthly performance dashboard.
"""
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import os
import webbrowser
import yaml
from src.reporting.report_generator import ReportGenerator
from src.utils.logger import log

def main():
    print("=" * 60)
    print("   GRAVITY OPTIONS - PERFORMANCE ANALYTICS REPORT GENERATOR")
    print("=" * 60)

    web_path = None
    try:
        with open("config/config.yaml", "r") as f:
            cfg = yaml.safe_load(f)
            web_path = cfg.get("system", {}).get("web_report_path")
    except Exception:
        pass

    generator = ReportGenerator(web_export_path=web_path)
    abs_path = generator.generate_html_report()

    
    file_url = f"file:///{abs_path.replace(os.sep, '/')}"
    print(f"\n✅ Report generated successfully!")
    print(f"📁 Local File: {abs_path}")
    print(f"🌐 Browser URL: {file_url}\n")

    # If --open passed or user wants to preview
    if "--open" in sys.argv:
        log.info("Opening dashboard in default web browser...")
        webbrowser.open(file_url)

if __name__ == "__main__":
    main()
