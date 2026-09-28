from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "sample_cases" / "batch_fixture"
APP_DIR = FIXTURE_DIR / "applications"
LABEL_DIR = FIXTURE_DIR / "labels"


CASES = [
    {"id": "APP-1001", "brand": "North Valley Lager", "type": "Lager", "abv": "5.0%", "net": "355 ml", "expected": "PASS"},
    {"id": "APP-1002", "brand": "Cedar Creek Vodka", "type": "Vodka", "abv": "40%", "net": "750 ml", "expected": "PASS"},
    {"id": "APP-1003", "brand": "Red Mesa Tequila", "type": "Tequila", "abv": "38%", "net": "750 ml", "expected": "PASS"},
    {"id": "APP-1004", "brand": "Wrong Brand Example", "type": "Ale", "abv": "8.8%", "net": "12 oz", "expected": "FAIL"},
    {"id": "APP-1005", "brand": "Harbor Light Gin", "type": "Gin", "abv": "42%", "net": "750 ml", "expected": "PASS"},
    {"id": "APP-1006", "brand": "Pine Ridge Whiskey", "type": "Whiskey", "abv": "58%", "net": "1.5 L", "expected": "FAIL"},
    {"id": "APP-1007", "brand": "Lakeside Cider", "type": "Cider", "abv": "5.8%", "net": "12 fl oz", "expected": "FAIL"},
    {"id": "APP-1008", "brand": "Hillside Hard Lemonade", "type": "Ready-to-drink", "abv": "5.0%", "net": "12 fl oz", "expected": "PASS"},
    {"id": "APP-1009", "brand": "Ember Rye", "type": "Rye", "abv": "40%", "net": "500 ml", "expected": "FAIL"},
    {"id": "APP-1010", "brand": "Canyon Bloom Wine", "type": "Wine", "abv": "13.5%", "net": "750 ml", "expected": "PASS"},
]


def escape_pdf_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_pdf(application_id: str, brand: str, label_type: str, abv: str, net: str) -> bytes:
    lines = [
        f"Application ID: {application_id}",
        f"Brand: {brand}",
        f"Class/Type: {label_type}",
        f"ABV: {abv}",
        f"Net Contents: {net}",
        "Government Warning: (1) According to the Surgeon General, women should not drink alcoholic beverages during pregnancy. (2) Consumption of alcohol impairs your ability to drive a car or operate machinery, and may cause health problems.",
    ]
    stream_parts = []
    y = 760
    for line in lines:
        stream_parts.append(f"BT /F1 12 Tf 60 {y} Td ({escape_pdf_text(line)}) Tj ET")
        y -= 22
    content = "\n".join(stream_parts)
    content_bytes = content.encode("latin-1", errors="replace")

    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        f"<< /Length {len(content_bytes)} >>\nstream\n{content}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for idx, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{idx} 0 obj\n".encode("latin-1"))
        pdf.extend(obj.encode("latin-1", errors="replace"))
        pdf.extend(b"\nendobj\n")

    xref_position = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("latin-1"))
    pdf.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        pdf.extend(f"{off:010d} 00000 n \n".encode("latin-1"))
    pdf.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_position}\n%%EOF\n".encode("latin-1"))
    return bytes(pdf)


def make_label_image(case: dict) -> Image.Image:
    img = Image.new("RGB", (1200, 900), "white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 36)
    except OSError:
        font = ImageFont.load_default()

    lines = [
        f"APPLICATION ID: {case['id']}",
        f"BRAND: {case['brand']}",
        f"CLASS/TYPE: {case['type']}",
        f"ABV: {case['abv']}",
        f"NET CONTENTS: {case['net']}",
        "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not drink alcoholic beverages during pregnancy. (2) Consumption of alcohol impairs your ability to drive a car or operate machinery, and may cause health problems.",
    ]
    if case["expected"] == "FAIL":
        lines[1] = "BRAND: Label Does Not Match Application"
        lines[2] = "CLASS/TYPE: Wrong Type"
        lines[3] = "ABV: 9.9%"
        lines[4] = "NET CONTENTS: 20 oz"

    y = 120
    for line in lines:
        draw.text((80, y), line, fill="black", font=font)
        y += 70
    return img


def main():
    APP_DIR.mkdir(parents=True, exist_ok=True)
    LABEL_DIR.mkdir(parents=True, exist_ok=True)

    for existing in list(APP_DIR.iterdir()):
        if existing.is_file():
            existing.unlink()
    for existing in list(LABEL_DIR.iterdir()):
        if existing.is_file():
            existing.unlink()

    manifest_cases = []
    for case in CASES:
        app_name = f"application_{case['id'].replace('-', '_')}.pdf"
        label_name = f"label_{case['id'].replace('-', '_')}.png"

        (APP_DIR / app_name).write_bytes(
            build_pdf(case["id"], case["brand"], case["type"], case["abv"], case["net"])
        )
        make_label_image(case).save(LABEL_DIR / label_name)
        manifest_cases.append(
            {
                "application_id": case["id"],
                "application_file": app_name,
                "label_file": label_name,
                "expected_result": case["expected"],
            }
        )

    manifest = {
        "name": "batch_fixture",
        "total_applications": len(CASES),
        "total_labels": len(CASES),
        "pass_count": sum(1 for case in CASES if case["expected"] == "PASS"),
        "fail_count": sum(1 for case in CASES if case["expected"] == "FAIL"),
        "cases": manifest_cases,
    }
    (FIXTURE_DIR / "batch_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    pdf_count = len(list(APP_DIR.glob("*.pdf")))
    label_count = len(list(LABEL_DIR.glob("*.png")))
    print(f"APP_COUNT={pdf_count}")
    print(f"LABEL_COUNT={label_count}")
    print(f"PASS_COUNT={manifest['pass_count']}")
    print(f"FAIL_COUNT={manifest['fail_count']}")
    print(f"FIRST_APP={sorted(APP_DIR.glob('*.pdf'))[0].name}")
    print(f"FIRST_LABEL={sorted(LABEL_DIR.glob('*.png'))[0].name}")


if __name__ == "__main__":
    main()
