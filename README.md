[![MCP Badge](https://lobehub.com/badge/mcp/ljove02-krpc-mcp)](https://lobehub.com/mcp/ljove02-krpc-mcp)
# krpc-mcp

An MCP server that gives AI models access to the full [kRPC](https://krpc.github.io/krpc/) Python documentation.

## What is this?

If you use AI assistants (Claude, ChatGPT, Codex, etc.) to write kRPC Python code for Kerbal Space Program, the models often guess or hallucinate API calls because kRPC's documentation is uncommon in their training data. This MCP server solves that by letting the AI query the real documentation before writing code.

The server crawls and indexes all kRPC Python API pages, caches them locally, and exposes them through 4 search/retrieval tools via the [Model Context Protocol](https://modelcontextprotocol.io/).

## Quick Start

Pick your AI client below and run the setup command. That's it -- the AI will automatically have access to kRPC docs.

### Claude Code (CLI)

```bash
claude mcp add krpc-mcp -- uvx krpc-mcp
```

### OpenAI Codex CLI

```bash
codex mcp add krpc-mcp -- uvx krpc-mcp
```

Or add it manually to `~/.codex/config.toml`:

```toml
[mcp_servers.krpc-mcp]
command = "uvx"
args = ["krpc-mcp"]
```

### Claude Desktop

Add this to your `claude_desktop_config.json`:

| OS      | Config file location                                              |
|---------|-------------------------------------------------------------------|
| macOS   | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json`                     |

```json
{
  "mcpServers": {
    "krpc-mcp": {
      "command": "uvx",
      "args": ["krpc-mcp"]
    }
  }
}
```

### Cursor

Add this to `.cursor/mcp.json` in your project root:

```json
{
  "mcpServers": {
    "krpc-mcp": {
      "command": "uvx",
      "args": ["krpc-mcp"]
    }
  }
}
```

### Other MCP clients

Any MCP client that supports stdio transport can use this server. The command is:

```
uvx krpc-mcp
```

## Alternative Installation

If you don't have or don't want to use `uvx`, there are other ways to install.

### pip install from GitHub

```bash
pip install git+https://github.com/Ljove02/krpc-mcp.git
```

Then use `krpc-mcp` as the command in any of the configs above (instead of `uvx krpc-mcp`).

### Manual setup (for development)

```bash
git clone https://github.com/Ljove02/krpc-mcp.git
cd krpc-mcp
python -m venv .venv
```

Activate the virtual environment:

```bash
# macOS / Linux
source .venv/bin/activate

# Windows (PowerShell)
.\.venv\Scripts\Activate.ps1

# Windows (cmd)
.venv\Scripts\activate.bat
```

Install and run:

```bash
pip install -e .
krpc-mcp
```

## Available Tools

Once connected, your AI assistant gets these tools:

| Tool | Parameters | Description |
|------|-----------|-------------|
| `search_docs` | `query` (str), `limit` (int, default 5) | Search all indexed kRPC Python docs by keyword. Returns matching pages with snippets. |
| `get_doc_page` | `slug_or_url` (str) | Get the full content of a specific docs page. Accepts a slug like `python/api/space-center/vessel.html` or a full URL. |
| `get_api_member` | `service` (str), `class_name` (str), `member` (str) | Look up a specific API member. For example: `service="SpaceCenter"`, `class_name="Vessel"`, `member="orbit"`. Uses fuzzy matching. |
| `reindex_docs` | `force` (bool, default false) | Manually trigger a re-crawl of the kRPC documentation. |

## Example: Real Usage

Here's what it looks like when an AI assistant uses krpc-mcp. In this test, Claude Code was asked about vessel launch telemetry data.

### User prompt

> *"Give me info about all kinds of data we can get from a launching vessel -- speed, altitude, g-force. Give me 5 examples in detail so I can cross-check with the docs."*

### What the AI did behind the scenes

The AI automatically called the MCP tools to look up real documentation before answering:

```
Tool call:  search_docs(query="vessel flight telemetry speed altitude", limit=5)
Result:     3 matching pages found, including Flight and Vessel API references

Tool call:  search_docs(query="g force flight data", limit=5)
Result:     Matched the Flight API page

Tool call:  get_doc_page(slug_or_url="python/api/space-center/flight.html")
Result:     Full Flight class documentation (104 lines of API details)

Tool call:  get_doc_page(slug_or_url="python/api/space-center/vessel.html")
Result:     Full Vessel class documentation (173 lines of API details)
```

### AI response (sourced from real docs)

| # | Property | Class | Returns | Description |
|---|----------|-------|---------|-------------|
| 1 | `Flight.speed` | Flight | `float` | Speed in m/s in the given reference frame. Pass an appropriate reference frame (e.g. `vessel.orbit.body.reference_frame`) to get meaningful values. |
| 2 | `Flight.mean_altitude` | Flight | `float` | Altitude above sea level in meters. Related: `surface_altitude`, `bedrock_altitude`, `elevation`. |
| 3 | `Flight.g_force` | Flight | `float` | Current G-force in multiples of 9.81 m/s². Useful for monitoring crew safety and structural stress during launch. |
| 4 | `Flight.dynamic_pressure` | Flight | `float` | Dynamic pressure (Q) in Pascals. Equal to `0.5 * air_density * velocity²`. Critical for identifying Max Q during ascent. |
| 5 | `Flight.mach` | Flight | `float` | Speed as a multiple of the speed of sound. Related: `speed_of_sound`, `true_air_speed`, `terminal_velocity`. |

All properties are **read-only** and available in the **Flight** game scene. The AI pulled every detail -- types, descriptions, related members -- directly from the indexed docs instead of guessing.

## How It Works

1. On first use, the server crawls all Python documentation pages from `https://krpc.github.io/krpc/python.html`
2. It extracts page content and API member signatures/descriptions
3. Everything is cached locally at `~/.cache/krpc-mcp/`
4. The cache auto-refreshes every 24 hours
5. You can force a refresh anytime with the `reindex_docs` tool

## License

[MIT](LICENSE)
