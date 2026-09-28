import json
import random
import threading
from datetime import datetime, timezone
from typing import Any

import mysql.connector
from mysql.connector import Error

from app import config as app_config


_DB_INIT_LOCK = threading.Lock()
_DB_INITIALIZED = False


def _generate_numeric_id(length: int = 7) -> str:
    if length <= 0:
        return "0"
    min_value = 10 ** (length - 1)
    max_value = (10 ** length) - 1
    return str(random.SystemRandom().randint(min_value, max_value))


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _to_mysql_datetime(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1]
    if "T" in text:
        text = text.replace("T", " ", 1)
    return text


def _connect():
    try:
        conn = mysql.connector.connect(
            host=app_config.DB_HOST,
            port=app_config.DB_PORT,
            user=app_config.DB_USER,
            password=app_config.DB_PASSWORD,
            database=app_config.DB_NAME,
            autocommit=True,
            charset="utf8mb4",
            use_pure=True,
        )
        return conn
    except Error as exc:
        raise RuntimeError(f"Unable to connect to MySQL database at {app_config.DB_HOST}:{app_config.DB_PORT}: {exc}") from exc


def init_db() -> None:
    global _DB_INITIALIZED
    if _DB_INITIALIZED:
        return
    with _DB_INIT_LOCK:
        if _DB_INITIALIZED:
            return
        conn = _connect()
        try:
            cursor = conn.cursor()
            cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS verification_results (
                result_id VARCHAR(64) PRIMARY KEY,
                application_id VARCHAR(128),
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                filename VARCHAR(255),
                application_source_type VARCHAR(40),
                source_files JSON,
                application_data JSON,
                label_data JSON,
                result_json LONGTEXT NOT NULL
            )
            """
            )

            cursor.execute(
            """
            SELECT COUNT(*)
            FROM information_schema.columns
            WHERE table_schema = DATABASE()
              AND table_name = 'verification_results'
              AND column_name = 'application_id'
            """
            )
            if cursor.fetchone()[0] == 0:
                cursor.execute("ALTER TABLE verification_results ADD COLUMN application_id VARCHAR(128)")

            cursor.execute(
            """
            SELECT COUNT(*)
            FROM information_schema.columns
            WHERE table_schema = DATABASE()
              AND table_name = 'verification_results'
              AND column_name = 'label_data'
            """
            )
            if cursor.fetchone()[0] == 0:
                cursor.execute("ALTER TABLE verification_results ADD COLUMN label_data JSON")

            cursor.execute(
            """
            SELECT COUNT(*)
            FROM information_schema.statistics
            WHERE table_schema = DATABASE()
              AND table_name = 'verification_results'
              AND index_name = 'uq_verification_results_application_id'
            """
            )
            if cursor.fetchone()[0] == 0:
                cursor.execute(
                    "CREATE UNIQUE INDEX uq_verification_results_application_id ON verification_results (application_id)"
                )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS field_reviews (
                    result_id VARCHAR(64) NOT NULL,
                    field_name VARCHAR(128) NOT NULL,
                    agent_decision VARCHAR(32) NOT NULL,
                    user_decision VARCHAR(32),
                    comment TEXT,
                    override_value TEXT,
                    confidence DOUBLE,
                    PRIMARY KEY (result_id, field_name),
                    FOREIGN KEY (result_id) REFERENCES verification_results(result_id) ON DELETE CASCADE
                )
                """
            )
            conn.commit()
            _DB_INITIALIZED = True
        finally:
            conn.close()


def _normalize_agent_decision(status: Any) -> str:
    if status is None:
        return "need_review"
    normalized = str(status).lower().replace(" ", "_")
    if normalized in {"match", "pass", "approved", "approve"}:
        return "approve"
    if normalized in {"mismatch", "suspect", "missing", "disapproved", "disapprove", "fail", "failure", "not_match", "not_match", "not-match"}:
        return "disapprove"
    return "need_review"


def _compute_final_decision(field_reviews: dict[str, dict[str, Any]]) -> str:
    if not field_reviews:
        return "need_review"
    decisions = []
    for review in field_reviews.values():
        decision = review.get("user_decision") or review.get("agent_decision") or "need_review"
        decisions.append(str(decision).lower())
    if any(decision == "disapprove" for decision in decisions):
        return "failure"
    if any(decision == "need_review" for decision in decisions):
        return "need_review"
    if all(decision == "approve" for decision in decisions):
        return "pass"
    return "need_review"


def _public_status_from_review_decision(decision: Any) -> str:
    normalized = str(decision or "need_review").strip().lower().replace(" ", "_")
    if normalized in {"approve", "approved", "pass", "match"}:
        return "pass"
    if normalized in {"disapprove", "disapproved", "failure", "fail", "mismatch", "not_match", "not-match"}:
        return "failure"
    return "need_review"


