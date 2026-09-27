"""
Unit tests for compose() — validated against the 10 case-study anchors.
Run: pytest tests/test_compose.py -v
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from compose import compose, rank_triggers
from categories import get_category_config


# ── Fixtures ──────────────────────────────────────────────────────

DENTIST_CATEGORY = get_category_config("dentists")
SALON_CATEGORY   = get_category_config("salons")
RESTAURANT_CATEGORY = get_category_config("restaurants")
GYM_CATEGORY     = get_category_config("gyms")
PHARMACY_CATEGORY = get_category_config("pharmacies")

MERCHANT_MEERA = {
    "merchant_id": "m_001_drmeera_dentist_delhi",
    "category_slug": "dentists",
    "identity": {
        "name": "Dr. Meera's Dental Clinic",
        "city": "Delhi",
        "locality": "Lajpat Nagar",
        "owner_first_name": "Meera",
    },
    "subscription": {"status": "active", "plan": "Pro", "days_remaining": 82},
    "performance": {"views": 2410, "calls": 18, "ctr": 0.021, "delta_7d": {"views_pct": 0.18}},
    "offers": [
        {"id": "o_meera_001", "title": "Dental Cleaning @ ₹299", "status": "active"},
    ],
    "customer_aggregate": {
        "total_unique_ytd": 540, "lapsed_180d_plus": 78,
        "retention_6mo_pct": 0.38, "high_risk_adult_count": 124,
    },
    "signals": ["stale_posts:22d", "ctr_below_peer_median", "high_risk_adult_cohort"],
}

MERCHANT_STUDIO11 = {
    "merchant_id": "m_003_studio11_salon_hyderabad",
    "category_slug": "salons",
    "identity": {
        "name": "Studio11 Family Salon",
        "city": "Hyderabad",
        "locality": "Kapra",
        "owner_first_name": "Lakshmi",
    },
    "subscription": {"status": "active", "plan": "Pro", "days_remaining": 145},
    "performance": {"views": 4980, "calls": 62, "ctr": 0.048},
    "offers": [
        {"id": "o_studio11_001", "title": "Haircut @ ₹99", "status": "active"},
        {"id": "o_studio11_002", "title": "Hair Spa @ ₹499", "status": "active"},
    ],
    "customer_aggregate": {"total_unique_ytd": 1150, "lapsed_90d_plus": 220},
}

MERCHANT_SKPIZZA = {
    "merchant_id": "m_005_pizzajunction_restaurant_delhi",
    "category_slug": "restaurants",
    "identity": {
        "name": "SK Pizza Junction",
        "city": "Delhi",
        "locality": "Sant Nagar",
        "owner_first_name": "Suresh",
    },
    "subscription": {"status": "trial", "plan": "Trial", "days_remaining": 7},
    "performance": {"views": 2200, "calls": 12, "ctr": 0.020},
    "offers": [
        {"id": "o_skpz_001", "title": "Buy 1 Pizza Get 1 Free (Tue-Thu)", "status": "active"},
    ],
    "customer_aggregate": {"delivery_orders_30d": 180, "dine_in_orders_30d": 95},
}

MERCHANT_POWERHOUSE = {
    "merchant_id": "m_007_powerhouse_gym_bangalore",
    "category_slug": "gyms",
    "identity": {
        "name": "PowerHouse Fitness",
        "city": "Bangalore",
        "locality": "HSR Layout",
        "owner_first_name": "Karthik",
    },
    "subscription": {"status": "active", "plan": "Pro", "days_remaining": 95},
    "performance": {"views": 1480, "calls": 22, "ctr": 0.052},
    "offers": [
        {"id": "o_powerhouse_001", "title": "3 FREE Trial Classes", "status": "active"},
    ],
    "customer_aggregate": {"total_active_members": 245, "monthly_churn_pct": 0.10},
}

MERCHANT_APOLLO = {
    "merchant_id": "m_009_apollo_pharmacy_jaipur",
    "category_slug": "pharmacies",
    "identity": {
        "name": "Apollo Health Plus Pharmacy",
        "city": "Jaipur",
        "locality": "Malviya Nagar",
        "owner_first_name": "Ramesh",
    },
    "subscription": {"status": "active", "plan": "Pro", "days_remaining": 60},
    "performance": {"views": 1850, "calls": 38, "ctr": 0.045},
    "offers": [
        {"id": "o_apollo_001", "title": "Free Home Delivery > ₹499", "status": "active"},
        {"id": "o_apollo_002", "title": "Senior Citizen 15% OFF", "status": "active"},
    ],
    "customer_aggregate": {
        "total_unique_ytd": 1820, "repeat_customer_pct": 0.68, "chronic_rx_count": 240,
    },
}

CUSTOMER_PRIYA = {
    "customer_id": "c_001_priya_for_m001",
    "merchant_id": "m_001_drmeera_dentist_delhi",
    "identity": {"name": "Priya", "language_pref": "hi-en mix", "age_band": "25-35"},
    "state": "lapsed_soft",
    "preferences": {"preferred_slots": "weekday_evening", "channel": "whatsapp", "reminder_opt_in": True},
    "consent": {"opted_in_at": "2025-11-04", "scope": ["recall_reminders", "appointment_reminders"]},
}

CUSTOMER_KAVYA = {
    "customer_id": "c_005_kavya_for_m003",
    "merchant_id": "m_003_studio11_salon_hyderabad",
    "identity": {"name": "Kavya", "language_pref": "english", "age_band": "20-25"},
    "state": "new",
    "preferences": {"preferred_slots": "saturday", "channel": "whatsapp", "reminder_opt_in": True, "wedding_date": "2026-11-08"},
    "consent": {"opted_in_at": "2026-03-22", "scope": ["appointment_reminders", "bridal_package_followup"]},
}

CUSTOMER_RASHMI = {
    "customer_id": "c_010_rashmi_for_m007",
    "merchant_id": "m_007_powerhouse_gym_bangalore",
    "identity": {"name": "Rashmi", "language_pref": "english", "age_band": "30-40"},
    "state": "lapsed_hard",
    "preferences": {"preferred_slots": "weekday_evening", "channel": "whatsapp", "reminder_opt_in": True},
    "consent": {"opted_in_at": "2025-09-10", "scope": ["renewal_reminders", "winback_offers"]},
}

CUSTOMER_GRANDFATHER = {
    "customer_id": "c_013_grandfather_for_m009",
    "merchant_id": "m_009_apollo_pharmacy_jaipur",
    "identity": {"name": "Mr. Sharma", "language_pref": "hi", "age_band": "65-75", "senior_citizen": True},
    "state": "active",
    "preferences": {"preferred_slots": "morning_delivery", "channel": "whatsapp_via_son", "reminder_opt_in": True},
    "consent": {"opted_in_at": "2024-08-10", "scope": ["refill_reminders", "delivery_notifications", "recall_alerts"]},
}

CUSTOMER_OPTED_OUT = {
    "customer_id": "c_xxx_optedout",
    "merchant_id": "m_001_drmeera_dentist_delhi",
    "identity": {"name": "TestUser"},
    "state": "opted_out",
    "preferences": {"reminder_opt_in": False},
    "consent": {"opted_in_at": None, "scope": []},
}


# ── Case Study 1: Dentists / Research Digest ─────────────────────

class TestCS1ResearchDigest:
    def test_returns_message(self):
        trigger = {
            "id": "trg_001_research_digest_dentists",
            "kind": "research_digest",
            "source": "external",
            "merchant_id": "m_001_drmeera_dentist_delhi",
            "customer_id": None,
            "payload": {"category": "dentists", "top_item_id": "d_2026W17_jida_fluoride"},
            "urgency": 2,
            "suppression_key": "research:dentists:2026-W17",
        }
        result = compose(DENTIST_CATEGORY, MERCHANT_MEERA, trigger, None)
        assert result is not None
        assert len(result["message"]) > 30

    def test_contains_source_citation(self):
        trigger = {
            "id": "trg_001_research_digest_dentists",
            "kind": "research_digest",
            "payload": {"category": "dentists", "top_item_id": "d_2026W17_jida_fluoride"},
            "urgency": 2,
            "suppression_key": "research:dentists:2026-W17",
        }
        result = compose(DENTIST_CATEGORY, MERCHANT_MEERA, trigger)
        assert result is not None
        assert "JIDA" in result["message"] or "jida" in result["message"].lower()

    def test_mentions_high_risk_cohort(self):
        trigger = {
            "id": "trg_001",
            "kind": "research_digest",
            "payload": {"category": "dentists", "top_item_id": "d_2026W17_jida_fluoride"},
            "urgency": 2,
            "suppression_key": "research:dentists:2026-W17",
        }
        result = compose(DENTIST_CATEGORY, MERCHANT_MEERA, trigger)
        assert result is not None
        assert "124" in result["message"] or "high-risk" in result["message"]

    def test_send_as_vera(self):
        trigger = {
            "id": "trg_001", "kind": "research_digest",
            "payload": {"category": "dentists", "top_item_id": "d_2026W17_jida_fluoride"},
            "urgency": 2, "suppression_key": "research:dentists:2026-W17",
        }
        result = compose(DENTIST_CATEGORY, MERCHANT_MEERA, trigger)
        assert result["send_as"] == "vera"

    def test_deterministic(self):
        trigger = {
            "id": "trg_001", "kind": "research_digest",
            "payload": {"category": "dentists", "top_item_id": "d_2026W17_jida_fluoride"},
            "urgency": 2, "suppression_key": "research:dentists:2026-W17",
        }
        r1 = compose(DENTIST_CATEGORY, MERCHANT_MEERA, trigger)
        r2 = compose(DENTIST_CATEGORY, MERCHANT_MEERA, trigger)
        assert r1["message"] == r2["message"]


# ── Case Study 2: Dentists / Recall Reminder ─────────────────────

class TestCS2RecallReminder:
    TRIGGER = {
        "id": "trg_003_recall_due_priya",
        "kind": "recall_due",
        "merchant_id": "m_001_drmeera_dentist_delhi",
        "customer_id": "c_001_priya_for_m001",
        "payload": {
            "service_due": "6_month_cleaning",
            "last_service_date": "2026-05-12",
            "due_date": "2026-11-12",
            "available_slots": [
                {"iso": "2026-11-05T18:00:00+05:30", "label": "Wed 5 Nov, 6pm"},
                {"iso": "2026-11-06T17:00:00+05:30", "label": "Thu 6 Nov, 5pm"},
            ],
        },
        "urgency": 3,
        "suppression_key": "recall:c_001_priya_for_m001:6mo",
    }

    def test_addresses_customer_by_name(self):
        result = compose(DENTIST_CATEGORY, MERCHANT_MEERA, self.TRIGGER, CUSTOMER_PRIYA)
        assert result is not None
        assert "Priya" in result["message"]

    def test_contains_slots(self):
        result = compose(DENTIST_CATEGORY, MERCHANT_MEERA, self.TRIGGER, CUSTOMER_PRIYA)
        assert "Nov" in result["message"] or "slot" in result["message"].lower()

    def test_contains_price(self):
        result = compose(DENTIST_CATEGORY, MERCHANT_MEERA, self.TRIGGER, CUSTOMER_PRIYA)
        assert "₹299" in result["message"] or "299" in result["message"]

    def test_merchant_on_behalf(self):
        result = compose(DENTIST_CATEGORY, MERCHANT_MEERA, self.TRIGGER, CUSTOMER_PRIYA)
        assert result["send_as"] == "merchant_on_behalf"

    def test_multi_choice_slot_cta(self):
        result = compose(DENTIST_CATEGORY, MERCHANT_MEERA, self.TRIGGER, CUSTOMER_PRIYA)
        assert result["cta"] == "multi_choice_slot"


# ── Case Study 3: Salons / Bridal Followup ───────────────────────

class TestCS3BridalFollowup:
    TRIGGER = {
        "id": "trg_007_bridal_followup_kavya",
        "kind": "wedding_package_followup",
        "merchant_id": "m_003_studio11_salon_hyderabad",
        "customer_id": "c_005_kavya_for_m003",
        "payload": {
            "wedding_date": "2026-11-08",
            "trial_completed": "2026-03-22",
            "days_to_wedding": 196,
            "next_step_window_open": "skin_prep_program_30day",
        },
        "urgency": 2,
        "suppression_key": "bridal_followup:c_005_kavya_for_m003",
    }

    def test_mentions_days_to_wedding(self):
        result = compose(SALON_CATEGORY, MERCHANT_STUDIO11, self.TRIGGER, CUSTOMER_KAVYA)
        assert result is not None
        assert "196" in result["message"]

    def test_merchant_on_behalf(self):
        result = compose(SALON_CATEGORY, MERCHANT_STUDIO11, self.TRIGGER, CUSTOMER_KAVYA)
        assert result["send_as"] == "merchant_on_behalf"


# ── Case Study 4: Salons / Curious Ask ───────────────────────────

class TestCS4CuriousAsk:
    TRIGGER = {
        "id": "trg_008_curious_ask_studio11",
        "kind": "curious_ask_due",
        "merchant_id": "m_003_studio11_salon_hyderabad",
        "payload": {"ask_template": "what_service_in_demand_this_week", "last_ask_at": None},
        "urgency": 1,
        "suppression_key": "curious_ask:m_003:2026-W17",
    }

    def test_uses_owner_name(self):
        result = compose(SALON_CATEGORY, MERCHANT_STUDIO11, self.TRIGGER, None)
        assert "Lakshmi" in result["message"]

    def test_open_ended_cta(self):
        result = compose(SALON_CATEGORY, MERCHANT_STUDIO11, self.TRIGGER, None)
        assert result["cta"] == "open_ended"


# ── Case Study 5: Restaurants / IPL Match ────────────────────────

class TestCS5IPLMatch:
    TRIGGER_WEEKEND = {
        "id": "trg_010_ipl_match_delhi",
        "kind": "ipl_match_today",
        "merchant_id": "m_005_pizzajunction_restaurant_delhi",
        "payload": {
            "match": "DC vs MI",
            "venue": "Arun Jaitley Stadium",
            "city": "Delhi",
            "match_time_iso": "2026-04-26T19:30:00+05:30",
            "is_weeknight": False,
        },
        "urgency": 3,
        "suppression_key": "ipl:m_005:2026-04-26",
    }

    def test_weekend_ipl_warns_about_dip(self):
        result = compose(RESTAURANT_CATEGORY, MERCHANT_SKPIZZA, self.TRIGGER_WEEKEND, None)
        assert result is not None
        assert "12" in result["message"] or "covers" in result["message"].lower()

    def test_weekend_ipl_does_not_push_match_night_promo(self):
        result = compose(RESTAURANT_CATEGORY, MERCHANT_SKPIZZA, self.TRIGGER_WEEKEND, None)
        # Should NOT blindly push the match-night promo on a Saturday
        assert "delivery" in result["message"].lower() or "BOGO" in result["message"]


# ── Case Study 6: Restaurants / Active Planning ──────────────────

class TestCS6ActivePlanning:
    TRIGGER = {
        "id": "trg_013_corporate_thali_planning",
        "kind": "active_planning_intent",
        "merchant_id": "m_006_southindiancafe_restaurant_bangalore",
        "payload": {
            "intent_topic": "corporate_bulk_thali_package",
            "merchant_last_message": "Yes good idea, what would it look like",
        },
        "urgency": 4,
        "suppression_key": "planning:m_006:corp_thali:2026-W17",
    }
    MERCHANT_MYLARI = {
        "merchant_id": "m_006_southindiancafe_restaurant_bangalore",
        "category_slug": "restaurants",
        "identity": {"name": "Mylari South Indian Cafe", "owner_first_name": "Suresh", "locality": "Indiranagar"},
        "subscription": {"status": "active", "plan": "Pro"},
        "offers": [{"id": "o_mylari_001", "title": "Weekday Lunch Thali @ ₹149", "status": "active"}],
        "customer_aggregate": {"repeat_customer_pct": 0.42},
        "performance": {"views": 12400, "calls": 88, "ctr": 0.032},
    }

    def test_tiered_pricing_in_message(self):
        result = compose(RESTAURANT_CATEGORY, self.MERCHANT_MYLARI, self.TRIGGER, None)
        assert result is not None
        assert "₹" in result["message"]
        assert "10" in result["message"] or "thali" in result["message"].lower()


# ── Case Study 7: Gyms / Seasonal Dip ───────────────────────────

class TestCS7SeasonalDip:
    TRIGGER = {
        "id": "trg_014_seasonal_acquisition_dip_powerhouse",
        "kind": "seasonal_perf_dip",
        "merchant_id": "m_007_powerhouse_gym_bangalore",
        "payload": {
            "metric": "views",
            "delta_pct": -0.30,
            "window": "7d",
            "is_expected_seasonal": True,
            "season_note": "post_resolution_window_apr_jun",
        },
        "urgency": 1,
        "suppression_key": "seasonal_dip:m_007:2026-Q2",
    }

    def test_reframes_dip_as_normal(self):
        result = compose(GYM_CATEGORY, MERCHANT_POWERHOUSE, self.TRIGGER, None)
        assert result is not None
        assert "normal" in result["message"].lower() or "seasonal" in result["message"].lower()

    def test_mentions_member_count(self):
        result = compose(GYM_CATEGORY, MERCHANT_POWERHOUSE, self.TRIGGER, None)
        assert "245" in result["message"]


# ── Case Study 8: Gyms / Customer Lapse Winback ──────────────────

class TestCS8LapseWinback:
    TRIGGER = {
        "id": "trg_015_winback_rashmi",
        "kind": "customer_lapsed_hard",
        "merchant_id": "m_007_powerhouse_gym_bangalore",
        "customer_id": "c_010_rashmi_for_m007",
        "payload": {
            "days_since_last_visit": 57,
            "previous_focus": "weight_loss",
            "previous_membership_months": 5,
        },
        "urgency": 3,
        "suppression_key": "winback:c_010_rashmi_for_m007",
    }

    def test_no_shame_language(self):
        result = compose(GYM_CATEGORY, MERCHANT_POWERHOUSE, self.TRIGGER, CUSTOMER_RASHMI)
        assert result is not None
        assert "no judgment" in result["message"]

    def test_no_commitment_framing(self):
        result = compose(GYM_CATEGORY, MERCHANT_POWERHOUSE, self.TRIGGER, CUSTOMER_RASHMI)
        assert "no commitment" in result["message"] or "no auto-charge" in result["message"]

    def test_mentions_owner_name(self):
        result = compose(GYM_CATEGORY, MERCHANT_POWERHOUSE, self.TRIGGER, CUSTOMER_RASHMI)
        assert "Karthik" in result["message"]


# ── Case Study 9: Pharmacies / Supply Alert ──────────────────────

class TestCS9SupplyAlert:
    TRIGGER = {
        "id": "trg_018_supply_atorvastatin_recall",
        "kind": "supply_alert",
        "merchant_id": "m_009_apollo_pharmacy_jaipur",
        "payload": {
            "alert_id": "d_2026W17_atorvastatin_recall",
            "molecule": "atorvastatin",
            "affected_batches": ["AT2024-1102", "AT2024-1108"],
            "manufacturer": "MfrZ",
        },
        "urgency": 5,
        "suppression_key": "alert:atorvastatin:2026-04",
    }

    def test_batch_numbers_in_message(self):
        result = compose(PHARMACY_CATEGORY, MERCHANT_APOLLO, self.TRIGGER, None)
        assert result is not None
        assert "AT2024-1102" in result["message"]

    def test_no_alarm_framing(self):
        result = compose(PHARMACY_CATEGORY, MERCHANT_APOLLO, self.TRIGGER, None)
        assert "sub-potency" in result["message"] or "no safety risk" in result["message"]

    def test_uses_owner_name(self):
        result = compose(PHARMACY_CATEGORY, MERCHANT_APOLLO, self.TRIGGER, None)
        assert "Ramesh" in result["message"]


# ── Case Study 10: Pharmacies / Chronic Refill ───────────────────

class TestCS10ChronicRefill:
    TRIGGER = {
        "id": "trg_019_chronic_refill_grandfather",
        "kind": "chronic_refill_due",
        "merchant_id": "m_009_apollo_pharmacy_jaipur",
        "customer_id": "c_013_grandfather_for_m009",
        "payload": {
            "molecule_list": ["metformin", "atorvastatin", "telmisartan"],
            "last_refill": "2026-03-26",
            "stock_runs_out_iso": "2026-04-28T00:00:00+05:30",
            "delivery_address_saved": True,
        },
        "urgency": 3,
        "suppression_key": "refill:c_013_grandfather_for_m009:2026-04",
    }

    def test_namaste_for_hindi_senior(self):
        result = compose(PHARMACY_CATEGORY, MERCHANT_APOLLO, self.TRIGGER, CUSTOMER_GRANDFATHER)
        assert result is not None
        assert "Namaste" in result["message"]

    def test_molecule_names_present(self):
        result = compose(PHARMACY_CATEGORY, MERCHANT_APOLLO, self.TRIGGER, CUSTOMER_GRANDFATHER)
        assert "metformin" in result["message"]
        assert "atorvastatin" in result["message"]

    def test_senior_discount_mentioned(self):
        result = compose(PHARMACY_CATEGORY, MERCHANT_APOLLO, self.TRIGGER, CUSTOMER_GRANDFATHER)
        assert "15%" in result["message"] or "senior" in result["message"].lower()

    def test_delivery_mentioned(self):
        result = compose(PHARMACY_CATEGORY, MERCHANT_APOLLO, self.TRIGGER, CUSTOMER_GRANDFATHER)
        assert "delivery" in result["message"].lower()


# ── Hard constraints ──────────────────────────────────────────────

class TestHardConstraints:
    def test_consent_opted_out_suppressed(self):
        trigger = {
            "id": "trg_003",
            "kind": "recall_due",
            "merchant_id": "m_001_drmeera_dentist_delhi",
            "customer_id": "c_xxx_optedout",
            "payload": {
                "service_due": "6_month_cleaning",
                "last_service_date": "2026-01-01",
                "due_date": "2026-07-01",
                "available_slots": [],
            },
            "urgency": 3,
            "suppression_key": "recall:c_xxx:6mo",
        }
        result = compose(DENTIST_CATEGORY, MERCHANT_MEERA, trigger, CUSTOMER_OPTED_OUT)
        assert result is None, "Opted-out customer must return None"

    def test_no_url_in_output(self):
        """No http:// or https:// URLs in any composed message."""
        trigger = {
            "id": "trg_001", "kind": "research_digest",
            "payload": {"category": "dentists", "top_item_id": "d_2026W17_jida_fluoride"},
            "urgency": 2, "suppression_key": "research:dentists:2026-W17",
        }
        result = compose(DENTIST_CATEGORY, MERCHANT_MEERA, trigger)
        assert result is not None
        assert "http://" not in result["message"]
        assert "https://" not in result["message"]

    def test_exactly_one_cta(self):
        trigger = {
            "id": "trg_001", "kind": "research_digest",
            "payload": {"category": "dentists", "top_item_id": "d_2026W17_jida_fluoride"},
            "urgency": 2, "suppression_key": "research:dentists:2026-W17",
        }
        result = compose(DENTIST_CATEGORY, MERCHANT_MEERA, trigger)
        assert result is not None
        assert result["cta"] is not None
        # CTA is a single string (not a list)
        assert isinstance(result["cta"], str)

    def test_suppression_key_present(self):
        trigger = {
            "id": "trg_001", "kind": "research_digest",
            "payload": {"category": "dentists", "top_item_id": "d_2026W17_jida_fluoride"},
            "urgency": 2, "suppression_key": "research:dentists:2026-W17",
        }
        result = compose(DENTIST_CATEGORY, MERCHANT_MEERA, trigger)
        assert result is not None
        assert len(result["suppression_key"]) > 0

    def test_rationale_present(self):
        trigger = {
            "id": "trg_001", "kind": "research_digest",
            "payload": {"category": "dentists", "top_item_id": "d_2026W17_jida_fluoride"},
            "urgency": 2, "suppression_key": "research:dentists:2026-W17",
        }
        result = compose(DENTIST_CATEGORY, MERCHANT_MEERA, trigger)
        assert result is not None
        assert len(result["rationale"]) > 10


# ── Trigger ranking ───────────────────────────────────────────────

class TestTriggerRanking:
    def test_supply_alert_beats_research_digest(self):
        supply = {"id": "t1", "kind": "supply_alert", "urgency": 5, "payload": {"batches": ["A", "B"]}}
        research = {"id": "t2", "kind": "research_digest", "urgency": 2, "payload": {}}
        ranked = rank_triggers([research, supply])
        assert ranked[0]["kind"] == "supply_alert"

    def test_concrete_numbers_boost_score(self):
        high = {"id": "t1", "kind": "perf_dip", "urgency": 4, "payload": {"delta_pct": -0.50, "vs_baseline": 12}}
        low  = {"id": "t2", "kind": "perf_dip", "urgency": 4, "payload": {}}
        ranked = rank_triggers([low, high])
        assert ranked[0]["id"] == "t1"

    def test_ranking_is_deterministic(self):
        triggers = [
            {"id": f"t{i}", "kind": "festival_upcoming", "urgency": 1, "payload": {}}
            for i in range(5)
        ]
        r1 = rank_triggers(triggers)
        r2 = rank_triggers(triggers[::-1])
        assert [t["id"] for t in r1] == [t["id"] for t in r2]
