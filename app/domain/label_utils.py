import re
from difflib import SequenceMatcher


def _looks_like_warning_text(candidate: str) -> bool:
    text = (candidate or "").strip().lower()
    if not text:
        return True
    warning_markers = (
        "government warning",
        "surgeon general",
        "women should not drink",
        "ability to drive a car",
        "operate machinery",
        "not drink alcoholic beverages",
        "pregnancy",
        "impairs your ability",
        "may cause health problems",
        "according to the surgeon general",
    )
    return any(marker in text for marker in warning_markers)


def _is_metadata_line(candidate: str) -> bool:
    if not candidate:
        return True
    value = candidate.strip()
    lowered = value.lower()
    metadata_prefixes = (
        "application id",
        "app id",
        "case id",
        "application number",
        "application no",
        "lot number",
        "batch number",
        "country of origin",
        "product of",
        "made in",
        "imported by",
        "warning",
        "abv",
        "net contents",
        "volume",
        "class",
        "type",
    )
    if any(prefix in lowered for prefix in metadata_prefixes):
        return True
    if re.match(r"^(?:application|app|case)[\s:-]*id\b", lowered):
        return True
    if re.match(r"^(?:lot|batch)[\s:-]*number\b", lowered):
        return True
    if re.match(r"^(?:country of origin|product of|made in|imported by|distilled by|produced by|bottled by|packed by|distributed by)\b", lowered):
        return True
    if _looks_like_warning_text(value):
        return True
    if ":" in value:
        left = value.split(":", 1)[0].strip().lower()
        if any(prefix in left for prefix in metadata_prefixes):
            return True
        if re.match(r"^(?:application|app|case)[\s:-]*id\b", left):
            return True
    return False


def extract_producer_and_country(lines: list[str], joined: str) -> tuple[str | None, str | None, str | None]:
    _ = joined
    producer_keywords = [
        "bottled by", "bottled and distributed by", "distilled by", "produced by", "producer",
        "imported by", "packed by", "distributed by", "mfr by", "made by",
    ]
    country = None
    producer = None
    address = None

    for ln in lines[::-1]:
        low = ln.lower()
        if _is_metadata_line(ln):
            continue
        if low.startswith("product of") or low.startswith("made in") or "imported" in low:
            match = re.search(r"product of\s+(.+)$", ln, re.IGNORECASE)
            if not match:
                match = re.search(r"made in\s+(.+)$", ln, re.IGNORECASE)
            if not match:
                match = re.search(r"imported (?:from|by)?\s*(.+)$", ln, re.IGNORECASE)
            if match:
                country = match.group(1).strip()
                break

    for idx, ln in enumerate(lines):
        low = ln.lower()
        if not any(keyword in low for keyword in producer_keywords):
            continue

        candidate_lines = []
        for offset in (1, -1):
            candidate_idx = idx + offset
            if 0 <= candidate_idx < len(lines):
                candidate = lines[candidate_idx].strip()
                if not candidate:
                    continue
                candidate_low = candidate.lower()
                if _is_metadata_line(candidate):
                    continue
                if candidate_low in {"government warning", "warning", "usa", "canada", "mexico", "united states"}:
                    continue
                if candidate_low.startswith("government warning"):
                    continue
                if re.fullmatch(r"(?:distilled|bottled|produced|imported|packed|distributed|made) by", candidate_low):
                    continue
                candidate_lines.append(candidate)

        for candidate in candidate_lines:
            if candidate.lower() == low:
                continue
            if len(candidate) <= 2:
                continue
            producer = candidate
            break

        if producer is None:
            producer = ln

        possible_addr = lines[idx + 1].strip() if idx + 1 < len(lines) else None
        if possible_addr and re.search(r"\d+\s+\w+", possible_addr):
            address = possible_addr
        break

    if not address:
        for ln in lines[::-1]:
            if re.search(r"\d+\s+\w+\s+(street|st\.|road|rd\.|avenue|ave\.|lane|ln\.|boulevard|blvd|court|ct\.|drive|dr\.)", ln, re.IGNORECASE):
                address = ln
                break

    if not country:
        for ln in lines:
            low = ln.strip().lower()
            match = re.search(r"\b(usa|united states|canada|mexico|ireland|scotland|england|france|spain|italy|colombia|argentina|japan|china|australia)\b", low, re.IGNORECASE)
            if match:
                country = ln.strip()
                break

    return producer, address, country


def normalize_text_for_compare(value: str) -> str:
    if not value:
        return ""
    text = value.strip()
    text = re.sub(r"[\W_]+", " ", text, flags=re.UNICODE)
    return text.lower()


def fuzzy_score(left: str, right: str) -> float:
    left_normalized = normalize_text_for_compare(left)
    right_normalized = normalize_text_for_compare(right)
    if not left_normalized or not right_normalized:
        return 0.0
    return SequenceMatcher(None, left_normalized, right_normalized).ratio() * 100.0


def parse_abv_number(value: str) -> float | None:
    if not value:
        return None
    match = re.search(r"(\d{1,2}(?:\.\d+)?)\s*%", value)
    if not match:
        match = re.search(r"(\d{1,2}(?:\.\d+)?)", value)
    if not match:
        return None
    try:
        return float(match.group(1))
    except Exception:
        return None


def volume_to_ml(value: str) -> float | None:
    if not value:
        return None
    text = value.strip().lower()
    match = re.search(r"([\d\.,]+)\s*(ml|m l)\b", text)
    if match:
        return float(match.group(1).replace(',', ''))
    match = re.search(r"([\d\.,]+)\s*(l|litre|liter)s?\b", text)
    if match:
        return float(match.group(1).replace(',', '')) * 1000.0
    match = re.search(r"([\d\.,]+)\s*(fl\s?oz|floz|ounce|ounces)\b", text)
    if match:
        return float(match.group(1).replace(',', '')) * 29.5735
    return None


def field_status(score: float, thresholds=(90.0, 75.0)) -> str:
    if score >= thresholds[0]:
        return "match"
    if score >= thresholds[1]:
        return "suspect"
    return "mismatch"


def _extract_producer_and_country(lines: list[str], joined: str) -> tuple[str | None, str | None, str | None]:
    return extract_producer_and_country(lines, joined)


def _fuzzy_score(left: str, right: str) -> float:
    return fuzzy_score(left, right)


def _parse_abv_number(value: str) -> float | None:
    return parse_abv_number(value)


def _volume_to_ml(value: str) -> float | None:
    return volume_to_ml(value)


def _field_status(score: float, thresholds=(90.0, 75.0)) -> str:
    return field_status(score, thresholds)


__all__ = [
    "extract_producer_and_country",
    "normalize_text_for_compare",
    "fuzzy_score",
    "parse_abv_number",
    "volume_to_ml",
    "field_status",
    "_extract_producer_and_country",
    "_fuzzy_score",
    "_parse_abv_number",
    "_volume_to_ml",
    "_field_status",
]
