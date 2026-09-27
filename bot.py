"""
bot.py — Top-level entrypoint for the magicpin AI Challenge ("Vera").

Implements the official compose() interface specified in challenge-brief.md §7.1.
Delegates to the deterministic composition pipeline in vera-bot/compose.py.
"""
from __future__ import annotations
import os
import sys
from typing import Optional

# Ensure vera-bot directory is on sys.path using absolute path
_vera_bot_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vera-bot")
if _vera_bot_dir not in sys.path:
    sys.path.insert(0, _vera_bot_dir)

from compose import compose as _vera_compose


def compose(
    category: dict,
    merchant: dict,
    trigger: dict,
    customer: Optional[dict] = None
) -> dict:
    """
    Compose a personalized, deterministic WhatsApp message.

    Parameters:
        category: CategoryContext dict
        merchant: MerchantContext dict
        trigger: TriggerContext dict
        customer: Optional CustomerContext dict

    Returns:
        dict with keys:
            - body (or message): WhatsApp message text
            - cta: Call-to-action string
            - send_as: 'vera' or 'merchant_on_behalf'
            - suppression_key: Dedup key string
            - rationale: Short explanation of decision logic
    """
    res = _vera_compose(category, merchant, trigger, customer)
    if res is None:
        # Default fallback for hard-suppressed / opted-out contacts
        return {
            "body": "",
            "message": "",
            "cta": "none",
            "send_as": "vera",
            "suppression_key": f"suppressed:{merchant.get('merchant_id', '')}",
            "rationale": "Suppressed due to opt-out or missing consent"
        }
    
    # Ensure both 'body' and 'message' keys exist for compatibility
    res["body"] = res.get("message", "")
    return res


if __name__ == "__main__":
    import json
    
    print("Testing bot.py compose()...\n")
    
    sample_category = {
        "slug": "dentists",
        "voice": {"tone": "clinical_peer", "taboos": ["cure", "guaranteed"]},
        "peer_stats": {"avg_rating": 4.4, "avg_reviews": 62, "avg_ctr": 0.030},
        "digest": []
    }
    sample_merchant = {
        "merchant_id": "m_002_bharat_dentist_mumbai",
        "category_slug": "dentists",
        "identity": {"owner_first_name": "Bharat", "name": "Bharat Dental Care", "locality": "Bandra"},
        "subscription": {"days_remaining": 12, "plan": "Pro"},
        "performance": {"views": 1500, "calls": 6, "ctr": 0.025},
        "offers": [{"id": "off_1", "title": "Dental Cleaning @ ₹299", "status": "active"}]
    }
    sample_trigger = {
        "id": "trg_004_perf_dip_bharat",
        "kind": "perf_dip",
        "urgency": 4,
        "payload": {"metric": "calls", "delta_pct": -0.50, "window": "7d", "vs_baseline": 12}
    }
    
    result = compose(sample_category, sample_merchant, sample_trigger)
    print("Composed Output:")
    print(json.dumps(result, indent=2))
