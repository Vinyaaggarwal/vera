"""
Category voice/rule tables — table-driven, deterministic.
One record per category slug.
"""
from __future__ import annotations
from typing import Dict, List, Any


# ──────────────────────────────────────────────
# Category configs (loaded from stored CategoryContext at runtime,
# but these defaults mirror dataset/categories/*.json exactly)
# ──────────────────────────────────────────────

CATEGORY_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "dentists": {
        "slug": "dentists",
        "tone": "peer_clinical",
        "register": "respectful_collegial",
        "code_mix": "hindi_english_natural",
        "salutation_template": "Dr. {first_name}",     # use "Doc" as fallback
        "send_as_merchant_on_behalf": True,             # for customer-facing
        "vocab_taboo": [
            "guaranteed", "100% safe", "completely cure", "miracle",
            "best in city", "doctor approved",
        ],
        "never_do": [
            "no_urls",
            "no_fabricated_numbers",
            "no_medical_claims_to_patient",
        ],
        "cta_style": "open_ended_or_binary",
        "emoji_policy": "sparingly",
        "peer_stats_key": "avg_ctr",
        "seasonal_notes": {
            "Nov-Feb": "exam-stress bruxism spike — ortho consults rise 30%",
            "Oct-Dec": "wedding whitening peak — bookings 2x baseline",
            "Jan": "new-year resolution surge — annual check-up bookings +40%",
            "Apr-Jun": "school holiday window — pediatric appointments +50%",
        },
    },
    "salons": {
        "slug": "salons",
        "tone": "warm_practical",
        "register": "approachable_expert",
        "code_mix": "hindi_english_natural",
        "salutation_template": "Hi {first_name}",
        "send_as_merchant_on_behalf": True,
        "vocab_taboo": [
            "guaranteed glow", "permanent results", "instant transformation",
            "miracle", "best in city",
        ],
        "never_do": ["no_urls", "no_fabricated_numbers"],
        "cta_style": "binary_or_multi_slot",
        "emoji_policy": "moderate",
        "peer_stats_key": "avg_ctr",
        "seasonal_notes": {
            "Oct-Dec": "primary wedding/festival season — bridal package bookings 4x baseline",
            "Apr-May": "secondary bridal window + summer hair-care surge",
            "Jul-Aug": "monsoon haircare focus (anti-frizz, scalp treatments)",
            "Mar": "Holi colour-recovery surge",
        },
    },
    "restaurants": {
        "slug": "restaurants",
        "tone": "warm_busy_practical",
        "register": "fellow_operator",
        "code_mix": "hindi_english_natural",
        "salutation_template": "Hi {first_name}",
        "send_as_merchant_on_behalf": True,
        "vocab_taboo": [
            "best food in city", "guaranteed packed house",
            "miracle marketing", "viral guarantee",
        ],
        "never_do": ["no_urls", "no_fabricated_numbers"],
        "cta_style": "binary_or_open",
        "emoji_policy": "minimal",
        "peer_stats_key": "avg_ctr",
        "seasonal_notes": {
            "Mar-Apr": "IPL season — match-night promos on Tue/Wed/Thu; not weekends",
            "Oct-Nov": "Diwali corporate gifting + family-feast bookings",
            "Dec": "Christmas + New Year — set menu sales 3x baseline",
            "Jul-Aug": "monsoon delivery surge; rain-day discount window",
            "Feb 14": "Valentine's prix-fixe",
        },
    },
    "gyms": {
        "slug": "gyms",
        "tone": "energetic_disciplined",
        "register": "coach_to_member",
        "code_mix": "english_primary_some_hindi",
        "salutation_template": "Hi {first_name}",
        "send_as_merchant_on_behalf": True,
        "vocab_taboo": [
            "guaranteed weight loss", "shred in 7 days",
            "miracle transformation", "fastest results",
        ],
        "never_do": ["no_urls", "no_shame_language", "no_fabricated_numbers"],
        "cta_style": "binary_yes_no",
        "emoji_policy": "minimal",
        "peer_stats_key": "avg_ctr",
        "seasonal_notes": {
            "Jan": "resolution surge — trial walk-ins 4x baseline",
            "Apr-Jun": "lowest acquisition window — focus on retention",
            "Aug-Oct": "wedding-prep + festival window",
            "Nov-Dec": "holiday slowdown — right time to pilot new programs",
        },
    },
    "pharmacies": {
        "slug": "pharmacies",
        "tone": "trustworthy_precise",
        "register": "neighbourhood_pharmacist",
        "code_mix": "hindi_english_natural",
        "salutation_template": "Namaste",   # or "Hi {first_name}" for staff
        "send_as_merchant_on_behalf": True,
        "vocab_taboo": [
            "miracle cure", "guaranteed result", "100% safe",
            "doctor recommended", "best price",
        ],
        "never_do": [
            "no_urls", "no_fabricated_numbers",
            "no_alarmist_language", "no_prescription_advice",
        ],
        "cta_style": "binary_confirm_cancel",
        "emoji_policy": "none",
        "peer_stats_key": "avg_ctr",
        "seasonal_notes": {
            "Apr-Jun": "summer surge — ORS, sunscreen, anti-fungal",
            "Jul-Aug": "monsoon — anti-bacterial, immunity supplements",
            "Oct-Nov": "festival → blood sugar spike — diabetic monitoring",
            "Dec-Jan": "respiratory peak — cough/cold/anti-allergic 2x baseline",
        },
    },
}


