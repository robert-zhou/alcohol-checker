import io
import json
import logging
import re
import warnings

from fastapi import UploadFile


class ApplicationPayloadService:
    def __init__(self, pdf_reader_cls):
        self._pdf_reader_cls = pdf_reader_cls

    @staticmethod
    def _clean_field_value(value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        text = text.strip(";: ")
        return text or None

    @staticmethod
    def _normalize_mapping_name(value: object) -> str:
        if value is None:
            return ""
        return str(value).strip().replace("\\", "/").split("/")[-1].strip().lower()

    def normalize_mapping_name(self, value: object) -> str:
        return self._normalize_mapping_name(value)

    def parse_mapping_file(self, raw_bytes: bytes, filename: str | None = None) -> dict[str, str]:
        _ = filename
        text = raw_bytes.decode("utf-8", errors="replace")
        mapping: dict[str, str] = {}
        if not text.strip():
            return mapping

        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                for key, value in parsed.items():
                    if isinstance(value, dict):
                        if "application_file" in value and "label_file" in value:
                            mapping[self._normalize_mapping_name(value["application_file"])] = self._normalize_mapping_name(value["label_file"])
                        if "application" in value and "label" in value:
                            mapping[self._normalize_mapping_name(value["application"])] = self._normalize_mapping_name(value["label"])
                        if "application_id" in value and "label_file" in value:
                            mapping[self._normalize_mapping_name(value["application_id"])] = self._normalize_mapping_name(value["label_file"])
                    elif isinstance(value, str):
                        if key.lower() in {"application_file", "application", "application_id", "app_id"}:
                            mapping[self._normalize_mapping_name(key)] = self._normalize_mapping_name(value)
                if not mapping:
                    for candidate in [
                        parsed.get("application_to_label"),
                        parsed.get("application_map"),
                        parsed.get("mapping"),
                        parsed.get("mappings"),
                        parsed.get("pairs"),
                        parsed.get("application_file_to_label_file"),
                    ]:
                        if isinstance(candidate, dict):
                            for app_name, label_name in candidate.items():
                                if isinstance(label_name, str):
                                    mapping[self._normalize_mapping_name(app_name)] = self._normalize_mapping_name(label_name)
                        elif isinstance(candidate, list):
                            for item in candidate:
                                if isinstance(item, dict):
                                    app_name = item.get("application_file") or item.get("application") or item.get("application_id")
                                    label_name = item.get("label_file") or item.get("label")
                                    if app_name and label_name:
                                        mapping[self._normalize_mapping_name(app_name)] = self._normalize_mapping_name(label_name)
        except json.JSONDecodeError:
            pass

        if mapping:
            return mapping

        for line in text.splitlines():
            candidate = line.strip()
            if not candidate or candidate.startswith("#"):
                continue
            if "->" in candidate:
                left, right = candidate.split("->", 1)
            elif "=" in candidate:
                left, right = candidate.split("=", 1)
            elif "," in candidate:
                left, right = candidate.split(",", 1)
            elif ":" in candidate:
                left, right = candidate.split(":", 1)
            else:
                continue
            left_name = self._normalize_mapping_name(left)
            right_name = self._normalize_mapping_name(right)
            if left_name and right_name:
                mapping[left_name] = right_name

        return mapping

    def _extract_field_from_lines(self, lines, labels):
        for line in lines:
            normalized = line.strip()
            if not normalized:
                continue
            lower = normalized.lower()
            for label in labels:
                prefix = label.lower()
                if lower.startswith(prefix + ":"):
                    return self._clean_field_value(normalized[len(label) + 1 :])
                if lower.startswith(prefix + "-"):
                    return self._clean_field_value(normalized[len(label) + 1 :])
                if lower.startswith(prefix + " ") and lower != prefix:
                    return self._clean_field_value(normalized[len(label) :].strip())
        return None

    def extract_application_identifier(self, app_json: dict | None, raw_text: str | None = None) -> str | None:
        if isinstance(app_json, dict):
            for key in [
                "application_id",
                "applicationId",
                "app_id",
                "appId",
                "applicationid",
                "application_no",
                "application_number",
                "case_id",
                "caseId",
                "record_id",
                "id",
            ]:
                value = app_json.get(key)
                if value is None:
                    continue
                text = str(value).strip()
                if text:
                    return text

        if raw_text:
            patterns = [
                r"(?i)\bapplication\s*(?:id|number|no\.?|identifier)\s*[:#-]?\s*([A-Za-z0-9\-_]+)",
                r"(?i)\bapp\s*(?:id|number|no\.?|identifier)\s*[:#-]?\s*([A-Za-z0-9\-_]+)",
                r"(?i)\bcase\s*(?:id|number|no\.?|identifier)\s*[:#-]?\s*([A-Za-z0-9\-_]+)",
            ]
            for pattern in patterns:
                match = re.search(pattern, raw_text)
                if match:
                    return match.group(1).strip()
        return None

    def extract_from_text_document(self, raw_text: str) -> dict:
        payload = {}
        text = (raw_text or "").replace("\r\n", "\n").replace("\r", "\n")
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        lower_text = text.lower()

        application_id = self._extract_field_from_lines(lines, ["Application ID", "Application Id", "ApplicationID", "App ID", "AppID", "Case ID", "CaseId", "Application Number", "Application No."])
        if application_id:
            payload["application_id"] = application_id

        brand_value = self._extract_field_from_lines(lines, ["Brand", "Brand Name", "Product Name", "Product"])
        if brand_value:
            payload["brand"] = brand_value

        class_value = self._extract_field_from_lines(lines, ["Class", "Class Type", "Type", "Product Type"])
        if class_value:
            payload["class"] = class_value

        abv_value = self._extract_field_from_lines(lines, ["ABV", "Alcohol By Volume", "Alcohol Content", "Alc./Vol."])
        if abv_value:
            payload["abv"] = abv_value
        else:
            match = re.search(r"(?i)(?:abv|alcohol by volume|alc[./ ]?vol)[^0-9]*([0-9]+(?:\.\d+)?)\s*%?", text)
            if match:
                payload["abv"] = match.group(1) + "%"

        net_value = self._extract_field_from_lines(lines, ["Net Contents", "Net Volume", "Volume"])
        if net_value:
            payload["net_contents"] = net_value
        else:
            match = re.search(r"(?i)(?:net contents?|net volume|volume)\s*[:\-]?\s*([0-9]+(?:\.\d+)?\s*(?:ml|l|oz|fl\.?oz))", text)
            if match:
                payload["net_contents"] = match.group(1)

        producer_value = self._extract_field_from_lines(lines, ["Producer", "Producer Name", "Bottler", "Distiller", "Company"])
        if producer_value:
            payload["producer_name"] = producer_value

        country_value = self._extract_field_from_lines(lines, ["Country of Origin", "Country", "Origin"])
        if country_value:
            payload["country_of_origin"] = country_value

        if "government warning" in lower_text or "surgeon general" in lower_text or "warning" in lower_text:
            payload["government_warning_present"] = True

        if not payload.get("country_of_origin"):
            for line in lines:
                if "USA" in line or "CANADA" in line or "MEXICO" in line or "AUSTRALIA" in line:
                    payload["country_of_origin"] = line.strip()
                    break

        return payload

    def extract_application_from_pdf(self, raw_bytes: bytes) -> dict:
        if self._pdf_reader_cls is None:
            raise RuntimeError(
                "PDF parsing support is unavailable because the pypdf package is not installed in the runtime environment. "
                "Install it with: pip install pypdf==6.19.0"
            )

        pdf_logger = logging.getLogger("pypdf")
        previous_level = pdf_logger.level
        pdf_logger.setLevel(logging.ERROR)
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=UserWarning, message=".*incorrect startxref pointer.*")
                warnings.filterwarnings("ignore", category=UserWarning, message=".*parsing for Object Streams.*")
                reader = self._pdf_reader_cls(io.BytesIO(raw_bytes))
                text_parts = []
                for page in reader.pages:
                    page_text = page.extract_text() or ""
                    if page_text:
                        text_parts.append(page_text)
                raw_text = "\n".join(text_parts)
        except Exception as exc:
            raise ValueError("The uploaded PDF is malformed or unreadable. Please upload a valid PDF with readable text.") from exc
        finally:
            pdf_logger.setLevel(previous_level)

        payload = self.extract_from_text_document(raw_text)
        if not payload:
            raise ValueError("The uploaded PDF does not contain the expected application fields. Please upload a valid PDF with readable text.")
        return payload

    async def read_application_payload(self, application: str | None, application_file: UploadFile | None) -> tuple[str | None, dict | None, str | None]:
        application_parse_error: Exception | None = None

        if application:
            try:
                app_json = json.loads(application)
                if isinstance(app_json, dict):
                    app_json["application_id"] = app_json.get("application_id") or app_json.get("applicationId") or app_json.get("app_id") or self.extract_application_identifier(app_json)
                    return application, app_json, "json"
            except Exception as exc:
                application_parse_error = exc

        if application_file is not None:
            raw = await application_file.read()
            file_name = (application_file.filename or "").lower()

            if file_name.endswith(".json"):
                try:
                    decoded = raw.decode("utf-8")
                    app_json = json.loads(decoded)
                    if isinstance(app_json, dict):
                        app_json["application_id"] = app_json.get("application_id") or app_json.get("applicationId") or app_json.get("app_id") or self.extract_application_identifier(app_json)
                        return decoded, app_json, "json"
                except Exception as exc:
                    raise ValueError(f"invalid application JSON: {exc}") from exc

            if file_name.endswith(".pdf") or "pdf" in (application_file.content_type or ""):
                app_json = self.extract_application_from_pdf(raw)
                app_json["application_id"] = app_json.get("application_id") or app_json.get("applicationId") or app_json.get("app_id") or self.extract_application_identifier(app_json, json.dumps(app_json, ensure_ascii=False))
                return json.dumps(app_json, ensure_ascii=False), app_json, "pdf"

            try:
                decoded = raw.decode("utf-8")
                app_json = self.extract_from_text_document(decoded)
                if app_json:
                    app_json["application_id"] = app_json.get("application_id") or app_json.get("applicationId") or app_json.get("app_id") or self.extract_application_identifier(app_json, decoded)
                    return decoded, app_json, "text"
            except Exception:
                pass

        if application and application_parse_error is not None:
            raise ValueError(f"invalid application JSON: {application_parse_error}") from application_parse_error

        return None, None, None
