"""Native Apple Vision OCR; subprocess entry point permits page timeouts.

Vision raw coordinates are retained. Its bottom-left normalized x/y/width/height
is transformed to catalog top-left l/t/r/b. No other OCR engine is invoked.
"""

import hashlib
import importlib.metadata
import json
import platform
import sys

from .geometry import clip_box


def observe(path, languages):
    import objc
    import Vision
    from Foundation import NSURL
    from PIL import Image

    with Image.open(path) as image:
        pixels = list(image.size)
    with objc.autorelease_pool():
        request = Vision.VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        request.setRecognitionLanguages_(languages)
        request.setUsesLanguageCorrection_(True)
        handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(NSURL.fileURLWithPath_(str(path)), {})
        success, error = handler.performRequests_error_([request], None)
        if not success or error is not None:
            raise RuntimeError(f"Apple Vision recognition failed: {error}")
        observations = []
        for observation in request.results() or []:
            candidates = observation.topCandidates_(1)
            if not candidates:
                continue
            candidate = candidates[0]
            box = observation.boundingBox()
            observations.append({"text": str(candidate.string()), "confidence": float(candidate.confidence()),
                                 "bbox": [box.origin.x, box.origin.y, box.size.width, box.size.height]})
        return {"engine": "apple-vision", "image_sha256": hashlib.sha256(open(path, "rb").read()).hexdigest(),
            "render_pixels": pixels, "observations": observations,
            "engine_info": {"macos": platform.mac_ver()[0], "pyobjc_vision": importlib.metadata.version("pyobjc-framework-Vision"),
                "revision": int(request.revision()), "languages": languages, "recognition_level": "accurate",
                "raw_coordinates": "normalized bottom-left x,y,width,height"}}


def normalize(raw, page):
    import math
    if raw.get("engine") != "apple-vision" or raw.get("image_sha256") != page["image"]["sha256"]:
        raise ValueError("OCR evidence is not from the expected engine/image")
    if raw.get("render_pixels") != page["render_pixels"]:
        raise ValueError("OCR render dimensions do not match page")
    lines = []
    for index, item in enumerate(raw["observations"], 1):
        b, confidence, text = item["bbox"], item["confidence"], item["text"]
        if (len(b) != 4 or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in b)
                or min(b) < -1e-6 or b[0] + b[2] > 1 + 1e-6 or b[1] + b[3] > 1 + 1e-6
                or not isinstance(text, str) or not isinstance(confidence, (int, float))
                or not math.isfinite(confidence) or not 0 <= confidence <= 1):
            raise ValueError("Malformed Apple Vision observation")
        box = clip_box([b[0], 1 - b[1] - b[3], b[0] + b[2], 1 - b[1]])
        if text.strip() and not box:
            raise ValueError("Nonempty OCR text has a zero-area box")
        if text.strip():
            lines.append({"id": f"vision-{index}", "text": text, "bbox": box, "confidence": confidence,
                          "source": "apple-vision", "raw_observation_index": index - 1})
    return lines


if __name__ == "__main__":
    print(json.dumps(observe(sys.argv[1], json.loads(sys.argv[2])), allow_nan=False))
