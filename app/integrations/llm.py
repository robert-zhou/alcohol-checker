import base64
import json
import os
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app import config as app_config


class LLMClient:
    """Encapsulates access to the LLM vision extraction client."""

    def __init__(self, config=None):
        self.config = config or app_config
        self._client = None
        self._client_cache_key = None

    def _get_client(self):
        api_key = getattr(self.config, "OPENAI_API_KEY", None) or getattr(self.config, "openai_api_key", None) or os.getenv("OPENAI_API_KEY")
        base_url = getattr(self.config, "OPENAI_BASE_URL", None) or getattr(self.config, "openai_base_url", None) or os.getenv("OPENAI_BASE_URL")
        cache_key = (api_key, base_url)
        if self._client is None or self._client_cache_key != cache_key:
            from openai import OpenAI

            normalized_base_url, default_query = self._normalize_openai_base_url(base_url)
            client_kwargs = {
                "api_key": api_key,
                "base_url": normalized_base_url,
            }
            if default_query:
                client_kwargs["default_query"] = default_query
            self._client = OpenAI(**client_kwargs)
            self._client_cache_key = cache_key
        return self._client

    def _has_placeholder_key(self, api_key: str | None) -> bool:
        if not api_key:
            return True
        normalized = str(api_key).strip().lower()
        return normalized in {"demo-openai-api-key", "demo-key", "placeholder", "changeme", "dummy", "dummy-key"} or normalized.startswith("dummy-")

    def is_configured(self) -> bool:
        api_key = getattr(self.config, "OPENAI_API_KEY", None) or getattr(self.config, "openai_api_key", None) or os.getenv("OPENAI_API_KEY")
        base_url = getattr(self.config, "OPENAI_BASE_URL", None) or getattr(self.config, "openai_base_url", None) or os.getenv("OPENAI_BASE_URL")
        return bool(base_url) and not self._has_placeholder_key(api_key)

    def _normalize_openai_base_url(self, base_url: str) -> tuple[str, dict[str, str] | None]:
        parsed = urlsplit((base_url or "").strip())
        if not parsed.scheme or not parsed.netloc:
            return base_url, None

        query_params = dict(parse_qsl(parsed.query, keep_blank_values=True))
        configured_api_version = (
            getattr(self.config, "OPENAI_API_VERSION", None)
            or getattr(self.config, "openai_api_version", None)
            or os.getenv("OPENAI_API_VERSION")
            or os.getenv("AZURE_OPENAI_API_VERSION")
        )

        host = parsed.netloc.lower()
        path = parsed.path.rstrip("/")
        is_azure_host = host.endswith(".services.ai.azure.com") or host.endswith(".openai.azure.com")
        is_azure_project_endpoint = is_azure_host and "/api/projects/" in path
        is_openai_compatible_project_endpoint = is_azure_host and path.endswith("/openai/v1")

        normalized_path = path or "/"
        if is_azure_project_endpoint:
            normalized_path = "/openai/v1"
        elif is_azure_host and normalized_path and not normalized_path.endswith("/openai/v1") and "/api/projects/" not in path:
            normalized_path = normalized_path.rstrip("/")
            if normalized_path in {"", "/"}:
                normalized_path = "/openai/v1"

        default_query = None
        if is_azure_host and not is_azure_project_endpoint and not is_openai_compatible_project_endpoint:
            if configured_api_version and "api-version" not in query_params:
                default_query = {"api-version": configured_api_version}

        normalized_query = urlencode(query_params)
        if default_query:
            normalized_query = urlencode({**query_params, **default_query})

        normalized = urlunsplit((parsed.scheme, parsed.netloc, normalized_path, normalized_query, ""))
        return normalized, default_query

    @staticmethod
    def _vision_response_schema() -> dict:
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "field_analysis": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "brand": {"$ref": "#/$defs/field_result"},
                        "class": {"$ref": "#/$defs/field_result"},
                        "abv": {"$ref": "#/$defs/field_result"},
                        "net_contents": {"$ref": "#/$defs/field_result"},
                        "producer_name": {"$ref": "#/$defs/field_result"},
                        "country_of_origin": {"$ref": "#/$defs/field_result"},
                        "government_warning": {"$ref": "#/$defs/warning_result"},
                    },
                    "required": ["brand", "class", "abv", "net_contents", "producer_name", "country_of_origin", "government_warning"],
                },
                "government_warning_summary": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "exact": {"type": "boolean"},
                        "reason": {"type": "string"},
                    },
                    "required": ["exact", "reason"],
                },
            },
            "required": ["field_analysis", "government_warning_summary"],
            "$defs": {
                "field_result": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "value": {"type": ["string", "null"]},
                        "confidence": {"type": "number"},
                        "attributes": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "case_exact": {"type": "number"},
                                "bold_hint": {"type": "number"},
                                "legibility": {"type": "number"},
                                "tiny_text": {"type": "number"},
                            },
                            "required": ["case_exact", "bold_hint", "legibility", "tiny_text"],
                        },
                        "notes": {"type": "string"},
                    },
                    "required": ["value", "confidence", "attributes", "notes"],
                },
                "warning_result": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "value": {"type": ["string", "null"]},
                        "confidence": {"type": "number"},
                        "attributes": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "case_exact": {"type": "number"},
                                "bold_hint": {"type": "number"},
                                "legibility": {"type": "number"},
                                "tiny_text": {"type": "number"},
                            },
                            "required": ["case_exact", "bold_hint", "legibility", "tiny_text"],
                        },
                        "notes": {"type": "string"},
                    },
                    "required": ["value", "confidence", "attributes", "notes"],
                },
            },
        }

    @staticmethod
    def _text_response_schema() -> dict:
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "brand": {"type": ["string", "null"]},
                "class": {"type": ["string", "null"]},
                "abv": {"type": ["string", "null"]},
                "net_contents": {"type": ["string", "null"]},
                "producer_name": {"type": ["string", "null"]},
                "country_of_origin": {"type": ["string", "null"]},
                "government_warning_present": {"type": ["boolean", "null"]},
            },
            "required": ["brand", "class", "abv", "net_contents", "producer_name", "country_of_origin", "government_warning_present"],
        }

    @staticmethod
    def _chat_response_format(schema: dict) -> dict:
        name = "alcohol_label_json"
        return {"type": "json_schema", "json_schema": {"name": name, "schema": schema, "strict": True}}

    @staticmethod
    def _responses_json_schema(schema: dict) -> dict:
        return {"type": "json_schema", "name": "alcohol_label_json", "schema": schema, "strict": True}

    def _uses_responses_api(self, base_url: str | None) -> bool:
        if not base_url:
            return False
        parsed = urlsplit((base_url or "").strip())
        host = (parsed.netloc or "").lower()
        path = (parsed.path or "").lower()
        return host.endswith(".services.ai.azure.com") and (path.endswith("/openai/v1") or "/api/projects/" in path)

    @staticmethod
    def _extract_response_text(response) -> str:
        if hasattr(response, "output_text") and response.output_text:
            return str(response.output_text)

        def _collect_text_values(node):
            chunks: list[str] = []
            if isinstance(node, str):
                chunks.append(node)
                return chunks
            if isinstance(node, dict):
                value = node.get("text")
                if isinstance(value, str):
                    chunks.append(value)
                elif isinstance(value, list):
                    for child in value:
                        chunks.extend(_collect_text_values(child))
                content = node.get("content")
                if isinstance(content, list):
                    for child in content:
                        chunks.extend(_collect_text_values(child))
                elif isinstance(content, str):
                    chunks.append(content)
                if not chunks:
                    for nested_key in ("output_text", "value", "message"):
                        nested_value = node.get(nested_key)
                        if nested_value is not None:
                            chunks.extend(_collect_text_values(nested_value))
                return chunks
            if isinstance(node, list):
                for item in node:
                    chunks.extend(_collect_text_values(item))
            return chunks

        output = getattr(response, "output", None)
        if isinstance(output, list):
            chunks: list[str] = []
            for item in output:
                chunks.extend(_collect_text_values(item))
            if chunks:
                return "".join(chunks)

        choices = getattr(response, "choices", None)
        if isinstance(choices, list) and choices:
            message = getattr(choices[0], "message", None)
            if message is not None:
                content = getattr(message, "content", None)
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    return "".join(str(part.get("text", "")) for part in content if isinstance(part, dict))

        if hasattr(response, "model_dump"):
            model_dump = response.model_dump()
            text = LLMClient._extract_response_text(model_dump)
            if text:
                return text

        if isinstance(response, dict):
            text = "".join(_collect_text_values(response))
            if text:
                return text

        return ""

    def build_prompt(self, raw_text: str, app_json: dict | None = None) -> str:
        prompt = (
            "Extract the following alcohol label fields from the OCR text. "
            "Return ONLY one valid JSON object, with no markdown, no code fences, and no extra commentary. "
            "Use exactly this schema and these keys: "
            '{"brand": string|null, "class": string|null, "abv": string|null, "net_contents": string|null, '
            '"producer_name": string|null, "country_of_origin": string|null, "government_warning_present": boolean|null}. '
            "If a field is unclear, set it to null.\n\nOCR TEXT:\n" + raw_text
        )
        if app_json:
            prompt += "\n\nAPPLICATION CONTEXT:\n" + json.dumps(app_json, ensure_ascii=False)
        return prompt

    def build_image_prompt(self, app_json: dict | None = None) -> str:
        prompt = (
            "Inspect the uploaded alcohol label image directly. "
            "Return ONLY one valid JSON object, with no markdown, no code fences, and no extra commentary. "
            "No extra top-level keys or nested keys beyond the required schema are allowed. "
            "Use this exact top-level schema: {\"field_analysis\":{\"brand\":{\"value\":string|null,\"confidence\":number,\"attributes\":{...},\"notes\":string},\"class\":{\"value\":string|null,\"confidence\":number,\"attributes\":{...},\"notes\":string},\"abv\":{\"value\":string|null,\"confidence\":number,\"attributes\":{...},\"notes\":string},\"net_contents\":{\"value\":string|null,\"confidence\":number,\"attributes\":{...},\"notes\":string},\"producer_name\":{\"value\":string|null,\"confidence\":number,\"attributes\":{...},\"notes\":string},\"country_of_origin\":{\"value\":string|null,\"confidence\":number,\"attributes\":{...},\"notes\":string},\"government_warning\":{\"value\":string|null,\"confidence\":number,\"attributes\":{\"case_exact\":number,\"bold_hint\":number,\"legibility\":number,\"tiny_text\":number},\"notes\":string}},\"government_warning_summary\":{\"exact\":boolean,\"reason\":string}}. "
            "Each field must contain only: value, confidence, attributes, and notes. "
            "attributes should only include the smallest set of values needed for the field. "
            "Government warning must be treated as an exact compliance field. "
            "For government_warning, value should capture the exact warning text if visible, confidence should reflect whether the warning is fully readable, and attributes should include case_exact and bold_hint. "
            "If the image is skewed, blurry, shadowed, has glare, or the text is tiny, mentally rectify it before reading. "
            "The required statement must begin with GOVERNMENT WARNING: in all caps and bold. "
            "If the wording differs, the casing differs, the text is not bold, the font is too small, or the warning is buried in the label, mark government_warning_summary.exact as false and explain why in the reason field. "
            "Do not invent values. If a field cannot be read confidently, set value to null and reduce confidence. "
            "Use a compact JSON object only; no additional metadata, no debug arrays, no summaries beyond government_warning_summary."
        )
        if app_json:
            prompt += "\n\nAPPLICATION CONTEXT:\n" + json.dumps(app_json, ensure_ascii=False)
        return prompt

    def _parse_completion_json(self, content: str) -> dict:
        if isinstance(content, (dict, list)):
            return content

        text = (content or "").strip()
        if not text:
            raise json.JSONDecodeError("No valid JSON object found in model output", text, 0)

        if text.startswith("```"):
            lines = []
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith("```"):
                    continue
                lines.append(line)
            text = "\n".join(lines).strip()

        for candidate in [text, text.replace("```json", "").replace("```", "").strip()]:
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass

        candidates = self._iter_json_candidates(text)
        best_candidate = None
        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if best_candidate is None or len(candidate) > len(best_candidate[0]):
                best_candidate = (candidate, parsed)
        if best_candidate is not None:
            return best_candidate[1]

        raise json.JSONDecodeError("No valid JSON object found in model output", text, 0)

    def _iter_json_candidates(self, text: str):
        search_text = text.strip()
        if not search_text:
            return []

        candidates = []
        for start in range(len(search_text)):
            if search_text[start] != "{":
                continue
            depth = 0
            in_string = False
            escaped = False
            for index in range(start, len(search_text)):
                char = search_text[index]
                if in_string:
                    if escaped:
                        escaped = False
                    elif char == "\\":
                        escaped = True
                    elif char == '"':
                        in_string = False
                    continue

                if char == '"':
                    in_string = True
                elif char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        candidate = search_text[start : index + 1]
                        if candidate not in candidates:
                            candidates.append(candidate)
                        break
        return candidates

    def _extract_first_json_object(self, text: str) -> str:
        """Extract the first balanced JSON object from model output text."""
        candidates = self._iter_json_candidates(text)
        if not candidates:
            raise json.JSONDecodeError("No JSON object found", text, 0)
        return candidates[0]

    def _normalize_field_analysis(self, data: dict) -> dict:
        if not isinstance(data, dict):
            data = {}

        field_analysis = data.get("field_analysis")
        if not isinstance(field_analysis, dict):
            field_analysis = {}

        fallback_fields = data.get("fields") if isinstance(data.get("fields"), dict) else {}
        if field_analysis and not any(field_analysis.get(name) for name in ["brand", "class", "abv", "net_contents", "producer_name", "country_of_origin", "government_warning"]):
            field_analysis = {}

        for field_name in ["brand", "class", "abv", "net_contents", "producer_name", "country_of_origin", "government_warning"]:
            if field_name not in field_analysis and isinstance(fallback_fields.get(field_name), dict):
                field_analysis[field_name] = fallback_fields[field_name]

        def _to_score(value: object) -> float | None:
            try:
                score = float(value)
            except (TypeError, ValueError):
                return None
            if score > 1.0:
                score = score / 100.0
            return max(0.0, min(1.0, score))

        def _combine_confidences(value_confidence: object, attributes: dict) -> float | None:
            value_score = _to_score(value_confidence)
            attribute_scores = []
            if isinstance(attributes, dict):
                for attribute_value in attributes.values():
                    score = _to_score(attribute_value)
                    if score is not None:
                        attribute_scores.append(score)
            if value_score is None and not attribute_scores:
                return None
            if value_score is None:
                return round(sum(attribute_scores) / len(attribute_scores), 3)
            if not attribute_scores:
                return round(value_score, 3)
            attribute_average = sum(attribute_scores) / len(attribute_scores)
            return round((value_score * 0.7) + (attribute_average * 0.3), 3)

        normalized_fields: dict[str, dict] = {}
        flat_fields: dict[str, object] = {}

        for field_name in ["brand", "class", "abv", "net_contents", "producer_name", "country_of_origin", "government_warning"]:
            field_entry = field_analysis.get(field_name, {}) if isinstance(field_analysis, dict) else {}
            if not isinstance(field_entry, dict):
                field_entry = {"value": field_entry}

            value = field_entry.get("value")
            confidence = field_entry.get("confidence")
            attributes = field_entry.get("attributes") if isinstance(field_entry.get("attributes"), dict) else {}
            notes = field_entry.get("notes")
            overall_confidence = _combine_confidences(confidence, attributes)

            normalized_fields[field_name] = {
                "value": value,
                "confidence": confidence,
                "overall_confidence": overall_confidence,
                "attributes": attributes,
                "notes": notes,
            }
            flat_fields[field_name] = value

        warning_field = normalized_fields.get("government_warning", {})
        warning_value = warning_field.get("value")
        warning_text = warning_value if isinstance(warning_value, str) else None
        summary = data.get("government_warning_summary") if isinstance(data.get("government_warning_summary"), dict) else {}

        if not any((value is not None and value != "") for value in flat_fields.values()):
            for field_name in ["brand", "class", "abv", "net_contents", "producer_name", "country_of_origin", "government_warning"]:
                extracted_value = fallback_fields.get(field_name)
                if extracted_value is not None and extracted_value != "":
                    flat_fields[field_name] = extracted_value
                    field_analysis.setdefault(field_name, {"value": extracted_value})

        return {
            "field_analysis": normalized_fields,
            "fields": flat_fields,
            "government_warning_text": warning_text,
            "government_warning_exact": bool(warning_text and warning_text.startswith("GOVERNMENT WARNING:")),
            "government_warning_confidence": warning_field.get("confidence"),
            "government_warning_summary": summary,
        }

    def _build_data_url(self, image_bytes: bytes, mime_type: str | None = None) -> str:
        image_mime_type = (mime_type or "image/jpeg").split(";")[0].strip() or "image/jpeg"
        encoded = base64.b64encode(image_bytes).decode("ascii")
        return f"data:{image_mime_type};base64,{encoded}"

    @staticmethod
    def _event_value(event: object, key: str):
        if hasattr(event, key):
            return getattr(event, key)
        if isinstance(event, dict):
            return event.get(key)
        return None

    def _collect_stream_output_text(self, stream) -> tuple[str, float | None]:
        chunks: list[str] = []
        first_token_seconds: float | None = None
        stream_started = time.perf_counter()

        for event in stream:
            event_type = self._event_value(event, "type")
            if event_type == "response.output_text.delta":
                delta = self._event_value(event, "delta")
                if delta:
                    if first_token_seconds is None:
                        first_token_seconds = round(time.perf_counter() - stream_started, 4)
                    chunks.append(str(delta))
                continue

            if event_type == "response.output_text.done" and not chunks:
                done_text = self._event_value(event, "text")
                if done_text:
                    chunks.append(str(done_text))
                continue

            if event_type == "response.completed" and not chunks:
                response = self._event_value(event, "response")
                final_text = getattr(response, "output_text", None) if response is not None else None
                if final_text:
                    chunks.append(str(final_text))

        if hasattr(stream, "get_final_response"):
            final_response = stream.get_final_response()
            final_text = getattr(final_response, "output_text", None)
            if final_text:
                return str(final_text), first_token_seconds

        return "".join(chunks), first_token_seconds

    @staticmethod
    def _collect_chat_stream_text(stream) -> tuple[str, float | None]:
        chunks: list[str] = []
        first_token_seconds: float | None = None
        stream_started = time.perf_counter()

        for chunk in stream:
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            delta = getattr(choices[0], "delta", None)
            if delta is None:
                continue
            content = getattr(delta, "content", None)
            if not content:
                continue
            if first_token_seconds is None:
                first_token_seconds = round(time.perf_counter() - stream_started, 4)
            if isinstance(content, list):
                for item in content:
                    value = getattr(item, "text", None)
                    if value:
                        chunks.append(str(value))
            else:
                chunks.append(str(content))

        return "".join(chunks), first_token_seconds

    def extract_fields(self, raw_text: str, app_json: dict | None = None) -> dict:
        started = time.perf_counter()
        timings: dict[str, float] = {}
        api_key = getattr(self.config, "OPENAI_API_KEY", None) or getattr(self.config, "openai_api_key", None) or os.getenv("OPENAI_API_KEY")
        base_url = getattr(self.config, "OPENAI_BASE_URL", None) or getattr(self.config, "openai_base_url", None) or os.getenv("OPENAI_BASE_URL")
        model = getattr(self.config, "LLM_MODEL", None) or getattr(self.config, "llm_model", None) or os.getenv("LLM_MODEL", "gpt-4.1-mini")
        stream_enabled = bool(getattr(self.config, "LLM_STREAM", True))
        max_output_tokens = max(64, int(getattr(self.config, "LLM_MAX_OUTPUT_TOKENS", 350) or 350))

        if self._has_placeholder_key(api_key):
            return {
                "status": "not_configured",
                "fields": {},
                "reason": "An OpenAI-compatible API key is not configured for a real LLM call.",
                "timings": {"total_seconds": round(time.perf_counter() - started, 4)},
            }

        if not base_url:
            return {
                "status": "not_configured",
                "fields": {},
                "reason": "An OpenAI-compatible base URL is not configured for a real LLM call.",
                "timings": {"total_seconds": round(time.perf_counter() - started, 4)},
            }

        try:
            from openai import OpenAI  # noqa: F401
        except Exception:
            return {
                "status": "not_available",
                "fields": {},
                "reason": "Python OpenAI client is not installed.",
                "timings": {"total_seconds": round(time.perf_counter() - started, 4)},
            }

        try:
            stage_started = time.perf_counter()
            client = self._get_client()
            timings["client_build_seconds"] = round(time.perf_counter() - stage_started, 4)

            stage_started = time.perf_counter()
            content = ""
            used_streaming = False

            if self._uses_responses_api(base_url) and hasattr(client, "responses"):
                request_kwargs = {
                    "model": model,
                    "input": [{
                        "role": "user",
                        "content": [{"type": "input_text", "text": self.build_prompt(raw_text, app_json)}],
                    }],
                    "max_output_tokens": max_output_tokens,
                }
                response = client.responses.create(**request_kwargs)
                content = self._extract_response_text(response)
            else:
                request_kwargs = {
                    "model": model,
                    "messages": [{"role": "user", "content": self.build_prompt(raw_text, app_json)}],
                    "max_tokens": max_output_tokens,
                    "response_format": self._chat_response_format(self._text_response_schema()),
                }

                if stream_enabled:
                    try:
                        stream = client.chat.completions.create(**request_kwargs, stream=True)
                        content, first_token_seconds = self._collect_chat_stream_text(stream)
                        timings["first_token_seconds"] = first_token_seconds
                        used_streaming = True
                        if not content or not content.strip():
                            raise ValueError("empty streaming response")
                        self._parse_completion_json(content)
                    except Exception:
                        completion = client.chat.completions.create(**request_kwargs)
                        content = getattr(completion.choices[0].message, "content", None) or ""
                        used_streaming = False
                else:
                    completion = client.chat.completions.create(**request_kwargs)
                    content = getattr(completion.choices[0].message, "content", None) or ""

            timings["api_call_seconds"] = round(time.perf_counter() - stage_started, 4)
            timings["used_streaming"] = 1.0 if used_streaming else 0.0
            timings["max_output_tokens"] = float(max_output_tokens)

            stage_started = time.perf_counter()
            data = self._parse_completion_json(content)
            timings["parse_seconds"] = round(time.perf_counter() - stage_started, 4)
            timings["total_seconds"] = round(time.perf_counter() - started, 4)
            return {"status": "ok", "fields": data, "reason": "LLM fallback used", "timings": timings}
        except Exception as exc:
            timings["total_seconds"] = round(time.perf_counter() - started, 4)
            return {"status": "error", "fields": {}, "reason": str(exc), "timings": timings}

    def extract_fields_from_image(self, image_bytes: bytes, mime_type: str | None = None, app_json: dict | None = None) -> dict:
        started = time.perf_counter()
        timings: dict[str, float] = {}
        api_key = getattr(self.config, "OPENAI_API_KEY", None) or getattr(self.config, "openai_api_key", None) or os.getenv("OPENAI_API_KEY")
        base_url = getattr(self.config, "OPENAI_BASE_URL", None) or getattr(self.config, "openai_base_url", None) or os.getenv("OPENAI_BASE_URL")
        model = getattr(self.config, "LLM_MODEL", None) or getattr(self.config, "llm_model", None) or os.getenv("LLM_MODEL", "gpt-4.1-mini")
        stream_enabled = bool(getattr(self.config, "LLM_STREAM", True))
        max_output_tokens = max(64, int(getattr(self.config, "LLM_MAX_OUTPUT_TOKENS_VISION", 500) or 500))

        if self._has_placeholder_key(api_key):
            return {
                "status": "not_configured",
                "fields": {},
                "reason": "An OpenAI-compatible API key is not configured for a real vision call.",
                "timings": {"total_seconds": round(time.perf_counter() - started, 4)},
            }

        if not base_url:
            return {
                "status": "not_configured",
                "fields": {},
                "reason": "An OpenAI-compatible base URL is not configured for a real vision call.",
                "timings": {"total_seconds": round(time.perf_counter() - started, 4)},
            }

        try:
            from openai import OpenAI  # noqa: F401
        except Exception:
            return {
                "status": "not_available",
                "fields": {},
                "reason": "Python OpenAI client is not installed.",
                "timings": {"total_seconds": round(time.perf_counter() - started, 4)},
            }

        try:
            stage_started = time.perf_counter()
            client = self._get_client()
            timings["client_build_seconds"] = round(time.perf_counter() - stage_started, 4)

            stage_started = time.perf_counter()
            content = ""
            used_streaming = False

            if self._uses_responses_api(base_url) and hasattr(client, "responses"):
                data_url = self._build_data_url(image_bytes, mime_type)
                request_kwargs = {
                    "model": model,
                    "input": [{
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": self.build_image_prompt(app_json)},
                            {"type": "input_image", "image_url": data_url},
                        ],
                    }],
                    "max_output_tokens": max_output_tokens,
                }
                response = client.responses.create(**request_kwargs)
                content = self._extract_response_text(response)
            else:
                request_kwargs = {
                    "model": model,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": self.build_image_prompt(app_json)},
                                {"type": "image_url", "image_url": {"url": self._build_data_url(image_bytes, mime_type)}},
                            ],
                        }
                    ],
                    "max_tokens": max_output_tokens,
                    "response_format": self._chat_response_format(self._vision_response_schema()),
                }

                if stream_enabled:
                    try:
                        stream = client.chat.completions.create(**request_kwargs, stream=True)
                        content, first_token_seconds = self._collect_chat_stream_text(stream)
                        timings["first_token_seconds"] = first_token_seconds
                        used_streaming = True
                        if not content or not content.strip():
                            raise ValueError("empty streaming response")
                        try:
                            self._parse_completion_json(content)
                        except Exception:
                            raise
                    except Exception:
                        completion = client.chat.completions.create(**request_kwargs)
                        content = getattr(completion.choices[0].message, "content", None) or ""
                        used_streaming = False
                else:
                    completion = client.chat.completions.create(**request_kwargs)
                    content = getattr(completion.choices[0].message, "content", None) or ""

            timings["api_call_seconds"] = round(time.perf_counter() - stage_started, 4)
            timings["used_streaming"] = 1.0 if used_streaming else 0.0
            timings["max_output_tokens"] = float(max_output_tokens)

            stage_started = time.perf_counter()
            data = self._parse_completion_json(content)
            timings["parse_seconds"] = round(time.perf_counter() - stage_started, 4)

            stage_started = time.perf_counter()
            normalized = self._normalize_field_analysis(data)
            timings["normalize_seconds"] = round(time.perf_counter() - stage_started, 4)
            timings["total_seconds"] = round(time.perf_counter() - started, 4)
            normalized.update({"status": "ok", "reason": "Direct image analysis used", "timings": timings})
            return normalized
        except Exception as exc:
            timings["total_seconds"] = round(time.perf_counter() - started, 4)
            return {"status": "error", "fields": {}, "reason": str(exc), "timings": timings}


llm_client = LLMClient()


def _llm_fallback_extract(raw_text: str, app_json: dict | None = None) -> dict:
    return llm_client.extract_fields(raw_text, app_json)


__all__ = ["LLMClient", "llm_client", "_llm_fallback_extract"]
