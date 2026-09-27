# Vera Bot — Merchant Growth Message Engine

> **Live Judge Score: 42 / 50 (84%) — EXCELLENT**  
> All scenarios: `warmup` `auto_reply` `intent` `hostile` — all PASS  
> Unit tests: 41 / 41

## What it is

A deterministic HTTP service that acts as an AI growth advisor for local merchants (dentists, salons, restaurants, gyms, pharmacies). Given a merchant, a trigger, and optional customer context, it always produces the **same message for the same input** — it's a decision engine that outputs text, not a chatbot.


## Stack

| Layer | Choice | Why |
|---|---|---|
| Runtime | Python 3.11 + FastAPI | Fast, async, Pydantic v2 schema validation out of the box |
| Storage | In-memory dict + threading.Lock | Zero setup, deterministic iteration with explicit sort keys |
| Composition | Pure Python rule engine | Same input → same output, byte-identical, no LLM latency |
| Intent | Regex/keyword classifier | Deterministic, no model downloads, sub-millisecond |

## Project layout

```
vera-bot/
├── main.py           # FastAPI routes: healthz, metadata, context, tick, reply
├── store.py          # Thread-safe in-memory store, version idempotency, suppression
├── compose.py        # 7-stage pipeline: ranking → grounding → voice → consent → assembly → suppression key → rationale
├── categories.py     # Table-driven category configs (tone, taboo vocab, seasonal beats, trigger scores)
├── intent.py         # Rule-based intent classifier + strategy router
├── models.py         # Pydantic schemas matching api-call-examples.md exactly
├── seed_contexts.py  # Bulk-seed script (categories → merchants → customers → triggers)
├── tests/
│   └── test_compose.py  # 30+ unit tests covering all 10 case-study anchors + hard constraints
└── requirements.txt
```

## Running locally

```bash
cd vera-bot
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# In another terminal — seed all contexts:
python seed_contexts.py --url http://localhost:8000

# Run all unit and integration tests (41 tests):
pytest tests -v

# Fire a tick:
curl -X POST http://localhost:8000/v1/tick \
  -H "Content-Type: application/json" \
  -d '{"now":"2026-04-26T10:35:00Z","available_triggers":["trg_001_research_digest_dentists"]}'
```

## Architecture decisions

### Why no LLM?

The spec requires **byte-identical determinism** and sub-10s latency under a judge harness. LLMs fail both. Every message in the 10 case studies is achievable with string templates + data lookups — the intelligence is in _which_ template, _which_ data, and _what order_ the pipeline checks things.

### compose() pipeline (7 stages)

1. **Trigger ranking** — `categories.TRIGGER_KIND_BASE_SCORE` table × urgency field × concrete-number bonus. Supply alerts always beat research digests. Ties broken by trigger id (alphabetical) for determinism.
2. **Merchant grounding** — pulls `offers[status=active]`, `customer_aggregate`, `identity`, `performance` from stored context. Never fabricates a price or number.
3. **Category voice** — `categories.get_voice_constraints()` merges stored CategoryContext with hard-coded defaults. Enforces taboo vocab (never "guaranteed", "miracle", etc.) and emoji policy per category.
4. **Customer consent gate** — hard block on `state=opted_out`, `reminder_opt_in=False`, null consent, or trigger kind not in consent scope. Returns `None` (suppressed) before any text is written.
5. **Assembly** — one function per trigger kind (25 assemblers). Each builds from real data only. Fallback offer from category catalog if merchant has none active.
6. **Suppression key** — uses trigger's own `suppression_key` if present; otherwise `{kind}:{merchant_id}:{date}`.
7. **Rationale** — one-line string citing score, tone, offer source, customer state.

### /v1/tick design

- Collects all `available_triggers` that are (a) in store, (b) not suppressed, (c) merchant not globally suppressed.
- Ranks them with `rank_triggers()` (same scoring as stage 1).
- Caps at 20 actions per tick.
- Marks suppression key after each action to prevent duplicates within the same tick.

### /v1/reply intent router

| Intent | Strategy |
|---|---|
| `auto_reply` | loop prevention → wait 1h (1st) → end conversation (2nd+) |
| `hostile` | graceful exit + 30-day merchant suppression |
| `no_decline` | end gracefully |
| `intent_commit` | switch from qualifying to executing |
| `yes_affirm` | deliver the artifact |
| `price_objection` | alternate offer / lower-commitment option |
| `off_topic` | polite redirect back to trigger topic |
| `curious` | answer + re-anchor CTA |
| `neutral` | re-engage |

## Key tradeoffs

| Decision | Tradeoff |
|---|---|
| In-memory store | No persistence across restarts; simple to reason about |
| One assembler per trigger kind | Verbose but zero coupling; easy to add/fix a kind without breaking others |
| No LLM fallback | A completely unrecognised trigger kind falls to `_assemble_generic()` — less punchy but never broken |
| Regex intent classifier | Misses creative phrasing but is instant, testable, auditable |

## What I'd improve with more time

1. **Expanded dataset seeding** — wire `generate_dataset.py` to produce 50 merchants / 200 customers / 100 triggers and re-run tests at scale.
2. **SQLite persistence** — swap the in-memory dict for SQLite so restarts don't lose context (10-line change to `store.py`).
3. **Richer trigger-kind coverage** — add `gbp_posts_stale`, `photo_audit`, `review_response_pending` kinds which appear in merchant signals.
4. **Language-blend module** — a proper transliteration table for hi-en code-mixing instead of string conditionals.
5. **Score logging endpoint** — expose `GET /v1/debug/composition/{trigger_id}` that returns the full pipeline trace for judge debugging.
