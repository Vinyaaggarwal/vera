# Vera — Merchant Growth Message Engine

> **magicpin AI Challenge Entry**  
> Team: Vera Bot | Model: `deterministic-rule-engine-v1`

---

## Live Judge Evaluation Results

| Dimension | Score |
|:--|:--:|
| Decision Quality | **8 / 10** |
| Specificity | **9 / 10** |
| Category Fit | **9 / 10** |
| Merchant Fit | **8 / 10** |
| Engagement Compulsion | **8 / 10** |
| **Average Total** | **42 / 50 (84%) — EXCELLENT** |

Behavioral scenario results:

| Scenario | Result |
|:--|:--:|
| Warmup (healthz, metadata, context push) | PASS |
| Auto-Reply Loop Detection | PASS |
| Intent Transition (qualifying to action) | PASS |
| Hostile Merchant Opt-Out | PASS |
| Unit Test Suite (41 tests) | 41 / 41 |

---

## What is Vera?

Vera is a **deterministic** message-composition service for local merchants — dentists, salons, restaurants, gyms, and pharmacies. Given a merchant, a trigger, and optional customer context, it always produces **the same message for the same input**. It is a decision engine that outputs text, not a chatbot or LLM wrapper.

```
Same input -> Same output. Always. No randomness.
```

---

## Repository Layout

```
vera/
├── README.md                        <- you are here
├── requirements.txt                 <- top-level project dependencies
├── .env.example                     <- template for local test runs (API key in local .env, gitignored)
├── .gitignore                       <- excludes secrets (.env) and caches from git
├── bot.py                           <- official entrypoint: compose(category, merchant, trigger, customer)
├── submission.jsonl                 <- pre-computed outputs for 30 canonical test pairs
├── conversation_handlers.py         <- multi-turn reply handler: respond(state, merchant_message)
├── judge_simulator.py               <- official magicpin judge harness
├── dataset/
│   ├── categories/                  <- 5 category JSONs (dentists, salons, ...)
│   ├── merchants_seed.json          <- 10 merchants
│   ├── customers_seed.json          <- 15 customers
│   └── triggers_seed.json           <- 25 triggers across all categories
├── Examples/
│   ├── api-call-examples.md         <- official API spec examples
│   └── case-studies.md              <- 10 reference case-study scenarios
├── challenge-brief.md               <- full challenge specification
├── challenge-testing-brief.md       <- judge testing specification
└── vera-bot/                        <- the bot implementation
    ├── main.py                      <- FastAPI routes
    ├── compose.py                   <- 7-stage composition pipeline (25 assemblers)
    ├── store.py                     <- thread-safe in-memory context store
    ├── categories.py                <- table-driven category configs
    ├── intent.py                    <- regex intent classifier + strategy router
    ├── models.py                    <- Pydantic request/response schemas
    ├── seed_contexts.py             <- bulk-seed script
    ├── requirements.txt             <- Python dependencies
    └── tests/
        ├── test_compose.py          <- 37 unit tests
        └── test_judge_scenarios.py  <- 4 behavioral integration tests
```

---

## Quick Start

### 1. Install dependencies

```bash
cd vera-bot
pip install -r requirements.txt
```

### 2. Start the server

```bash
uvicorn main:app --port 8000 --host 0.0.0.0
```

### 3. Seed all contexts

```bash
python seed_contexts.py
```

### 4. Fire a tick

```bash
curl -X POST http://localhost:8000/v1/tick \
  -H "Content-Type: application/json" \
  -d '{
    "now": "2026-04-26T10:35:00Z",
    "available_triggers": [
      "trg_001_research_digest_dentists",
      "trg_002_compliance_dci_radiograph",
      "trg_003_recall_due_priya"
    ]
  }'
```

### 5. Run the judge

```bash
# Create a .env file in the repo root with:
# GCP_API_KEY=your_gemini_key_here

python judge_simulator.py
```

### 6. Run unit tests

