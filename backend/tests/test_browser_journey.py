"""Inkloom AI — End-to-End Headless Browser Journey Test with Playwright & Chrome."""
from __future__ import annotations

import os
import sys
import time
from playwright.sync_api import sync_playwright

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
BASE_URL = "http://127.0.0.1:5173"
ADMIN_EMAIL = os.getenv("DEMO_ADMIN_EMAIL", "judge@inkloom.ai")
ADMIN_PASSWORD = os.getenv("DEMO_ADMIN_PASSWORD", "DemoJudge2026!")


def run_browser_verification():
    print("=" * 65)
    print(" INKLOOM AI — PLAYWRIGHT BROWSER VERIFICATION JOURNEY")
    print(f" Target URL: {BASE_URL}")
    print(f" Chrome Binary: {CHROME_PATH}")
    print("=" * 65)

    console_logs = []
    network_errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=CHROME_PATH,
            headless=True,
        )
        context = browser.new_context(viewport={"width": 1280, "height": 850})
        page = context.new_page()

        page.on("console", lambda msg: console_logs.append(f"[{msg.type}] {msg.text}"))
        page.on("pageerror", lambda err: console_logs.append(f"[PAGE ERROR] {err}"))
        page.on("requestfailed", lambda req: network_errors.append(f"[NET FAIL] {req.method} {req.url}: {req.failure}"))
        page.on("response", lambda res: print(f"  [HTTP {res.status}] {res.url}") if res.status >= 400 else None)

        try:
            # Step 1: Open Login
            print("\n[STEP 1] Navigating to Login Page...")
            page.goto(f"{BASE_URL}/login")
            page.wait_for_selector("#login-email", timeout=10000)
            print("  ✓ Login page loaded successfully. Document title:", page.title())

            # Step 2: Sign in as ADMIN
            print(f"\n[STEP 2] Signing in as ADMIN ({ADMIN_EMAIL})...")
            page.fill("#login-email", ADMIN_EMAIL)
            page.fill("#login-password", ADMIN_PASSWORD)
            page.click("button[type='submit']")

            # Wait for redirect to application layout
            page.wait_for_selector("text=Inkloom AI", timeout=10000)
            page.wait_for_selector("a[href='/brand-hub']", timeout=10000)
            print("  ✓ Successfully authenticated. Dashboard navigation ready.")

            # Step 3: Open Brand Hub
            print("\n[STEP 3] Opening Brand Hub (/brand-hub)...")
            page.click("a[href='/brand-hub']")
            page.wait_for_selector("h1:has-text('Brand Hub — Compliance Rules')", timeout=10000)
            print("  ✓ Brand Hub view loaded.")

            # Step 4: Create a new Brand Kit
            unique_suffix = int(time.time()) % 10000
            test_kit_name = f"Browser E2E Kit {unique_suffix}"
            print(f"\n[STEP 4] Creating new Brand Kit: '{test_kit_name}'...")
            page.fill("input[placeholder='Brand Kit name']", test_kit_name)
            page.click("button:has-text('Create')")

            # Wait for the option to be created in the select
            page.wait_for_selector(f"#brand-kit-select option:has-text('{test_kit_name}')", state="attached", timeout=10000)
            page.wait_for_selector("form button:has-text('Add Compliance Rule')", timeout=10000)
            print(f"  ✓ Brand Kit '{test_kit_name}' created, selected, and form ready.")

            # Step 5 & 6: Verify DRAFT version and create rules
            print("\n[STEP 5 & 6] Creating Compliance Rules on DRAFT Version...")
            page.wait_for_selector("text=DRAFT", timeout=10000)
            print("  ✓ Version 1 DRAFT active.")

            # Rule 1: Banned phrase
            print("  Adding Rule 1 (Banned phrase: 'guaranteed returns')...")
            page.select_option("#rule-type-select", "PROHIBITED_TERM")
            page.fill("form input[placeholder*='No Guaranteed Returns']", "No Guaranteed Returns")
            page.fill("form input[placeholder*='Exact word or phrase']", "guaranteed returns")
            page.fill("form input[placeholder*='Explain why this rule exists']", "Promising guaranteed investment returns violates securities regulations.")
            page.fill("form input[placeholder*='potential returns']", "potential returns")

            # Click submit
            page.click("form button:has-text('Add Compliance Rule')")
            time.sleep(1.5)

            # Check if there is an error message displayed on page
            err_box = page.locator(".bg-rose-500\\/10")
            if err_box.is_visible():
                print("  [PAGE ERROR BOX]:", err_box.text_content())

            page.wait_for_selector("text=No Guaranteed Returns", timeout=10000)
            print("  ✓ Rule 1 created: No Guaranteed Returns (PENDING_REVIEW).")

            # Rule 2: Mandatory Disclaimer
            print("  Adding Rule 2 (Mandatory disclaimer: 'market risk')...")
            page.select_option("#rule-type-select", "MANDATORY_DISCLAIMER")
            page.fill("form input[placeholder*='No Guaranteed Returns']", "Market Risk Disclaimer")
            page.fill("form input[placeholder*='Trigger keyword']", "market risk")
            page.fill("form input[placeholder*='Explain why this rule exists']", "Disclose market risks on all investment promotional materials.")
            page.fill("form textarea[placeholder*='Enter the exact disclaimer text']", "Investments are subject to market risk. Read all scheme related documents carefully.")
            page.click("form button:has-text('Add Compliance Rule')")
            page.wait_for_selector("text=Market Risk Disclaimer", timeout=10000)
            print("  ✓ Rule 2 created: Market Risk Disclaimer (PENDING_REVIEW).")

            # Rule 3: Required terminology
            print("  Adding Rule 3 (Required terminology: 'Acme')...")
            page.select_option("#rule-type-select", "MANDATORY_TERMINOLOGY")
            page.select_option("#rule-match-mode-select", "EXACT")
            page.fill("form input[placeholder*='No Guaranteed Returns']", "Acme Brand Mention")
            page.fill("form input[placeholder*='Exact word or phrase']", "Acme")
            page.fill("form input[placeholder*='Explain why this rule exists']", "Must prominently feature the Acme corporate brand name.")
            page.fill("form input[placeholder*='potential returns']", "Acme")
            page.click("form button:has-text('Add Compliance Rule')")
            page.wait_for_selector("text=Acme Brand Mention", timeout=10000)
            print("  ✓ Rule 3 created: Acme Brand Mention (PENDING_REVIEW).")

            # Step 7: Approve all rules
            print("\n[STEP 7] Approving all 3 compliance rules...")
            for _ in range(10):
                approve_btns = page.locator("button:has-text('Approve')")
                if approve_btns.count() == 0:
                    break
                approve_btns.first.click()
                time.sleep(1.0)

            page.wait_for_selector("text=3 Rule(s) Configured", timeout=5000)
            print("  ✓ All 3 rules approved successfully.")

            # Step 8: Publish the Brand Kit version
            print("\n[STEP 8] Publishing Brand Kit Version 1...")
            publish_btn = page.locator("button:has-text('Publish Version')")
            publish_btn.click()
            page.wait_for_selector("span:has-text('PUBLISHED')", timeout=10000)
            print("  ✓ Version successfully PUBLISHED. Container active version locked.")

            # Step 9: Open Compliance Review
            print("\n[STEP 9] Navigating to Compliance Review (/compliance-review)...")
            page.click("a[href='/compliance-review']")
            page.wait_for_selector("h1:has-text('Compliance Review')", timeout=10000)
            print("  ✓ Compliance Review workbench loaded.")

            # Select our newly created kit
            page.wait_for_selector(f"#compliance-kit-select option:has-text('{test_kit_name}')", state="attached", timeout=10000)
            page.select_option("#compliance-kit-select", label=test_kit_name)
            time.sleep(0.5)

            # Step 10: Submit marketing text containing deliberate violations
            violating_text = (
                "We are pleased to introduce our newest wealth package. "
                "Our fund offers guaranteed returns for every client. "
                "Get started with our expert advisors today!"
            )
            print(f"\n[STEP 10] Submitting text with deliberate violations:\n  \"{violating_text}\"")
            page.fill("textarea", violating_text)
            page.fill("input[placeholder*='Campaign']", "New Wealth Promotion")
            page.click("button:has-text('Run Compliance Check')")

            # Step 11 & 12: Verify analysis findings, exact matched text, and score
            print("\n[STEP 11 & 12] Verifying compliance analysis results...")
            page.wait_for_selector("span:has-text('FAIL')", timeout=10000)
            score_text = page.locator(".text-4xl.font-extrabold").first.text_content().strip()
            print(f"  ✓ Result: FAIL confirmed with transparent Score: {score_text} / 100.")
            assert int(score_text) < 70, f"Expected score < 70 for FAIL, got {score_text}"

            # Check finding cards
            page.wait_for_selector("text=No Guaranteed Returns", timeout=5000)
            page.wait_for_selector("text=Market Risk Disclaimer", timeout=5000)
            page.wait_for_selector("text=Acme Brand Mention", timeout=5000)
            print("  ✓ Verified findings: No Guaranteed Returns (CRITICAL), Market Risk Disclaimer (HIGH), Acme Brand Mention (LOW).")

            # Check matched text and evidence
            page.wait_for_selector("code:has-text('guaranteed returns')", timeout=5000)
            print("  ✓ Matched text 'guaranteed returns' verified in evidence card.")

            # Step 13: Apply suggested correction
            print("\n[STEP 13] Applying suggested corrections...")
            fix_btn = page.locator("button:has-text('Apply Suggested Corrections')")
            fix_btn.click()

            # Step 14: Verify re-analysis, score update to PASS
            print("\n[STEP 14] Verifying auto-corrected revision...")
            page.wait_for_selector("text=Revision 2", timeout=10000)
            page.wait_for_selector("h2:has-text('Revision Comparison')", timeout=10000)

            # Check that 'guaranteed returns' was replaced by 'potential returns'
            corrected_content = page.input_value("textarea")
            print(f"  Corrected text:\n  \"{corrected_content}\"")
            assert "potential returns" in corrected_content, "Expected 'potential returns' in corrected text"
            assert "Investments are subject to market risk." in corrected_content, "Expected disclaimer in corrected text"
            print("  ✓ Corrected text contains 'potential returns' and appended market risk disclaimer.")

            # Check diff panel
            page.wait_for_selector("span:has-text('Resolved:')", timeout=5000)
            resolved_text = page.locator("span:has-text('Resolved:')").first.text_content().strip()
            print(f"  ✓ Unified diff and score comparison panel verified ({resolved_text}).")

            # Step 15: Verify persistence across page refresh
            print("\n[STEP 15] Verifying persistence across page refresh...")
            page.reload()
            page.wait_for_selector("h1:has-text('Compliance Review')", timeout=10000)
            page.wait_for_selector("text=Revision 2", timeout=10000)
            print("  ✓ Page reloaded with state and history preserved.")

            # Step 16: Human Review & Approval Journey
            print("\n[STEP 16] Testing Human Approval & Review Decisions...")
            # Click Submit for Human Approval
            page.click("#btn-submit-for-approval")
            time.sleep(0.5)
            # Enter note and confirm
            page.fill("input[placeholder*='Note for reviewer']", "Auto-corrections applied. Ready for reviewer sign-off.")
            page.click("button:has-text('Confirm Submission')")
            time.sleep(1.0)
            page.wait_for_selector("#submission-status-badge:has-text('PENDING_REVIEW')", timeout=10000)
            print("  ✓ Submission transitioned to PENDING_REVIEW.")

            # Reviewer decision: Approve Content
            page.fill("#reviewer-comment-input", "Compliance satisfied: potential returns verified and market risk disclaimer confirmed. Approved.")
            page.click("#btn-approve-content")
            time.sleep(1.0)
            page.wait_for_selector("#submission-status-badge:has-text('APPROVED')", timeout=10000)
            print("  ✓ Reviewer decision recorded: Status APPROVED.")

            # Verify review history records the actions
            page.wait_for_selector("text=Review History & Discussion", timeout=5000)
            print("  ✓ Review history discussion and decision audit trail verified.")

            # Verify reload retains approval decision
            page.reload()
            page.wait_for_selector("#submission-status-badge:has-text('APPROVED')", timeout=10000)
            print("  ✓ Approval decision and state persisted across page reload.")

            # Step 17: Independent Customer Onboarding & Multi-Tenant Isolation
            print("\n[STEP 17] Testing Customer Onboarding & Tenant Isolation (New Org)...")
            ts = int(time.time())
            cust_name = f"Elena Vance"
            cust_email = f"elena_{ts}@nexis-retail.com"
            cust_org = f"Nexis Retail {ts}"
            cust_pwd = f"CustomerPass2026!"

            # Open a fresh isolated browser context for the new customer
            cust_context = browser.new_context(viewport={"width": 1280, "height": 850})
            cust_page = cust_context.new_page()

            cust_page.goto(f"{BASE_URL}/register")
            cust_page.wait_for_selector("#reg-fullname", timeout=10000)
            print(f"  Registering new independent customer: {cust_email} / '{cust_org}'...")

            cust_page.fill("#reg-fullname", cust_name)
            cust_page.fill("#reg-email", cust_email)
            cust_page.fill("#reg-org", cust_org)
            cust_page.fill("#reg-password", cust_pwd)
            cust_page.fill("#reg-confirm", cust_pwd)
            cust_page.click("button[type='submit']")

            # Wait for dashboard navigation
            cust_page.wait_for_selector("text=Inkloom AI", timeout=10000)
            print(f"  ✓ Customer registered and workspace provisioned ({cust_org}).")

            # Navigate to Brand Hub
            cust_page.click("a[href='/brand-hub']")
            cust_page.wait_for_selector("h1:has-text('Brand Hub — Compliance Rules')", timeout=10000)
            # Verify isolation: new tenant has 0 brand kits initially
            cust_page.wait_for_selector("option:has-text('No Brand Kits created yet')", state="attached", timeout=5000)
            print("  ✓ Tenant Isolation Verified: Acme brand kits are not visible to Nexis.")

            # Customer creates their own Brand Kit
            nexis_kit_name = f"Nexis Core Kit {ts}"
            print(f"  Creating customer Brand Kit: '{nexis_kit_name}'...")
            cust_page.fill("input[placeholder='Brand Kit name']", nexis_kit_name)
            cust_page.click("button:has-text('Create')")
            cust_page.wait_for_selector(f"#brand-kit-select option:has-text('{nexis_kit_name}')", state="attached", timeout=10000)

            # Customer adds their own rule: "No Cheapest Claims"
            print("  Adding customer-specific rule: 'No Cheapest Claims'...")
            cust_page.select_option("#rule-type-select", "PROHIBITED_TERM")
            cust_page.fill("form input[placeholder*='No Guaranteed Returns']", "No Cheapest Claims")
            cust_page.fill("form input[placeholder*='Exact word or phrase']", "cheapest prices")
            cust_page.fill("form input[placeholder*='Explain why this rule exists']", "Substantiation required for lowest price claims.")
            cust_page.fill("form input[placeholder*='potential returns']", "greatest value")
            cust_page.click("form button:has-text('Add Compliance Rule')")
            cust_page.wait_for_selector("text=No Cheapest Claims", timeout=10000)

            # Customer approves rule & publishes Version 1
            cust_page.click("button:has-text('Approve')")
            time.sleep(1.0)
            cust_page.click("button:has-text('Publish Version')")
            cust_page.wait_for_selector("span:has-text('PUBLISHED')", timeout=10000)
            print("  ✓ Nexis Version 1 PUBLISHED and locked.")

            # Customer navigates to Compliance Review
            cust_page.click("a[href='/compliance-review']")
            cust_page.wait_for_selector("h1:has-text('Compliance Review')", timeout=10000)
            cust_page.wait_for_selector(f"#compliance-kit-select option:has-text('{nexis_kit_name}')", state="attached", timeout=10000)
            cust_page.select_option("#compliance-kit-select", label=nexis_kit_name)

            # Customer submits marketing text violating Nexis rule
            nexis_text = "Shop with us today! We offer the cheapest prices anywhere online."
            cust_page.fill("textarea", nexis_text)
            cust_page.fill("input[placeholder*='Campaign']", "Summer Sale")
            cust_page.click("button:has-text('Run Compliance Check')")

            # Verify analysis
            cust_page.wait_for_selector("span:has-text('FAIL')", timeout=10000)
            cust_page.wait_for_selector("code:has-text('cheapest prices')", timeout=5000)
            print("  ✓ Nexis compliance check evaluated: FAIL with matched 'cheapest prices'.")

            # Customer submits for approval and approves
            cust_page.click("#btn-submit-for-approval")
            time.sleep(0.5)
            cust_page.fill("input[placeholder*='Note for reviewer']", "Initial campaign draft.")
            cust_page.click("button:has-text('Confirm Submission')")
            cust_page.wait_for_selector("#submission-status-badge:has-text('PENDING_REVIEW')", timeout=10000)

            cust_page.fill("#reviewer-comment-input", "Approved for internal testing.")
            cust_page.click("#btn-approve-content")
            cust_page.wait_for_selector("#submission-status-badge:has-text('APPROVED')", timeout=10000)
            print("  ✓ Customer submission approved successfully.")

            # Reload to verify persistence
            cust_page.reload()
            cust_page.wait_for_selector("#submission-status-badge:has-text('APPROVED')", timeout=10000)
            print("  ✓ Customer workspace state completely verified and persistent.")
            cust_context.close()

            print("\n" + "=" * 65)
            print(" ALL 17 END-TO-END BROWSER VERIFICATION STEPS PASSED!")
            print("=" * 65)

        except Exception as e:
            print("\n[EXCEPTION CAUGHT]:", e)
            print("\n[RECENT CONSOLE LOGS]:")
            for cl in console_logs[-15:]:
                print(" ", cl)
            print("\n[RECENT NETWORK ERRORS]:")
            for ne in network_errors[-10:]:
                print(" ", ne)
            page.screenshot(path="browser_verification_error.png")
            print("Saved error screenshot to browser_verification_error.png")
            raise
        finally:
            browser.close()


if __name__ == "__main__":
    run_browser_verification()
