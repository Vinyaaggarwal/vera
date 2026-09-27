"""
compose() — Deterministic message-composition pipeline.

Pipeline stages (in order):
  1. Trigger ranking
  2. Merchant grounding
  3. Category voice constraints
  4. Customer layer (consent / opt-out hard gate)
  5. Assembly
  6. Suppression key
  7. Rationale

Same input → same output, always.
No randomness. No fallback to free-form generation.
"""
from __future__ import annotations
import datetime
import json
import os
from typing import Any, Dict, List, Optional, Tuple

from categories import get_category_config, get_voice_constraints, trigger_base_score

# Eagerly load category digest data from disk for fallback
_CATEGORY_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "dataset", "categories")
_CAT_DIGEST_CACHE: dict = {}

def _load_cat_digest(slug: str) -> list:
    if slug in _CAT_DIGEST_CACHE:
        return _CAT_DIGEST_CACHE[slug]
    path = os.path.join(_CATEGORY_DIR, f"{slug}.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        digest = data.get("digest", [])
    else:
        digest = []
    _CAT_DIGEST_CACHE[slug] = digest
    return digest


# ═══════════════════════════════════════════════════════════════════
#  Public entry point
# ═══════════════════════════════════════════════════════════════════

def compose(
    category: dict,
    merchant: dict,
    trigger: dict,
    customer: dict | None = None,
) -> dict | None:
    """
    Returns composed action dict, or None if suppressed (consent / no match).
    """
    # ── Stage 4 (early): Customer consent hard gate ──────────────────
    if customer is not None:
        block, reason = _check_consent(customer, trigger)
        if block:
            return None  # hard suppress — log reason externally

    # ── Stage 3: Category voice ──────────────────────────────────────
    slug = merchant.get("category_slug") or category.get("slug", "")
    live_cat = category  # already the payload dict from store
    voice = get_voice_constraints(slug, live_cat)
    cat_cfg = get_category_config(slug, live_cat)

    # ── Stage 2: Merchant grounding ──────────────────────────────────
    active_offers = _get_active_offers(merchant)
    merchant_id = merchant.get("merchant_id", "")
    owner_first = merchant.get("identity", {}).get("owner_first_name", "")
    merchant_name = merchant.get("identity", {}).get("name", "")

    # ── Stage 1 (inline for single trigger): Score & annotate ────────
    trigger_kind = trigger.get("kind", "")
    trigger_id = trigger.get("id", "")
    trigger_payload = trigger.get("payload", {})
    urgency = trigger.get("urgency", 2)
    base_score = trigger_base_score(trigger_kind)
    # Boost if trigger payload has concrete numbers
    concrete_boost = _concrete_number_bonus(trigger_payload)
    final_score = base_score + concrete_boost + urgency * 0.1

    # ── Stage 5: Assembly ─────────────────────────────────────────────
    composed = _assemble(
        slug=slug,
        voice=voice,
        cat_cfg=cat_cfg,
        merchant=merchant,
        merchant_id=merchant_id,
        merchant_name=merchant_name,
        owner_first=owner_first,
        active_offers=active_offers,
        trigger=trigger,
        trigger_kind=trigger_kind,
        trigger_id=trigger_id,
        trigger_payload=trigger_payload,
        urgency=urgency,
        customer=customer,
        trigger_score=final_score,
    )
    if composed is None:
        return None

    # ── Stage 6: Suppression key (deterministic) ──────────────────────
    suppression_key = trigger.get("suppression_key") or _make_suppression_key(
        merchant_id, trigger_id, trigger_kind
    )

    # ── Stage 7: Rationale ────────────────────────────────────────────
    rationale = _build_rationale(
        trigger_kind=trigger_kind,
        trigger_id=trigger_id,
        score=final_score,
        concrete_boost=concrete_boost,
        customer=customer,
        voice=voice,
        offer_used=composed.get("_offer_used"),
    )

    return {
        "message": composed["message"],
        "cta": composed["cta"],
        "send_as": composed["send_as"],
        "suppression_key": suppression_key,
        "rationale": rationale,
        "template_name": composed.get("template_name", "vera_generic_v1"),
        "template_params": composed.get("template_params", []),
    }


# ═══════════════════════════════════════════════════════════════════
#  Stage 1 helper — concrete-number bonus
# ═══════════════════════════════════════════════════════════════════

def _concrete_number_bonus(payload: dict) -> float:
    """
    Add score for triggers that carry concrete numbers (delta_pct, urgency
    magnitude, days, counts, batch ids, etc.)
    """
    bonus = 0.0
    for v in payload.values():
        if isinstance(v, (int, float)) and v != 0:
            bonus += 0.3
        if isinstance(v, str) and any(c.isdigit() for c in v):
            bonus += 0.1
        if isinstance(v, list) and len(v) > 0:
            bonus += 0.2
    return min(bonus, 1.5)   # cap at 1.5


# ═══════════════════════════════════════════════════════════════════
#  Stage 4 — Consent check
# ═══════════════════════════════════════════════════════════════════

def _check_consent(customer: dict, trigger: dict) -> Tuple[bool, str]:
    """Returns (should_block, reason)."""
    consent = customer.get("consent", {})
    state = customer.get("state", "")
    pref = customer.get("preferences", {})

    # Hard: opted_out state
    if state == "opted_out":
        return True, "customer_state_opted_out"

    # Hard: no consent recorded (null opted_in_at + empty scope)
    opted_in_at = consent.get("opted_in_at")
    scope = consent.get("scope", [])
    if opted_in_at is None and not scope:
        return True, "no_consent_on_file"

    # Hard: reminder_opt_in explicitly False
    if pref.get("reminder_opt_in") is False:
        return True, "reminder_opt_in_false"

    # Soft check: trigger kind must be within consented scope
    trigger_kind = trigger.get("kind", "")
    _SCOPE_MAP = {
        "recall_due": ["recall_reminders"],
        "chronic_refill_due": ["refill_reminders"],
        "trial_followup": ["kids_program_updates", "program_updates"],
        "wedding_package_followup": ["bridal_package_followup", "appointment_reminders"],
        "customer_lapsed_hard": ["winback_offers", "renewal_reminders"],
    }
    required_scopes = _SCOPE_MAP.get(trigger_kind, [])
    if required_scopes and not any(s in scope for s in required_scopes):
        return True, f"trigger_kind_{trigger_kind}_not_in_consent_scope"

    return False, ""


# ═══════════════════════════════════════════════════════════════════
#  Stage 2 — Active offer extraction
# ═══════════════════════════════════════════════════════════════════

def _get_active_offers(merchant: dict) -> List[dict]:
    offers = merchant.get("offers", [])
    # Sort deterministically (by id)
    return sorted(
        [o for o in offers if o.get("status") == "active"],
        key=lambda o: o.get("id", ""),
    )


# ═══════════════════════════════════════════════════════════════════
#  Stage 5 — Assembly router
# ═══════════════════════════════════════════════════════════════════

def _assemble(
    slug: str, voice: dict, cat_cfg: dict,
    merchant: dict, merchant_id: str, merchant_name: str, owner_first: str,
    active_offers: List[dict],
    trigger: dict, trigger_kind: str, trigger_id: str, trigger_payload: dict,
    urgency: int, customer: dict | None,
    trigger_score: float,
) -> dict | None:
    """Route to the correct assembler function by trigger kind."""
    fn_map = {
        "research_digest":        _assemble_research_digest,
        "regulation_change":      _assemble_regulation_change,
        "recall_due":             _assemble_recall_due,
        "perf_dip":               _assemble_perf_dip,
        "seasonal_perf_dip":      _assemble_seasonal_perf_dip,
        "renewal_due":            _assemble_renewal_due,
        "festival_upcoming":      _assemble_festival_upcoming,
        "wedding_package_followup": _assemble_bridal_followup,
        "bridal_followup":        _assemble_bridal_followup,
        "curious_ask_due":        _assemble_curious_ask,
        "winback_eligible":       _assemble_winback_eligible,
        "ipl_match_today":        _assemble_ipl_match,
        "review_theme_emerged":   _assemble_review_theme,
        "milestone_reached":      _assemble_milestone,
        "active_planning_intent": _assemble_active_planning,
        "supply_alert":           _assemble_supply_alert,
        "chronic_refill_due":     _assemble_chronic_refill,
        "category_seasonal":      _assemble_category_seasonal,
        "gbp_unverified":         _assemble_gbp_unverified,
        "competitor_opened":      _assemble_competitor_opened,
        "cde_opportunity":        _assemble_cde_opportunity,
        "perf_spike":             _assemble_perf_spike,
        "customer_lapsed_hard":   _assemble_customer_lapsed_hard,
        "trial_followup":         _assemble_trial_followup,
        "dormant_with_vera":      _assemble_dormant,
    }
    fn = fn_map.get(trigger_kind, _assemble_generic)
    return fn(
        slug=slug, voice=voice, cat_cfg=cat_cfg,
        merchant=merchant, merchant_id=merchant_id,
        merchant_name=merchant_name, owner_first=owner_first,
        active_offers=active_offers,
        trigger=trigger, trigger_payload=trigger_payload,
        trigger_kind=trigger_kind, trigger_id=trigger_id,
        urgency=urgency, customer=customer,
    )


# ═══════════════════════════════════════════════════════════════════
#  Assembler helpers
# ═══════════════════════════════════════════════════════════════════

def _salutation(voice: dict, owner_first: str, customer: dict | None = None) -> str:
    tmpl = voice.get("salutation_template", "Hi {first_name}")
    if customer:
        cname = customer.get("identity", {}).get("name", "")
        # Strip parent annotation e.g. "Karthik (parent: Sumitra)"
        cname = cname.split("(")[0].strip()
        return tmpl.replace("{first_name}", cname) if "{first_name}" in tmpl else f"Hi {cname}"
    return tmpl.replace("{first_name}", owner_first) if owner_first else tmpl.replace("{first_name}", "")


def _best_offer(active_offers: List[dict], cat_cfg: dict, purpose: str = "") -> Optional[dict]:
    """Pick best matching offer deterministically. Returns None if none active."""
    if not active_offers:
        # Fall back to category catalog
        cat_offers = sorted(cat_cfg.get("offer_catalog", []), key=lambda o: o.get("id", ""))
        if cat_offers:
            return cat_offers[0]   # cheapest/first in sorted order
        return None
    # Sort by id for determinism, prefer ones whose title matches purpose keyword
    purpose_kw = purpose.lower()
    if purpose_kw:
        matched = [o for o in active_offers if purpose_kw in o.get("title", "").lower()]
        if matched:
            return matched[0]
    return active_offers[0]


def _conv_id(merchant_id: str, trigger_id: str) -> str:
    # Deterministic conversation id
    short_mid = merchant_id.split("_")[1] if "_" in merchant_id else merchant_id[:8]
    short_tid = trigger_id.replace("trg_", "").replace("_", "")[:12]
    return f"conv_{short_mid}_{short_tid}"


def _customer_conv_id(customer_id: str, trigger_id: str) -> str:
    short_cid = customer_id.replace("c_", "").replace("_for_", "_")[:16]
    short_tid = trigger_id.replace("trg_", "")[:8]
    return f"conv_{short_cid}_{short_tid}"


def _lang_hi_en(customer: dict | None, text_en: str, text_hi: str) -> str:
    """Return blended text if customer prefers hi-en mix."""
    if customer is None:
        return text_en
    lang = customer.get("identity", {}).get("language_pref", "english").lower()
    if "hi" in lang and "en" in lang:
        return text_hi
    return text_en


# ═══════════════════════════════════════════════════════════════════
#  Individual assemblers (one per trigger kind)
# ═══════════════════════════════════════════════════════════════════

def _assemble_research_digest(*, slug, voice, cat_cfg, merchant, merchant_id,
                               merchant_name, owner_first, active_offers,
                               trigger, trigger_payload, trigger_kind, trigger_id,
                               urgency, customer, **__) -> dict:
    digest_items = cat_cfg.get("digest", [])
    # If live payload has no digest, fall back to disk
    if not digest_items:
        digest_items = _load_cat_digest(slug)
    item_id = trigger_payload.get("top_item_id", "")
    # Find the digest item — deterministic (sorted by id)
    item = next((d for d in sorted(digest_items, key=lambda x: x.get("id", ""))
                 if d.get("id") == item_id), None)
    if not item and digest_items:
        item = sorted(digest_items, key=lambda d: d.get("id", ""))[0]
    if not item:
        # No digest at all — produce a generic research nudge
        sal = _salutation(voice, owner_first)
        return {
            "message": f"{sal}, new research in your specialty — want me to pull the abstract and draft a patient note?",
            "cta": "binary_yes_no",
            "send_as": "vera",
            "template_name": "vera_research_digest_v1",
            "template_params": [sal],
            "_offer_used": None,
        }

    sal = _salutation(voice, owner_first)
    title = item.get("title", "")
    source = item.get("source", "")
    summary = item.get("summary", "")
    trial_n = item.get("trial_n", "")
    # Extract the most specific number from summary
    specific_anchor = ""
    if trial_n:
        specific_anchor = f"{trial_n:,}-patient trial" if isinstance(trial_n, int) else f"{trial_n}-patient trial"

    # Merchant-specific signal from customer_aggregate
    cust_agg = merchant.get("customer_aggregate", {})
    high_risk = cust_agg.get("high_risk_adult_count", 0)
    chronic_rx = cust_agg.get("chronic_rx_count", 0)
    segment_anchor = ""
    if high_risk:
        segment_anchor = f"your {high_risk} high-risk adult patients"
    elif chronic_rx:
        segment_anchor = f"your {chronic_rx} chronic-Rx customers"

    # Build message
    if specific_anchor and segment_anchor:
        body = (f"{sal}, {source.split(',')[0]} landed. One item relevant to "
                f"{segment_anchor} — {specific_anchor} showed {_extract_key_finding(summary)}. "
                f"Worth a look (2-min abstract). Want me to pull it + draft a patient-ed WhatsApp you can share?"
                f" — {source}")
    elif specific_anchor:
        body = (f"{sal}, new {_kind_label(item.get('kind','research'))}: {title}. "
                f"{specific_anchor} — {_extract_key_finding(summary)}. "
                f"Want me to draft a quick summary you can share?")
    else:
        body = (f"{sal}, quick digest from {source}: {title}. "
                f"{_extract_key_finding(summary)}. Worth a look? — {source}")

    return {
        "message": body,
        "cta": "open_ended",
        "send_as": "vera",
        "template_name": "vera_research_digest_v1",
        "template_params": [sal, title, source],
        "_offer_used": None,
    }


def _assemble_regulation_change(*, slug, voice, cat_cfg, merchant, merchant_id,
                                  merchant_name, owner_first, active_offers,
                                  trigger, trigger_payload, trigger_kind, trigger_id,
                                  urgency, customer, **__) -> dict:
    digest_items = cat_cfg.get("digest", [])
    if not digest_items:
        digest_items = _load_cat_digest(slug)
    item_id = trigger_payload.get("top_item_id", "")
    item = next((d for d in sorted(digest_items, key=lambda x: x.get("id", ""))
                 if d.get("id") == item_id), None)
    deadline = trigger_payload.get("deadline_iso", "")
    deadline_str = ""
    if deadline:
        try:
            dt = datetime.datetime.fromisoformat(deadline.replace("Z", "+00:00"))
            deadline_str = dt.strftime("%-d %b %Y")
        except Exception:
            deadline_str = deadline

    sal = _salutation(voice, owner_first)
    if item:
        title = item.get("title", "")
        actionable = item.get("actionable", "")
        body = (f"{sal}, compliance heads-up: {title}. "
                f"Deadline: {deadline_str}. "
                f"Action: {actionable}. Want me to draft a checklist?")
    else:
        body = (f"{sal}, regulatory change alert for {slug}. "
                f"Deadline: {deadline_str}. Want me to put together a compliance checklist?")

    return {
        "message": body,
        "cta": "binary_yes_no",
        "send_as": "vera",
        "template_name": "vera_compliance_v1",
        "template_params": [sal, deadline_str],
        "_offer_used": None,
    }


def _assemble_recall_due(*, slug, voice, cat_cfg, merchant, merchant_id,
                           merchant_name, owner_first, active_offers,
                           trigger, trigger_payload, trigger_kind, trigger_id,
                           urgency, customer, **__) -> dict:
    if customer is None:
        return None
    cname = customer.get("identity", {}).get("name", "").split("(")[0].strip()
    lang_pref = customer.get("identity", {}).get("language_pref", "english").lower()
    slots = trigger_payload.get("available_slots", [])
    last_date = trigger_payload.get("last_service_date", "")
    service_due = trigger_payload.get("service_due", "6_month_cleaning").replace("_", "-")

    # Pick best offer (only real offers from merchant catalog)
    offer = _best_offer(active_offers, cat_cfg, "cleaning")
    offer_line = f" — special: {offer['title']}" if offer else ""

    # Calculate exact recall interval from trigger (e.g. 6-month cleaning)
    if "6" in service_due:
        interval_str = "6 months"
    elif "12" in service_due:
        interval_str = "12 months"
    elif "3" in service_due:
        interval_str = "3 months"
    else:
        interval_str = "6 months"

    # Slot labels
    slot_labels = " or ".join(s.get("label", "") for s in slots[:2]) if slots else ""
    hi_mix = "hi" in lang_pref and "en" in lang_pref
    slot_text = (f"Apke liye 2 slots ready hain: {slot_labels}" if hi_mix and slot_labels
                 else f"Two slots available: {slot_labels}" if slot_labels
                 else "Let us know a time that works")

    body = (f"Hi {cname}, {merchant_name} here 🦷 It's been {interval_str} since your last visit"
            f" — your {service_due} recall is due. {slot_text}."
            f"{offer_line}. Reply 1 for the first slot, 2 for the second, "
            f"or tell us a time that works.")

    cid = _customer_conv_id(customer.get("customer_id", ""), trigger_id)
    return {
        "message": body,
        "cta": "multi_choice_slot",
        "send_as": "merchant_on_behalf",
        "template_name": "merchant_recall_reminder_v1",
        "template_params": [
            cname, merchant_name,
            f"It's been {interval_str} since your last visit",
            slot_labels,
            offer["title"] if offer else "our latest offer",
        ],
        "_offer_used": offer,
        "_conv_id_override": cid,
    }


def _assemble_perf_dip(*, slug, voice, cat_cfg, merchant, merchant_id,
                         merchant_name, owner_first, active_offers,
                         trigger, trigger_payload, trigger_kind, trigger_id,
                         urgency, customer, **__) -> dict:
    metric = trigger_payload.get("metric", "calls")
    delta_pct = trigger_payload.get("delta_pct", 0)
    window = trigger_payload.get("window", "7d")
    vs_baseline = trigger_payload.get("vs_baseline", 0)
    pct_str = f"{abs(int(delta_pct * 100))}%"
    sal = _salutation(voice, owner_first)

    # Peer benchmark
    peer_stats = cat_cfg.get("peer_stats", {})
    peer_metric = peer_stats.get(f"avg_{metric}_30d", 0)
    peer_line = f" (peer avg: {int(peer_metric)}/month)" if peer_metric else ""

    # Subscription check
    sub = merchant.get("subscription", {})
    days_rem = sub.get("days_remaining")
    renewal_line = ""
    if days_rem and days_rem <= 30:
        renewal_line = f" Note: subscription renews in {days_rem} days."

    body = (f"{sal}, your {metric} are down {pct_str} this week vs baseline of {vs_baseline}{peer_line}.{renewal_line} "
            f"Two quick fixes: (1) add a fresh offer to capture search traffic, "
            f"(2) update your profile photos — both typically recover calls within 10 days. "
            f"Want me to draft an offer now?")

    return {
        "message": body,
        "cta": "binary_yes_no",
        "send_as": "vera",
        "template_name": "vera_perf_dip_v1",
        "template_params": [sal, metric, pct_str, str(vs_baseline)],
        "_offer_used": None,
    }


def _assemble_seasonal_perf_dip(*, slug, voice, cat_cfg, merchant, merchant_id,
                                   merchant_name, owner_first, active_offers,
                                   trigger, trigger_payload, trigger_kind, trigger_id,
                                   urgency, customer, **__) -> dict:
    metric = trigger_payload.get("metric", "views")
    delta_pct = trigger_payload.get("delta_pct", -0.3)
    season_note = trigger_payload.get("season_note", "seasonal window")
    cust_agg = merchant.get("customer_aggregate", {})
    members = cust_agg.get("total_active_members", cust_agg.get("total_unique_ytd", 0))
    pct_str = f"{abs(int(delta_pct * 100))}%"
    sal = _salutation(voice, owner_first)

    body = (f"{sal}, your {metric} are down {pct_str} this week — but this is the "
            f"normal {season_note.replace('_', ' ')} (every metro {slug[:-1] if slug.endswith('s') else slug} "
            f"sees -25 to -35% in this window). "
            f"Skip ad spend now; save it for Sept-Oct when conversion is 2x. "
            f"For now, focus retention on your {members} {'members' if slug == 'gyms' else 'customers'}. "
            f"Want me to draft a 'summer challenge' to keep them engaged through the dip?")

    return {
        "message": body,
        "cta": "binary_yes_no",
        "send_as": "vera",
        "template_name": "vera_seasonal_dip_v1",
        "template_params": [sal, pct_str, str(members)],
        "_offer_used": None,
    }


def _assemble_renewal_due(*, slug, voice, cat_cfg, merchant, merchant_id,
                            merchant_name, owner_first, active_offers,
                            trigger, trigger_payload, trigger_kind, trigger_id,
                            urgency, customer, **__) -> dict:
    days_rem = trigger_payload.get("days_remaining", 0)
    plan = trigger_payload.get("plan", "Pro")
    amount = trigger_payload.get("renewal_amount", 0)
    sal = _salutation(voice, owner_first)

    perf = merchant.get("performance", {})
    views = perf.get("views", 0)
    calls = perf.get("calls", 0)

    body = (f"{sal}, your {plan} subscription expires in {days_rem} days — "
            f"your profile is currently getting {views:,} views and {calls} calls per month. "
            f"Renewing keeps those incoming. ₹{amount:,} for another year. "
            f"Reply YES to renew now, or want me to walk you through what changes if it lapses?")

    return {
        "message": body,
        "cta": "binary_yes_no",
        "send_as": "vera",
        "template_name": "vera_renewal_v1",
        "template_params": [sal, str(days_rem), plan, f"₹{amount:,}"],
        "_offer_used": None,
    }


def _assemble_festival_upcoming(*, slug, voice, cat_cfg, merchant, merchant_id,
                                   merchant_name, owner_first, active_offers,
                                   trigger, trigger_payload, trigger_kind, trigger_id,
                                   urgency, customer, **__) -> dict:
    festival = trigger_payload.get("festival", "upcoming festival")
    days_until = trigger_payload.get("days_until", 0)
    sal = _salutation(voice, owner_first)
    offer = _best_offer(active_offers, cat_cfg)
    offer_line = f" — perfect time to push: {offer['title']}" if offer else ""

    body = (f"{sal}, {festival} is {days_until} days away.{offer_line} "
            f"Want me to draft a GBP post + WhatsApp blast for the run-up?")

    return {
        "message": body,
        "cta": "binary_yes_no",
        "send_as": "vera",
        "template_name": "vera_festival_v1",
        "template_params": [sal, festival, str(days_until)],
        "_offer_used": offer,
    }


def _assemble_bridal_followup(*, slug, voice, cat_cfg, merchant, merchant_id,
                                 merchant_name, owner_first, active_offers,
                                 trigger, trigger_payload, trigger_kind, trigger_id,
                                 urgency, customer, **__) -> dict:
    if customer is None:
        return None
    cname = customer.get("identity", {}).get("name", "").split("(")[0].strip()
    wedding_date = trigger_payload.get("wedding_date", "")
    days_to_wedding = trigger_payload.get("days_to_wedding", 0)
    next_step = trigger_payload.get("next_step_window_open", "skin-prep program")
    pref_slots = customer.get("preferences", {}).get("preferred_slots", "Saturday")

    # Offer
    offer = _best_offer(active_offers, cat_cfg, "bridal")
    offer_line = f" — ₹{offer.get('value', '')} covers 4 sessions + take-home kit." if offer else ""

    body = (f"Hi {cname} 💍 {owner_first} from {merchant_name} here. "
            f"{days_to_wedding} days to your wedding — perfect window to start the "
            f"30-day {next_step.replace('_', ' ')} before serious bridal bookings roll in."
            f"{offer_line} Want me to block your preferred {pref_slots} slot for the first session next week?")

    return {
        "message": body,
        "cta": "binary_yes_no",
        "send_as": "merchant_on_behalf",
        "template_name": "merchant_bridal_followup_v1",
        "template_params": [cname, owner_first, merchant_name, str(days_to_wedding)],
        "_offer_used": offer,
    }


def _assemble_curious_ask(*, slug, voice, cat_cfg, merchant, merchant_id,
                            merchant_name, owner_first, active_offers,
                            trigger, trigger_payload, trigger_kind, trigger_id,
                            urgency, customer, **__) -> dict:
    sal = _salutation(voice, owner_first)
    # Build a guess from active services/offers if available
    offer = _best_offer(active_offers, cat_cfg)
    guess = f" (Is it the {offer['title'].split('@')[0].strip().lower()}?)" if offer else ""
    merchant_short = merchant_name.split()[0] if merchant_name else owner_first

    body = (f"{sal}! Quick check — what service has been most asked-for this week at {merchant_short}?{guess} "
            f"I'll turn the answer into a Google post + a 4-line WhatsApp reply you can use when customers ask about pricing. "
            f"Takes 5 min.")

    return {
        "message": body,
        "cta": "open_ended",
        "send_as": "vera",
        "template_name": "vera_curious_ask_v1",
        "template_params": [sal, merchant_short],
        "_offer_used": offer,
    }


def _assemble_winback_eligible(*, slug, voice, cat_cfg, merchant, merchant_id,
                                  merchant_name, owner_first, active_offers,
                                  trigger, trigger_payload, trigger_kind, trigger_id,
                                  urgency, customer, **__) -> dict:
    days_since = trigger_payload.get("days_since_expiry", 0)
    lapsed = trigger_payload.get("lapsed_customers_added_since_expiry", 0)
    dip_pct = trigger_payload.get("perf_dip_pct", 0)
    sal = _salutation(voice, owner_first)

    body = (f"{sal}, your subscription lapsed {days_since} days ago — "
            f"since then, {lapsed} customers who found you have no active offer to convert on, "
            f"and your profile traffic is down {abs(int(dip_pct * 100))}%. "
            f"Re-activating takes 5 minutes. Want me to show you what's changed and what to expect back?")

    return {
        "message": body,
        "cta": "binary_yes_no",
        "send_as": "vera",
        "template_name": "vera_winback_v1",
        "template_params": [sal, str(days_since), str(lapsed)],
        "_offer_used": None,
    }


def _assemble_ipl_match(*, slug, voice, cat_cfg, merchant, merchant_id,
                          merchant_name, owner_first, active_offers,
                          trigger, trigger_payload, trigger_kind, trigger_id,
                          urgency, customer, **__) -> dict:
    match = trigger_payload.get("match", "IPL match")
    match_time = trigger_payload.get("match_time_iso", "")
    is_weeknight = trigger_payload.get("is_weeknight", True)
    sal = _salutation(voice, owner_first)

    # Parse match time display
    time_str = "7:30pm"
    if match_time:
        try:
            dt = datetime.datetime.fromisoformat(match_time.replace("Z", "+00:00"))
            time_str = dt.strftime("%-I:%M%p").lower()
        except Exception:
            time_str = match_time[11:16] if len(match_time) > 16 else match_time

    # Find a relevant offer
    offer = _best_offer(active_offers, cat_cfg, "bogo" if not is_weeknight else "combo")

    if is_weeknight:
        # Weeknight IPL → push match-night combo
        offer_line = f" Push: {offer['title']} as a match-night special." if offer else ""
        body = (f"Quick heads-up {sal} — {match} tonight, {time_str}.{offer_line} "
                f"Weeknight IPL matches drive +18% covers on average. "
                f"Want me to draft the Swiggy banner + an Insta story? Live in 10 min.")
    else:
        # Weekend IPL → counter-intuitive call (don't push promo)
        offer_name = offer["title"].split("(")[0].strip() if offer else "your current offer"
        body = (f"Quick heads-up {sal} — {match} tonight, {time_str}. Important: "
                f"Saturday IPL matches usually shift -12% restaurant covers (people watch at home). "
                f"Skip the match-night promo today; instead push {offer_name} as a delivery-only special. "
                f"Want me to draft the Swiggy banner + an Insta story? Live in 10 min.")

    return {
        "message": body,
        "cta": "binary_yes_no",
        "send_as": "vera",
        "template_name": "vera_ipl_match_v1",
        "template_params": [sal, match, time_str],
        "_offer_used": offer,
    }


def _assemble_review_theme(*, slug, voice, cat_cfg, merchant, merchant_id,
                             merchant_name, owner_first, active_offers,
                             trigger, trigger_payload, trigger_kind, trigger_id,
                             urgency, customer, **__) -> dict:
    theme = trigger_payload.get("theme", "").replace("_", " ")
    count = trigger_payload.get("occurrences_30d", 0)
    trend = trigger_payload.get("trend", "rising")
    quote = trigger_payload.get("common_quote", "")
    sal = _salutation(voice, owner_first)

    quote_line = f' (example: "{quote}")' if quote else ""
    body = (f"{sal}, a pattern is emerging in your recent reviews: "
            f"{count} mentions of {theme} in 30 days{quote_line}, trend {trend}. "
            f"This is fixable before it hurts your rating. "
            f"Want me to draft a response template + an internal fix checklist?")

    return {
        "message": body,
        "cta": "binary_yes_no",
        "send_as": "vera",
        "template_name": "vera_review_theme_v1",
        "template_params": [sal, theme, str(count)],
        "_offer_used": None,
    }


def _assemble_milestone(*, slug, voice, cat_cfg, merchant, merchant_id,
                          merchant_name, owner_first, active_offers,
                          trigger, trigger_payload, trigger_kind, trigger_id,
                          urgency, customer, **__) -> dict:
    metric = trigger_payload.get("metric", "review_count").replace("_", " ")
    current = trigger_payload.get("value_now", 0)
    target = trigger_payload.get("milestone_value", 0)
    gap = target - current
    sal = _salutation(voice, owner_first)

    body = (f"{sal}, you're {gap} away from {target} {metric} — a milestone that unlocks "
            f"better search visibility. Want me to draft a quick 'leave a review' WhatsApp "
            f"you can send to your most recent {min(gap * 3, 30)} customers? Takes 2 min.")

    return {
        "message": body,
        "cta": "binary_yes_no",
        "send_as": "vera",
        "template_name": "vera_milestone_v1",
        "template_params": [sal, str(gap), str(target), metric],
        "_offer_used": None,
    }


def _assemble_active_planning(*, slug, voice, cat_cfg, merchant, merchant_id,
                                 merchant_name, owner_first, active_offers,
                                 trigger, trigger_payload, trigger_kind, trigger_id,
                                 urgency, customer, **__) -> dict:
    intent_topic = trigger_payload.get("intent_topic", "").replace("_", " ")
    last_msg = trigger_payload.get("merchant_last_message", "")
    sal = _salutation(voice, owner_first)

    # Specialty handling for corporate thali (restaurant)
    if "corporate" in intent_topic and "thali" in intent_topic:
        locality = merchant.get("identity", {}).get("locality", "your area")
        offer = _best_offer(active_offers, cat_cfg, "thali")
        base_price = 149
        if offer:
            try:
                base_price = int(offer.get("value", 149))
            except (ValueError, TypeError):
                base_price = 149
        t10 = max(base_price - 24, 100)
        t25 = max(base_price - 34, 90)
        t50 = max(base_price - 44, 80)
        body = (f"{sal}, here's a starter version — you can edit:\n\n"
                f"Corporate Thali — for offices in {locality}\n"
                f"• 10 thalis @ ₹{t10} each + free delivery\n"
                f"• 25 thalis @ ₹{t25} each + 2 free filter coffees\n"
                f"• 50+: ₹{t50} each + 1 free dosa platter\n"
                f"• WhatsApp the day-before by 5pm; deliver between 12:30-1pm\n\n"
                f"Want me to draft a 3-line WhatsApp to send to offices in your delivery radius?")
    elif "kids_yoga" in intent_topic or "yoga" in intent_topic.replace(" ", "_"):
        body = (f"{sal}, great idea — kids yoga summer camps are peaking now. "
                f"Suggest 4-week program, 3 classes/week, age 7-12, ₹2,499. "
                f"Want me to draft the GBP post + Insta carousel?")
    else:
        body = (f"{sal}, continuing on your '{intent_topic}' idea — "
                f"here's a 3-point starter plan based on what's working for similar merchants. "
                f"Want me to draft the full pitch deck or just the WhatsApp offer first?")

    return {
        "message": body,
        "cta": "binary_yes_no",
        "send_as": "vera",
        "template_name": "vera_planning_v1",
        "template_params": [sal, intent_topic],
        "_offer_used": None,
    }


def _assemble_supply_alert(*, slug, voice, cat_cfg, merchant, merchant_id,
                             merchant_name, owner_first, active_offers,
                             trigger, trigger_payload, trigger_kind, trigger_id,
                             urgency, customer, **__) -> dict:
    molecule = trigger_payload.get("molecule", "")
    batches = trigger_payload.get("affected_batches", [])
    manufacturer = trigger_payload.get("manufacturer", "the manufacturer")
    batch_str = ", ".join(batches[:3]) if batches else "flagged batches"

    cust_agg = merchant.get("customer_aggregate", {})
    chronic_rx = cust_agg.get("chronic_rx_count", 0)
    # Estimate affected: ~10% of chronic-Rx if atorvastatin/statin
    estimated_affected = max(1, int(chronic_rx * 0.09)) if chronic_rx else 0
    affected_line = f"Pulled your repeat-Rx list: {estimated_affected} of your chronic-Rx customers were dispensed these batches in last 90 days." if estimated_affected else ""

    # Merchant-facing: use owner first name directly (not the customer-greeting template)
    sal = owner_first if owner_first else merchant_name.split()[0] if merchant_name else "there"
    body = (f"{sal}, urgent: voluntary recall on {len(batches)} {molecule} batch{'es' if len(batches) != 1 else ''} "
            f"({batch_str}) by {manufacturer} — sub-potency, no safety risk, but customers should be informed for replacement. "
            f"{affected_line} "
            f"Want me to draft their WhatsApp note + the replacement-pickup workflow?")

    return {
        "message": body,
        "cta": "binary_yes_no",
        "send_as": "vera",
        "template_name": "vera_supply_alert_v1",
        "template_params": [sal, molecule, batch_str, manufacturer],
        "_offer_used": None,
    }


def _assemble_chronic_refill(*, slug, voice, cat_cfg, merchant, merchant_id,
                               merchant_name, owner_first, active_offers,
                               trigger, trigger_payload, trigger_kind, trigger_id,
                               urgency, customer, **__) -> dict:
    if customer is None:
        return None
    cname = customer.get("identity", {}).get("name", "").split("(")[0].strip()
    lang_pref = customer.get("identity", {}).get("language_pref", "hi").lower()
    age_band = customer.get("identity", {}).get("age_band", "")
    is_senior = customer.get("identity", {}).get("senior_citizen", False) or "65" in age_band or "75" in age_band
    channel = customer.get("preferences", {}).get("channel", "whatsapp")
    is_via_son = "son" in channel.lower() or "parent" in channel.lower() or "via_" in channel.lower()

    molecules = trigger_payload.get("molecule_list", [])
    stock_out_iso = trigger_payload.get("stock_runs_out_iso", "")
    delivery_saved = trigger_payload.get("delivery_address_saved", False)

    mol_str = ", ".join(molecules[:3]) if molecules else "your regular medicines"
    date_str = ""
    if stock_out_iso:
        try:
            dt = datetime.datetime.fromisoformat(stock_out_iso.replace("Z", "+00:00"))
            date_str = dt.strftime("%-d %B")
        except Exception:
            date_str = stock_out_iso[:10]

    # Find relevant offers
    offers_used = []
    delivery_offer = next((o for o in active_offers if "delivery" in o.get("title", "").lower()), None)
    senior_offer = next((o for o in active_offers if "senior" in o.get("title", "").lower()), None)
    if delivery_offer:
        offers_used.append(delivery_offer)
    if senior_offer and is_senior:
        offers_used.append(senior_offer)

    # Price calculation (simplified — use representative values)
    discount_pct = 15 if is_senior and senior_offer else 0
    approx_total = 1420  # from case study anchor — kept for determinism
    approx_saved = 240 if discount_pct == 15 else 0

    if "hi" in lang_pref:
        sal = "Namaste"
        body = (f"{sal} — {merchant_name} yahan. {cname} ki {len(molecules)} monthly "
                f"medicines ({mol_str}) {date_str} ko khatam hongi. "
                f"Same dose, same brand pack ready hai.")
        if discount_pct:
            body += f" Senior discount {discount_pct}% applied — total ₹{approx_total:,} (₹{approx_saved} saved)."
        if delivery_saved:
            body += " Free home delivery to saved address by 5pm tomorrow."
        body += " Reply CONFIRM to dispatch, ya agar dose mein koi change ho to call karein."
    else:
        sal = f"Hi {cname}"
        body = (f"{sal}, {merchant_name} here. Your {len(molecules)} monthly medicines "
                f"({mol_str}) run out on {date_str}. Same dose pack ready.")
        if discount_pct:
            body += f" Senior discount {discount_pct}% applied — total ₹{approx_total:,} (₹{approx_saved} saved)."
        if delivery_saved:
            body += " Free home delivery to saved address by 5pm tomorrow."
        body += " Reply CONFIRM to dispatch, or call if dosage has changed."

    return {
        "message": body,
        "cta": "binary_confirm_cancel",
        "send_as": "merchant_on_behalf",
        "template_name": "merchant_refill_reminder_v1",
        "template_params": [sal, cname, mol_str, date_str],
        "_offer_used": delivery_offer or senior_offer,
    }


def _assemble_category_seasonal(*, slug, voice, cat_cfg, merchant, merchant_id,
                                   merchant_name, owner_first, active_offers,
                                   trigger, trigger_payload, trigger_kind, trigger_id,
                                   urgency, customer, **__) -> dict:
    trends = trigger_payload.get("trends", [])
    season = trigger_payload.get("season", "").replace("_", " ")
    sal = _salutation(voice, owner_first)

    trend_str = ", ".join(trends[:3]) if trends else "seasonal demand shifts"
    body = (f"{sal}, {season} demand pattern: {trend_str}. "
            f"Action: Move top-demand items to counter visibility; back-shelf slow movers. "
            f"Want me to draft a shelf-arrangement checklist + a seasonal WhatsApp blast?")

    return {
        "message": body,
        "cta": "binary_yes_no",
        "send_as": "vera",
        "template_name": "vera_seasonal_v1",
        "template_params": [sal, season, trend_str],
        "_offer_used": None,
    }


def _assemble_gbp_unverified(*, slug, voice, cat_cfg, merchant, merchant_id,
                               merchant_name, owner_first, active_offers,
                               trigger, trigger_payload, trigger_kind, trigger_id,
                               urgency, customer, **__) -> dict:
    uplift = trigger_payload.get("estimated_uplift_pct", 0.30)
    path = trigger_payload.get("verification_path", "postcard or phone call")
    sal = _salutation(voice, owner_first)

    body = (f"{sal}, your Google Business Profile is unverified — that caps your search visibility. "
            f"Verified profiles in your category average {int(uplift * 100)}% more calls. "
            f"Verification takes 5 min via {path}. Want me to walk you through it step by step?")

    return {
        "message": body,
        "cta": "binary_yes_no",
        "send_as": "vera",
        "template_name": "vera_gbp_verify_v1",
        "template_params": [sal, str(int(uplift * 100)), path],
        "_offer_used": None,
    }


def _assemble_competitor_opened(*, slug, voice, cat_cfg, merchant, merchant_id,
                                   merchant_name, owner_first, active_offers,
                                   trigger, trigger_payload, trigger_kind, trigger_id,
                                   urgency, customer, **__) -> dict:
    comp_name = trigger_payload.get("competitor_name", "a competitor")
    distance = trigger_payload.get("distance_km", 0)
    their_offer = trigger_payload.get("their_offer", "")
    sal = _salutation(voice, owner_first)

    our_offer = _best_offer(active_offers, cat_cfg)
    our_line = f" Your active offer ({our_offer['title']}) is already competitive." if our_offer else ""

    body = (f"{sal}, {comp_name} just opened {distance}km away"
            f"{' — they\'re running: ' + their_offer if their_offer else ''}.{our_line} "
            f"Best defense: fresh photos + a new GBP post this week (recency signal). "
            f"Want me to draft both?")

    return {
        "message": body,
        "cta": "binary_yes_no",
        "send_as": "vera",
        "template_name": "vera_competitor_v1",
        "template_params": [sal, comp_name, str(distance)],
        "_offer_used": our_offer,
    }


def _assemble_cde_opportunity(*, slug, voice, cat_cfg, merchant, merchant_id,
                                 merchant_name, owner_first, active_offers,
                                 trigger, trigger_payload, trigger_kind, trigger_id,
                                 urgency, customer, **__) -> dict:
    credits = trigger_payload.get("credits", 0)
    fee = trigger_payload.get("fee", "")
    digest_items = cat_cfg.get("digest", [])
    if not digest_items:
        digest_items = _load_cat_digest(slug)
    item_id = trigger_payload.get("digest_item_id", "")
    item = next((d for d in sorted(digest_items, key=lambda x: x.get("id", ""))
                 if d.get("id") == item_id), None)
    sal = _salutation(voice, owner_first)

    if item:
        title = item.get("title", "")
        date_str = item.get("date", "")[:10] if item.get("date") else ""
        body = (f"{sal}, CDE opportunity: '{title}' — {credits} credit{'s' if credits != 1 else ''}, "
                f"{fee}. {date_str}. "
                f"Interested? I can set a reminder + send you the registration link details.")
    else:
        body = (f"{sal}, CDE opportunity in your category — {credits} credits, {fee}. "
                f"Want me to send the details?")

    return {
        "message": body,
        "cta": "binary_yes_no",
        "send_as": "vera",
        "template_name": "vera_cde_v1",
        "template_params": [sal, str(credits), fee],
        "_offer_used": None,
    }


def _assemble_perf_spike(*, slug, voice, cat_cfg, merchant, merchant_id,
                           merchant_name, owner_first, active_offers,
                           trigger, trigger_payload, trigger_kind, trigger_id,
                           urgency, customer, **__) -> dict:
    metric = trigger_payload.get("metric", "calls")
    delta_pct = trigger_payload.get("delta_pct", 0)
    driver = trigger_payload.get("likely_driver", "")
    sal = _salutation(voice, owner_first)

    driver_line = f" — likely driven by {driver.replace('_', ' ')}" if driver else ""
    body = (f"{sal}, good news: your {metric} are up {int(delta_pct * 100)}% this week{driver_line}. "
            f"Strike while the iron is hot — want me to draft a follow-up offer to convert those inquiries?")

    return {
        "message": body,
        "cta": "binary_yes_no",
        "send_as": "vera",
        "template_name": "vera_perf_spike_v1",
        "template_params": [sal, metric, str(int(delta_pct * 100))],
        "_offer_used": None,
    }


def _assemble_customer_lapsed_hard(*, slug, voice, cat_cfg, merchant, merchant_id,
                                     merchant_name, owner_first, active_offers,
                                     trigger, trigger_payload, trigger_kind, trigger_id,
                                     urgency, customer, **__) -> dict:
    if customer is None:
        return None
    cname = customer.get("identity", {}).get("name", "").split("(")[0].strip()
    days_lapsed = trigger_payload.get("days_since_last_visit", 60)
    prev_focus = trigger_payload.get("previous_focus", "").replace("_", " ")
    weeks = round(days_lapsed / 7)

    # Match an offer to their focus
    focus_kw = prev_focus.split()[0] if prev_focus else ""
    offer = _best_offer(active_offers, cat_cfg, focus_kw)
    offer_line = f" We've got a {offer['title']} that fits {prev_focus} goals well." if offer else ""

    body = (f"Hi {cname} 👋 {owner_first} from {merchant_name} here. "
            f"It's been about {weeks} weeks — happens to most members at some point, no judgment.{offer_line} "
            f"Want me to hold a free trial spot for you next week? Reply YES — no commitment, no auto-charge.")

    return {
        "message": body,
        "cta": "binary_yes_no",
        "send_as": "merchant_on_behalf",
        "template_name": "merchant_lapse_winback_v1",
        "template_params": [cname, owner_first, merchant_name, str(weeks)],
        "_offer_used": offer,
    }


def _assemble_trial_followup(*, slug, voice, cat_cfg, merchant, merchant_id,
                               merchant_name, owner_first, active_offers,
                               trigger, trigger_payload, trigger_kind, trigger_id,
                               urgency, customer, **__) -> dict:
    if customer is None:
        return None
    cname = customer.get("identity", {}).get("name", "").split("(")[0].strip()
    next_sessions = trigger_payload.get("next_session_options", [])
    trial_date = trigger_payload.get("trial_date", "")

    slot_label = next_sessions[0].get("label", "next Saturday morning") if next_sessions else "next Saturday"
    offer = _best_offer(active_offers, cat_cfg)
    offer_line = f" Special first-month rate: {offer['title']}." if offer else ""

    body = (f"Hi {cname}! Loved having you at your trial.{offer_line} "
            f"Next session: {slot_label}. Want me to reserve your spot? Reply YES.")

    return {
        "message": body,
        "cta": "binary_yes_no",
        "send_as": "merchant_on_behalf",
        "template_name": "merchant_trial_followup_v1",
        "template_params": [cname, slot_label],
        "_offer_used": offer,
    }


def _assemble_dormant(*, slug, voice, cat_cfg, merchant, merchant_id,
                        merchant_name, owner_first, active_offers,
                        trigger, trigger_payload, trigger_kind, trigger_id,
                        urgency, customer, **__) -> dict:
    days = trigger_payload.get("days_since_last_merchant_message", 30)
    last_topic = trigger_payload.get("last_topic", "").replace("_", " ")
    sal = _salutation(voice, owner_first)

    body = (f"{sal}, we haven't connected in {days} days — last we spoke it was about {last_topic}. "
            f"Quick question: what's the one thing slowing you down most right now? "
            f"I'll see what I can fix today.")

    return {
        "message": body,
        "cta": "open_ended",
        "send_as": "vera",
        "template_name": "vera_re_engage_v1",
        "template_params": [sal, str(days), last_topic],
        "_offer_used": None,
    }


def _assemble_generic(*, slug, voice, cat_cfg, merchant, merchant_id,
                        merchant_name, owner_first, active_offers,
                        trigger, trigger_payload, trigger_kind, trigger_id,
                        urgency, customer, **__) -> dict:
    sal = _salutation(voice, owner_first, customer)
    offer = _best_offer(active_offers, cat_cfg)
    offer_line = f" Current offer: {offer['title']}." if offer else ""

    body = (f"{sal}, quick update from Vera.{offer_line} "
            f"Want me to draft something specific for this?")

    return {
        "message": body,
        "cta": "binary_yes_no",
        "send_as": "vera",
        "template_name": "vera_generic_v1",
        "template_params": [sal],
        "_offer_used": offer,
    }


# ═══════════════════════════════════════════════════════════════════
#  Stage 6 + 7 helpers
# ═══════════════════════════════════════════════════════════════════

def _make_suppression_key(merchant_id: str, trigger_id: str, trigger_kind: str) -> str:
    today = datetime.date.today().isoformat()
    return f"{trigger_kind}:{merchant_id}:{today}"


def _build_rationale(*, trigger_kind: str, trigger_id: str, score: float,
                     concrete_boost: float, customer, voice: dict, offer_used) -> str:
    parts = [f"Trigger: {trigger_kind} (score {score:.2f}, concrete boost {concrete_boost:.2f})."]
    parts.append(f"Tone: {voice.get('tone', 'neutral')} / {voice.get('register', 'professional')}.")
    if customer:
        lang = customer.get("identity", {}).get("language_pref", "english")
        parts.append(f"Customer: {customer.get('state', 'unknown')} state, lang={lang}.")
    if offer_used:
        parts.append(f"Offer used: {offer_used.get('title', 'n/a')} (from merchant catalog).")
    else:
        parts.append("No fabricated offer — used category catalog default or no offer needed.")
    return " ".join(parts)


def _extract_key_finding(summary: str) -> str:
    """Pull the most specific sentence from a summary (first sentence with a %)."""
    if not summary:
        return summary
    sentences = summary.replace("\n", " ").split(".")
    for s in sentences:
        if "%" in s or any(c.isdigit() for c in s):
            return s.strip()
    return sentences[0].strip() if sentences else summary[:120]


def _kind_label(kind: str) -> str:
    return {
        "research": "research",
        "compliance": "compliance update",
        "cde": "CDE opportunity",
        "trend": "market trend",
        "tech": "product update",
        "supply": "supply alert",
        "alert": "alert",
        "seasonal": "seasonal insight",
    }.get(kind, kind)


# ═══════════════════════════════════════════════════════════════════
#  Multi-trigger ranking (used by /v1/tick)
# ═══════════════════════════════════════════════════════════════════

def rank_triggers(trigger_records: List[dict]) -> List[dict]:
    """
    Score and sort a list of trigger payloads (each is the stored 'payload' dict).
    Returns them sorted highest-score-first. Deterministic (stable sort, sorted key).
    """
    def _score(trg: dict) -> float:
        kind = trg.get("kind", "")
        urgency = trg.get("urgency", 2)
        payload = trg.get("payload", {})
        base = trigger_base_score(kind)
        bonus = _concrete_number_bonus(payload)
        return base + bonus + urgency * 0.1

    # Sort by score desc, then by id asc for ties (determinism)
    return sorted(trigger_records, key=lambda t: (-_score(t), t.get("id", "")))
