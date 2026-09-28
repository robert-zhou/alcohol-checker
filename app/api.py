import logging
import time

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover - dependency fallback for older installs
    PdfReader = None

from app import config as app_config
from app.domain.format_validator import FormatValidator
from app.infrastructure.db import get_verification_result as db_get_verification_result
from app.infrastructure.db import init_db
from app.infrastructure.db import review_verification_result as db_review_verification_result
from app.infrastructure.db import save_verification_result
from app.infrastructure.db import set_final_decision as db_set_final_decision
from app.integrations.llm import LLMClient
from app.services import ApplicationPayloadService, BatchJobService, VerificationService

llm_client = LLMClient()
format_validator = FormatValidator()
application_payload_service = ApplicationPayloadService(pdf_reader_cls=PdfReader)
verification_service = VerificationService(
    llm_client=llm_client,
    format_validator=format_validator,
    save_verification_result=save_verification_result,
    extract_application_identifier=application_payload_service.extract_application_identifier,
)
batch_job_service = BatchJobService(
    application_service=application_payload_service,
    id_generator=verification_service._generate_numeric_id,
)

init_db()

app = FastAPI(title="Alcohol Label Verification - Prototype")
app.config = app_config
config = app_config

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.post("/api/verify")
async def verify(
    application: str | None = Form(None),
    application_file: UploadFile | None = File(None),
    file: UploadFile | None = File(None),
    include_debug: bool = Form(False),
):
    """Compare an application record (JSON, PDF, or text) with a provided label image."""
    request_started = time.perf_counter()
    stage_started = time.perf_counter()
    try:
        application, app_json, app_source = await application_payload_service.read_application_payload(application, application_file)
    except ValueError as exc:
        return JSONResponse(
            {
                "error": "invalid application data",
                "detail": str(exc),
                "profiling": {
                    "application_payload_parse_seconds": round(time.perf_counter() - stage_started, 4),
                    "api_verify_total_seconds": round(time.perf_counter() - request_started, 4),
                },
            },
            status_code=400,
        )

    pre_profile = {
        "application_payload_parse_seconds": round(time.perf_counter() - stage_started, 4),
        "api_verify_request_seconds_before_service": round(time.perf_counter() - request_started, 4),
    }

    if not app_json:
        return JSONResponse(
            {
                "error": "missing application data",
                "detail": "Provide JSON, PDF, or text application data in the application field or upload an application file.",
                "profiling": {
                    **pre_profile,
                    "api_verify_total_seconds": round(time.perf_counter() - request_started, 4),
                },
            },
            status_code=400,
        )

    include_debug_flag = include_debug if isinstance(include_debug, bool) else False

    if isinstance(app_json, dict):
        app_json["debug"] = bool(app_json.get("debug") or include_debug_flag)

    return await verification_service.verify(
        application=application,
        app_json=app_json,
        app_source=app_source,
        application_file=application_file,
        file=file,
        pre_profile=pre_profile,
        include_debug=include_debug_flag,
    )


async def start_batch_job(
    application_files: list[UploadFile] = None,
    label_files: list[UploadFile] = None,
    mapping_file: UploadFile | None = None,
):
    """Queue a batch verification job and return a job id immediately for polling."""
    return await batch_job_service.start_batch_job(
        verify_callable=verify,
        application_files=application_files,
        label_files=label_files,
        mapping_file=mapping_file,
    )


async def get_batch_job(job_id: str):
    return await batch_job_service.get_batch_job(job_id)


async def _verify_batch_inline(
    application_files: list[UploadFile],
    label_files: list[UploadFile],
    mapping_file: UploadFile | None = None,
):
    """Inline batch execution kept for backward compatibility and direct unit tests."""
    if not isinstance(mapping_file, UploadFile):
        mapping_file = None
    return await batch_job_service.verify_batch_inline(
        verify_callable=verify,
        application_files=application_files,
        label_files=label_files,
        mapping_file=mapping_file,
    )


@app.post("/api/verify_batch")
async def verify_batch(
    application_files: list[UploadFile] = File(default=[]),
    label_files: list[UploadFile] = File(default=[]),
    mapping_file: UploadFile | None = File(default=None),
):
    """Legacy direct batch API for compatibility; use /api/batch for queued async job processing."""
    if not isinstance(mapping_file, UploadFile):
        mapping_file = None
    return await _verify_batch_inline(application_files, label_files, mapping_file=mapping_file)


@app.post("/api/batch")
async def batch_job_submit(
    application_files: list[UploadFile] = File(default=[]),
    label_files: list[UploadFile] = File(default=[]),
    mapping_file: UploadFile | None = File(default=None),
):
    """Start a background batch job and return a polling id."""
    if not isinstance(mapping_file, UploadFile):
        mapping_file = None
    return await start_batch_job(application_files, label_files, mapping_file=mapping_file)


@app.get("/api/jobs/{job_id}")
async def batch_job_status(job_id: str):
    return await get_batch_job(job_id)


@app.get("/api/results/{result_id}")
async def get_verification_result(result_id: str):
    try:
        payload = db_get_verification_result(result_id)
    except Exception as exc:
        logging.exception("get_verification_result failed for %s", result_id)
        return JSONResponse({"error": "db_error", "detail": str(exc)}, status_code=500)
    if payload is None:
        return JSONResponse({"error": "result_not_found", "detail": "Verification result was not found."}, status_code=404)
    return JSONResponse(payload)


@app.post("/api/results/{result_id}/review")
async def review_verification_result(
    result_id: str,
    field_name: str = Form(...),
    decision: str = Form(...),
    comment: str | None = Form(None),
    override_value: str | None = Form(None),
):
    try:
        payload = db_review_verification_result(
            result_id=result_id,
            field_name=field_name,
            decision=decision,
            comment=comment,
            override_value=override_value,
        )
    except Exception as exc:
        logging.exception("review_verification_result failed for %s/%s", result_id, field_name)
        return JSONResponse({"error": "db_error", "detail": str(exc)}, status_code=500)
    if payload is None:
        return JSONResponse({"error": "result_not_found", "detail": "Verification result was not found."}, status_code=404)
    return JSONResponse(payload)


@app.post("/api/results/{result_id}/final-decision")
async def set_final_verification_decision(
    result_id: str,
    decision: str = Form(...),
    comment: str | None = Form(None),
):
    try:
        payload = db_set_final_decision(result_id=result_id, decision=decision, comment=comment)
    except Exception as exc:
        logging.exception("final decision save failed for %s", result_id)
        return JSONResponse({"error": "db_error", "detail": str(exc)}, status_code=500)
    if payload is None:
        return JSONResponse({"error": "result_not_found", "detail": "Verification result was not found."}, status_code=404)
    return JSONResponse(payload)


@app.get("/", response_class=HTMLResponse)
async def index():
    with open("app/static/index.html", "r", encoding="utf-8") as file_handle:
        return file_handle.read()


__all__ = ["app", "verify", "verify_batch", "llm_client"]
