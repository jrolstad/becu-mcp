import json
import os
import re
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, BrowserContext, Page

SESSION_FILE = Path(__file__).parent / "session.json"
SUMMARY_URL = "https://onlinebanking.becu.org/BECUBankingWeb/Accounts/Summary.aspx"
ACTIVITY_URL = "https://onlinebanking.becu.org/BECUBankingWeb/Accounts/Activity.aspx"
LOGIN_DOMAIN = "auth.secure.becu.org"


def _is_logged_in(page: Page) -> bool:
    return LOGIN_DOMAIN not in page.url


async def _login(page: Page) -> None:
    username = os.environ["BECU_USERNAME"]
    password = os.environ["BECU_PASSWORD"]

    await page.goto(SUMMARY_URL)
    await page.wait_for_load_state("networkidle")

    if _is_logged_in(page):
        return

    # Fill login form on auth.secure.becu.org
    await page.fill('input[type="text"], input[name*="user"], input[id*="user"]', username)
    await page.fill('input[type="password"]', password)
    await page.click('button[type="submit"], input[type="submit"]')
    await page.wait_for_load_state("networkidle")

    # If MFA is required, wait for user to complete it (up to 60 seconds)
    if LOGIN_DOMAIN in page.url:
        print("MFA may be required. Please complete authentication in the browser window...")
        await page.wait_for_url(f"**/{SUMMARY_URL.split('becu.org')[1]}**", timeout=60000)

    await page.wait_for_load_state("networkidle")


async def _save_session(context: BrowserContext) -> None:
    cookies = await context.cookies()
    SESSION_FILE.write_text(json.dumps(cookies))


async def _load_session(context: BrowserContext) -> bool:
    if not SESSION_FILE.exists():
        return False
    try:
        cookies = json.loads(SESSION_FILE.read_text())
        await context.add_cookies(cookies)
        return True
    except Exception:
        return False


async def _get_page_html(url: str, params: Optional[dict] = None) -> str:
    """Fetch a BECU page, handling auth as needed. Returns raw HTML."""
    async with async_playwright() as p:
        # Use headless if we have a saved session; show browser for initial auth/MFA
        headless = SESSION_FILE.exists()
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context()

        await _load_session(context)
        page = await context.new_page()

        full_url = url
        if params:
            qs = "&".join(f"{k}={v}" for k, v in params.items())
            full_url = f"{url}?{qs}"

        await page.goto(full_url)
        await page.wait_for_load_state("networkidle")

        # Re-authenticate if session expired
        if not _is_logged_in(page):
            if headless:
                # Session expired — reopen with visible browser for MFA
                await browser.close()
                browser = await p.chromium.launch(headless=False)
                context = await browser.new_context()
                page = await context.new_page()
            await _login(page)
            await page.goto(full_url)
            await page.wait_for_load_state("networkidle")

        html = await page.content()
        await _save_session(context)
        await browser.close()
        return html


def _parse_currency(text: str) -> Optional[float]:
    if not text:
        return None
    # Extract the last currency-like value (handles "LabelText$1,234.56")
    match = re.search(r"-?\$?([\d,]+\.?\d*)", text.strip())
    if not match:
        return None
    cleaned = match.group(1).replace(",", "")
    # Preserve negative sign if present
    if text.strip().startswith("-") or "-$" in text:
        cleaned = "-" + cleaned
    try:
        return float(cleaned)
    except ValueError:
        return None


def _cell_label_and_value(cell) -> tuple[str, str]:
    """Return (label, value) from a tablesaw cell with a <b class="tablesaw-cell-label"> element."""
    label_el = cell.find("b", class_="tablesaw-cell-label")
    label = label_el.get_text(strip=True).lower() if label_el else ""
    if label_el:
        label_el.extract()
    value = cell.get_text(strip=True)
    return label, value


