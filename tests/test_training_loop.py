import sys
import warnings
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import train  # noqa: E402


def _setup():
    torch.manual_seed(0)
    model = torch.nn.Linear(4, 1)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)
    scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, lambda step: 1.0 - step / 10)
    scaler = torch.amp.GradScaler("cpu", enabled=True)
    return model, optimizer, scheduler, scaler


def test_scheduler_does_not_advance_when_amp_skips_the_optimizer_step():
    """Reproduces the round-2 warning: an overflowing first step is skipped by GradScaler; the
    scheduler must not advance for it (it did before the fix)."""
    model, optimizer, scheduler, scaler = _setup()
    weights_before = model.weight.detach().clone()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        overflow = model(torch.full((2, 4), float("inf"))).sum()
        scaler.scale(overflow).backward()
        assert train.optimizer_step(model, optimizer, scheduler, scaler) is False
        assert scheduler.last_epoch == 0 and torch.equal(model.weight, weights_before)

        loss = model(torch.ones(2, 4)).sum()
        scaler.scale(loss).backward()
        assert train.optimizer_step(model, optimizer, scheduler, scaler) is True
        assert scheduler.last_epoch == 1 and not torch.equal(model.weight, weights_before)
    assert not [w for w in caught if "lr_scheduler.step()" in str(w.message)]


def test_without_amp_every_step_counts():
    model, optimizer, scheduler, _ = _setup()
    scaler = torch.amp.GradScaler("cpu", enabled=False)
    for _ in range(3):
        scaler.scale(model(torch.ones(2, 4)).sum()).backward()
        assert train.optimizer_step(model, optimizer, scheduler, scaler)
    assert scheduler.last_epoch == 3
