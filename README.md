# Invoice Validation Agent

A LangGraph state-machine agent that extracts structured data from an invoice and validates its internal arithmetic, with an LLM self-correction cycle and a human-review fallback.

## Context

E-invoicing standards such as **ZUGFeRD / Factur-X** (the German/French hybrid PDF+XML formats built on the European **EN 16931** semantic model) require that an invoice's stated figures be internally consistent — line items must sum to the net, and net plus tax must equal the gross. This agent demonstrates that compliance step: it transcribes an invoice exactly as printed and then runs deterministic checks to decide whether the document can be posted automatically or must be escalated for human review. Crucially, it validates *what the document actually says* — it never silently "fixes" a wrong total.

## Architecture

The agent is an explicit `StateGraph` (not a prebuilt ReAct agent) with a conditional branch and a self-correction cycle.

```
START → ingest → extract → validate ─┬─ (no errors) ──────────────→ finalize → END
                    ▲                │
                    │                ├─ (errors, attempts < MAX) ──→ extract   ← CYCLE
                    └────────────────┘
                                     └─ (errors, attempts ≥ MAX) ──→ flag     → END
```

| Node | Responsibility |
|------|----------------|
| `ingest` | Load invoice text into `raw_text`; reset `attempts`/`status`. |
| `extract` | Call Gemini via `.with_structured_output(InvoiceData)` to transcribe fields **exactly as printed** (no recomputation). On a retry, the prior validation errors are folded into the prompt as feedback. Increments `attempts`. |
| `validate` | **Deterministic, no LLM.** Checks required fields, line-item sum vs. subtotal, subtotal + tax vs. total, tax_amount vs. subtotal × tax_rate, non-empty currency, and no negative amounts. |
| `finalize` | Emit clean JSON + a success summary; `status = "valid"`. |
| `flag` | Emit a human-review report listing unresolved errors; `status = "flagged"`. |

The router after `validate` is the decision point: no errors → `finalize`; errors with attempts remaining → back to `extract` (the **cycle**); errors with attempts exhausted (`MAX_ATTEMPTS = 2`) → `flag`.

**State** (`src/state.py`): `raw_text`, `extracted`, `validation_errors`, `status`, `attempts`, `summary`. The Pydantic `InvoiceData` schema captures vendor, invoice number/date, currency, line items, subtotal, tax_rate, tax_amount, and total.

### Sample behaviour

- `samples/clean_invoice.txt` — math is internally consistent (line items sum to subtotal; subtotal + 19% VAT = total). Faithful extraction → passes validation → **finalize**.
- `samples/broken_invoice.txt` — the printed figures are deliberately inconsistent (Subtotal 100.00, Tax 19.00, Total 150.00). Faithful extraction records `total = 150`, the validator catches `subtotal + tax ≠ total`, the cycle retries up to `MAX_ATTEMPTS`, and the invoice is **flagged**.

## Setup

Requires Python 3.11+. Using [`uv`](https://github.com/astral-sh/uv) (recommended):

```bash
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -r requirements.txt          # runtime deps
uv pip install -r requirements-dev.txt      # + pytest
```

Or with stdlib `venv`:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

Configure secrets — copy `.env.example` to `.env` and set your key:

```bash
cp .env.example .env
# edit .env:
#   GEMINI_API_KEY=your-key-here
#   GEMINI_MODEL=gemini-2.5-flash
#   USE_MOCK_LLM=0
```

`.env` is git-ignored and must never be committed.

## Run

Live mode (calls the Gemini API — the default):

```bash
python -m src.main --sample clean     # consistent invoice → status "valid"
python -m src.main --sample broken     # inconsistent invoice → status "flagged"
python -m src.main --file path/to/invoice.txt
```

Each run prints the compiled graph diagram (mermaid), then the final state: status, extracted JSON, validation errors, and a summary. Exit code `0` means the run completed (valid **or** flagged); exit code `2` means the Gemini key was rejected.

Offline / mock mode (deterministic, no network — useful for demos or CI):

```bash
USE_MOCK_LLM=1 python -m src.main --sample clean
```

## Tests

The unit tests cover the deterministic validator only — no API key or network required:

```bash
pytest                # or: python -m pytest -v
```

## Error handling

- **Auth failure** (invalid/blocked key) → the run halts immediately with exit code 2 and reports the exact error. It never falls back to mock.
- **Model 404 / NOT_FOUND** → the agent lists available models, falls back to a flash-tier model, retries once, and logs which model was used.
- **Transient errors** (429 / timeout / 5xx) → retried in place with short backoff; these are not treated as extraction attempts.

## Future Enhancements

- **ZUGFeRD / Factur-X XML export** — emit a validated EN 16931 CII XML alongside the JSON, and ingest the embedded XML directly from PDF/A-3 invoices.
- **Batch processing** — fan out across an invoice folder or queue with per-document status reporting.
- **Per-field confidence scores** — surface extraction confidence so reviewers can prioritise low-certainty fields.
- **Human-in-the-loop approval gate** — pause flagged invoices on an interrupt and resume after a reviewer's decision (LangGraph checkpointer + `interrupt`).
- **ERP push** — post validated invoices to an accounting/ERP system (e.g. DATEV, SAP) on success.