async def get_accounts() -> list[dict]:
    """Scrape account summary page and return all accounts with balances."""
    html = await _get_page_html(SUMMARY_URL)
    soup = BeautifulSoup(html, "html.parser")
    accounts = []
    seen_account_numbers: set[str] = set()

    for table in soup.select("table"):
        # Only process tables that have account links
        if not table.find("a", href=re.compile(r"index=\d+|loanId=")):
            continue

        for row in table.select("tr.item, tr.alternatingItem"):
            # Parse each cell using its embedded label
            link = None
            cell_data: dict[str, str] = {}
            for cell in row.select("td"):
                label, value = _cell_label_and_value(cell)
                cell_data[label] = value
                if not link:
                    link = cell.find("a")

            if not link:
                continue

            name = link.get_text(strip=True)
            href = link.get("href", "")

            # Extract account index from URL (?index=N)
            idx_match = re.search(r"index=(\d+)", href)
            account_index = int(idx_match.group(1)) if idx_match else None

            # Extract account number from name (last space-separated token if numeric)
            parts = name.rsplit(" ", 1)
            account_number = parts[-1] if len(parts) > 1 and parts[-1].isdigit() else None
            display_name = parts[0] if account_number else name

            # Deduplicate by account number (or full name if no account number)
            dedup_key = account_number or name
            if dedup_key in seen_account_numbers:
                continue
            seen_account_numbers.add(dedup_key)

            account = {
                "index": account_index,
                "name": display_name,
                "account_number": account_number,
                "full_name": name,
                "current_balance": _parse_currency(cell_data.get("current balance", "")),
                "available_balance": _parse_currency(cell_data.get("available balance", "")),
                "ytd_interest": _parse_currency(cell_data.get("ytd interest", "")),
            }
            accounts.append(account)

    return accounts


async def get_balance(account_index: int) -> Optional[dict]:
    """Return balance info for a single account by its index."""
    accounts = await get_accounts()
    for acct in accounts:
        if acct.get("index") == account_index:
            return acct
    return None


async def get_transactions(account_index: int, days: int = 30) -> list[dict]:
    """Scrape the Activity page for an account and return transactions."""
    html = await _get_page_html(ACTIVITY_URL, params={"index": account_index})
    soup = BeautifulSoup(html, "html.parser")
    transactions = []

    # Find the transaction table — prefer one with a Date header
    table = None
    for t in soup.select("table"):
        headers = [th.get_text(strip=True).lower() for th in t.select("th")]
        has_date = any("date" in h for h in headers)
        has_amount = any(any(k in h for k in ("amount", "debit", "credit", "withdrawal", "deposit")) for h in headers)
        if has_date and has_amount:
            table = t
            break

    if not table:
        return []

    for row in table.select("tr.item, tr.alternatingItem"):
        cell_data: dict[str, str] = {}
        for cell in row.select("td"):
            label, value = _cell_label_and_value(cell)
            cell_data[label] = value

        # Date label may be "post / transaction date" or similar — find by keyword
        date_val = next((v for k, v in cell_data.items() if "date" in k), "")

        # Skip non-transaction rows (e.g. summary rows without a real date)
        if not re.search(r"\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}", date_val):
            continue

        # Use only the first date if two are present (post date / transaction date)
        date_val = re.search(r"\d{1,2}/\d{1,2}/\d{4}", date_val).group()

        txn: dict = {"date": date_val}

        desc_val = next((v for k, v in cell_data.items() if "description" in k and "date" not in k), None)
        if desc_val:
            txn["description"] = desc_val

        # Handle amount / withdrawal+deposit columns
        if "amount" in cell_data:
            txn["amount"] = _parse_currency(cell_data["amount"])
        else:
            debit = next((_parse_currency(v) for k, v in cell_data.items() if "withdrawal" in k or "debit" in k), None)
            credit = next((_parse_currency(v) for k, v in cell_data.items() if "deposit" in k or "credit" in k), None)
            if debit is not None:
                txn["amount"] = -debit
            elif credit is not None:
                txn["amount"] = credit

        balance_val = next((v for k, v in cell_data.items() if k == "balance"), None)
        if balance_val:
            txn["balance"] = _parse_currency(balance_val)

        if txn.get("date") or txn.get("description"):
            transactions.append(txn)

    return transactions
