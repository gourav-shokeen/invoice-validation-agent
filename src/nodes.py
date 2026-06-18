"""Graph nodes; the LLM is only called inside extract()."""
import logging
import os
import time
from pathlib import Path
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from .state import InvoiceData
from .validation import validate_invoice

logger = logging.getLogger("invoice_agent")

# fallback models if the configured one 404s
_FALLBACK_MODELS = ("gemini-flash-latest", "gemini-2.0-flash", "gemini-1.5-flash")

# retry transient errors (429/timeout/5xx)
_TRANSIENT_RETRIES = 3
_TRANSIENT_BACKOFF = (2.0, 5.0, 10.0)

SYSTEM_PROMPT = (
    "You are an invoice data-extraction engine for an e-invoicing compliance "
    "platform (ZUGFeRD / Factur-X, EN 16931). Extract the invoice into the "
    "required structured schema.\n\n"
    "CRITICAL RULES:\n"
    "1. Transcribe every value EXACTLY as printed on the document. Copy the "
    "numbers character-for-character.\n"
    "2. Do NOT recompute, correct, reconcile, or 'fix' any figure. If the "
    "printed subtotal, tax, or total do not add up, transcribe them anyway. "
    "Downstream validation depends on capturing what the document literally "
    "states, not what it 'should' say.\n"
    "3. Express tax_rate as a decimal fraction (e.g. 0.19 for a 19% rate). If "
    "no tax rate is shown, leave it null.\n"
    "4. line_total is the per-line amount as printed; subtotal, tax_amount and "
    "total are the document's own stated figures.\n"
    "5. Use the currency code as printed (e.g. EUR)."
)


class AuthError(RuntimeError):
    """Raised when the Gemini API key is rejected."""


def _classify_error(exc: Exception) -> str:
    msg = str(exc).lower()
    if any(t in msg for t in (
        "api key not valid", "api_key_invalid", "invalid api key",
        "permission denied", "permission_denied", "unauthenticated",
        "401", "403",
    )):
        return "auth"
    if any(t in msg for t in (
        "not_found", "not found", "404",
        "is not found for api version", "is not supported for",
    )):
        return "not_found"
    if any(t in msg for t in (
        "429", "resource_exhausted", "resourceexhausted", "rate limit",
        "quota", "timeout", "timed out", "deadline", "503", "502", "504",
        "unavailable", "overloaded", "internal error", "500",
    )):
        return "transient"
    return "other"


def get_llm(model: Optional[str] = None):
    from langchain_google_genai import ChatGoogleGenerativeAI

    model = model or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise AuthError("GEMINI_API_KEY is not set in the environment.")
    llm = ChatGoogleGenerativeAI(model=model, google_api_key=api_key, temperature=0)
    return llm.with_structured_output(InvoiceData)


def _list_models_safe() -> list[str]:
    api_key = os.getenv("GEMINI_API_KEY")
    try:
        from google import genai  # type: ignore

        client = genai.Client(api_key=api_key)
        names = []
        for m in client.models.list():
            name = getattr(m, "name", "") or ""
            actions = (
                getattr(m, "supported_actions", None)
                or getattr(m, "supported_generation_methods", None)
                or []
            )
            if not actions or "generateContent" in actions:
                names.append(name)
        if names:
            logger.info("Available models: %s", ", ".join(n.split("/")[-1] for n in names))
            return names
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("google-genai listing unavailable: %s", exc)
    try:
        import google.generativeai as gga  # type: ignore

        gga.configure(api_key=api_key)
        names = [
            m.name
            for m in gga.list_models()
            if "generateContent" in getattr(m, "supported_generation_methods", [])
        ]
        if names:
            logger.info("Available models: %s", ", ".join(n.split("/")[-1] for n in names))
            return names
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("google.generativeai listing unavailable: %s", exc)
    return []


def _pick_fallback_model(failed_model: str) -> str:
    for name in _list_models_safe():
        short = name.split("/")[-1]
        if "flash" in short and short != failed_model:
            return short
    for candidate in _FALLBACK_MODELS:
        if candidate != failed_model:
            return candidate
    return _FALLBACK_MODELS[0]


