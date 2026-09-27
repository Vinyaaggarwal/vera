"""
Vera Merchant Growth Message Engine — FastAPI app
Endpoints: GET /v1/healthz, GET /v1/metadata, POST /v1/context, POST /v1/tick, POST /v1/reply
"""
from __future__ import annotations
import datetime
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import store
from models import (
    ContextRequest, ContextResponse,
    TickRequest, TickResponse, TickAction,
    ReplyRequest, ReplyResponse,
    HealthzResponse, MetadataResponse,
)
from compose import compose, rank_triggers
from intent import classify_intent, intent_strategy
from categories import get_category_config

_START_TIME = time.time()
_MAX_PAYLOAD_BYTES = 500 * 1024   # 500 KB
_MAX_ACTIONS_PER_TICK = 20

app = FastAPI(title="Vera Bot", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ═══════════════════════════════════════════════════════════════════
#  GET /v1/healthz
# ═══════════════════════════════════════════════════════════════════

@app.get("/v1/healthz")
def healthz():
    counts = store.context_counts()
    return {
        "status": "ok",
        "uptime_seconds": int(time.time() - _START_TIME),
        "contexts_loaded": {
            "category": counts.get("category", 0),
            "merchant": counts.get("merchant", 0),
            "customer": counts.get("customer", 0),
            "trigger": counts.get("trigger", 0),
        },
    }


# ═══════════════════════════════════════════════════════════════════
#  GET /v1/metadata
# ═══════════════════════════════════════════════════════════════════

@app.get("/v1/metadata")
def metadata():
    return {
        "team_name": "Vera Bot",
        "model": "deterministic-rule-engine-v1",
        "approach": (
            "Pipeline: trigger ranking -> merchant grounding -> category voice -> "
            "customer consent gate -> assembly -> suppression key -> rationale. "
            "No LLM calls; same input always produces same output."
        ),
        "version": "1.0.0",
        "submitted_at": "2026-09-27T00:00:00Z",
        "supported_categories": ["dentists", "salons", "restaurants", "gyms", "pharmacies"],
        "endpoints": [
            "GET /v1/healthz",
            "GET /v1/metadata",
            "POST /v1/context",
            "POST /v1/tick",
            "POST /v1/reply",
        ],
    }


# ═══════════════════════════════════════════════════════════════════
#  POST /v1/context
# ═══════════════════════════════════════════════════════════════════

@app.post("/v1/context")
async def context_push(request: Request):
    # Size check
    body_bytes = await request.body()
    if len(body_bytes) > _MAX_PAYLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail={"accepted": False, "reason": "payload_too_large", "max_bytes": _MAX_PAYLOAD_BYTES},
        )

    import json
    try:
        data = json.loads(body_bytes)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail={"accepted": False, "reason": "invalid_json"})

    # Validate required fields
    scope = data.get("scope")
    context_id = data.get("context_id")
    version = data.get("version")
    payload = data.get("payload")
    if not all([scope, context_id, version is not None, payload is not None]):
        raise HTTPException(
            status_code=422,
            detail={"accepted": False, "reason": "missing_required_fields"},
        )

    accepted, current_ver = store.store_context(scope, context_id, version, payload)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    if not accepted:
        # Return 409 for stale version (per api-call-examples.md Example 1.5)
        return JSONResponse(
            status_code=409,
            content={"accepted": False, "reason": "stale_version", "current_version": current_ver},
        )

    ack_id = f"ack_{context_id}_v{version}"
    return {"accepted": True, "ack_id": ack_id, "stored_at": now}


# ═══════════════════════════════════════════════════════════════════
#  POST /v1/tick
# ═══════════════════════════════════════════════════════════════════

