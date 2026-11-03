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
from src.reporting.helper_generator import HelperPageGenerator
from src.utils.logger import log

def main():
    print("=" * 60)
    print("   GRAVITY OPTIONS - WEB PAGES GENERATOR")
    print("=" * 60)

    web_path = None
    try:
        with open("config/config.yaml", "r") as f:
            cfg = yaml.safe_load(f)
            web_path = cfg.get("system", {}).get("web_report_path")
    except Exception:
        pass

    # 1. Generate Performance Dashboard
    generator = ReportGenerator(web_export_path=web_path)
    abs_path = generator.generate_html_report()
    
    # 2. Generate Helper & Control Page
    web_helper_path = None
    if web_path and "index.html" in web_path:
        web_helper_path = web_path.replace("index.html", "helper.html")

    helper_gen = HelperPageGenerator(web_export_path=web_helper_path)
    helper_path = helper_gen.generate_html()

    file_url = f"file:///{abs_path.replace(os.sep, '/')}"
    print(f"\n✅ All pages generated successfully!")
    print(f"📊 Dashboard: {abs_path}")
    print(f"🛠️ Helper Page: {helper_path}")
    if web_path:
        print(f"🌐 Live Web URLs:")
        print(f"   • Dashboard:   https://gravity.work.gd/")
        print(f"   • Helper Page: https://gravity.work.gd/helper.html\n")


    # If --open passed or user wants to preview
    if "--open" in sys.argv:
        log.info("Opening dashboard in default web browser...")
        webbrowser.open(file_url)

if __name__ == "__main__":
    main()
