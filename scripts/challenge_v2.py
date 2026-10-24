"""Tooling for the independently written, hidden challenge_v2 set (docs/CHALLENGE_V2_SPEC.md).

The developers must never see the cases. Every command therefore prints aggregates only:
no case text, no values. Case-level output (ids, categories, error types, never text) is
written only to the author's own folder, and only when --case-details is passed.

  python scripts/challenge_v2.py validate  <file>        # author: format + policy checks
  python scripts/challenge_v2.py seal      <file>        # author: freeze (sha256 -> reports/challenge_v2/SEAL.json)
  python scripts/challenge_v2.py contamination <file>    # similarity to all training data (aggregates)
  python scripts/challenge_v2.py freeze --model-dir <ckpt> --verify-pred-dir <dir> --evidence <json>   # developers
  python scripts/challenge_v2.py verify-frozen --model-dir <ckpt>       # re-check the frozen system (no challenge data)
  python scripts/challenge_v2.py evaluate  <file> --model-dir <ckpt> [--mode strict]

Freezing refuses uncommitted changes to tracked files, a checkpoint that does not reproduce its
archived predictions, and a live system whose BLOCK/ALLOW decisions differ from the documented
evidence. The frozen identity (configs/inference/frozen_system.json) covers every checkpoint file
(weights, config, tokenizer), the policy file, the inference code (including the rules), the
inference windows, the runtime library versions and the git commit.

Safeguards: evaluation refuses unsealed or modified files, and refuses a system that does not
match configs/inference/frozen_system.json; every evaluation is appended to reports/challenge_v2/LEDGER.jsonl (system fingerprints, mode,
time, a fingerprint of the predictions) so repeated evaluation is visible; the Colab bundle
builder refuses to package anything named challenge_v2; data/challenge_v2/ is git-ignored.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import importlib.metadata
import platform
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from confidentiality_detector.challenge import load_challenge  # noqa: E402
from confidentiality_detector.documents import Span, file_sha256, load_documents  # noqa: E402
from confidentiality_detector.labels import TARGET_LABELS, cvv_has_evidence  # noqa: E402
from confidentiality_detector.metrics import evaluate_by_tag, evaluate_documents, evaluate_entities  # noqa: E402

STATE = ROOT / "reports/challenge_v2"
FROZEN = ROOT / "configs/inference/frozen_system.json"
# Everything that turns a prompt into a decision. Hashes of these files are part of the frozen identity.
INFERENCE_CODE = ("__init__.py", "__main__.py", "alignment.py", "decoding.py", "documents.py", "labels.py",
                  "pipeline.py", "policy.py", "detectors/__init__.py", "detectors/hybrid.py", "detectors/rules.py",
                  "detectors/transformer.py")
RUNTIME_PACKAGES = ("torch", "transformers", "tokenizers", "safetensors", "numpy", "phonenumbers")
IDENTITY_KEYS = ("model_sha256", "checkpoint_files_sha256", "policy_sha256", "rules_version", "code_sha256",
                 "max_length", "overlap", "stitching", "runtime")
MIN_CASES = {"BLOCK": 100, "ALLOW": 100}
RECOMMENDED_TAGS = ("enterprise", "lookalike", "structured", "difficult-positive", "unfamiliar-format", "long", "oos-secret")
# Decision F: API keys, tokens and similar credentials are outside the 13 categories. They must be
# annotated as look-alikes ([[!APIKEY:...]]), never as ignored spans, so that a detector that calls
# them PASSWORD is charged a false positive (and a False BLOCK on an otherwise clean document).
OOS_CREDENTIAL_TYPES = {"SECRET", "APIKEY", "API_KEY", "TOKEN", "ACCESSTOKEN", "ACCESS_TOKEN", "BEARER", "JWT",
                        "PRIVATEKEY", "PRIVATE_KEY", "SSHKEY", "CLIENTSECRET", "CLIENT_SECRET", "WEBHOOK"}
LENGTH_BUCKETS = ((0, 1000, "<=1000 chars"), (1000, 3000, "1001-3000 chars"), (3000, None, ">3000 chars"))


def validate(path: Path) -> dict:
    """Parse and check a case file. Errors make the file unusable; warnings need the author's review."""
    errors, warnings = [], []
    try:
        docs = load_challenge(path)
    except ValueError as exc:
        return {"ok": False, "errors": [str(exc)], "warnings": [], "n_cases": 0}
    from confidentiality_detector.detectors.rules import iban_valid, luhn_valid

    if not docs:
        errors.append("the file contains no cases (expected '@@ <id> | <tags> | <decision>' headers)")
    for d in docs:
        if "expected" not in d.meta:
            errors.append(f"{d.doc_id}: missing document decision (| BLOCK, | ALLOW or | AMBIGUOUS in the header)")
        cards = [(s.start, s.end) for s in d.spans if s.label == "CREDITCARDNUMBER"]
        for s in d.ignore_spans:
            if s.label in OOS_CREDENTIAL_TYPES:
                errors.append(f"{d.doc_id}: ~{s.label} hides an out-of-scope credential from scoring; "
                              f"annotate it as [[!{s.label}:...]] (decision F)")
        for s in d.spans:
            value = d.text[s.start:s.end]
            if value != value.strip() or not value:
                errors.append(f"{d.doc_id}: {s.label} span has leading/trailing whitespace")
            if s.label == "CREDITCARDCVV" and not cvv_has_evidence(d.text, s.start, s.end, cards):
                warnings.append(f"{d.doc_id}: CVV without contextual evidence (policy: mark ~AMBIG or add context)")
            if s.label == "IBAN" and not iban_valid(value):
                warnings.append(f"{d.doc_id}: IBAN fails the mod-97 checksum (intended?)")
            if s.label == "CREDITCARDNUMBER" and not luhn_valid(re.sub(r"\D", "", value)):
                warnings.append(f"{d.doc_id}: card number fails the Luhn check (intended?)")
        if not d.meta.get("tags"):
            warnings.append(f"{d.doc_id}: no tags")
    decisions = Counter(d.gold_decision() for d in docs)
    for decision, minimum in MIN_CASES.items():
        if decisions.get(decision, 0) < minimum:
            warnings.append(f"only {decisions.get(decision, 0)} {decision} cases (spec recommends >= {minimum})")
    tags = Counter(t for d in docs for t in d.meta.get("tags", []))
    for t in RECOMMENDED_TAGS:
        if not tags.get(t):
            warnings.append(f"no case tagged '{t}' (spec coverage requirement)")
    return {"ok": not errors, "errors": errors, "warnings": warnings, "n_cases": len(docs), "sha256": file_sha256(path),
            "decisions": dict(decisions), "labels": dict(Counter(s.label for d in docs for s in d.spans)),
            "tags": dict(tags)}


