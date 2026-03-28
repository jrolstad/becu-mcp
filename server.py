#!/usr/bin/env python3
"""BECU MCP Server - read-only access to BECU account data via browser automation."""

import os
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

mcp = FastMCP("becu")


@mcp.tool()
async def get_accounts() -> list[dict]:
    """
    Get all BECU accounts with current and available balances.

    Returns a list of accounts including name, account number, current balance,
    available balance, and the account index needed for get_transactions.
    """
    from becu_client import get_accounts as _get_accounts
    return await _get_accounts()


@mcp.tool()
async def get_balance(account_index: int) -> dict | None:
    """
    Get the current and available balance for a single BECU account.

    Args:
        account_index: The account index (obtained from get_accounts).

    Returns the account with its balance details, or None if not found.
    """
    from becu_client import get_balance as _get_balance
    return await _get_balance(account_index)


@mcp.tool()
async def get_transactions(account_index: int, days: int = 30) -> list[dict]:
    """
    Get recent transactions for a BECU account.

    Args:
        account_index: The account index (obtained from get_accounts).
        days: Number of days of history to retrieve (default: 30).

    Returns a list of transactions with date, description, amount, and running balance.
    """
    from becu_client import get_transactions as _get_transactions
    return await _get_transactions(account_index, days)


if __name__ == "__main__":
    mcp.run()
