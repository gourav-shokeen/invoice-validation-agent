# Invoice Validation Agent

I built this to check whether the numbers on an invoice actually add up. It's aimed at e-invoicing — formats like ZUGFeRD and Factur-X build on the EN 16931 model, which expects line items to sum to the net and net plus tax to equal the gross. So the job is: read an invoice, pull out the figures, and confirm they're consistent.

It works in two steps. Gemini transcribes the invoice into structured fields, then plain Python checks the arithmetic. I deliberately don't let the model do the math — I don't trust an LLM to add, and the whole point is catching documents where the totals are wrong. If a check fails, it feeds the errors back and asks for a re-extract a couple of times before giving up and flagging the invoice for a human.

To run it, set `GEMINI_API_KEY` in `.env`. You can optionally set `GEMINI_MODEL`; otherwise it defaults to `gemini-2.5-flash`.

```
python3 -m src.main --sample clean
python3 -m src.main --sample broken
```

Stuff I'd add later: emitting ZUGFeRD/Factur-X XML, running over a batch instead of one invoice at a time, and a real approval step for the flagged ones.
