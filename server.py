#!/usr/bin/env python3
"""BECU MCP Server - read-only access to BECU account data via browser automation."""

import time
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

mcp = FastMCP("becu")

CACHE_MAX_AGE = 6 * 60 * 60  # 6 hours in seconds
_cache: dict = {}


def _cache_get(key: str):
    entry = _cache.get(key)
    if entry and (time.time() - entry["ts"]) < CACHE_MAX_AGE:
        return entry["data"]
    return None


def _cache_set(key: str, data) -> None:
    _cache[key] = {"ts": time.time(), "data": data}


@mcp.tool()
async def get_accounts() -> list[dict]:
    """
    Get all BECU accounts with current and available balances.

    Returns a list of accounts including name, account number, current balance,
    available balance, and the account index needed for get_transactions.
    """
    cached = _cache_get("accounts")
    if cached is not None:
        return cached
    from becu_client import get_accounts as _get_accounts
    result = await _get_accounts()
    _cache_set("accounts", result)
    return result


@mcp.tool()
async def get_balance(account_index: int) -> dict | None:
    """
    Get the current and available balance for a single BECU account.

    Args:
        account_index: The account index (obtained from get_accounts).

    Returns the account with its balance details, or None if not found.
    """
    key = f"balance:{account_index}"
    cached = _cache_get(key)
    if cached is not None:
        return cached
    from becu_client import get_balance as _get_balance
    result = await _get_balance(account_index)
    _cache_set(key, result)
    return result


@mcp.tool()
async def get_transactions(account_index: int, days: int = 30) -> list[dict]:
    """
    Get recent transactions for a BECU account.

    Args:
        account_index: The account index (obtained from get_accounts).
        days: Number of days of history to retrieve (default: 30).

    Returns a list of transactions with date, description, amount, and running balance.
    """
    key = f"transactions:{account_index}:{days}"
    cached = _cache_get(key)
    if cached is not None:
        return cached
    from becu_client import get_transactions as _get_transactions
    result = await _get_transactions(account_index, days)
    _cache_set(key, result)
    return result


@mcp.tool()
async def reset_cache() -> str:
    """
    Clear all cached BECU data, forcing fresh data to be fetched on the next request.
    """
    _cache.clear()
    return "Cache cleared."


if __name__ == "__main__":
    mcp.run()
