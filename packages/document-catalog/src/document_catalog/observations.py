"""Text quality symptoms and configured prompt evidence, separate from roles."""

from collections import Counter
import json
import re
import subprocess
import sys
import unicodedata

from .vision import normalize


def text_quality(text):
    categories = Counter(unicodedata.category(c) for c in text if c not in "\t\n\r")
    symptoms = {"unexpected_controls": categories["Cc"] + categories["Cs"],
                "replacement_characters": text.count("\ufffd"), "private_use_characters": categories["Co"]}
    flags = [name for name, count in symptoms.items() if count and count / max(len(text), 1) >= 0.01]
    # Repeated single glyph runs are measured symptoms, not language judgments.
    if re.search(r"([^\W\d_])\1{15,}", text):
        flags.append("repeated_glyph_run")
    return {"flags": flags, "characters": len(text), "alphanumeric_characters": sum(c.isalnum() for c in text),
            **symptoms, "accuracy": "unverified", "scope": "Encoding and repetition symptoms; printable font corruption can evade these checks."}


def recognize(store, page, config):
    native = "\n".join(line["text"] for line in page["lines"])
    quality = text_quality(native)
    image_area = sum((b[2] - b[0]) * (b[3] - b[1]) for b in page["image_boxes"])
    reasons = []
    if quality["alphanumeric_characters"] < 40:
        reasons.append("sparse_native_text")
    if quality["flags"]:
        reasons.append("native_encoding_symptoms")
    if image_area >= 0.15:
        reasons.append("embedded_image_may_contain_text")
    if config["mode"] == "always":
        reasons.append("configured_always")
    needed = bool(reasons)
    if config["mode"] == "never" or not needed:
        return {"status": "ocr_disabled" if config["mode"] == "never" else "native_text_used",
                "lines": page["lines"], "text_source": "native", "native_quality": quality,
                "quality": quality, "recognition_reasons": reasons, "needs_recognition": needed}
    try:
        completed = subprocess.run([sys.executable, "-m", "document_catalog.vision", str(store.path(page["image"]["path"])),
                                    json.dumps(config["languages"])], capture_output=True, text=True,
                                   timeout=config["timeout_seconds"], check=False)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Apple Vision timeout after {config['timeout_seconds']}s; stdout={exc.stdout!r}; stderr={exc.stderr!r}") from exc
    if completed.returncode:
        raise RuntimeError(f"Apple Vision exit {completed.returncode}; stdout={completed.stdout}; stderr={completed.stderr}")
    raw = json.loads(completed.stdout)
    lines = normalize(raw, page)
    return {"status": "ocr_success" if lines else "ocr_empty", "raw": store.put_json(raw),
            "lines": lines, "text_source": "apple-vision", "native_quality": quality,
            "quality": text_quality("\n".join(line["text"] for line in lines)),
            "recognition_reasons": reasons, "needs_recognition": False,
            "transform": "[x,y,width,height] -> [x,1-y-height,x+width,1-y]"}


def anchors(lines, category):
    result = []
    # Search every line, including mid-page prompts. A hit is never an answer box.
    for anchor in category["anchors"]:
        pattern = re.compile(anchor["pattern"], re.IGNORECASE)
        for line in lines:
            if pattern.search(line["text"]):
                result.append({"anchor_id": anchor["id"], "line_id": line["id"], "bbox": line["bbox"],
                    "text": line["text"], "proposed_role": anchor.get("role"), "schema_ref": anchor.get("schema_ref"),
                    "method": "configured_regex", "status": "candidate", "bounds_meaning": "prompt_text_only"})
    return result
