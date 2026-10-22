# -*- coding: utf-8 -*-
"""End-to-end smoke check for the GeoPortal UI.

Logs in as admin, opens every page, drives the ledger's core flows (filters,
column chooser, create modal, Excel export) and fails when any page reports a
console/page error or a flow breaks.

Usage (the dev stack must already be running):
    venv\\Scripts\\python.exe e2e\\smoke_ui.py
    run_e2e.cmd

Environment:
    E2E_BASE      frontend origin          (default http://localhost:5173)
    E2E_USER      login username           (default admin)
    E2E_PASSWORD  login password           (default admin123)
    E2E_HEADLESS  0 to watch the browser   (default 1)
"""

import json
import os
import re
import sys
import traceback

sys.stdout.reconfigure(encoding="utf-8")
from playwright.sync_api import sync_playwright

BASE = os.environ.get("E2E_BASE", "http://localhost:5173").rstrip("/")
USER = os.environ.get("E2E_USER", "admin")
PASSWORD = os.environ.get("E2E_PASSWORD", "admin123")
HEADLESS = os.environ.get("E2E_HEADLESS", "1") != "0"

PAGES = [
    ("/", "map"),
    ("/requests", "company ledger"),
    ("/mudryia-requests", "mudryia ledger"),
    ("/tracking", "tracking"),
    ("/import", "import"),
    ("/dashboard", "dashboard"),
    ("/users", "users"),
    ("/lookups", "lookups"),
    ("/reports", "reports"),
    ("/processor", "processor"),
    ("/point", "point"),
    ("/db-settings", "db settings"),
]


def main() -> int:
    report, errors = {}, {}
    current = {"page": "login"}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        page = browser.new_page()
        page.on("pageerror", lambda e: errors.setdefault(current["page"], []).append(f"PAGEERROR {e}"))
        page.on("console", lambda m: errors.setdefault(current["page"], []).append(f"CONSOLE {m.text}")
                if m.type == "error" else None)

        page.goto(BASE + "/login")
        page.fill("input[type=text]", USER)
        page.fill("input[type=password]", PASSWORD)
        page.click("button[type=submit]")
        page.wait_for_timeout(2500)
        report["login"] = "ok" if "Login" not in page.inner_text("body")[:80] else "FAILED"

        for path, label in PAGES:
            current["page"] = path
            page.goto(BASE + path)
            page.wait_for_timeout(2400)
            text = page.inner_text("body")
            report[path] = {"label": label, "loaded": len(text) > 30}

        current["page"] = "ledger flows"
        page.goto(BASE + "/mudryia-requests")
        page.wait_for_timeout(2400)

        page.get_by_role("button", name="فلترة").click()
        page.wait_for_timeout(400)
        page.locator("label", has_text=re.compile("^حالة الطلب$")).first.locator(
            "xpath=following-sibling::div[1]//button").first.click()
        page.wait_for_timeout(300)
        report["filter_empty_option"] = page.locator("li button", has_text="(فارغ)").count() >= 1
        page.keyboard.press("Escape")

        page.locator("summary", has_text="الأعمدة والعروض المحفوظة").click()
        page.wait_for_timeout(400)
        chips = page.locator("details").first.locator("label").count()
        report["column_chips"] = chips

        page.get_by_role("button", name="طلب جديد").first.click()
        page.wait_for_timeout(700)
        modal = page.locator("div.fixed.inset-0.z-50")
        report["create_modal"] = modal.count() > 0
        report["create_empty_option"] = modal.locator("label", has_text=re.compile("^المساح$")).first.locator(
            "xpath=following-sibling::select").first.locator("option", has_text="(فارغ)").count() > 0
        report["create_groups"] = {
            "office": modal.get_by_text("بيانات المكتب الفنى", exact=True).count(),
            "survey": modal.get_by_text("بيانات المعاينة", exact=True).count(),
            "old": modal.get_by_text("المساح والمكتب الفني", exact=True).count(),
        }
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)

        # bulk toolbar: selecting rows must offer the survey fields
        row_boxes = page.locator("tbody input[type=checkbox]")
        if row_boxes.count() > 0:
            row_boxes.first.evaluate("el => el.click()")
            page.wait_for_timeout(500)
            bar = page.locator("div.bg-blue-600").first
            report["bulk_bar"] = {
                "survey_status": bar.locator("select[title='حالة المعاينة']").count(),
                "office_comment": bar.locator("input[placeholder='تعليق المكتب الفني']").count(),
                "entry_date_neighbour": bar.locator("input[placeholder='تعليق المكتب الفني']").evaluate(
                    "el => el.closest('div').nextElementSibling?.querySelector('input[type=date]') ? 1 : 0"),
                "transition_comment": bar.locator("input[placeholder='تعليق تغيير الحالة...']").count(),
                "assign_btn": bar.get_by_role("button", name="إسناد").count(),
                "transition_btn": bar.get_by_role("button", name="تغيير الحالة").count(),
                "dates": bar.locator("input[type=date]").count(),
                "apply": bar.get_by_role("button", name="تحديث الحقول").count(),
            }
            row_boxes.first.evaluate("el => el.click()")
            page.wait_for_timeout(300)

        with page.expect_download(timeout=120000) as dl:
            page.get_by_role("button", name="تصدير Excel").first.click()
        report["export_file"] = dl.value.suggested_filename
        browser.close()

    failed = [k for k, v in errors.items()]
    print(json.dumps(report, ensure_ascii=False, indent=1))
    print("--- console/page errors")
    for key in failed:
        print(f"  {key}: {len(errors[key])}")
        for e in errors[key][:3]:
            print("     ", e[:180])

    problems = []
    if report.get("login") != "ok":
        problems.append("login failed")
    problems += [f"{k}: page did not load" for k, v in report.items()
                 if isinstance(v, dict) and "loaded" in v and not v.get("loaded")]
    if errors:
        problems.append("console/page errors: " + ", ".join(failed))
    if not report.get("filter_empty_option"):
        problems.append("(فارغ) missing from a filter dropdown")
    if report.get("column_chips", 0) < 15:
        problems.append("column chooser looks empty")
    if not report.get("create_modal"):
        problems.append("create modal did not open")
    groups = report.get("create_groups") or {}
    if groups and (groups.get("office") != 1 or groups.get("survey") != 1 or groups.get("old") != 0):
        problems.append(f"create form groups wrong: {groups}")
    if not report.get("export_file", "").endswith(".xlsx"):
        problems.append("export did not download an .xlsx")
    bulk = report.get("bulk_bar")
    if bulk and (bulk["survey_status"] != 1 or bulk["office_comment"] != 1
                 or bulk["entry_date_neighbour"] != 1 or bulk["transition_comment"] != 0
                 or bulk["assign_btn"] != 0 or bulk["transition_btn"] != 0
                 or bulk["dates"] != 2 or bulk["apply"] != 1):
        problems.append(f"bulk toolbar incomplete: {bulk}")

    print("RESULT:", "PASS" if not problems else "FAIL")
    for pr in problems:
        print(" -", pr)
    return 0 if not problems else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(2)