def seal(path: Path) -> dict:
    report = validate(path)
    if not report["ok"]:
        raise SystemExit("cannot seal: validation errors:\n" + "\n".join(report["errors"][:20]))
    STATE.mkdir(parents=True, exist_ok=True)
    record = {"file_name": Path(path).name, "sha256": report["sha256"], "sealed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
              "n_cases": report["n_cases"], "decisions": report["decisions"], "labels": report["labels"]}
    (STATE / "SEAL.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def check_sealed(path: Path) -> dict:
    seal_file = STATE / "SEAL.json"
    if not seal_file.exists():
        raise SystemExit("challenge_v2 is not sealed: the author must run `challenge_v2.py seal <file>` first")
    record = json.loads(seal_file.read_text(encoding="utf-8"))
    if file_sha256(path) != record["sha256"]:
        raise SystemExit("this file does not match the sealed challenge_v2 (sha256 differs); refusing to evaluate")
    return record


def score(docs, findings_per_doc: dict[str, list[Span]], decisions: dict[str, bool]) -> dict:
    """Aggregate metrics. Document metrics use the system's BLOCK/ALLOW decision, which can differ
    from 'any finding' (e.g. fail-closed decisions)."""
    block_preds = {doc_id: ([Span(0, 1, "BLOCK")] if blocked else []) for doc_id, blocked in decisions.items()}
    entity = evaluate_entities(docs, findings_per_doc, max_examples=0)
    document = evaluate_documents(docs, block_preds)
    document.pop("false_allow_doc_ids", None)
    document.pop("false_block_doc_ids", None)
    by_tag = evaluate_by_tag(docs, block_preds)
    all_found = sum(1 for d in docs if d.spans and all(any(f.overlaps(s) for f in findings_per_doc.get(d.doc_id, [])) for s in d.spans))
    n_block = sum(1 for d in docs if d.spans)
    by_length = {}
    for lo, hi, name in LENGTH_BUCKETS:
        subset = [d for d in docs if len(d.text) > lo and (hi is None or len(d.text) <= hi)]
        if subset:
            r = evaluate_documents(subset, block_preds)
            by_length[name] = {"n_docs": r["n_docs"], "block_docs": r["n_block_docs"], "allow_docs": r["n_allow_docs"],
                               "false_allow": r["confusion"]["FN_false_allow"], "false_block": r["confusion"]["FP_false_block"]}
    return {"document": document, "entity_micro": entity["micro"], "entity_per_class": entity["per_class"],
            "fn_breakdown": entity["fn_breakdown"], "fp_breakdown": entity["fp_breakdown"],
            "block_docs_with_every_entity_caught": all_found / n_block if n_block else None,
            "by_tag": {t: {k: r[k] for k in ("n_docs", "block_docs", "allow_docs", "false_allow", "false_block")}
                       for t, r in by_tag.items()},
            "by_length": by_length}


def findings_fingerprint(findings_per_doc: dict[str, list[Span]], decisions: dict[str, bool]) -> str:
    """sha256 over ids, decisions, positions and labels (no text): identical system + data must
    reproduce it, so a re-run can be checked without exposing anything."""
    canon = [[doc_id, decisions[doc_id], sorted([s.start, s.end, s.label] for s in findings_per_doc.get(doc_id, []))]
             for doc_id in sorted(decisions)]
    return hashlib.sha256(json.dumps(canon, separators=(",", ":")).encode()).hexdigest()


def system_fingerprint(model_dir: Path, policy_path: Path) -> dict:
    """The identity of a deployable system: every file that determines a decision, plus the runtime."""
    from confidentiality_detector.detectors.rules import RULES_VERSION
    from confidentiality_detector.policy import PolicyConfig

    files = sorted(p for p in Path(model_dir).iterdir() if p.is_file())
    weights = [p for p in files if p.suffix == ".safetensors"]
    if not weights:
        raise SystemExit(f"{model_dir}: no .safetensors weights")
    policy = PolicyConfig.from_json(policy_path)  # what ConfidentialityDetector.load uses
    package = ROOT / "src/confidentiality_detector"
    runtime = {"python": platform.python_version()}
    for name in RUNTIME_PACKAGES:
        try:
            runtime[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            runtime[name] = None
    return {"model_dir": Path(model_dir).name,
            "model_sha256": {p.name: file_sha256(p) for p in weights},
            "checkpoint_files_sha256": {p.name: file_sha256(p) for p in files if p.suffix != ".safetensors"},
            "policy_sha256": file_sha256(policy_path), "rules_version": RULES_VERSION,
            "code_sha256": {rel: file_sha256(package / rel) for rel in INFERENCE_CODE},
            **policy.inference, "runtime": runtime}


def git_state() -> dict:
    def git(*args: str) -> str:
        return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=True).stdout.strip()

    try:
        return {"commit": git("rev-parse", "HEAD"),
                "uncommitted_changes": bool(git("status", "--porcelain", "--untracked-files=no"))}
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "uncommitted_changes": None}


