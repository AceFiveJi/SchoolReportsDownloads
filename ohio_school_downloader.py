"""
Ohio Community/STEM School – Statement Of Settlement downloader (Playwright)

- Opens the Ohio foundation payment report portal.
- Selects:
    LEA Type = Community/STEM School
    Fiscal Year = most recent option
    Payment Date = most recent option
    LEA = Specific LEA
- Reads *all* schools from the Specific LEA dropdown.
- For each school:
    - selects the school
    - selects "Statement Of Settlement" under School Finance Payment Reports
    - clicks "Process the Report"
    - downloads the PDF
    - returns to Process Reports screen
- All waits are at least 3 seconds after major actions.
"""

import os
import csv
import time
import logging
from datetime import datetime

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# --------------------------------------------------------------------
# CONFIG
# --------------------------------------------------------------------

ROOT_URL = "https://reports.education.ohio.gov/finance/foundation-payment-report"

LEA_TYPE_TEXT = "Community/STEM School"
REPORT_TYPE_TEXT = "Statement Of Settlement"

WAIT_TIMEOUT = 30000  # ms
GLOBAL_WAIT = 3       # seconds after each major action
MAX_RETRIES = 3

USER_DOWNLOADS = os.path.join(os.environ["USERPROFILE"], "Downloads")

log_filename = os.path.join(
    USER_DOWNLOADS,
    f"ohio_school_downloader_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log",
)

SUMMARY_CSV = os.path.join(
    USER_DOWNLOADS,
    f"ohio_school_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
)