```bash
cd vera-bot
pytest tests/ -v
```

---

## API Endpoints

| Method | Path | Description |
|:--|:--|:--|
| GET | /v1/healthz | Liveness check |
| GET | /v1/metadata | Static bot metadata (team, model, categories) |
| POST | /v1/context | Ingest a context object (category / merchant / customer / trigger) |
| POST | /v1/tick | Evaluate available triggers and return composed actions |
| POST | /v1/reply | Handle merchant/customer reply with intent routing |
| POST | /v1/reset | Test helper — clear suppressions for a clean run |

---

## How Each Scoring Criterion Is Met

### Decision Quality
`rank_triggers()` computes a composite priority score per trigger:
- Trigger-kind base score (supply alert > renewal > perf dip > research digest)
- Urgency field weight (x25 multiplier)
- Merchant state affinity (e.g. perf dip trigger preferred for merchants with falling CTR)

Only the highest-priority, non-suppressed trigger per merchant proceeds to composition.

### Specificity
Every assembler extracts real values from the payload — no fabrication:
- Exact regulatory deadlines and regulation codes (DCI Radiograph 2026, deadline 15 Dec)
- Exact slot times from available_slots in the trigger payload
- Exact trial sizes, page citations, efficacy percentages from research digest items
- Exact offer prices from the merchant active offer catalog only

### Category Fit
`categories.py` defines per-category voice constraints enforced at compose time:

| Category | Tone | Taboo Words |
|:--|:--|:--|
| Dentists | peer-clinical, collegial | "discount", "guaranteed", "miracle", "best in city" |
| Salons | aesthetic, trend-forward, visual | "cheap", "bargain", medical terms |
| Gyms | high-energy, metric-driven | "easy", "relax", "slow" |
| Restaurants | sensory, cover-count, time-sensitive | "cheap food", clinical phrasing |
| Pharmacies | compliance-first, fast utility | wellness hype, "guarantee" |

### Merchant Fit
Every message uses: owner first name, locality, active offers, performance metrics,
language preference (hi-en code mixing), and prior conversation state.

### Engagement Compulsion
Every message ends with exactly one low-friction CTA:
- Binary: "Reply YES / NO"
- Multi-choice: "Reply 1 for Wed 6pm or 2 for Thu 5pm"
- Confirmation: "Reply CONFIRM to proceed"

---

## Hard Constraints

| Constraint | How Vera Handles It |
|:--|:--|
| Determinism | Zero randomness; pure rule + template pipeline |
| Hostile opt-out | Intent hostile -> immediate end + 30-day merchant suppression |
| Auto-reply loop | Intent auto_reply -> wait 1h on first detection, end on second |
| No fake claims | Prices/dates/numbers only extracted from provided payload |
| Single CTA | Each assembler specifies exactly one CTA type |
| Suppression key | Uses trigger suppression_key; enforced before and after sending |

---

## Architecture

### compose() Pipeline (7 stages)

1. **Trigger ranking** — priority score = base score + urgency x25 + merchant affinity
2. **Merchant grounding** — pulls active offers, customer aggregate, identity, performance from stored context
3. **Category voice** — enforces taboo vocab, emoji policy, tone register per category
4. **Customer consent gate** — hard block on opted_out, reminder_opt_in=False, null consent
5. **Assembly** — one deterministic assembler function per trigger kind (25 total)
6. **Suppression key** — uses trigger suppression_key or falls back to kind:merchant_id:date
7. **Rationale** — one-line string citing score, tone, offer source, customer state

### Intent Router

| Intent | Strategy |
|:--|:--|
| auto_reply | wait 1h on first hit; end on second |
| hostile | graceful exit + 30-day merchant suppression |
| no_decline | end gracefully |
| intent_commit | switch from qualifying to executing |
| yes_affirm | deliver the artifact |
| price_objection | alternate offer / lower-commitment option |
| off_topic | polite redirect |
| curious | answer + re-anchor CTA |
| neutral | re-engage |