def _sync_case_result(payload: dict[str, Any], field_reviews: dict[str, dict[str, Any]]) -> None:
    case_status = _compute_final_decision(field_reviews)
    payload["final_decision"] = case_status
    payload["overall"] = case_status
    payload["case_result"] = {
        "status": case_status,
        "confidence": payload.get("overall_confidence"),
        "source": "field_aggregation",
    }


def _field_reviews_from_comparisons(comparisons: dict[str, Any]) -> dict[str, dict[str, Any]]:
    reviews: dict[str, dict[str, Any]] = {}
    for field_name, entry in (comparisons or {}).items():
        if not isinstance(entry, dict):
            continue
        review = {
            "field_name": field_name,
            "agent_decision": _normalize_agent_decision(entry.get("status")),
            "user_decision": None,
            "decision": _normalize_agent_decision(entry.get("status")),
            "comment": None,
            "override_value": entry.get("override_value") or entry.get("app") or entry.get("label"),
            "confidence": entry.get("confidence"),
        }
        reviews[field_name] = review
    return reviews


def save_verification_result(result: dict[str, Any]) -> dict[str, Any]:
    init_db()
    application_id = result.get("application_id") or result.get("applicationId") or result.get("app_id")
    result_id = application_id or result.get("result_id") or _generate_numeric_id()
    created_at = _to_mysql_datetime(result.get("created_at") or _now_iso())
    updated_at = _to_mysql_datetime(result.get("updated_at") or created_at)
    source_files = json.dumps(result.get("source_files") or {}, ensure_ascii=False)
    application_data = json.dumps(result.get("application") or {}, ensure_ascii=False)
    label_data = json.dumps(result.get("label") or result.get("label_data") or result.get("parsed") or {}, ensure_ascii=False)
    result_payload = dict(result)
    result_payload["application_id"] = application_id or result_id
    result_payload["result_id"] = result_id
    result_payload["created_at"] = result.get("created_at") or _now_iso()
    result_payload["updated_at"] = result.get("updated_at") or result_payload["created_at"]

    field_reviews = result_payload.get("field_reviews") or _field_reviews_from_comparisons(result_payload.get("comparisons") or {})
    for review in field_reviews.values():
        if "decision" not in review:
            review["decision"] = review.get("user_decision") or review.get("agent_decision") or "review"
    result_payload["field_reviews"] = field_reviews
    _sync_case_result(result_payload, field_reviews)

    conn = _connect()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO verification_results (result_id, application_id, created_at, updated_at, filename, application_source_type, source_files, application_data, label_data, result_json)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                application_id = VALUES(application_id),
                updated_at = VALUES(updated_at),
                filename = VALUES(filename),
                application_source_type = VALUES(application_source_type),
                source_files = VALUES(source_files),
                application_data = VALUES(application_data),
                label_data = VALUES(label_data),
                result_json = VALUES(result_json)
            """,
            (
                result_id,
                result_payload.get("application_id") or result_id,
                created_at,
                updated_at,
                result.get("filename"),
                result.get("application_source_type"),
                source_files,
                application_data,
                label_data,
                json.dumps(result_payload, ensure_ascii=False),
            ),
        )

        for field_name, review in field_reviews.items():
            cursor.execute(
                """
                INSERT INTO field_reviews (result_id, field_name, agent_decision, user_decision, comment, override_value, confidence)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    agent_decision = VALUES(agent_decision),
                    user_decision = VALUES(user_decision),
                    comment = VALUES(comment),
                    override_value = VALUES(override_value),
                    confidence = VALUES(confidence)
                """,
                (
                    result_id,
                    field_name,
                    review.get("agent_decision") or "review",
                    review.get("user_decision"),
                    review.get("comment"),
                    review.get("override_value"),
                    review.get("confidence"),
                ),
            )
        conn.commit()
    finally:
        conn.close()

    return result_payload


def get_verification_result(result_id: str) -> dict[str, Any] | None:
    init_db()
    conn = _connect()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM verification_results WHERE result_id = %s", (result_id,))
        row = cursor.fetchone()
        if row is None:
            return None

        payload = json.loads(row["result_json"])
        cursor.execute(
            "SELECT field_name, agent_decision, user_decision, comment, override_value, confidence FROM field_reviews WHERE result_id = %s ORDER BY field_name",
            (result_id,),
        )
        reviews = cursor.fetchall()

        field_reviews: dict[str, dict[str, Any]] = {}
        for review in reviews:
            decision = review["user_decision"] or review["agent_decision"] or "review"
            field_reviews[review["field_name"]] = {
                "field_name": review["field_name"],
                "agent_decision": review["agent_decision"],
                "user_decision": review["user_decision"],
                "decision": decision,
                "comment": review["comment"],
                "override_value": review["override_value"],
                "confidence": review["confidence"],
            }

        payload["field_reviews"] = field_reviews
        _sync_case_result(payload, field_reviews)
        payload["updated_at"] = row["updated_at"].strftime("%Y-%m-%dT%H:%M:%SZ") if hasattr(row["updated_at"], "strftime") else row["updated_at"]
        payload["created_at"] = row["created_at"].strftime("%Y-%m-%dT%H:%M:%SZ") if hasattr(row["created_at"], "strftime") else row["created_at"]

        comparisons = payload.get("comparisons") or {}
        for field_name, review in field_reviews.items():
            if field_name not in comparisons:
                continue
            status_value = review.get("user_decision") or review.get("agent_decision") or comparisons[field_name].get("status")
            comparisons[field_name]["status"] = _public_status_from_review_decision(status_value)
            comparisons[field_name]["review_decision"] = review.get("user_decision")
            comparisons[field_name]["comment"] = review.get("comment")
            comparisons[field_name]["override_value"] = review.get("override_value")

        payload["comparisons"] = comparisons
        return payload
    finally:
        conn.close()


def review_verification_result(
    result_id: str,
    field_name: str,
    decision: str,
    comment: str | None = None,
    override_value: str | None = None,
) -> dict[str, Any] | None:
    init_db()
    conn = _connect()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT result_json FROM verification_results WHERE result_id = %s", (result_id,))
        row = cursor.fetchone()
        if row is None:
            return None

        payload = json.loads(row["result_json"])
        field_reviews = payload.get("field_reviews") or {}
        existing = field_reviews.get(field_name) or {}
        current_decision = str(decision or "need_review").strip().lower().replace(" ", "_")
        normalized_decision = _normalize_agent_decision(current_decision)
        existing["field_name"] = field_name
        existing["agent_decision"] = existing.get("agent_decision") or "review"
        existing["user_decision"] = normalized_decision
        existing["decision"] = normalized_decision
        existing["comment"] = comment or existing.get("comment")
        existing["override_value"] = override_value or existing.get("override_value")
        field_reviews[field_name] = existing
        payload["field_reviews"] = field_reviews
        _sync_case_result(payload, field_reviews)

        comparisons = payload.get("comparisons") or {}
        if field_name in comparisons:
            comparisons[field_name]["status"] = _public_status_from_review_decision(normalized_decision)
            comparisons[field_name]["review_decision"] = normalized_decision
            comparisons[field_name]["comment"] = comment
            comparisons[field_name]["override_value"] = override_value or comparisons[field_name].get("override_value")
            comparisons[field_name]["reason"] = "Manual override applied." if override_value else (comment or "Manual override applied.")

        cursor.execute(
            """
            INSERT INTO field_reviews (result_id, field_name, agent_decision, user_decision, comment, override_value, confidence)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                agent_decision = VALUES(agent_decision),
                user_decision = VALUES(user_decision),
                comment = VALUES(comment),
                override_value = VALUES(override_value),
                confidence = VALUES(confidence)
            """,
            (
                result_id,
                field_name,
                existing.get("agent_decision") or "review",
                existing.get("user_decision"),
                existing.get("comment"),
                existing.get("override_value"),
                existing.get("confidence"),
            ),
        )

        payload["updated_at"] = _now_iso()
        mysql_updated_at = _to_mysql_datetime(payload["updated_at"])
        cursor.execute(
            "UPDATE verification_results SET updated_at = %s, result_json = %s WHERE result_id = %s",
            (mysql_updated_at, json.dumps(payload, ensure_ascii=False), result_id),
        )
        conn.commit()
        return payload
    finally:
        conn.close()


def set_final_decision(result_id: str, decision: str, comment: str | None = None) -> dict[str, Any] | None:
    _ = decision
    init_db()
    conn = _connect()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT result_json FROM verification_results WHERE result_id = %s", (result_id,))
        row = cursor.fetchone()
        if row is None:
            return None

        payload = json.loads(row["result_json"])
        field_reviews = payload.get("field_reviews") or {}
        _sync_case_result(payload, field_reviews)
        payload["review_summary"] = comment or ""
        payload["updated_at"] = _now_iso()
        mysql_updated_at = _to_mysql_datetime(payload["updated_at"])
        cursor.execute(
            "UPDATE verification_results SET updated_at = %s, result_json = %s WHERE result_id = %s",
            (mysql_updated_at, json.dumps(payload, ensure_ascii=False), result_id),
        )
        conn.commit()
        return payload
    finally:
        conn.close()