def _build_messages(raw_text: str, prior_errors: Optional[list[str]]) -> list:
    human = (
        "Extract the structured data from this invoice:\n\n"
        f"<INVOICE>\n{raw_text}\n</INVOICE>"
    )
    if prior_errors:
        bullets = "\n".join(f"- {e}" for e in prior_errors)
        human += (
            "\n\nA previous extraction FAILED deterministic validation with these "
            f"issues:\n{bullets}\n\n"
            "Re-examine the document and correct ONLY genuine transcription mistakes "
            "(misread digits, wrong field mapping). Do NOT alter figures that are "
            "printed as-is merely to make the totals reconcile — if the document "
            "itself is inconsistent, transcribe it faithfully."
        )
    return [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=human)]


def _invoke_llm(raw_text: str, prior_errors: Optional[list[str]]):
    messages = _build_messages(raw_text, prior_errors)
    current_model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    tried_fallback = False
    attempt = 0

    while True:
        llm = get_llm(current_model)
        try:
            result = llm.invoke(messages)
            logger.info("Extraction completed via Gemini model '%s'.", current_model)
            return result, current_model
        except Exception as exc:  # noqa: BLE001 - classified and re-raised below
            kind = _classify_error(exc)
            if kind == "auth":
                raise AuthError(str(exc)) from exc
            if kind == "not_found" and not tried_fallback:
                fallback = _pick_fallback_model(current_model)
                logger.warning(
                    "Model '%s' returned NOT_FOUND (%s). Falling back to '%s'.",
                    current_model, exc, fallback,
                )
                current_model = fallback
                tried_fallback = True
                continue
            if kind == "transient" and attempt < _TRANSIENT_RETRIES:
                backoff = _TRANSIENT_BACKOFF[min(attempt, len(_TRANSIENT_BACKOFF) - 1)]
                logger.warning(
                    "Transient API error (%s). Waiting %.0fs then retrying (%d/%d).",
                    exc, backoff, attempt + 1, _TRANSIENT_RETRIES,
                )
                time.sleep(backoff)
                attempt += 1
                continue
            raise


def ingest(state: dict, config: RunnableConfig | None = None) -> dict:
    raw_text = state.get("raw_text") or ""
    source_path = None
    if config:
        source_path = (config.get("configurable") or {}).get("source_path")
    if source_path:
        raw_text = Path(source_path).read_text(encoding="utf-8")
        logger.info("Ingested invoice from %s (%d chars).", source_path, len(raw_text))
    return {
        "raw_text": raw_text,
        "extracted": None,
        "validation_errors": [],
        "status": "pending",
        "attempts": 0,
        "summary": "",
    }


def extract(state: dict) -> dict:
    attempts = state.get("attempts", 0) + 1
    prior_errors = state.get("validation_errors") or []
    feedback = prior_errors if attempts > 1 else None
    result, model_used = _invoke_llm(state["raw_text"], feedback)
    extracted = result.model_dump() if hasattr(result, "model_dump") else dict(result)
    logger.info("Extraction attempt %d complete (model=%s).", attempts, model_used)
    return {"extracted": extracted, "attempts": attempts}


def validate(state: dict) -> dict:
    errors = validate_invoice(state.get("extracted"))
    status = "valid" if not errors else "invalid"
    logger.info("Validation found %d error(s).", len(errors))
    return {"validation_errors": errors, "status": status}


def finalize(state: dict) -> dict:
    data = state.get("extracted") or {}
    summary = (
        f"Invoice {data.get('invoice_number', '?')} from "
        f"{data.get('vendor', '?')} validated successfully. "
        f"{len(data.get('line_items', []))} line item(s); "
        f"total {data.get('total', '?')} {data.get('currency', '')}. "
        f"All EN 16931 consistency checks passed on attempt {state.get('attempts', 1)}."
    )
    return {"status": "valid", "summary": summary}


def flag(state: dict) -> dict:
    errors = state.get("validation_errors") or []
    data = state.get("extracted") or {}
    report = [
        "INVOICE FLAGGED FOR HUMAN REVIEW",
        f"Invoice: {data.get('invoice_number', '?')}   Vendor: {data.get('vendor', '?')}",
        f"Unresolved after {state.get('attempts', 0)} extraction attempt(s) — "
        f"{len(errors)} validation issue(s):",
    ]
    report += [f"  - {e}" for e in errors]
    report.append(
        "Recommended action: a compliance reviewer should reconcile the printed "
        "figures against source records before posting."
    )
    return {"status": "flagged", "summary": "\n".join(report)}
