"""Local Docling layout detector. Model artifacts must already exist on disk."""

import os
from pathlib import Path

from .geometry import clip_box
from .store import digest

_PREDICTORS = {}


def model_identity(config):
    if config["provider"] == "none":
        return {"provider": "none"}
    path = Path(config["artifacts_path"] or "/missing-local-docling-model").expanduser().resolve()
    names = ["config.json", "preprocessor_config.json", "model.safetensors"]
    return {"provider": "docling-ibm-models.LayoutPredictor", "artifacts_path": str(path),
            "files": {name: digest((path / name).read_bytes()) if (path / name).is_file() else None for name in names}}


def predict(store, page, config, model):
    if config["provider"] == "none":
        return {"status": "disabled", "regions": [], "semantic_accuracy": "not_assessed"}
    if any(value is None for value in model["files"].values()):
        raise FileNotFoundError("Docling requires an existing local directory with config.json, preprocessor_config.json and model.safetensors")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    from docling_ibm_models.layoutmodel.layout_predictor import LayoutPredictor
    from PIL import Image

    key = (model["artifacts_path"], tuple(model["files"].values()), config["threads"], config["threshold"])
    if key not in _PREDICTORS:
        _PREDICTORS[key] = LayoutPredictor(model["artifacts_path"], device="cpu", num_threads=config["threads"], base_threshold=config["threshold"])
    with Image.open(store.path(page["image"]["path"])) as image:
        raw = list(_PREDICTORS[key].predict(image.convert("RGB")))
        width, height = image.size
    regions, rejected = [], []
    for index, item in enumerate(raw, 1):
        box = clip_box([item["l"] / width, item["t"] / height, item["r"] / width, item["b"] / height])
        if box:
            regions.append({"id": f"layout-{index}", "label": item["label"], "confidence": item["confidence"],
                            "bbox": box, "raw_prediction_index": index - 1, "evidence_kind": "model_prediction"})
        else:
            rejected.append(index - 1)
    return {"status": "predicted", "regions": regions, "raw": store.put_json(raw),
            "model": model, "rejected_zero_area_predictions": rejected,
            "transform": {"source": "top-left pixels l,t,r,b", "divisors": [width, height]},
            "semantic_accuracy": "unverified", "remote_inference": False}