logging.basicConfig(
    filename=log_filename,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
console = logging.StreamHandler()
console.setLevel(logging.INFO)
logging.getLogger().addHandler(console)


# --------------------------------------------------------------------
# UTILS
# --------------------------------------------------------------------

def wait():
    logging.info(f"Waiting {GLOBAL_WAIT} seconds...")
    time.sleep(GLOBAL_WAIT)


def safe_filename(name: str) -> str:
    return "".join(c if c not in "\\/*?:\"<>|" else "_" for c in name).strip()


def unique_path(folder: str, base: str) -> str:
    path = os.path.join(folder, base)
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(base)
    i = 1
    while True:
        candidate = os.path.join(folder, f"{stem} ({i}){ext}")
        if not os.path.exists(candidate):
            return candidate
        i += 1


# --------------------------------------------------------------------
# SELECT HELPERS
# --------------------------------------------------------------------

def select_ng_option(page, ng_select_locator: str, option_text: str | None = None):
    """
    Generic helper to open an ng-select and pick an option.
    If option_text is None, picks first available option.
    """
    dd = page.locator(ng_select_locator).first
    dd.wait_for(state="visible", timeout=WAIT_TIMEOUT)
    dd.click()
    wait()

    if option_text:
        opt = page.locator(".ng-option-label", has_text=option_text).first
    else:
        opt = page.locator(".ng-option-label").first

    opt.wait_for(state="visible", timeout=WAIT_TIMEOUT)
    text = opt.inner_text().strip()
    opt.click()
    wait()

    return text


def select_lea_type(page):
    logging.info("Selecting LEA Type...")
    # bindlabel/bindvalue based on HTML snippet you provided
    text = select_ng_option(
        page,
        "ng-select[bindlabel='paymentTypeName'][bindvalue='paymentTypeID']",
        LEA_TYPE_TEXT,
    )
    logging.info(f"LEA Type selected: {text}")


def select_fiscal_year(page):
    logging.info("Selecting Fiscal Year...")
    text = select_ng_option(
        page,
        "ng-select[bindlabel='fiscalYear'][bindvalue='fiscalYearID']",
        option_text=None,  # newest is first
    )
    logging.info(f"Fiscal Year selected: {text}")
    return text


def select_payment_date(page):
    logging.info("Selecting Payment Date...")
    text = select_ng_option(
        page,
        "ng-select[bindlabel='paymentDate'][bindvalue='paymentDateID']",
        option_text=None,  # newest is first
    )
    logging.info(f"Payment Date selected: {text}")
    return text


def ensure_specific_lea_radio(page):
    logging.info("Ensuring 'Specific LEA' radio is selected...")
    radio = page.locator("input[name='reportRegion'][value='lea']").first
    radio.wait_for(state="visible", timeout=WAIT_TIMEOUT)

    if not radio.is_checked():
        radio.click(force=True)
        wait()

    if not radio.is_checked():
        # fallback: click label
        label = page.locator("label:has-text('Specific LEA')").first
        if label.count():
            label.click(force=True)
            wait()

    if not radio.is_checked():
        raise RuntimeError("Could not select 'Specific LEA' radio.")

    logging.info("'Specific LEA' radio is selected.")


def get_school_list(page):
    """
    Open Specific LEA dropdown and capture all school labels.
    """
    logging.info("Reading school list...")
    ensure_specific_lea_radio(page)

    dd = page.locator("ng-select[bindlabel='schoolName'][bindvalue='schoolID']").first
    dd.wait_for(state="visible", timeout=WAIT_TIMEOUT)
    dd.click()
    wait()

    options = page.locator(".ng-option-label")
    count = options.count()
    if count == 0:
        raise RuntimeError("No schools found in Specific LEA dropdown.")

    schools = [options.nth(i).inner_text().strip() for i in range(count)]

    # Close dropdown
    page.keyboard.press("Escape")
    wait()

    logging.info(f"Found {len(schools)} schools.")
    return schools


def select_school(page, school_label: str):
    """
    Select a school in the Specific LEA dropdown using its full label text.
    Uses the internal ng-select input to filter options.
    """
    logging.info(f"Selecting school: {school_label}")
    ensure_specific_lea_radio(page)

    dd = page.locator("ng-select[bindlabel='schoolName'][bindvalue='schoolID']").first
    dd.wait_for(state="visible", timeout=WAIT_TIMEOUT)

    # Use the internal input for filtering
    input_box = dd.locator("input[aria-autocomplete='list']").first
    input_box.wait_for(state="visible", timeout=WAIT_TIMEOUT)

    input_box.click()
    input_box.fill("")   # clear existing
    input_box.fill(school_label)
    wait()

    opt = page.locator(".ng-option-label", has_text=school_label).first
    opt.wait_for(state="visible", timeout=WAIT_TIMEOUT)
    opt.click()
    wait()

    logging.info(f"School selected: {school_label}")


def select_report_type(page):
    """
    Select 'Statement Of Settlement' under School Finance Payment Reports.
    Uses bindlabel/bindvalue selectors instead of placeholder text.
    """
    logging.info("Selecting report type...")

    dd = page.locator(
        "ng-select[bindlabel='reportTypeName'][bindvalue='reportTypeID']"
    ).first
    dd.wait_for(state="visible", timeout=WAIT_TIMEOUT)

    # Wait until input is enabled
    input_box = dd.locator("input[aria-autocomplete='list']").first
    input_box.wait_for(state="visible", timeout=WAIT_TIMEOUT)

    # In practice this input is enabled as soon as school is selected
    input_box.click()
    wait()

    opt = page.locator(".ng-option-label", has_text=REPORT_TYPE_TEXT).first
    opt.wait_for(state="visible", timeout=WAIT_TIMEOUT)
    opt.click()
    wait()

    logging.info("Report type selected: Statement Of Settlement")


# --------------------------------------------------------------------
# MAIN
# --------------------------------------------------------------------

def main():
    summary = []

    logging.info("Starting Ohio Statement Of Settlement downloader (Playwright).")
    logging.info(f"Downloads & logs directory: {USER_DOWNLOADS}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--start-maximized"])
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()

        try:
            # Navigate to root page
            logging.info("Navigating to Process Reports page...")
            page.goto(ROOT_URL, timeout=WAIT_TIMEOUT)
            page.wait_for_load_state("networkidle")
            wait()

            # Initial selections (you only do these once manually)
            select_lea_type(page)
            fiscal = select_fiscal_year(page)
            logging.info(f"Initial Fiscal Year: {fiscal}")

            logging.info("Clicking 'Go'...")
            page.locator("button:has-text('Go')").first.click()
            page.wait_for_load_state("networkidle")
            wait()

            payment = select_payment_date(page)
            logging.info(f"Initial Payment Date: {payment}")

            ensure_specific_lea_radio(page)
            wait()

            # Read full school list once
            schools = get_school_list(page)

            # Process each school
            for idx, school in enumerate(schools, start=1):
                logging.info("=" * 60)
                logging.info(f"[{idx}/{len(schools)}] Processing: {school}")

                success = False
                last_error = ""

                for attempt in range(1, MAX_RETRIES + 1):
                    logging.info(f"Attempt {attempt} for {school}")
                    try:
                        # Ensure we're on the Process Reports page
                        if "finance/preview" in page.url:
                            logging.info("On report preview page; returning to Process Reports.")
                            back_btn = page.locator("text=Back to Process Reports").first
                            if back_btn.count():
                                back_btn.click()
                                page.wait_for_load_state("networkidle")
                                wait()
                            else:
                                page.goto(ROOT_URL, timeout=WAIT_TIMEOUT)
                                page.wait_for_load_state("networkidle")
                                wait()

                        if ROOT_URL not in page.url:
                            logging.info("Not on Process Reports; navigating again.")
                            page.goto(ROOT_URL, timeout=WAIT_TIMEOUT)
                            page.wait_for_load_state("networkidle")
                            wait()
                            select_lea_type(page)
                            select_fiscal_year(page)
                            logging.info("Clicking 'Go' after re-navigation...")
                            page.locator("button:has-text('Go')").first.click()
                            page.wait_for_load_state("networkidle")
                            wait()
                            select_payment_date(page)
                            ensure_specific_lea_radio(page)
                            wait()

                        # Now select school and report type
                        select_school(page, school)
                        select_report_type(page)

                        # Click Process The Report
                        logging.info("Clicking 'Process The Report'...")
                        with page.expect_navigation(timeout=WAIT_TIMEOUT):
                            page.locator("button:has-text('Process The Report')").first.click()

                        page.wait_for_load_state("networkidle")
                        wait()

                        # Download PDF
                        logging.info("Initiating PDF download...")
                        with page.expect_download(timeout=WAIT_TIMEOUT) as dl_info:
                            page.locator("text=Download PDF").first.click()
                        download = dl_info.value

                        today_str = datetime.now().strftime("%Y-%m-%d")
                        base_name = f"{today_str} - {safe_filename(school)} - Statement of Settlement.pdf"
                        dest_path = unique_path(USER_DOWNLOADS, base_name)
                        download.save_as(dest_path)

                        logging.info(f"Downloaded PDF to: {dest_path}")
                        summary.append([school, "success", dest_path, datetime.now().isoformat()])
                        success = True

                        # Back to Process Reports
                        logging.info("Returning to Process Reports page...")
                        back_btn = page.locator("text=Back to Process Reports").first
                        if back_btn.count():
                            with page.expect_navigation(timeout=WAIT_TIMEOUT):
                                back_btn.click()
                            page.wait_for_load_state("networkidle")
                            wait()
                        else:
                            page.goto(ROOT_URL, timeout=WAIT_TIMEOUT)
                            page.wait_for_load_state("networkidle")
                            wait()

                        break

                    except Exception as e:
                        last_error = str(e)
                        logging.exception(f"Error processing {school} on attempt {attempt}: {e}")

                        # Screenshot for debugging
                        screenshot_path = os.path.join(
                            USER_DOWNLOADS,
                            f"error_{safe_filename(school)}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png",
                        )
                        try:
                            page.screenshot(path=screenshot_path, full_page=True)
                            logging.info(f"Screenshot saved: {screenshot_path}")
                        except Exception:
                            logging.warning("Failed to capture screenshot.")

                        # Try to reset back to root for next attempt
                        try:
                            page.goto(ROOT_URL, timeout=WAIT_TIMEOUT)
                            page.wait_for_load_state("networkidle")
                            wait()
                            select_lea_type(page)
                            select_fiscal_year(page)
                            page.locator("button:has-text('Go')").first.click()
                            page.wait_for_load_state("networkidle")
                            wait()
                            select_payment_date(page)
                            ensure_specific_lea_radio(page)
                            wait()
                        except Exception as e2:
                            logging.warning(f"Failed to fully reset page after error: {e2}")

                if not success:
                    logging.error(f"FAILED to process {school} after {MAX_RETRIES} attempts.")
                    summary.append([school, "failed", last_error, datetime.now().isoformat()])

        finally:
            try:
                context.close()
            except Exception:
                pass
            try:
                browser.close()
            except Exception:
                pass

    # Write summary CSV
    logging.info(f"Writing summary CSV to {SUMMARY_CSV}")
    with open(SUMMARY_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["School", "Status", "Info/PathOrError", "Timestamp"])
        writer.writerows(summary)

    logging.info("Done. Review the CSV and log file for details.")
    print(f"Log file: {log_filename}")
    print(f"Summary CSV: {SUMMARY_CSV}")
    print(f"Downloads folder: {USER_DOWNLOADS}")


if __name__ == "__main__":
    main()