def behaviour(model_dir: Path, policy_path: Path, sets: list[str], eval_dir: Path) -> dict:
    """Run the live system (real checkpoint, rules, policy) in both modes; record decisions only."""
    from confidentiality_detector.pipeline import ConfidentialityDetector

    detector = ConfidentialityDetector.load(model_dir, policy_path)
    out = {}
    for s in sets:
        docs = load_documents(eval_dir / f"{s}.jsonl")
        for mode in ("strict", "maximum"):
            results = detector.inspect_batch([d.text for d in docs], mode)
            findings = {d.doc_id: [Span(f.start, f.end, f.label) for f in r.findings] for d, r in zip(docs, results)}
            decisions = {d.doc_id: r.blocked for d, r in zip(docs, results)}
            m = evaluate_documents(docs, {k: [Span(0, 1, "BLOCK")] if v else [] for k, v in decisions.items()})
            out[f"{s}/{mode}"] = {"n_docs": len(docs), "FA": m["confusion"]["FN_false_allow"],
                                  "FB": m["confusion"]["FP_false_block"],
                                  "false_allow_ids": m["false_allow_doc_ids"], "false_block_ids": m["false_block_doc_ids"],
                                  "decisions_sha256": findings_fingerprint(findings, decisions)}
    return out


def compare_with_evidence(observed: dict, evidence_path: Path, run: str) -> list[str]:
    """Differences between the live system and the documented results (scripts/evaluate_system.py --detail)."""
    evidence = json.loads(Path(evidence_path).read_text(encoding="utf-8"))["sets"]
    problems = []
    for key, obs in observed.items():
        s, mode = key.split("/")
        documented = evidence.get(s, {}).get("runs", {}).get(run, {}).get(f"system_{mode}")
        if documented is None:
            problems.append(f"{key}: not in {Path(evidence_path).name}")
            continue
        for k in ("FA", "FB", "false_allow_ids", "false_block_ids"):
            if obs[k] != documented[k]:
                problems.append(f"{key}: {k} differs from the evidence")
    return problems