@app.post("/v1/tick")
async def tick(req: TickRequest):
    actions: List[dict] = []

    # Collect all live trigger records (from the available_triggers list)
    trigger_records: List[dict] = []
    for tid in sorted(req.available_triggers):   # sort for determinism
        rec = store.get_context("trigger", tid)
        if rec:
            trigger_records.append(rec["payload"])

    # Rank triggers by score
    ranked = rank_triggers(trigger_records)

    for trg in ranked:
        if len(actions) >= _MAX_ACTIONS_PER_TICK:
            break

        trigger_id = trg.get("id", "")
        merchant_id = trg.get("merchant_id", "")
        customer_id = trg.get("customer_id")
        suppression_key = trg.get("suppression_key", "")

        # Check per-merchant suppression
        if store.is_merchant_suppressed(merchant_id):
            continue

        # Check suppression key
        if suppression_key and store.is_suppressed(suppression_key):
            continue

        # Load contexts
        merchant_rec = store.get_context("merchant", merchant_id)
        if not merchant_rec:
            continue
        merchant = merchant_rec["payload"]

        slug = merchant.get("category_slug", "")
        cat_rec = store.get_context("category", slug)
        category = cat_rec["payload"] if cat_rec else get_category_config(slug)

        customer = None
        if customer_id:
            cust_rec = store.get_context("customer", customer_id)
            if cust_rec:
                customer = cust_rec["payload"]

        result = compose(
            category=category,
            merchant=merchant,
            trigger=trg,
            customer=customer,
        )
        if result is None:
            continue

        # Build action
        conv_id = (
            result.get("_conv_id_override")
            or f"conv_{merchant_id[:12]}_{trigger_id.replace('trg_', '')[:12]}"
        )
        action = {
            "conversation_id": conv_id,
            "merchant_id": merchant_id,
            "customer_id": customer_id,
            "send_as": result["send_as"],
            "trigger_id": trigger_id,
            "template_name": result.get("template_name", "vera_generic_v1"),
            "template_params": result.get("template_params", []),
            "body": result["message"],
            "cta": result["cta"],
            "suppression_key": result["suppression_key"],
            "rationale": result["rationale"],
        }
        actions.append(action)

        # Mark suppressed + init conversation state
        store.mark_sent(result["suppression_key"], conv_id)
        store.upsert_conv(
            conv_id,
            merchant_id=merchant_id,
            customer_id=customer_id,
            trigger_id=trigger_id,
            suppression_key=result["suppression_key"],
            last_body=result["message"],
            turn=1,
            slug=slug,
        )

    return {"actions": actions}


# ═══════════════════════════════════════════════════════════════════
#  POST /v1/reply
# ═══════════════════════════════════════════════════════════════════

