# Invoice Validation Agent

Extracts structured data from an invoice with an LLM and checks that the figures printed on the document are internally consistent.

## Context

E-invoicing formats like ZUGFeRD and Factur-X are built on the EN 16931 data model, which requires an invoice's numbers to add up: line items sum to the net, and net plus tax equals the gross. This tool runs that check. It transcribes an invoice exactly as printed and then validates the arithmetic, so it can decide whether a document is safe to post automatically or needs a human to look at it. It does not correct wrong totals — an inconsistent document is reported, not silently fixed.

## Architecture

A LangGraph `StateGraph` with a deterministic validation step and a retry loop:

```
ingest -> extract -> validate
                       |
                       |-- no errors ............. finalize  (status: valid)
                       |-- errors, attempts < 2 ... back to extract
                       |-- errors, attempts >= 2 .. flag      (status: flagged)
```

- `ingest` reads the invoice text and resets the run counters.
- `extract` calls Gemini with `with_structured_output(InvoiceData)` and transcribes the fields as printed. On a retry it feeds the previous validation errors back to the model.
- `validate` runs deterministically, no LLM: required fields present, line items sum to the subtotal, subtotal + tax equals the total, tax equals subtotal * rate, currency present, no negative amounts.
- `finalize` writes a short summary and sets status to `valid`.
- `flag` writes a human-review report and sets status to `flagged`.

The router after `validate` sends a clean invoice to `finalize`. If there are errors it loops back to `extract` up to `MAX_ATTEMPTS` (2), then routes to `flag`. The state passed between nodes (`src/state.py`) holds the raw text, the extracted dict, the validation errors, the status, the attempt count, and the summary.

## Setup

Python 3.11 or newer.

```
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and set your key:

```
GEMINI_API_KEY=your-key
GEMINI_MODEL=gemini-2.5-flash
USE_MOCK_LLM=0
```

`.env` is git-ignored.

## Run

Live mode calls Gemini:

```
python -m src.main --sample clean      # consistent invoice, ends valid
python -m src.main --sample broken     # inconsistent invoice, ends flagged
python -m src.main --file path/to/invoice.txt
```

Each run prints the compiled graph diagram, then the final state: status, extracted JSON, validation errors, and summary. Exit code 0 means the run completed (valid or flagged); exit code 2 means the API key was rejected.

Mock mode runs offline with a deterministic parser, no network:

```
USE_MOCK_LLM=1 python -m src.main --sample clean
```

## Tests

The tests cover the validator only and need no API key or network. pytest is the one extra dependency:

```
pip install pytest
python -m pytest
```

## Error handling

- Rejected key: the run stops with exit code 2 and prints the error. It does not fall back to the mock.
- Unknown model name (404): lists available models, retries once on a flash-tier model, and logs the model used.
- Transient errors (429, timeout, 5xx): retried with backoff and not counted as extraction attempts.

## Future work

- ZUGFeRD / Factur-X XML export: emit EN 16931 CII XML next to the JSON, and read embedded XML from PDF/A-3 invoices.
- Batch processing over a folder or queue.
- Per-field confidence scores.
- Human-in-the-loop approval gate using a LangGraph checkpointer and interrupt.
- Push validated invoices to an ERP such as DATEV or SAP.
