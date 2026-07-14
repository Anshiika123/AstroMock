# astromock

Vedic astrology monorepo.

```
astromock/
  apps/
    web/                 Flask app: kundali UI, /api/kundali, /api/ask,
                         /api/horoscope ("Your Guidance"), LLM provider
  packages/
    core/                Calculation engine (single source of truth):
                         kundali (D-1), navamsa (D-9), Vimshottari dasha,
                         gochar/transits, house analysis, topic->house
                         routing, BPHS retrieval (book_index.json),
                         interpretation prompt, North Indian SVG charts
    astromock-mcp/       MCP server exposing core as tools for Claude
                         Desktop / any MCP client (stdio or --http)
```

## Setup

Core is an installable package; both apps consume it editable:

```powershell
# web app
cd apps\web
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python app.py

# MCP server
cd packages\astromock-mcp
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python server.py          # stdio (Claude Desktop)
.venv\Scripts\python server.py --http   # Streamable HTTP on :8000/mcp
```

Claude Desktop config points at the MCP venv + server.py inside
`packages/astromock-mcp` (see its README).

One-time BPHS index (already committed as
`packages/core/book_index.json`; rebuild with a new book):

```powershell
cd packages\core
python book_retriever.py path\to\book.pdf
```

## Legacy layout note

The `.py` files at the repo root (and the separate `astromock-mcp/` folder
in Downloads) are the pre-monorepo layout, kept for reference. The
canonical, tested code now lives in `apps/web/` and `packages/` — make new
changes there; the copies will drift if the root files keep being edited.
Claude Desktop should now point at
`packages\astromock-mcp\server.py` (with that package's venv).