def freeze(model_dir: Path, policy_path: Path, verify_pred_dir: Path | None, verify_sets: list[str], eval_dir: Path,
           evidence: Path | None = None, evidence_run: str = "R3", require_clean: bool = True) -> dict:
    """Developers: record the system that will face challenge_v2, refusing anything unverified.

    1. No uncommitted changes to tracked files, so the git commit identifies the code.
    2. With --verify-pred-dir: the local checkpoint reproduces the stored predictions it was selected
       on (scripts/verify_checkpoint.py, under the evaluated 512/64/"first" windows).
    3. With --evidence: the live full system (both modes) makes exactly the documented BLOCK/ALLOW
       decisions on the verification sets."""
    git = git_state()
    if require_clean and (git["commit"] is None or git["uncommitted_changes"]):
        raise SystemExit("refusing to freeze: commit all changes to tracked files first (the freeze records the git commit)")
    record = system_fingerprint(model_dir, policy_path)
    record["git"] = git
    if verify_pred_dir is not None:
        from verify_checkpoint import verify

        report = verify(model_dir, verify_pred_dir, verify_sets, eval_dir)
        if report["problems"]:
            raise SystemExit("refusing to freeze: " + "; ".join(report["problems"]))
        record["verified_against"] = {"pred_dir": Path(verify_pred_dir).name,
                                      "sets": {s: {"n_docs": r["n_docs"], "documents_differing": 0,
                                                   "max_abs_diff_p_not_O": r["max_abs_diff_p_not_O"]}
                                               for s, r in report["sets"].items()}}
    if evidence is not None:
        observed = behaviour(model_dir, policy_path, verify_sets, eval_dir)
        problems = compare_with_evidence(observed, evidence, evidence_run)
        if problems:
            raise SystemExit("refusing to freeze: " + "; ".join(problems))
        record["behaviour"] = {"matches": f"{Path(evidence).name} (run {evidence_run}, sha256 {file_sha256(evidence)[:16]})",
                               **{k: {m: v[m] for m in ("n_docs", "FA", "FB", "decisions_sha256")} for k, v in observed.items()}}
    record["frozen_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    FROZEN.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def check_frozen(model_dir: Path, policy_path: Path) -> dict:
    if not FROZEN.exists():
        raise SystemExit("no frozen system: run `challenge_v2.py freeze --model-dir <ckpt>` before the hidden evaluation")
    frozen = json.loads(FROZEN.read_text(encoding="utf-8"))
    actual = system_fingerprint(model_dir, policy_path)
    diffs = [k for k in IDENTITY_KEYS if frozen.get(k) != actual[k]]
    if diffs:
        raise SystemExit(f"this system does not match the frozen system ({', '.join(diffs)} differ); refusing to evaluate")
    return frozen


def verify_frozen(model_dir: Path, policy_path: Path, eval_dir: Path) -> dict:
    """Identity check plus a re-run of the recorded behaviour; touches no challenge_v2 data."""
    frozen = check_frozen(model_dir, policy_path)
    recorded = {k: v for k, v in frozen.get("behaviour", {}).items() if k != "matches"}
    if not recorded:
        raise SystemExit("the frozen record has no behaviour fingerprint; freeze with --evidence")
    observed = behaviour(model_dir, policy_path, sorted({k.split("/")[0] for k in recorded}), eval_dir)
    differing = [k for k in recorded if observed[k]["decisions_sha256"] != recorded[k]["decisions_sha256"]]
    if differing:
        raise SystemExit(f"decisions differ from the frozen record on {differing}")
    return {"identity": "matches the frozen record", "behaviour": {k: "identical decisions and findings" for k in recorded},
            "frozen_at": frozen["frozen_at"], "git_commit": frozen["git"]["commit"]}


def case_details(docs, findings_per_doc, decisions) -> list[dict]:
    """Per case: id, tags, gold and predicted decision, missed/extra labels. Never text or values."""
    rows = []
    for d in docs:
        found = findings_per_doc.get(d.doc_id, [])
        rows.append({"id": d.doc_id, "tags": d.meta.get("tags"), "gold": d.gold_decision(),
                     "predicted": "BLOCK" if decisions[d.doc_id] else "ALLOW",
                     "missed": [s.label for s in d.spans if not any(f.overlaps(s) for f in found)],
                     "extra": [f.label for f in found if not any(f.overlaps(s) for s in d.spans + d.ignore_spans)]})
    return rows


def run_detector(docs, model_dir: Path, policy_path: Path, mode: str | None):
    from confidentiality_detector.pipeline import ConfidentialityDetector

    detector = ConfidentialityDetector.load(model_dir, policy_path)
    results = detector.inspect_batch([d.text for d in docs], mode)
    findings = {d.doc_id: [Span(f.start, f.end, f.label, f.score) for f in r.findings] for d, r in zip(docs, results)}
    decisions = {d.doc_id: r.blocked for d, r in zip(docs, results)}
    return findings, decisions, detector


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("freeze")
    p.add_argument("--model-dir", type=Path, required=True)
    p.add_argument("--policy", type=Path, default=ROOT / "configs/inference/policy.json")
    p.add_argument("--verify-pred-dir", type=Path, default=None, help="stored predictions of this checkpoint")
    p.add_argument("--verify-sets", nargs="+", default=["dev_v1", "test_long"])
    p.add_argument("--evidence", type=Path, default=None, help="documented results (scripts/evaluate_system.py --detail)")
    p.add_argument("--evidence-run", default="R3")
    p.add_argument("--eval-dir", type=Path, default=ROOT / "data/eval_v3")
    p = sub.add_parser("verify-frozen")
    p.add_argument("--model-dir", type=Path, required=True)
    p.add_argument("--policy", type=Path, default=ROOT / "configs/inference/policy.json")
    p.add_argument("--eval-dir", type=Path, default=ROOT / "data/eval_v3")
    for name in ("validate", "seal", "contamination", "evaluate"):
        p = sub.add_parser(name)
        p.add_argument("file", type=Path)
        if name == "evaluate":
            p.add_argument("--model-dir", type=Path, required=True)
            p.add_argument("--policy", type=Path, default=ROOT / "configs/inference/policy.json")
            p.add_argument("--mode", default=None)
            p.add_argument("--case-details", type=Path, default=None,
                           help="author only: write per-case outcomes (ids/labels, no text) to this file")
    args = ap.parse_args()

    if args.cmd == "freeze":
        print(json.dumps(freeze(args.model_dir, args.policy, args.verify_pred_dir, args.verify_sets, args.eval_dir,
                                args.evidence, args.evidence_run), indent=2))
        return
    if args.cmd == "verify-frozen":
        print(json.dumps(verify_frozen(args.model_dir, args.policy, args.eval_dir), indent=2))
        return
    if args.cmd == "validate":
        r = validate(args.file)
        print(json.dumps({k: v for k, v in r.items() if k not in ("errors", "warnings")}, indent=2))
        print(f"{len(r['errors'])} error(s), {len(r['warnings'])} warning(s)")
        for line in r["errors"][:50] + r["warnings"][:50]:
            print("  -", line)  # case ids and categories only
        sys.exit(0 if r["ok"] else 1)
    if args.cmd == "seal":
        print(json.dumps(seal(args.file), indent=2))
        return
    record = check_sealed(args.file)
    docs = load_challenge(args.file)
    if args.cmd == "contamination":
        from contamination import max_similarity_to_training

        sims = max_similarity_to_training([d.text for d in docs])
        print(json.dumps({"n_cases": len(docs), "median_max_cosine": float(sorted(sims)[len(sims) // 2]),
                          "share_ge_0.5": sum(s >= 0.5 for s in sims) / len(sims),
                          "share_ge_0.8": sum(s >= 0.8 for s in sims) / len(sims), "max": max(sims)}, indent=2))
        return
    frozen = check_frozen(args.model_dir, args.policy)
    findings, decisions, detector = run_detector(docs, args.model_dir, args.policy, args.mode)
    result = score(docs, findings, decisions)
    mode = detector.policy.mode(args.mode).name
    entry = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "challenge_sha256": record["sha256"],
             **{k: frozen[k] for k in ("model_dir", *IDENTITY_KEYS)}, "git_commit": frozen.get("git", {}).get("commit"),
             "frozen_at": frozen.get("frozen_at"), "mode": mode, "predictions_sha256": findings_fingerprint(findings, decisions),
             "far": result["document"]["false_allow_rate"], "fbr": result["document"]["false_block_rate"]}
    STATE.mkdir(parents=True, exist_ok=True)
    ledger = STATE / "LEDGER.jsonl"
    previous = ledger.read_text(encoding="utf-8").count("\n") if ledger.exists() else 0
    with open(ledger, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
    out = STATE / f"result_{args.model_dir.name}_{mode}.json"
    out.write_text(json.dumps({"ledger_entry": entry, **result}, indent=2), encoding="utf-8")
    if args.case_details:
        args.case_details.write_text(json.dumps(case_details(docs, findings, decisions), indent=2), encoding="utf-8")
    d = result["document"]

    def rate(value, ci):
        return "n/a" if value is None else f"{value:.3f} {tuple(round(x, 3) for x in ci)}"

    print(f"challenge_v2 ({record['n_cases']} cases) model={args.model_dir.name} mode={mode}: "
          f"FAR {rate(d['false_allow_rate'], d['false_allow_rate_ci95'])}  "
          f"FBR {rate(d['false_block_rate'], d['false_block_rate_ci95'])}  -> {out}")
    if previous:
        print(f"NOTE: this challenge_v2 has now been evaluated {previous + 1} times (see {ledger}). "
              "Repeated evaluation while changing the system turns it into a development set.")


if __name__ == "__main__":
    main()