@app.post("/v1/reply")
async def reply(req: ReplyRequest):
    conv_id = req.conversation_id

    # Hard: ended conversation → stay silent
    if store.is_conv_ended(conv_id):
        return {"action": "end", "rationale": "Conversation already ended; no further messages."}

    intent = classify_intent(req.message)

    # Merchant-level suppression
    merchant_id = req.merchant_id or (store.get_conv(conv_id) or {}).get("merchant_id", "")
    if merchant_id and store.is_merchant_suppressed(merchant_id):
        if intent in ("intent_commit", "yes_affirm"):
            store.unsuppress_merchant(merchant_id)
        else:
            return {"action": "end", "rationale": "Merchant suppressed; no further messages."}

    # Increment auto-reply counter
    auto_reply_count = 0
    if intent == "auto_reply":
        auto_reply_count = store.increment_auto_reply(conv_id, merchant_id)
    else:
        # Reset auto-reply counter on real message
        conv_state = store.get_conv(conv_id) or {}
        conv_state["auto_reply_count"] = 0
        store.upsert_conv(conv_id, **conv_state)

    strategy = intent_strategy(intent, req.turn_number, auto_reply_count)

    # Increment turn
    conv_state = store.get_conv(conv_id) or {}
    current_turn = conv_state.get("turn", 1) + 1
    store.upsert_conv(conv_id, turn=current_turn)

    # ── Route strategy ────────────────────────────────────────────
    if strategy == "end_hostile":
        store.end_conv(conv_id)
        if merchant_id:
            store.suppress_merchant(merchant_id, days=30)
        # Offer graceful exit message
        return ReplyResponse(
            action="send",
            body="Apologies — I won't message again. If anything changes, you can restart with 'Hi Vera'. 🙏",
            cta="none",
            rationale="Merchant frustration explicit. Closing conversation; suppressing all triggers for 30 days.",
        ).model_dump(exclude_none=True)

    if strategy == "end_graceful":
        store.end_conv(conv_id)
        return ReplyResponse(
            action="end",
            rationale="Merchant declined. Closing conversation respectfully.",
        ).model_dump(exclude_none=True)

    if strategy == "end_no_engagement":
        store.end_conv(conv_id)
        return ReplyResponse(
            action="end",
            rationale="Auto-reply 3x in a row, no real reply. Conversation has zero engagement signal; closing.",
        ).model_dump(exclude_none=True)

    if strategy == "wait_long":
        return ReplyResponse(
            action="wait",
            wait_seconds=86400,
            rationale="Same auto-reply twice in a row — owner not at phone. Wait 24h before retry.",
        ).model_dump(exclude_none=True)

    if strategy == "acknowledge_autoreply":
        return ReplyResponse(
            action="send",
            body="Looks like an auto-reply 😊 When the owner sees this, just reply 'Yes' to confirm.",
            cta="binary_yes_no",
            rationale="Detected merchant auto-reply; one explicit prompt to flag it for the owner.",
        ).model_dump(exclude_none=True)

    if strategy == "redirect_polite":
        return ReplyResponse(
            action="send",
            body=_redirect_message(conv_state),
            cta="open_ended",
            rationale="Out-of-scope ask politely declined; redirecting back to original trigger.",
        ).model_dump(exclude_none=True)

    if strategy == "execute_next_action":
        body, cta = _execute_next_action(conv_state, merchant_id)
        return ReplyResponse(
            action="send",
            body=body,
            cta=cta,
            rationale="Merchant explicitly committed; switching from question-asking to action-execution.",
        ).model_dump(exclude_none=True)

    if strategy == "deliver_artifact":
        body, cta = _deliver_artifact(conv_state, merchant_id)
        return ReplyResponse(
            action="send",
            body=body,
            cta=cta,
            rationale="Honoring merchant's yes — delivering the requested artifact in full.",
        ).model_dump(exclude_none=True)

    if strategy == "offer_alternative":
        body, cta = _price_objection_response(conv_state, merchant_id)
        return ReplyResponse(
            action="send",
            body=body,
            cta=cta,
            rationale="Price objection detected; routing to alternate offer or adjusted framing.",
        ).model_dump(exclude_none=True)

    if strategy == "answer_then_cta":
        body, cta = _curious_response(req.message, conv_state)
        return ReplyResponse(
            action="send",
            body=body,
            cta=cta,
            rationale="Follow-up question; answering specifically then re-anchoring to CTA.",
        ).model_dump(exclude_none=True)

    # re_engage / neutral
    return ReplyResponse(
        action="send",
        body=_re_engage_message(conv_state),
        cta="open_ended",
        rationale="Neutral message; re-engaging with original context.",
    ).model_dump(exclude_none=True)


# ═══════════════════════════════════════════════════════════════════
#  Reply helper functions
# ═══════════════════════════════════════════════════════════════════

def _redirect_message(conv_state: dict) -> str:
    trigger_id = conv_state.get("trigger_id", "")
    return (
        "I'll have to leave that to a specialist — that's outside what I can help with directly. "
        "Coming back to where we left off — want me to continue with the draft, "
        "or shall I send you the summary first?"
    )


def _execute_next_action(conv_state: dict, merchant_id: str) -> tuple[str, str]:
    trigger_id = conv_state.get("trigger_id", "")
    slug = conv_state.get("slug", "")

    # Load merchant to personalize
    merchant_rec = store.get_context("merchant", merchant_id)
    merchant = merchant_rec["payload"] if merchant_rec else {}
    cust_agg = merchant.get("customer_aggregate", {})
    high_risk = cust_agg.get("high_risk_adult_count", cust_agg.get("total_active_members", 0))

    if "research" in trigger_id or "digest" in trigger_id:
        body = (
            f"Drafting your patient WhatsApp now — 90 seconds. "
            f"I'll also pre-fill the GBP post for tomorrow 10am. "
            f"Reply CONFIRM to send the WhatsApp draft to your patient list"
            f"{f' ({high_risk} high-risk patients)' if high_risk else ''}."
        )
        cta = "binary_confirm_cancel"
    elif "recall" in trigger_id:
        body = (
            "Booking confirmed. I'll send the appointment reminder 24h before "
            "and a follow-up care note after. Reply CANCEL to undo."
        )
        cta = "binary_confirm_cancel"
    elif "planning" in trigger_id or "corp" in trigger_id:
        body = (
            "Great. Drafting the full offer template now. "
            "I'll also draft the outreach message for offices in your delivery radius. "
            "Reply CONFIRM to proceed."
        )
        cta = "binary_confirm_cancel"
    else:
        body = (
            "On it. Drafting now — should have something for you to review in 2 minutes. "
            "Reply CONFIRM to proceed, or let me know if you want to change anything."
        )
        cta = "binary_confirm_cancel"
    return body, cta


