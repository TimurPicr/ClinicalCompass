"""Compatibility facade: compose clinical feature routers without changing imports.

Each feature owns its validation, routes and straightforward database functions.
Existing scripts/tests can continue importing the public helpers from this module.
"""
from fastapi import APIRouter
from app.backend import patients, questionnaire_routes, medications, diary, monitoring
from app.backend.clinical_common import Input, ScheduleInput, aware, row_dict, lock_patient, patient_only
from app.backend.patients import (RecordInput, pending_count, patient_dict,
                                  list_patients, get_patient, get_record, update_record)
from app.backend.questionnaire_routes import (TemplateInput, AssignmentInput, ResponseInput,
    ensure_standard_templates, response_dict, assignment_dict, list_templates, create_template,
    update_template, list_assignments, create_assignment, next_due, submit_response)
from app.backend.medications import (PrescriptionInput, IntakeInput, prescription_dict,
    list_prescriptions, create_prescription, update_prescription, create_intake)
from app.backend.diary import DiaryInput, list_diary, create_diary, diary_schedule
from app.backend.monitoring import (AlertInput, alert_dict, list_alerts, all_alerts,
    act_on_alert, evaluate_rules, record_event)

router = APIRouter(prefix='/api', tags=['clinical'])
for feature in (patients, questionnaire_routes, medications, diary, monitoring):
    router.include_router(feature.router)
