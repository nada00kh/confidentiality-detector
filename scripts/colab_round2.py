"""Round 2 experiment specification (driven by notebooks/colab/06_round2_experiments.ipynb).

Stage order follows the one-factor-at-a-time design (docs/METHODOLOGY.md):
  R0  existing E2 checkpoint (round 1), predictions on the v3 evaluation suite (no training)
  R1  r2_e2_v3        E2 recipe + v3 annotation policy (CVV evidence)        parent: E2
  R2  r2_e3a_hardneg  R1 + hard-negative synthetic documents (experiment A)  parent: R1
  R3  r2_e3b_positive R1 + difficult-positive synthetic documents (exp. B)   parent: R1
  R4  r2_e4_combined  R1 + A + B                                             parent: R1
"""

from colab_runner import (  # noqa: F401  (re-exported for the notebook)
    Context, RoundSpec, StageError, StageSpec, check_environment, install_dependencies, package, run_stage,
    run_tests, stage_status, verify_bundle,
)

BUNDLE_VERSION = "round2-r1"

ROUND2 = RoundSpec(
    name="round2",
    bundle_version=BUNDLE_VERSION,
    eval_dir="data/eval_v3",
    stages=(
        StageSpec("R0", "e2_mbert_v2_fmtA", "baseline: existing E2 checkpoint on the v3 evaluation suite", model="e2"),
        StageSpec("R1", "r2_e2_v3", "E2 recipe + v3 annotation policy", config="configs/experiments/r2_e2_v3.json"),
        StageSpec("R2", "r2_e3a_hardneg", "experiment A: + hard negatives", config="configs/experiments/r2_e3a_hardneg.json"),
        StageSpec("R3", "r2_e3b_positive", "experiment B: + difficult positives", config="configs/experiments/r2_e3b_positive.json"),
        StageSpec("R4", "r2_e4_combined", "A + B combined", config="configs/experiments/r2_e4_combined.json"),
    ),
    smoke_config="configs/experiments/smoke_tiny_r2.json",
    smoke_sets=("validation", "dev_v1", "synth_A_heldout", "challenge_v1_policy"),
)