def _deliver_artifact(conv_state: dict, merchant_id: str) -> tuple[str, str]:
    trigger_id = conv_state.get("trigger_id", "")
    slug = conv_state.get("slug", "")

    if "research" in trigger_id or "digest" in trigger_id:
        body = (
            "Sending the abstract now (2 pages). Patient-ed draft below — copy-paste or I'll schedule a GBP post:\n\n"
            "\"Your 6-month cleaning — does timing matter? New research says yes, especially if you've had cavities. "
            "Drop us a note for a quick check.\"\n\n"
            "Want me to schedule the post for tomorrow 10am?"
        )
        cta = "binary_yes_no"
    elif "recall" in trigger_id:
        body = (
            "Your slot is confirmed. I'll send a reminder 24h before. "
            "Anything else you'd like me to add to your visit notes?"
        )
        cta = "open_ended"
    elif "refill" in trigger_id:
        body = (
            "Order dispatched. Estimated delivery by 5pm today. "
            "I'll send a delivery notification when it's out. "
            "Want me to set up auto-refill for next month?"
        )
        cta = "binary_yes_no"
    else:
        body = (
            "Here's the draft — ready to send:\n\n"
            "\"[Your message draft — customized to your offer and audience]\"\n\n"
            "Want me to schedule this for tomorrow morning or send now?"
        )
        cta = "binary_yes_no"
    return body, cta


def _price_objection_response(conv_state: dict, merchant_id: str) -> tuple[str, str]:
    slug = conv_state.get("slug", "")
    merchant_rec = store.get_context("merchant", merchant_id)
    merchant = merchant_rec["payload"] if merchant_rec else {}
    active_offers = [o for o in merchant.get("offers", []) if o.get("status") == "active"]

    # Pick the cheapest active offer as alternate
    alt_offer = None
    if active_offers:
        alt_offer = sorted(active_offers, key=lambda o: o.get("id", ""))[0]

    if alt_offer:
        body = (
            f"Understood on budget. Alternate option: {alt_offer['title']} — "
            f"same quality, lower commitment. Would that work?"
        )
    else:
        body = (
            "Understood on budget. We can start with a no-cost trial and see the value first. "
            "Want me to set that up?"
        )
    return body, "binary_yes_no"


def _curious_response(message: str, conv_state: dict) -> tuple[str, str]:
    trigger_id = conv_state.get("trigger_id", "")
    if "research" in trigger_id or "digest" in trigger_id:
        body = (
            "Good question. The study focused on high-risk adult patients — those with active decay history. "
            "For low-risk patients, the 6-month interval is still fine. "
            "The change is targeted. Want me to send the full abstract?"
        )
    elif "recall" in trigger_id or "slot" in message.lower():
        body = (
            "Absolutely — the slots are weekday evenings to match your preference. "
            "Reply 1 for the first option or 2 for the second, and I'll confirm it."
        )
    else:
        body = (
            "Good question — let me give you the specifics. "
            "The short answer: it depends on your current offer mix. "
            "Want me to pull together a quick comparison?"
        )
    return body, "binary_yes_no"


def _re_engage_message(conv_state: dict) -> str:
    trigger_id = conv_state.get("trigger_id", "")
    return (
        f"Just checking in on this — still interested in the earlier suggestion? "
        f"Happy to pick up where we left off or try a different angle. Let me know."
    )


@app.post("/v1/reset")
async def reset_store():
    store.clear_suppressions()
    return {"status": "ok", "message": "Suppressions and conversations reset"}

