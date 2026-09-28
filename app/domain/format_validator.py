import re


class FormatValidator:
    """Applies local format and visual-rule validation for parsed label fields."""

    def to_unit_score(self, value: object) -> float | None:
        try:
            score = float(value)
        except (TypeError, ValueError):
            return None
        if score > 1.0:
            score = score / 100.0
        return max(0.0, min(1.0, score))

    def format_is_valid(self, field_name: str, value: object) -> tuple[bool, str | None]:
        text = str(value or "").strip()
        if not text:
            return False, "Field value is missing."

        if field_name == "abv":
            if not re.search(r"\d+(?:\.\d+)?\s*%", text):
                return False, "ABV format is invalid (expected numeric percent)."
        elif field_name == "net_contents":
            if not re.search(r"\d+(?:\.\d+)?\s*(?:ml|l|oz|fl\.?\s*oz)\b", text, flags=re.IGNORECASE):
                return False, "Net contents format is invalid (expected value + unit)."
        elif field_name in {"brand", "class", "producer_name", "country_of_origin"}:
            if len(text) < 2:
                return False, "Field value is too short to validate confidently."

        return True, None

    def evaluate_local_visual_rules(
        self,
        field_name: str,
        value: object,
        attributes: dict,
        overall_confidence: float | None,
    ) -> tuple[bool, list[str]]:
        failures: list[str] = []
        attrs = attributes if isinstance(attributes, dict) else {}

        legibility = self.to_unit_score(attrs.get("legibility"))
        tiny_text = self.to_unit_score(attrs.get("tiny_text"))
        case_exact = self.to_unit_score(attrs.get("case_exact"))
        bold_hint = self.to_unit_score(attrs.get("bold_hint"))

        if overall_confidence is not None and overall_confidence < 0.55:
            failures.append("Low overall field confidence from visual analysis.")
        if legibility is not None and legibility < 0.55:
            failures.append("Field legibility is too low.")
        if tiny_text is not None and tiny_text >= 0.6:
            failures.append("Field appears to be tiny text.")

        valid_format, format_reason = self.format_is_valid(field_name, value)
        if not valid_format and format_reason:
            failures.append(format_reason)

        if field_name == "government_warning":
            warning_text = str(value or "").strip()
            if not warning_text:
                failures.append("Government warning text is missing.")
            else:
                if warning_text != warning_text.upper():
                    failures.append("Government warning is not all upper case.")
                if not warning_text.startswith("GOVERNMENT WARNING:"):
                    failures.append("Government warning does not start with 'GOVERNMENT WARNING:'.")
            if case_exact is not None and case_exact < 0.99:
                failures.append("Government warning case-exact confidence is below threshold.")
            if bold_hint is not None and bold_hint < 0.6:
                failures.append("Government warning boldness confidence is below threshold.")

        return len(failures) == 0, failures


__all__ = ["FormatValidator"]
