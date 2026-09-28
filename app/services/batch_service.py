import asyncio
import io
import json
import re
import threading
import time
from pathlib import Path

from fastapi import UploadFile
from fastapi.responses import JSONResponse


class BatchJobService:
    def __init__(self, application_service, id_generator):
        self._application_service = application_service
        self._id_generator = id_generator
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()

    async def clone_upload_file(self, file: UploadFile | None) -> UploadFile | None:
        if file is None:
            return None

        try:
            data = await file.read()
        except Exception:
            return file

        return UploadFile(
            filename=file.filename,
            file=io.BytesIO(data),
            headers=file.headers,
        )

    @staticmethod
    def safe_application_identifier_from_upload(file: UploadFile | None) -> str | None:
        if file is None:
            return None

        filename = (file.filename or "").strip()
        if not filename:
            return None

        stem = Path(filename).stem
        explicit_app_match = re.search(r"(?i)(app[-_][A-Za-z0-9\-_]+)", stem)
        if explicit_app_match:
            return explicit_app_match.group(1)

        match = re.search(r"(?i)(?:application|app|case)[_-]?(?:id|number|no)?[-_]?([A-Za-z0-9\-_]+)", stem)
        if match:
            return match.group(1)

        match = re.search(r"(?i)([A-Za-z0-9\-_]{4,})$", stem)
        if match:
            return match.group(1)

        return None

    async def build_batch_pairs(self, application_files: list[UploadFile], label_files: list[UploadFile], mapping_file: UploadFile | None = None):
        app_candidates = []
        for upload in application_files:
            payload = None
            candidate_upload = await self.clone_upload_file(upload)
            try:
                raw = await candidate_upload.read()
                candidate_upload.file.seek(0)
                app_json = self._application_service.extract_application_from_pdf(raw) if (candidate_upload.filename or "").lower().endswith(".pdf") else None
                if app_json is not None:
                    payload = app_json
            except Exception:
                payload = None

            app_candidates.append({
                "upload": candidate_upload,
                "id": (payload or {}).get("application_id") or self.safe_application_identifier_from_upload(candidate_upload),
                "source": "pdf" if payload is not None else "filename",
                "payload": payload,
            })

        label_candidates = []
        for upload in label_files:
            label_upload = await self.clone_upload_file(upload)
            label_id = self.safe_application_identifier_from_upload(label_upload)
            label_candidates.append({
                "upload": label_upload,
                "id": label_id,
                "filename": label_upload.filename,
            })

        explicit_map: dict[str, str] = {}
        if mapping_file is not None:
            cloned_mapping_file = await self.clone_upload_file(mapping_file)
            raw = await cloned_mapping_file.read() if cloned_mapping_file is not None else b""
            explicit_map = self._application_service.parse_mapping_file(raw, mapping_file.filename)

        matched_pairs = []
        matched_label_indexes = set()
        for app in app_candidates:
            app_id = app["id"]
            app_filename = self._application_service.normalize_mapping_name(app["upload"].filename)
            target_label = None

            if explicit_map:
                explicit_label_name = explicit_map.get(app_filename) or explicit_map.get(self._application_service.normalize_mapping_name(app_id))
                if explicit_label_name:
                    for label_idx, label in enumerate(label_candidates):
                        if label_idx in matched_label_indexes:
                            continue
                        if self._application_service.normalize_mapping_name(label["filename"]) == self._application_service.normalize_mapping_name(explicit_label_name):
                            target_label = label
                            matched_label_indexes.add(label_idx)
                            break

            if target_label is None and app_id:
                for label_idx, label in enumerate(label_candidates):
                    if label_idx in matched_label_indexes:
                        continue
                    label_id = label["id"]
                    if label_id and label_id.lower() == app_id.lower():
                        target_label = label
                        matched_label_indexes.add(label_idx)
                        break

            if target_label is None:
                fallback_label = None
                for label_idx, label in enumerate(label_candidates):
                    if label_idx in matched_label_indexes:
                        continue
                    fallback_label = label
                    matched_label_indexes.add(label_idx)
                    break
                target_label = fallback_label

            if target_label is None:
                continue

            matched_pairs.append({
                "index": len(matched_pairs),
                "application": app["upload"],
                "label": target_label["upload"],
                "application_id": app_id,
            })

        unpaired_applications = [app for app in app_candidates if not any(pair["application"] is app["upload"] for pair in matched_pairs)]
        unmatched_labels = [label for idx, label in enumerate(label_candidates) if idx not in matched_label_indexes]

        return matched_pairs, unpaired_applications, unmatched_labels

    async def _run_batch_job(self, verify_callable, job_id: str, application_files: list[UploadFile], label_files: list[UploadFile], mapping_file: UploadFile | None = None):
        try:
            with self._lock:
                job = self._jobs[job_id]
                job["status"] = "processing"
                job["updated_at"] = time.time()

            matched_pairs, unpaired_applications, unmatched_labels = await self.build_batch_pairs(application_files, label_files, mapping_file=mapping_file)
            pair_count = len(matched_pairs)
            results = []
            skipped = {
                "extra_application_files": len(unpaired_applications),
                "extra_label_files": len(unmatched_labels),
            }

            for idx, pair in enumerate(matched_pairs):
                app_file = pair["application"]
                label_file = pair["label"]
                try:
                    response = await verify_callable(application_file=app_file, file=label_file)
                    payload = json.loads(response.body.decode("utf-8"))
                    public_payload = dict(payload)
                    public_payload.pop("result_id", None)
                    public_payload.pop("label_id", None)
                    item_result = {
                        "index": idx,
                        "job_id": job_id,
                        "application_file": app_file.filename,
                        "label_file": label_file.filename,
                        "status_code": response.status_code,
                        "overall": public_payload.get("overall"),
                        "status": public_payload.get("status"),
                        "application_id": pair.get("application_id"),
                        "result": public_payload,
                    }
                except Exception as exc:
                    item_result = {
                        "index": idx,
                        "job_id": job_id,
                        "application_file": app_file.filename,
                        "label_file": label_file.filename,
                        "status_code": 400,
                        "overall": None,
                        "status": None,
                        "application_id": pair.get("application_id"),
                        "result": {"error": "invalid application data", "detail": str(exc)},
                    }

                results.append(item_result)

                with self._lock:
                    job["progress"] = {"completed": idx + 1, "total": pair_count}
                    job["updated_at"] = time.time()

            with self._lock:
                job["status"] = "completed"
                job["progress"] = {"completed": pair_count, "total": pair_count}
                job["result"] = {
                    "summary": {
                        "requested": len(application_files),
                        "processed": len(results),
                        "label_count": len(label_files),
                        "skipped": skipped,
                    },
                    "results": results,
                }
                job["updated_at"] = time.time()
        except Exception as exc:
            with self._lock:
                job = self._jobs.get(job_id)
                if job is not None:
                    job["status"] = "failed"
                    job["error"] = str(exc)
                    job["updated_at"] = time.time()

    async def start_batch_job(self, verify_callable, application_files: list[UploadFile] = None, label_files: list[UploadFile] = None, mapping_file: UploadFile | None = None) -> JSONResponse:
        if application_files is None:
            application_files = []
        if label_files is None:
            label_files = []

        if not application_files:
            return JSONResponse({"error": "missing application files", "detail": "Please upload at least one application file."}, status_code=400)

        if not label_files:
            return JSONResponse({"error": "missing label files", "detail": "Please upload at least one label image."}, status_code=400)

        safe_application_files = [await self.clone_upload_file(file) for file in application_files]
        safe_label_files = [await self.clone_upload_file(file) for file in label_files]
        safe_mapping_file = await self.clone_upload_file(mapping_file) if mapping_file is not None else None

        job_id = self._id_generator()
        job = {
            "job_id": job_id,
            "status": "queued",
            "created_at": time.time(),
            "updated_at": time.time(),
            "progress": {"completed": 0, "total": min(len(safe_application_files), len(safe_label_files))},
            "error": None,
            "result": None,
        }
        with self._lock:
            self._jobs[job_id] = job

        def _runner():
            asyncio.run(self._run_batch_job(verify_callable, job_id, safe_application_files, safe_label_files, mapping_file=safe_mapping_file))

        threading.Thread(target=_runner, daemon=True).start()
        return JSONResponse({
            "job_id": job_id,
            "status": "queued",
            "progress": job["progress"],
            "message": "Batch processing started. Poll the job status endpoint for results.",
        })

    async def get_batch_job(self, job_id: str) -> JSONResponse:
        job = self._jobs.get(job_id)
        if job is None:
            return JSONResponse({"error": "job_not_found", "detail": "Batch job id was not found."}, status_code=404)

        payload = {
            "job_id": job["job_id"],
            "status": job["status"],
            "progress": job["progress"],
            "created_at": job["created_at"],
            "updated_at": job["updated_at"],
        }
        if job.get("error"):
            payload["error"] = job["error"]
        if job.get("result") is not None:
            payload["result"] = job["result"]
        return JSONResponse(payload)

    async def verify_batch_inline(self, verify_callable, application_files: list[UploadFile], label_files: list[UploadFile], mapping_file: UploadFile | None = None) -> JSONResponse:
        if not application_files:
            return JSONResponse({"error": "missing application files", "detail": "Please upload at least one application file."}, status_code=400)

        if not label_files:
            return JSONResponse({"error": "missing label files", "detail": "Please upload at least one label image."}, status_code=400)

        matched_pairs, unpaired_applications, unmatched_labels = await self.build_batch_pairs(application_files, label_files, mapping_file=mapping_file)
        results = []
        skipped = {
            "extra_application_files": len(unpaired_applications),
            "extra_label_files": len(unmatched_labels),
        }

        for idx, pair in enumerate(matched_pairs):
            app_file = pair["application"]
            label_file = pair["label"]
            try:
                response = await verify_callable(application_file=app_file, file=label_file)
                payload = json.loads(response.body.decode("utf-8"))
                public_payload = dict(payload)
                public_payload.pop("result_id", None)
                public_payload.pop("label_id", None)
                item_result = {
                    "index": idx,
                    "job_id": None,
                    "application_file": app_file.filename,
                    "label_file": label_file.filename,
                    "status_code": response.status_code,
                    "overall": public_payload.get("overall"),
                    "status": public_payload.get("status"),
                    "application_id": pair.get("application_id"),
                    "result": public_payload,
                }
            except Exception as exc:
                item_result = {
                    "index": idx,
                    "job_id": None,
                    "application_file": app_file.filename,
                    "label_file": label_file.filename,
                    "status_code": 400,
                    "overall": None,
                    "status": None,
                    "application_id": pair.get("application_id"),
                    "result": {"error": "invalid application data", "detail": str(exc)},
                }
            results.append(item_result)

        return JSONResponse({
            "summary": {
                "requested": len(application_files),
                "processed": len(results),
                "label_count": len(label_files),
                "skipped": skipped,
            },
            "results": results,
        })
