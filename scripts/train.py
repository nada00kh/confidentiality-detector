"""Fine-tune a token-classification model (GPU recommended; designed for Colab).

  python scripts/train.py --config configs/experiments/e1_mbert_v2.json --work-dir /content/runs --save-dir <drive dir>

Plain PyTorch loop (no Trainer): each epoch is checkpointed with save_pretrained, scored on
the validation documents with the same character-span evaluation used everywhere else, and
the best checkpoint is RELOADED FROM DISK and re-scored to prove it round-trips. (The
original run's Trainer `load_best_model_at_end` reported missing LayerNorm keys when
restoring, so in-memory evaluation after train() was not trustworthy.)
The test sets are never touched here.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402
import torch  # noqa: E402

from confidentiality_detector.alignment import training_features  # noqa: E402
from confidentiality_detector.challenge import load_challenge  # noqa: E402
from confidentiality_detector.detectors.transformer import TransformerDetector  # noqa: E402  (fail fast, before training)
from confidentiality_detector.documents import document_from_ai4privacy, file_sha256, load_documents, read_jsonl  # noqa: E402
from confidentiality_detector.labels import ID2LABEL, IGNORE_INDEX, LABEL2ID, POLICIES  # noqa: E402
from confidentiality_detector.metrics import evaluate  # noqa: E402
from confidentiality_detector.perturb import FormatPerturber  # noqa: E402
from confidentiality_detector.runio import environment_info, write_json  # noqa: E402

DEFAULTS = {
    "model_name": "google-bert/bert-base-multilingual-cased",
    "label_policy": "v2",
    "augment": "none",            # "none" | "format_A"
    "augment_fraction": 0.5,      # share of target-bearing train docs that get one family-A copy
    "learning_rate": 2e-5,
    "epochs": 2,
    "batch_size": 16,
    "weight_decay": 0.01,
    "warmup_ratio": 0.1,
    "max_length": 512,
    "window_overlap": 32,
    "fp16": True,
    "seed": 42,
    "selection_metric": "entity_f1",  # on validation (gold of label_policy)
    "extra_train": [],              # round 2: extra JSONL documents (hash-checked)
    "diagnostic_sets": [],          # logged per epoch, never used for selection
}


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def optimizer_step(model, optimizer, scheduler, scaler, max_grad_norm: float = 1.0) -> bool:
    """One AMP-aware update. Returns False when the GradScaler skipped the optimizer step.

    With fp16, GradScaler skips optimizer.step() whenever the scaled gradients overflow (always
    at the first steps, while the loss scale calibrates, and occasionally after each scale
    growth). The scheduler must then not advance either; otherwise the learning-rate schedule
    runs ahead of the real updates (and PyTorch warns "lr_scheduler.step() before
    optimizer.step()"). A skipped step is detected, as in HF Accelerate, by the scale decreasing.
    """
    scaler.unscale_(optimizer)
    torch.nn.utils.clip_grad_norm_(model.parameters(), max_grad_norm)
    scale_before = scaler.get_scale()
    scaler.step(optimizer)
    scaler.update()
    optimizer.zero_grad(set_to_none=True)
    stepped = scaler.get_scale() >= scale_before
    if stepped:
        scheduler.step()
    return stepped


def load_train_docs(cfg: dict, raw_path: Path, manifest_dir: Path, eval_dir: Path, challenge_path: Path,
                    limit: int | None = None):
    policy = POLICIES[cfg["label_policy"]]
    train_ids = (manifest_dir / "train.ids").read_text().split()[:limit]
    wanted = set(train_ids)
    raw = {str(r["id"]): r for r in read_jsonl(raw_path) if str(r["id"]) in wanted}
    docs = [document_from_ai4privacy(raw[i], policy) for i in train_ids]
    n_aug = 0
    if cfg["augment"] == "format_A":
        # Never let augmentation introduce a name that occurs in any evaluation set.
        held_out_names = set()
        for path in list(eval_dir.glob("*.jsonl")):
            for d in load_documents(path):
                held_out_names |= {d.text[s.start:s.end] for s in d.spans if s.label in ("FIRSTNAME", "LASTNAME")}
        for d in load_challenge(challenge_path):
            held_out_names |= {d.text[s.start:s.end] for s in d.spans if s.label in ("FIRSTNAME", "LASTNAME")}
        perturb = FormatPerturber("A", excluded_names=held_out_names)
        rng = random.Random(cfg["seed"])
        extra = [perturb(d) for d in docs if d.spans and rng.random() < cfg["augment_fraction"]]
        n_aug = len(extra)
        docs += extra
    return docs, n_aug


def load_extra_train(cfg: dict) -> tuple[list, dict]:
    """Extra training documents (round-2 synthetic data). Each file must match the sha256
    recorded in its directory's manifest.json, and every document must pass the annotation
    policy checks; otherwise training stops before any GPU time is spent."""
    from confidentiality_detector.labels import TARGET_SET, cvv_has_evidence

    docs, info = [], {}
    for rel in cfg.get("extra_train", []):
        path = ROOT / rel
        manifest = json.loads((path.parent / "manifest.json").read_text(encoding="utf-8"))
        expected = manifest["files"][path.stem]["sha256"]
        actual = file_sha256(path)
        if actual != expected:
            raise RuntimeError(f"{rel}: sha256 {actual[:12]} does not match manifest {expected[:12]}")
        loaded = load_documents(path)
        for d in loaded:
            cards = [(s.start, s.end) for s in d.spans if s.label == "CREDITCARDNUMBER"]
            for s in d.spans:
                if s.label not in TARGET_SET:
                    raise RuntimeError(f"{d.doc_id}: label {s.label} outside the 13-label scope")
                if s.label == "CREDITCARDCVV" and not cvv_has_evidence(d.text, s.start, s.end, cards):
                    raise RuntimeError(f"{d.doc_id}: CVV without contextual evidence")
        docs += loaded
        info[rel] = {"n_docs": len(loaded), "sha256": actual, "generator": manifest.get("generator")}
    return docs, info


def collate(batch, pad_id):
    width = max(len(x["input_ids"]) for x in batch)
    ids = torch.full((len(batch), width), pad_id, dtype=torch.long)
    mask = torch.zeros((len(batch), width), dtype=torch.long)
    labels = torch.full((len(batch), width), IGNORE_INDEX, dtype=torch.long)
    for i, x in enumerate(batch):
        n = len(x["input_ids"])
        ids[i, :n] = torch.tensor(x["input_ids"])
        mask[i, :n] = 1
        labels[i, :n] = torch.tensor(x["labels"])
    return ids, mask, labels


def batches(features, batch_size, rng):
    """Length-bucketed shuffled batches (cuts padding without fixing batch composition)."""
    order = list(range(len(features)))
    rng.shuffle(order)
    chunks = [order[i:i + batch_size * 50] for i in range(0, len(order), batch_size * 50)]
    out = []
    for chunk in chunks:
        chunk.sort(key=lambda i: len(features[i]["input_ids"]))
        out += [chunk[i:i + batch_size] for i in range(0, len(chunk), batch_size)]
    rng.shuffle(out)
    return out


def validate(model, tokenizer, docs, device):
    det = TransformerDetector.from_model(model, tokenizer, device=device, batch_size=64)
    preds = dict(zip([d.doc_id for d in docs], det.detect_batch([d.text for d in docs])))
    res = evaluate(docs, preds)
    model.train()
    return {
        "entity_precision": res["entity"]["micro"]["precision"],
        "entity_recall": res["entity"]["micro"]["recall"],
        "entity_f1": res["entity"]["micro"]["f1"],
        "entity_caught_any_type": res["entity"]["micro"]["caught_any_type"],
        "doc_false_allow_rate": res["document"]["false_allow_rate"],
        "doc_false_block_rate": res["document"]["false_block_rate"],
        "fp_breakdown": res["entity"]["fp_breakdown"],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", type=Path, required=True)
    ap.add_argument("--work-dir", type=Path, default=ROOT / "runs")
    ap.add_argument("--save-dir", type=Path, default=None, help="persistent dir for the best checkpoint (e.g. Drive)")
    ap.add_argument("--raw", type=Path, default=ROOT / "data/raw/english_pii_43k.jsonl")
    ap.add_argument("--manifests", type=Path, default=ROOT / "data/splits/original")
    ap.add_argument("--eval-dir", type=Path, default=ROOT / "data/eval")
    ap.add_argument("--challenge", type=Path, default=ROOT / "data/challenge/challenge_v1.txt")
    ap.add_argument("--limit-train", type=int, default=None, help="smoke test only")
    ap.add_argument("--limit-val", type=int, default=None, help="smoke test only")
    ap.add_argument("--run-name", default=None, help="override the config name (output directory name)")
    args = ap.parse_args()

    cfg = {**DEFAULTS, **json.loads(args.config.read_text())}
    if args.run_name:
        cfg["name"] = args.run_name
    name = cfg["name"]
    set_seed(cfg["seed"])
    device = "cuda" if torch.cuda.is_available() else "cpu"
    work = args.work_dir / name
    work.mkdir(parents=True, exist_ok=True)

    from transformers import AutoModelForTokenClassification, AutoTokenizer, get_linear_schedule_with_warmup

    tokenizer = AutoTokenizer.from_pretrained(cfg["model_name"])
    if not tokenizer.is_fast:
        raise ValueError("fast tokenizer required")

    t0 = time.time()
    train_docs, n_aug = load_train_docs(cfg, args.raw, args.manifests, args.eval_dir, args.challenge, args.limit_train)
    extra_docs, extra_info = load_extra_train(cfg)
    if args.limit_train:
        extra_docs = extra_docs[:args.limit_train]
    train_docs += extra_docs
    diagnostic = {name: load_documents(args.eval_dir / f"{name}.jsonl") for name in cfg["diagnostic_sets"]}
    val_docs = load_documents(args.eval_dir / "validation.jsonl")
    if args.limit_val:
        val_docs = val_docs[:args.limit_val]
    features = [f for d in train_docs for f in training_features(tokenizer, d, cfg["max_length"], cfg["window_overlap"])]
    supervised = sum(sum(l != IGNORE_INDEX for l in f["labels"]) for f in features)
    total = sum(len(f["labels"]) for f in features)
    print(f"train docs {len(train_docs)} (+{n_aug} augmented, +{len(extra_docs)} extra), windows {len(features)}, "
          f"supervised tokens {supervised}/{total} ({supervised / total:.1%}), prep {time.time() - t0:.0f}s", flush=True)

    model = AutoModelForTokenClassification.from_pretrained(
        cfg["model_name"], num_labels=len(LABEL2ID), id2label=ID2LABEL, label2id=LABEL2ID,
        ignore_mismatched_sizes=True)  # the classification head is always freshly initialised
    model.to(device).train()
    no_decay = ("bias", "LayerNorm.weight", "LayerNorm.bias", "layernorm", "norm.weight", "norm.bias")
    groups = [
        {"params": [p for n, p in model.named_parameters() if not any(k in n for k in no_decay)], "weight_decay": cfg["weight_decay"]},
        {"params": [p for n, p in model.named_parameters() if any(k in n for k in no_decay)], "weight_decay": 0.0},
    ]
    optimizer = torch.optim.AdamW(groups, lr=cfg["learning_rate"])
    steps_per_epoch = math.ceil(len(features) / cfg["batch_size"])
    total_steps = steps_per_epoch * cfg["epochs"]
    scheduler = get_linear_schedule_with_warmup(optimizer, int(cfg["warmup_ratio"] * total_steps), total_steps)
    use_amp = cfg["fp16"] and device == "cuda"
    scaler = torch.amp.GradScaler("cuda", enabled=use_amp)
    rng = random.Random(cfg["seed"])

    history, best = [], None
    step = skipped = 0
    for epoch in range(1, cfg["epochs"] + 1):
        running, t_epoch = 0.0, time.time()
        for b, idx in enumerate(batches(features, cfg["batch_size"], rng)):
            ids, mask, labels = collate([features[i] for i in idx], tokenizer.pad_token_id)
            with torch.autocast(device_type="cuda", dtype=torch.float16, enabled=use_amp):
                loss = model(input_ids=ids.to(device), attention_mask=mask.to(device), labels=labels.to(device)).loss
            if not torch.isfinite(loss):
                raise RuntimeError(f"non-finite loss at step {step}")
            scaler.scale(loss).backward()
            skipped += not optimizer_step(model, optimizer, scheduler, scaler)
            step += 1
            running += loss.item()
            if step % 200 == 0:
                print(f"epoch {epoch} step {step}/{total_steps} loss {running / (b + 1):.4f}", flush=True)
        ckpt = work / f"epoch-{epoch}"
        model.save_pretrained(ckpt)  # save before validating so an evaluation error cannot lose the epoch
        tokenizer.save_pretrained(ckpt)
        val = validate(model, tokenizer, val_docs, device)
        row = {"epoch": epoch, "step": step, "skipped_optimizer_steps": skipped,
               "lr": scheduler.get_last_lr()[0], "train_loss": running / steps_per_epoch,
               "epoch_seconds": round(time.time() - t_epoch), **val,
               "diagnostic": {name: {k: v for k, v in validate(model, tokenizer, docs, device).items() if k != "fp_breakdown"}
                              for name, docs in diagnostic.items()}}
        history.append(row)
        print(json.dumps(row), flush=True)
        if best is None or val[cfg["selection_metric"]] > best[1]:
            best = (ckpt, val[cfg["selection_metric"]])
        write_json(work / "history.json", history)

    # Reload the selected checkpoint from disk and verify it reproduces its validation score.
    del model
    torch.cuda.empty_cache()
    reloaded = TransformerDetector(best[0], device=device, batch_size=64)
    preds = dict(zip([d.doc_id for d in val_docs], reloaded.detect_batch([d.text for d in val_docs])))
    reload_f1 = evaluate(val_docs, preds)["entity"]["micro"]["f1"]
    reload_ok = abs(reload_f1 - best[1]) < 1e-3 if cfg["selection_metric"] == "entity_f1" else None
    print(f"best {best[0].name}: {cfg['selection_metric']}={best[1]:.4f}; reloaded entity_f1={reload_f1:.4f} ok={reload_ok}")
    if reload_ok is False:
        raise RuntimeError("Reloaded checkpoint does not reproduce its validation score")

    eval_manifest = args.eval_dir / "manifest.json"
    data_versions = {"raw_sha256": file_sha256(args.raw), "extra_train": extra_info,
                     "split_manifest_sha256": {n: file_sha256(args.manifests / f"{n}.ids") for n in ("train", "validation")},
                     "eval_manifest_sha256": file_sha256(eval_manifest) if eval_manifest.exists() else None,
                     "tokenizer": cfg["model_name"]}
    summary = {"config": cfg, "environment": environment_info(), "data_versions": data_versions, "n_train_docs": len(train_docs),
               "n_augmented": n_aug, "n_windows": len(features), "supervised_token_fraction": supervised / total,
               "skipped_optimizer_steps": skipped, "history": history, "best_checkpoint": best[0].name, "best_score": best[1],
               "reload_entity_f1": reload_f1, "reload_ok": reload_ok, "wall_seconds": round(time.time() - t0)}
    write_json(work / "training_summary.json", summary)
    write_json(best[0] / "training_summary.json", summary)
    if args.save_dir:
        dest = args.save_dir / name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(best[0], dest)
        shutil.copy(work / "history.json", dest / "history.json")
        print("saved best checkpoint to", dest)


if __name__ == "__main__":
    main()
