"""Configurable technical rule evaluators, with no clinical thresholds supplied.

To introduce a medical rule an expert must validate its source, scale/version,
parameters and message, then ship an audited data migration. There is deliberately
no public activation endpoint. Unknown/invalid rules are ignored, never inferred.
"""
from sqlalchemy import select
from app.backend.models.clinical import ClinicalAlertRule
from app.backend.services.workflows import create_alert


def score_at_least(result, parameters):
    threshold = parameters.get("threshold")
    return type(threshold) is int and 0 <= threshold <= result.max_score and result.score >= threshold


EVALUATORS = {"score_at_least": score_at_least}


def evaluate_reviewed_rules(db, patient, result):
    if not patient.doctor_id:
        return
    rules = db.scalars(select(ClinicalAlertRule).where(
        ClinicalAlertRule.active.is_(True), ClinicalAlertRule.review_status == "expert_reviewed",
        ClinicalAlertRule.reviewed_by.is_not(None), ClinicalAlertRule.reviewed_at.is_not(None),
        ClinicalAlertRule.scale_code == result.scale_code, ClinicalAlertRule.scale_version == result.scale_version,
    ))
    for rule in rules:
        evaluator = EVALUATORS.get(rule.evaluator)
        if not evaluator or not rule.source.strip() or rule.severity not in {"info", "warning", "critical"}:
            continue
        if evaluator(result, rule.parameters):
            create_alert(db, patient, "reviewed_clinical_rule", f"rule:{rule.id}:result:{result.id}",
                         rule.message, rule.severity)
