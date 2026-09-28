import io
import json
import random
import time

from fastapi import UploadFile
from fastapi.responses import JSONResponse
from PIL import Image

from app.domain.label_utils import field_status, fuzzy_score, normalize_text_for_compare, parse_abv_number, volume_to_ml


class VerificationService:
    def __init__(self, llm_client, format_validator, save_verification_result, extract_application_identifier):
        self._llm_client = llm_client
        self._format_validator = format_validator
        self._save_verification_result = save_verification_result
        self._extract_application_identifier = extract_application_identifier

    @staticmethod
    def _generate_numeric_id(length: int = 7) -> str:
        if length <= 0:
            return "0"
        min_value = 10 ** (length - 1)
        max_value = (10 ** length) - 1
        return str(random.SystemRandom().randint(min_value, max_value))

    @staticmethod
    def _model_field_entry(field_analysis: dict, field_name: str) -> dict:
        entry = field_analysis.get(field_name, {}) if isinstance(field_analysis, dict) else {}
        return entry if isinstance(entry, dict) else {}

    @classmethod
    def _model_field_confidence(cls, field_analysis: dict, field_name: str) -> float | None:
        value = cls._model_field_entry(field_analysis, field_name).get("confidence")
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @classmethod
    def _model_field_overall_confidence(cls, field_analysis: dict, field_name: str) -> float | None:
        value = cls._model_field_entry(field_analysis, field_name).get("overall_confidence")
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _text_decision_confidence(score: float, status: str, thresholds: tuple[float, float] = (90.0, 75.0)) -> float:
        bounded = max(0.0, min(100.0, score))
        pass_threshold, review_threshold = thresholds

        if status == "match":
            if pass_threshold >= 100.0:
                return 75.0
            progress = max(0.0, min(1.0, (bounded - pass_threshold) / max(100.0 - pass_threshold, 1e-6)))
            return round(75.0 + (progress * 25.0), 2)

        if status == "mismatch":
            if review_threshold <= 0.0:
                return 100.0
            progress = max(0.0, min(1.0, (review_threshold - bounded) / review_threshold))
            return round(75.0 + (progress * 25.0), 2)

        band = max(pass_threshold - review_threshold, 1.0)
        midpoint = (pass_threshold + review_threshold) / 2.0
        distance = abs(bounded - midpoint)
        normalized = min(1.0, distance / (band / 2.0))
        confidence = 45.0 + (normalized * 15.0)
        return round(max(40.0, min(60.0, confidence)), 2)

    @staticmethod
    def _numeric_decision_confidence(delta: float | None, match_tolerance: float, suspect_tolerance: float, status: str) -> float | None:
        if delta is None:
            return None
        if status == "match":
            if match_tolerance <= 0:
                return 100.0
            confidence = 100.0 - ((delta / match_tolerance) * 40.0)
            return round(max(0.0, min(100.0, confidence)), 2)
        if status == "mismatch":
            if suspect_tolerance <= match_tolerance:
                return 100.0
            spread = max(suspect_tolerance - match_tolerance, 1e-6)
            exceed = max(0.0, delta - suspect_tolerance)
            confidence = 75.0 + (min(exceed / spread, 1.0) * 25.0)
            return round(max(75.0, min(100.0, confidence)), 2)
        if suspect_tolerance <= match_tolerance:
            return 50.0
        midpoint = (match_tolerance + suspect_tolerance) / 2.0
        distance = abs(delta - midpoint)
        half_band = max((suspect_tolerance - match_tolerance) / 2.0, 1e-6)
        confidence = 45.0 + (min(1.0, distance / half_band) * 20.0)
        return round(max(45.0, min(65.0, confidence)), 2)

    @staticmethod
    def _binary_decision_confidence(status: str, has_values: bool) -> float | None:
        if not has_values:
            return None
        if status == "match":
            return 100.0
        if status == "mismatch":
            return 100.0
        return 50.0

    @staticmethod
    def _public_comparison_status(status: str | None) -> str | None:
        if status is None:
            return None
        if status == "match":
            return "pass"
        if status == "mismatch":
            return "failure"
        if status in {"suspect", "review", "missing"}:
            return "need_review"
        return status

    @staticmethod
    def _should_skip_llm_for_application(app_json: dict | None) -> bool:
        return False

    @staticmethod
    def _case_status_from_field_statuses(statuses: list[str | None]) -> str:
        filtered_statuses = [status for status in statuses if status is not None]
        if not filtered_statuses:
            return "need_review"
        if any(status == "failure" for status in filtered_statuses):
            return "failure"
        if any(status == "need_review" for status in filtered_statuses):
            return "need_review"
        if all(status == "pass" for status in filtered_statuses):
            return "pass"
        return "need_review"

    @staticmethod
    def _trim_comparisons_for_public(comparisons: dict) -> dict:
        if not isinstance(comparisons, dict):
            return {}
        allowed_keys = {
            "status",
            "confidence",
            "reason",
            "app",
            "label",
            "app_ml",
            "label_ml",
            "review_decision",
            "comment",
            "override_value",
            "exact",
        }
        trimmed: dict[str, dict] = {}
        for field_name, entry in comparisons.items():
            if not isinstance(entry, dict):
                continue
            trimmed[field_name] = {key: value for key, value in entry.items() if key in allowed_keys}
        return trimmed

    @staticmethod
    def _trim_application_payload_for_public(app_json: dict | None) -> dict:
        if not isinstance(app_json, dict):
            return {}
        allowed_fields = {
            "brand",
            "class",
            "abv",
            "net_contents",
            "government_warning_present",
            "producer_name",
            "country_of_origin",
        }
        return {key: value for key, value in app_json.items() if key in allowed_fields}

    @classmethod
    def _build_public_result(cls, payload: dict) -> dict:
        public = {
            "result_id": payload.get("result_id"),
            "application_id": payload.get("application_id"),
            "filename": payload.get("filename"),
            "application_source_type": payload.get("application_source_type"),
            "source_files": payload.get("source_files") or {},
            "application": cls._trim_application_payload_for_public(payload.get("application")),
            "comparisons": cls._trim_comparisons_for_public(payload.get("comparisons") or {}),
            "case_result": payload.get("case_result") or {},
            "overall": payload.get("overall"),
            "overall_confidence": payload.get("overall_confidence"),
            "status": payload.get("status"),
            "status_message": payload.get("status_message"),
            "final_decision": payload.get("final_decision"),
            "created_at": payload.get("created_at"),
            "updated_at": payload.get("updated_at"),
            "vision_quality_score": payload.get("vision_quality_score"),
            "llm_status": payload.get("llm_status"),
        }
        if "profiling" in payload:
            public["profiling"] = payload.get("profiling")
        if payload.get("debug") is True:
            public["debug"] = True
            public["parsed"] = payload.get("parsed")
            public["field_analysis"] = payload.get("field_analysis")
            public["model_debug"] = payload.get("model_debug")
            public["local_policy_validation"] = payload.get("local_policy_validation")
        return public

    @staticmethod
    def _field_tokens(text: object, field_name: str) -> list[str]:
        normalized = normalize_text_for_compare(str(text or ""))
        tokens = [token for token in normalized.split() if token]
        if field_name == "producer_name":
            generic_tokens = {
                "distillery",
                "distillers",
                "winery",
                "brewery",
                "company",
                "co",
                "inc",
                "llc",
                "ltd",
                "limited",
                "bottling",
                "bottlers",
                "spirits",
            }
            refined = [token for token in tokens if token not in generic_tokens]
            if refined:
                return refined
        return tokens

    @classmethod
    def _field_similarity_score(cls, app_value: object, label_value: object, field_name: str) -> float:
        left = str(app_value or "")
        right = str(label_value or "")
        if not left.strip() or not right.strip():
            return 0.0

        sequence_score = fuzzy_score(left, right)
        left_tokens = cls._field_tokens(left, field_name)
        right_tokens = cls._field_tokens(right, field_name)
        if not left_tokens or not right_tokens:
            return round(sequence_score, 2)

        left_set = set(left_tokens)
        right_set = set(right_tokens)
        intersection = left_set.intersection(right_set)
        union = left_set.union(right_set)
        token_jaccard = (len(intersection) / max(len(union), 1)) * 100.0

        combined = (sequence_score * 0.55) + (token_jaccard * 0.45)

        left_first = left_tokens[0] if left_tokens else ""
        right_first = right_tokens[0] if right_tokens else ""
        if left_first and right_first and left_first != right_first and len(intersection) <= 1:
            combined = min(combined, 55.0)

        return round(max(0.0, min(100.0, combined)), 2)

    async def verify(
        self,
        application: str | None,
        app_json: dict,
        app_source: str | None,
        application_file: UploadFile | None,
        file: UploadFile | None,
        pre_profile: dict | None = None,
        include_debug: bool = False,
    ) -> JSONResponse:
        request_started = time.perf_counter()
        profiling = dict(pre_profile or {})

        if not file:
            profiling["total_verify_seconds"] = round(time.perf_counter() - request_started, 4)
            return JSONResponse({"error": "missing label image file", "profiling": profiling}, status_code=400)

        stage_started = time.perf_counter()
        content = await file.read()
        profiling["label_file_read_seconds"] = round(time.perf_counter() - stage_started, 4)

        started = time.perf_counter()
        try:
            stage_started = time.perf_counter()
            Image.open(io.BytesIO(content)).convert("RGB")
            profiling["image_validation_seconds"] = round(time.perf_counter() - stage_started, 4)
        except Exception as exc:
            profiling["image_validation_seconds"] = round(time.perf_counter() - stage_started, 4)
            profiling["total_verify_seconds"] = round(time.perf_counter() - request_started, 4)
            return JSONResponse({"error": "ocr_failed", "detail": str(exc), "profiling": profiling}, status_code=500)

        skip_llm = self._should_skip_llm_for_application(app_json)
        if skip_llm:
            stage_started = time.perf_counter()
            llm_result = {
                "status": "skipped",
                "fields": {},
                "field_analysis": {},
                "reason": "Application payload already covered all required fields; skipping direct image analysis for latency.",
                "timings": {"total_seconds": 0.0, "used_streaming": 0.0, "max_output_tokens": 0.0},
            }
            profiling["llm_total_seconds"] = round(time.perf_counter() - stage_started, 4)
            llm_timings = llm_result.get("timings") if isinstance(llm_result, dict) else None
            if isinstance(llm_timings, dict):
                profiling["llm_breakdown"] = llm_timings
            llm_status = llm_result.get("status", "skipped")
        else:
            stage_started = time.perf_counter()
            llm_result = self._llm_client.extract_fields_from_image(content, file.content_type, app_json)
            profiling["llm_total_seconds"] = round(time.perf_counter() - stage_started, 4)
            llm_timings = llm_result.get("timings") if isinstance(llm_result, dict) else None
            if isinstance(llm_timings, dict):
                profiling["llm_breakdown"] = llm_timings

            llm_status = llm_result.get("status", "not_configured")
            if llm_status not in {"ok", "skipped"}:
                profiling["total_verify_seconds"] = round(time.perf_counter() - request_started, 4)
                return JSONResponse(
                    {
                        "error": "vision_failed",
                        "detail": llm_result.get("reason", "Direct image analysis failed."),
                        "profiling": profiling,
                    },
                    status_code=502,
                )

        parsed = dict(llm_result.get("fields", {})) if isinstance(llm_result.get("fields", {}), dict) else {}
        field_analysis = llm_result.get("field_analysis") if isinstance(llm_result.get("field_analysis"), dict) else {}
        vision_quality_score = 100.0
        parsed["_processing_time_seconds"] = round(time.perf_counter() - started, 3)
        parsed["vision_quality_score"] = vision_quality_score
        parsed["vision_quality_issues"] = ["Direct image analysis was used."] if llm_status == "ok" else ["Application data already covered the required fields; LLM was skipped to reduce latency."]
        parsed["field_analysis"] = field_analysis
        parsed["llm_fallback"] = {
            "status": llm_status,
            "reason": llm_result.get("reason", "Direct image analysis used."),
            "quality_score": 100.0,
            "ambiguous_fields": [],
        }
        parsed["semantic_quality_gate"] = {
            "needs_llm": False,
            "reason": "Direct vision analysis was used instead of local OCR." if llm_status == "ok" else "Application payload covered the verification fields; LLM extraction was skipped for latency.",
            "quality_score": 100.0,
            "ambiguous_fields": [],
        }

        stage_started = time.perf_counter()
        if app_json.get("government_warning_present") and not parsed.get("government_warning_present"):
            parsed["government_warning_present"] = False
            parsed["government_warning_exact"] = False
            parsed["government_warning_confidence"] = 0.0

        if parsed.get("government_warning_text") and not parsed.get("government_warning_exact"):
            warning_text = str(parsed.get("government_warning_text") or "")
            parsed["government_warning_exact"] = warning_text.startswith("GOVERNMENT WARNING:")
            parsed["government_warning_confidence"] = 1.0 if parsed["government_warning_exact"] else 0.5
        profiling["enrichment_seconds"] = round(time.perf_counter() - stage_started, 4)

        stage_started = time.perf_counter()
        brand_app = app_json.get("brand") or app_json.get("brand_name")
        brand_label = parsed.get("brand")
        brand_score = self._field_similarity_score(brand_app, brand_label, "brand")
        brand_status = field_status(brand_score)
        brand_reason = "Brand text matches application data." if brand_status == "match" else (
            "Brand text differs from the application value." if brand_status == "mismatch" else "Brand text is close but not exact."
        )

        producer_app = app_json.get("producer_name") or app_json.get("bottler") or app_json.get("producer")
        producer_label = parsed.get("producer_name")
        producer_score = self._field_similarity_score(producer_app, producer_label, "producer_name")
        producer_status = field_status(producer_score, thresholds=(85.0, 60.0))
        producer_reason = "Producer matches application data." if producer_status == "match" else (
            "Producer differs from the application value." if producer_status == "mismatch" else "Producer is reasonably close but not exact."
        )

        class_app = app_json.get("class") or app_json.get("class_type") or app_json.get("type")
        class_label = parsed.get("class")
        class_score = fuzzy_score(str(class_app or ""), str(class_label or ""))
        class_status = field_status(class_score, thresholds=(85.0, 65.0))
        class_reason = "Class matches application data." if class_status == "match" else (
            "Class differs from the application value." if class_status == "mismatch" else "Class is similar but not exact."
        )

        abv_app_raw = app_json.get("abv") or app_json.get("alcohol_content")
        abv_label_raw = parsed.get("abv")
        abv_app = parse_abv_number(str(abv_app_raw))
        abv_label = parse_abv_number(str(abv_label_raw))
        abv_status = "mismatch"
        abv_diff = None
        if abv_app is not None and abv_label is not None:
            abv_diff = abs(abv_app - abv_label)
            abv_status = "match" if abv_diff == 0 else "mismatch"
        elif abv_app is None and abv_label is None:
            abv_status = "missing"
        abv_reason = "ABV exactly matches." if abv_status == "match" else (
            "ABV differs from the application value." if abv_status == "mismatch" else "ABV is close but not exact."
        )

        net_app_raw = app_json.get("net_contents") or app_json.get("net")
        net_label_raw = parsed.get("net_contents")
        net_app_ml = volume_to_ml(str(net_app_raw))
        net_label_ml = volume_to_ml(str(net_label_raw))
        net_status = "mismatch"
        net_diff_ml = None
        net_match_tolerance = None
        net_suspect_tolerance = None
        if net_app_ml is not None and net_label_ml is not None:
            net_diff_ml = abs(net_app_ml - net_label_ml)
            tol = max(10.0, 0.02 * net_app_ml)
            net_match_tolerance = tol
            net_suspect_tolerance = 2 * tol
            net_status = "match" if net_diff_ml <= net_match_tolerance else "suspect" if net_diff_ml <= net_suspect_tolerance else "mismatch"
        elif net_app_ml is None and net_label_ml is None:
            net_status = "missing"
        net_reason = "Net contents exactly matches." if net_status == "match" else (
            "Net contents differs from the application value." if net_status == "mismatch" else "Net contents is close but not exact."
        )

        gov_conf = parsed.get("government_warning_confidence", 0.0)
        gov_model_confidence = self._model_field_confidence(field_analysis, "government_warning")
        if gov_model_confidence is not None and gov_conf in (None, 0.0):
            gov_conf = gov_model_confidence
        gov_exact = parsed.get("government_warning_exact", False)
        if gov_exact or gov_conf >= 0.95:
            gov_status = "match"
        elif gov_conf >= 0.5:
            gov_status = "suspect"
        else:
            gov_status = "mismatch"
        gov_reason = "Government warning quality assessed from model output and local policy checks."
        profiling["comparison_seconds"] = round(time.perf_counter() - stage_started, 4)

        review_state = "ready"
        if vision_quality_score < 80:
            review_state = "llm_review_pending" if llm_status in {"not_configured", "not_available", "error"} else "llm_review_in_progress"
            if llm_status == "ok":
                review_state = "llm_review_complete"

        comparisons = {
            "brand": {"status": brand_status, "score": brand_score, "app": brand_app, "label": brand_label, "confidence": self._text_decision_confidence(brand_score, brand_status, (90.0, 75.0)), "model_confidence": self._model_field_confidence(field_analysis, "brand"), "model_overall_confidence": self._model_field_overall_confidence(field_analysis, "brand"), "model_attributes": self._model_field_entry(field_analysis, "brand").get("attributes", {}), "reason": brand_reason},
            "producer": {"status": producer_status, "score": producer_score, "app": producer_app, "label": producer_label, "confidence": self._text_decision_confidence(producer_score, producer_status, (85.0, 60.0)), "model_confidence": self._model_field_confidence(field_analysis, "producer_name"), "model_overall_confidence": self._model_field_overall_confidence(field_analysis, "producer_name"), "model_attributes": self._model_field_entry(field_analysis, "producer_name").get("attributes", {}), "reason": producer_reason},
            "class": {"status": class_status, "score": class_score, "app": class_app, "label": class_label, "confidence": self._text_decision_confidence(class_score, class_status, (85.0, 65.0)), "model_confidence": self._model_field_confidence(field_analysis, "class"), "model_overall_confidence": self._model_field_overall_confidence(field_analysis, "class"), "model_attributes": self._model_field_entry(field_analysis, "class").get("attributes", {}), "reason": class_reason},
            "abv": {"status": abv_status, "app": abv_app, "label": abv_label, "diff": abv_diff, "confidence": self._binary_decision_confidence(abv_status, abv_app is not None and abv_label is not None), "model_confidence": self._model_field_confidence(field_analysis, "abv"), "model_overall_confidence": self._model_field_overall_confidence(field_analysis, "abv"), "model_attributes": self._model_field_entry(field_analysis, "abv").get("attributes", {}), "reason": abv_reason},
            "net_contents": {"status": net_status, "app_ml": net_app_ml, "label_ml": net_label_ml, "diff_ml": net_diff_ml, "confidence": self._numeric_decision_confidence(net_diff_ml, net_match_tolerance or 0.0, net_suspect_tolerance or 0.0, net_status), "model_confidence": self._model_field_confidence(field_analysis, "net_contents"), "model_overall_confidence": self._model_field_overall_confidence(field_analysis, "net_contents"), "model_attributes": self._model_field_entry(field_analysis, "net_contents").get("attributes", {}), "reason": net_reason},
            "government_warning": {"status": gov_status, "confidence": round(float(gov_conf), 2), "model_confidence": self._model_field_confidence(field_analysis, "government_warning"), "model_overall_confidence": self._model_field_overall_confidence(field_analysis, "government_warning"), "model_attributes": self._model_field_entry(field_analysis, "government_warning").get("attributes", {}), "exact": gov_exact, "reason": gov_reason},
            "country_of_origin": {"status": None, "app": app_json.get("country_of_origin"), "label": parsed.get("country_of_origin"), "confidence": None, "model_confidence": self._model_field_confidence(field_analysis, "country_of_origin"), "model_overall_confidence": self._model_field_overall_confidence(field_analysis, "country_of_origin"), "model_attributes": self._model_field_entry(field_analysis, "country_of_origin").get("attributes", {}), "reason": "Country of origin was not validated by OCR."},
        }

        field_name_map = {
            "brand": "brand",
            "producer": "producer_name",
            "class": "class",
            "abv": "abv",
            "net_contents": "net_contents",
            "government_warning": "government_warning",
            "country_of_origin": "country_of_origin",
        }

        local_policy_summary: dict[str, dict] = {}
        stage_started = time.perf_counter()
        for comparison_key, source_field in field_name_map.items():
            entry = comparisons.get(comparison_key)
            if not isinstance(entry, dict):
                continue
            value = parsed.get(source_field)
            source_analysis = field_analysis.get(source_field) if isinstance(field_analysis.get(source_field), dict) else {}
            model_attributes = source_analysis.get("attributes") if isinstance(source_analysis.get("attributes"), dict) else {}
            model_overall_confidence = self._format_validator.to_unit_score(source_analysis.get("overall_confidence"))
            passes_local_policy, failure_reasons = self._format_validator.evaluate_local_visual_rules(source_field, value, model_attributes, model_overall_confidence)
            local_policy_summary[comparison_key] = {
                "passes": passes_local_policy,
                "reasons": failure_reasons,
                "value": value,
                "model_overall_confidence": model_overall_confidence,
            }
            if not passes_local_policy:
                entry["status"] = "mismatch"
                entry["reason"] = (entry.get("reason") or "") + (" Local policy: " if entry.get("reason") else "") + "; ".join(failure_reasons)
        profiling["local_policy_seconds"] = round(time.perf_counter() - stage_started, 4)

        parsed["local_policy_validation"] = local_policy_summary

        if not local_policy_summary.get("government_warning", {}).get("passes", True):
            parsed["government_warning_exact"] = False
            parsed["government_warning_confidence"] = min(float(parsed.get("government_warning_confidence", 0.0) or 0.0), 0.49)

        if review_state != "ready":
            for entry in comparisons.values():
                if isinstance(entry, dict) and entry.get("status") not in (None, "match", "missing"):
                    entry["status"] = "review"
                    if not entry.get("reason"):
                        entry["reason"] = "Manual review required due to low vision confidence."

        for entry in comparisons.values():
            if isinstance(entry, dict):
                entry["status"] = self._public_comparison_status(entry.get("status"))

        stage_started = time.perf_counter()
        case_field_statuses = [
            comparisons.get("brand", {}).get("status"),
            comparisons.get("class", {}).get("status"),
            comparisons.get("abv", {}).get("status"),
            comparisons.get("net_contents", {}).get("status"),
            comparisons.get("government_warning", {}).get("status"),
            comparisons.get("producer", {}).get("status"),
        ]
        case_status = self._case_status_from_field_statuses(case_field_statuses)

        match_confidences = []
        for entry in comparisons.values():
            if isinstance(entry, dict) and entry.get("confidence") is not None:
                try:
                    match_confidences.append(float(entry["confidence"]))
                except (TypeError, ValueError):
                    continue

        average_match_confidence = sum(match_confidences) / len(match_confidences) if match_confidences else 0.0
        vision_confidence = float(vision_quality_score or 0.0)
        overall_confidence = round((average_match_confidence * 0.7) + (vision_confidence * 0.3), 2)
        profiling["aggregation_seconds"] = round(time.perf_counter() - stage_started, 4)
        case_result = {
            "status": case_status,
            "confidence": overall_confidence,
            "source": "field_aggregation",
        }

        result = {
            "filename": file.filename,
            "application": app_json,
            "application_source_type": app_source,
            "source_files": {
                "application": application_file.filename if application_file else None,
                "label": file.filename,
            },
            "comparisons": comparisons,
            "case_result": case_result,
            "overall_confidence": overall_confidence,
            "overall": case_status,
            "status": review_state,
            "vision_quality_score": vision_quality_score,
            "llm_status": llm_status,
            "status_message": (
                "LLM review pending while vision quality is low."
                if review_state == "llm_review_pending"
                else "LLM review is in progress."
                if review_state == "llm_review_in_progress"
                else "LLM review complete."
                if review_state == "llm_review_complete"
                else "Ready for review."
            ),
            "profiling": {"totals": profiling},
            "debug": False,
        }

        if bool(include_debug or app_json.get("debug") or (application is not None and str(application).strip().lower() == "debug")):
            result["parsed"] = parsed
            result["local_policy_validation"] = local_policy_summary
            result["field_analysis"] = field_analysis
            result["model_debug"] = {
                "parsed": parsed,
                "local_policy_validation": local_policy_summary,
                "field_analysis": field_analysis,
            }
            result["profiling"] = profiling
            result["debug"] = True

        result["debug"] = bool(result.get("debug"))

        result["application_id"] = app_json.get("application_id") or app_json.get("applicationId") or app_json.get("app_id") or self._extract_application_identifier(app_json, json.dumps(app_json, ensure_ascii=False))
        result["result_id"] = str(result["application_id"] or self._generate_numeric_id())
        result["created_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        result["updated_at"] = result["created_at"]
        result["field_reviews"] = {}
        result["final_decision"] = case_status

        stage_started = time.perf_counter()
        saved_result = self._save_verification_result(result)
        profiling["db_save_seconds"] = round(time.perf_counter() - stage_started, 4)
        profiling["total_verify_seconds"] = round(time.perf_counter() - request_started, 4)
        saved_result["profiling"] = dict(profiling)
        return JSONResponse(self._build_public_result(saved_result))