def get_category_config(slug: str, live_payload: dict | None = None) -> dict:
    """
    Return merged category config.
    live_payload (from stored CategoryContext) takes precedence over CATEGORY_DEFAULTS.
    """
    base = dict(CATEGORY_DEFAULTS.get(slug, {}))
    if live_payload:
        # Merge top-level keys from live payload (offer_catalog, digest, peer_stats, etc.)
        for k, v in live_payload.items():
            if v is not None:
                base[k] = v
    return base


def get_voice_constraints(slug: str, live_payload: dict | None = None) -> dict:
    cfg = get_category_config(slug, live_payload)
    return {
        "tone": cfg.get("tone", "neutral"),
        "register": cfg.get("register", "professional"),
        "salutation_template": cfg.get("salutation_template", "Hi {first_name}"),
        "vocab_taboo": cfg.get("vocab_taboo", []),
        "never_do": cfg.get("never_do", []),
        "cta_style": cfg.get("cta_style", "open_ended"),
        "emoji_policy": cfg.get("emoji_policy", "minimal"),
    }


# ──────────────────────────────────────────────
# Trigger-kind → human priority hint
# (higher = rank higher when composing)
# ──────────────────────────────────────────────

TRIGGER_KIND_BASE_SCORE: Dict[str, float] = {
    # Urgency-5 / time-critical
    "supply_alert": 10.0,
    "regulation_change": 9.0,
    # Urgency-4 / action-needed
    "renewal_due": 8.5,
    "perf_dip": 8.0,
    "active_planning_intent": 8.0,
    # Urgency-3 / standard
    "recall_due": 7.0,
    "customer_lapsed_hard": 6.5,
    "ipl_match_today": 6.0,
    "review_theme_emerged": 6.0,
    "chronic_refill_due": 7.5,
    "trial_followup": 6.0,
    "gbp_unverified": 5.5,
    # Urgency-2 / opportunity
    "competitor_opened": 5.0,
    "seasonal_perf_dip": 4.5,
    "winback_eligible": 4.5,
    "bridal_followup": 4.5,
    "wedding_package_followup": 4.5,
    "research_digest": 4.0,
    "category_seasonal": 4.0,
    "dormant_with_vera": 3.5,
    # Urgency-1 / low
    "festival_upcoming": 3.0,
    "milestone_reached": 3.0,
    "cde_opportunity": 2.5,
    "perf_spike": 2.0,
    "curious_ask_due": 2.0,
}


def trigger_base_score(kind: str) -> float:
    return TRIGGER_KIND_BASE_SCORE.get(kind, 3.0)
