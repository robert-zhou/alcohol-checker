# Alcohol Label Verification — Prototype

Prototype web app to extract and validate required fields from alcohol label images (brand, class/type, ABV, net contents, government warning). Designed for fast local processing (no external ML APIs) using Tesseract OCR.

Highlights
- Fast, local OCR via pytesseract (Tesseract must be installed separately)
- Single-file upload and batch uploads supported
- Simple browser UI for agents, designed to be easy to use

Quick start (Windows)

1. Install Tesseract OCR (separate installer):

   - Download from: https://github.com/tesseract-ocr/tesseract
   - After installing, if Tesseract is not on PATH, set `TESSERACT_CMD` environment variable or edit `app/main.py` to point to the `tesseract.exe` path.

2. Create and activate a Python venv, then install dependencies:

```bash
python -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt

# If using a separate conda environment for the app runtime, ensure the PDF parser is also installed there:
pip install pypdf==6.19.0
```

3. Run the app:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

4. Open http://localhost:8000 in a browser. Use the form to upload one or more label images.

Notes
- This is a prototype focused on local processing and fast turnaround times. In production you'd want hardened input handling, security reviews, and a store for audit/retention.
- If your network blocks outbound connections, this prototype does not require external network access for OCR.

Next steps
- Add sample label images and unit tests (optional). If you'd like, I can add synthetic labels and tests.
