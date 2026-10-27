export interface User { id: number; email: string; full_name: string; role: 'patient' | 'doctor'; doctor_id: number | null }
export interface Question { id: number; text: string; options: string[] }
export interface Scale { id: number; code: string; version: string; title: string; active: boolean; review_status: string; questions: Question[]; validation_source: string | null; license: string | null }
export interface Result { id: number; scale_code: string; scale_version: string; score: number; max_score: number; created_at: string; note: string }
export interface Series { scale: string; version: string; points: { result_id: number; at: string; score: number; max_score: number }[] }
export interface Alert { id: number; patient_id: number; kind: string; severity: string; text: string; status: string; created_at: string }
export interface Recommendation { id: number; title: string; explanation: string; source: string; rule_version: string; status: string; review_comment: string | null; evidence?: { sources?: { document: string; page: number }[]; missing_information?: string[]; clinical_validation?: string } }
export interface Drug { id: number; name: string; status: string; indications: string; contraindications: string; dosing: string; source_url: string; registration_number: string; verified_at: string | null }
export interface Prescription { drug_id: number; regimen: string; drug: Drug }
export interface Plan { id: number; title: string; instructions: string; version: number; status: string; confirmed_at: string | null; prescriptions: Prescription[] }
export interface Report { id: number; plan_id: number; report_date: string; status: string; note: string }
export interface Adverse { id: number; plan_id: number | null; onset_date: string; description: string; status: string; comment: string | null }
export interface Message { id: number; sender_id: number; text: string; created_at: string }
export interface DiaryEntry { id: number; entry_date: string; text: string; result_id: number; answers: number[]; score: number; max_score: number; scale_code: string; scale_version: string; updated_at: string }
