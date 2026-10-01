"""Measured PDF pages, native text, widgets, images and source transforms."""

from io import BytesIO
import math

from .geometry import clip_box


def capture(store, document, config):
    import fitz
    from PIL import Image, ImageStat

    pages = []
    with fitz.open(stream=store.read(document["source"]), filetype="pdf") as pdf:
        if pdf.needs_pass:
            raise ValueError("Encrypted PDF requires a password; no password was supplied")
        if not len(pdf):
            raise ValueError("PDF contains no pages")
        for index, page in enumerate(pdf):
            page_id = f"{document['document_id']}:p{index + 1}"
            try:
                width, height = page.rect.width, page.rect.height
                if width <= 0 or height <= 0:
                    raise ValueError("Nonpositive page dimensions")
                scale = min(config["render_width"] / width, math.sqrt(config["max_pixels"] / (width * height)))
                pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False, colorspace=fitz.csRGB)
                image_bytes = pix.tobytes("png")
                transform = page.rotation_matrix

                def box(raw):
                    rect = fitz.Rect(raw) * transform
                    return clip_box([rect.x0 / width, rect.y0 / height, rect.x1 / width, rect.y1 / height])

                lines, discarded = [], []
                # TEXTFLAGS_TEXT omits embedded image bytes from raw text evidence.
                native = page.get_text("dict", flags=fitz.TEXTFLAGS_TEXT, sort=False)
                for block in native.get("blocks", []):
                    for line in block.get("lines", []):
                        text = "".join(span["text"] for span in line.get("spans", []))
                        bbox = box(line["bbox"])
                        item = {"text": text, "raw_bbox": list(line["bbox"]), "bbox": bbox}
                        if not bbox:
                            discarded.append(item)
                        elif text.strip():
                            lines.append({**item, "id": f"native-{len(lines) + 1}", "source": "native"})
                widgets = [{"name": w.field_name, "value": w.field_value, "type": w.field_type_string,
                            "raw_bbox": list(w.rect), "bbox": box(w.rect)} for w in page.widgets() or []]
                image_boxes = [b for image in page.get_image_info() if (b := box(image["bbox"]))]
                drawings = []
                for drawing in page.get_drawings():
                    rect = drawing["rect"]
                    # Retain thin rules as measured endpoints. A one-dimensional
                    # rule has no valid area box and is never silently widened.
                    a = fitz.Point(rect.x0, rect.y0) * transform
                    b = fitz.Point(rect.x1, rect.y1) * transform
                    drawings.append({"raw_bbox": list(rect), "bbox": box(rect),
                        "endpoints": [[a.x / width, a.y / height], [b.x / width, b.y / height]],
                        "type": drawing["type"], "width_points": drawing["width"],
                        "item_count": len(drawing["items"]), "fill": drawing.get("fill"), "color": drawing.get("color")})
                with Image.open(BytesIO(image_bytes)) as image:
                    variance = float(ImageStat.Stat(image.convert("L")).var[0])
                pages.append({"page_id": page_id, "document_id": document["document_id"], "page_number": index + 1,
                    "status": "captured", "source_sha256": document["source_sha256"],
                    "size_points": [width, height], "render_pixels": [pix.width, pix.height],
                    "image": store.put(image_bytes, "png"), "native": store.put_json(native),
                    "lines": lines, "discarded_native_boxes": discarded, "widgets": widgets,
                    "image_boxes": image_boxes, "drawings": drawings, "render_grayscale_variance": variance,
                    "transform": {"source_coordinates": "PyMuPDF unrotated crop-relative top-left points",
                        "target_coordinates": "normalized rendered-page top-left l,t,r,b", "rotation_degrees": page.rotation,
                        "rotation_matrix": list(transform), "cropbox": list(page.cropbox), "mediabox": list(page.mediabox),
                        "normalization_divisors": [width, height], "render_scale": scale}})
            except Exception as exc:
                pages.append({"page_id": page_id, "document_id": document["document_id"], "page_number": index + 1,
                              "source_sha256": document["source_sha256"], "status": "capture_failed",
                              "error": f"{type(exc).__name__}: {exc}"})
    return {"page_count": len(pages), "pages": pages,
            "stage_status": "partial" if any(p["status"] != "captured" for p in pages) else "success"}
