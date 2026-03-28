# becu-mcp

An [MCP (Model Context Protocol)](https://modelcontextprotocol.io) server that provides read-only access to your [BECU](https://www.becu.org) accounts via browser automation. Use it with Claude Code or any MCP-compatible client to query account balances and transaction history conversationally.

## What it does

Exposes three tools:

| Tool | Description |
|------|-------------|
| `get_accounts` | Returns all accounts with current balance, available balance, and YTD interest |
| `get_balance` | Returns balance details for a single account by index |
| `get_transactions` | Returns transaction history for an account (date, description, amount, balance) |

Authentication is handled automatically using Playwright to drive a Chromium browser. Sessions are persisted to `session.json` so subsequent calls run headlessly. If the session expires or MFA is required, a visible browser window opens for you to complete login.

## Installation

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) or pip

### Steps

1. Clone the repository:
   ```bash
   git clone https://github.com/jrolstad/becu-mcp.git
   cd becu-mcp
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Install Playwright's Chromium browser:
   ```bash
   playwright install chromium
   ```

4. Create a `.env` file with your BECU credentials:
   ```bash
   cp .env.example .env
   ```
   Then edit `.env`:
   ```
   BECU_USERNAME=your_username_here
   BECU_PASSWORD=your_password_here
   ```

### Configure with Claude Code

Add the server to your Claude Code MCP settings (`~/.claude/settings.json`):

```json
{
  "mcpServers": {
    "becu": {
      "command": "python",
      "args": ["/path/to/becu-mcp/server.py"],
      "cwd": "/path/to/becu-mcp"
    }
  }
}
```

## Usage

Once connected, you can ask Claude things like:

- "List my BECU accounts with their balances"
- "What are the last 20 transactions from My Checking?"
- "What's the balance on my savings account?"
- "How much YTD interest has the Annual Payments savings account earned?"

## Authentication and sessions

- On first run, a Chromium browser window opens and logs in with your credentials.
- If MFA is required, you have 60 seconds to complete it in the browser window.
- After a successful login, cookies are saved to `session.json` for future headless runs.
- If a session expires, the browser window opens again automatically.
- `session.json` is gitignored — do not commit it.

## Development

### Project structure

```
becu_client.py   # Playwright scraping and HTML parsing logic
server.py        # MCP server (FastMCP) — exposes tools to MCP clients
requirements.txt # Python dependencies
.env.example     # Credential template
session.json     # Persisted browser session cookies (gitignored)
```

### How scraping works

`becu_client.py` uses Playwright to load pages from `onlinebanking.becu.org`, then parses the HTML with BeautifulSoup. The BECU pages use a [Tablesaw](https://github.com/filamentgroup/tablesaw) responsive table library that embeds column labels inside each `<td>` as `<b class="tablesaw-cell-label">` elements. The parser extracts these labels to identify each cell's field regardless of column order, making it resilient to layout changes.

Key functions:

- `_get_page_html()` — fetches a page, handles auth/session management
- `_cell_label_and_value()` — extracts the field label and value from a tablesaw `<td>`
- `_parse_currency()` — converts `"$1,234.56"` to `1234.56`
- `get_accounts()` — scrapes the Summary page, deduplicates by account number
- `get_transactions()` — scrapes the Activity page, filters out summary/non-transaction rows

### Running locally

```bash
python server.py
```

Or via the MCP CLI:

```bash
mcp dev server.py
```

### Adding new tools

1. Add a new async function to `becu_client.py` that fetches and parses the relevant BECU page.
2. Register it as a tool in `server.py` using the `@mcp.tool()` decorator.
3. Reconnect your MCP client to pick up the new tool.

### Dependencies

| Package | Purpose |
|---------|---------|
| `mcp` | MCP server framework (FastMCP) |
| `playwright` | Headless browser automation for scraping |
| `beautifulsoup4` | HTML parsing |
| `python-dotenv` | Loading credentials from `.env` |
