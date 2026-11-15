"""Distinguish verified settlement rules from an observed personal cash receipt."""
from datetime import date

import numpy as np
import pandas as pd


RULE_MODE = "RULE_BASED_SIMULATION"


def rule_errors(action):
    """A documentary attestation is necessary; this does not verify the document."""
    errors = []
    verified = action.get("settlement_rule_verified")
    if not isinstance(verified, (bool, np.bool_)) or not verified:
        errors.append("verified settlement rule required")
    source = action.get("settlement_rule_source_url")
    if not isinstance(source, str) or not source.startswith(("https://", "http://")):
        errors.append("settlement rule source URL required")
    scope = action.get("settlement_rule_event_types")
    if not isinstance(scope, list) or action.get("action_type") not in scope:
        errors.append("settlement rule does not cover this event type")
    if action.get("settlement_account_type") != "HYPOTHETICAL_DESIGNATED_TRADING_ACCOUNT":
        errors.append("explicit hypothetical designated-trading account required")
    if pd.notna(action.get("actual_pay_date")):
        errors.append("rule-based simulation cannot assert actual account receipt")
    try:
        pay = str(action["pay_date"])
        if date.fromisoformat(pay).isoformat() != pay or action.get("scheduled_pay_date") != pay:
            raise ValueError("scheduled date mismatch")
        basis = action.get("settlement_rule_credit_basis")
        basis = "ANNOUNCED_INVESTOR_PAY_DATE" if basis is None or pd.isna(basis) else basis
        if basis == "NEXT_SESSION_AFTER_PARTICIPANT_TRANSFER":
            participant, modeled = action.get("participant_transfer_date"), action.get("modeled_cash_date")
            if (date.fromisoformat(participant).isoformat() != participant
                    or date.fromisoformat(modeled).isoformat() != modeled or participant < pay or modeled <= participant):
                raise ValueError("invalid participant/credit chronology")
        elif basis != "ANNOUNCED_INVESTOR_PAY_DATE":
            raise ValueError("unknown modeled credit basis")
        elif pd.notna(action.get("modeled_cash_date")) and action["modeled_cash_date"] != pay:
            raise ValueError("announced investor credit must use the announced day")
        start = str(action["settlement_rule_effective_from"])
        end = action.get("settlement_rule_effective_to")
        if date.fromisoformat(start).isoformat() != start or start > pay:
            raise ValueError("rule not yet effective")
        if pd.notna(end) and (date.fromisoformat(str(end)).isoformat() != end or pay > end):
            raise ValueError("rule expired")
        known, available = pd.Timestamp(action["settlement_rule_available_at"]), pd.Timestamp(action["available_at"])
        if pd.isna(known) or known.tzinfo is None or available.tzinfo is None or known > available:
            raise ValueError("future or naive settlement evidence")
    except (ValueError, TypeError, KeyError):
        errors.append("invalid settlement-rule chronology or payment date")
    return errors
