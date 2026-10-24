import dataclasses
import re
from pathlib import Path

import pytest

from confidentiality_detector.documents import Span
from confidentiality_detector.labels import LABEL2ID
from confidentiality_detector.pipeline import ConfidentialityDetector
from confidentiality_detector.policy import PolicyConfig
from confidentiality_detector.postprocess import ipv4_addresses, ipv4_gate

ROOT = Path(__file__).resolve().parents[1]
POLICY = PolicyConfig.from_json(ROOT / "configs/inference/policy.json")


def spans_for(text, *pieces, label="IPV4"):
    out = []
    for piece in pieces:
        start = text.index(piece)
        out.append(Span(start, start + len(piece), label))
    return out


@pytest.mark.parametrize("text,piece", [
    ("ssh into 10.20.30.40 now", "10.20.30.40"),
    ("the host is 192.168.1.10.", "192.168.1.10"),            # sentence-final full stop
    ("connect to 10.0.0.5:8080 please", "10.0.0.5:8080"),     # model span includes the port
    ("server IP 172.16.0.9 is down", "IP 172.16.0.9"),        # model span starts too early
    ("firmware 2.4.1.7 is installed", "2.4.1.7"),             # a valid quad stays (ambiguous by policy)
])
def test_spans_overlapping_a_complete_address_are_kept(text, piece):
    spans = spans_for(text, piece)
    assert ipv4_gate(text, spans) == spans


@pytest.mark.parametrize("text,piece", [
    ("upgrade to release 4.12.0 tonight", ".12.0"),           # fragment of a version number
    ("build 10.4.1.2.7 failed", "4.1.2.7"),                    # inside a five-part version
    ("the value 300.1.1.1 is not an address", "300.1.1.1"),   # octet out of range
    ("ticket 9.9. was closed", "9.9."),
])
def test_ipv4_fragments_without_an_address_are_dropped(text, piece):
    assert ipv4_gate(text, spans_for(text, piece)) == []


def test_other_labels_are_never_touched():
    text = "card 4.12.0 and name 1.2"
    spans = spans_for(text, "4.12.0", label="CREDITCARDNUMBER") + spans_for(text, "1.2", label="PHONENUMBER")
    assert ipv4_gate(text, spans) == spans
    assert ipv4_addresses("a 1.2.3.4 b 5.6.7.8") == [(2, 9), (12, 19)]


class VersionAsIPModel:
    """Labels the fragment '.12.0' of '4.12.0' as IPV4 (the measured round-2 failure mode)."""

    def token_predictions(self, texts):
        out = []
        for t in texts:
            rows = []
            for m in re.finditer(r"\S+", t):
                if m.group() == "4.12.0":  # two tokens: '4' (O) and '.12.0' (IPV4)
                    rows.append((m.start(), m.start() + 1, 0.99, LABEL2ID["B-IPV4"], 0.01))
                    rows.append((m.start() + 1, m.end(), 0.02, LABEL2ID["B-IPV4"], 0.98))
                else:
                    rows.append((m.start(), m.end(), 0.99, LABEL2ID["B-EMAIL"], 0.01))
            out.append(rows)
        return out


def test_gate_is_off_by_default_and_integrates_with_rules():
    from confidentiality_detector.detectors.rules import RuleDetector

    assert POLICY.postprocessing == {"ipv4_requires_valid_address": False}
    gated = dataclasses.replace(POLICY, postprocessing={"ipv4_requires_valid_address": True})
    version = "Please upgrade the agent to 4.12.0 tonight."
    assert ConfidentialityDetector(VersionAsIPModel(), RuleDetector(), POLICY).inspect(version).blocked
    assert not ConfidentialityDetector(VersionAsIPModel(), RuleDetector(), gated).inspect(version).blocked
    # rule findings are never removed by the gate
    host = "Please upgrade the agent to 4.12.0 tonight on 10.20.30.40"
    d = ConfidentialityDetector(VersionAsIPModel(), RuleDetector(), gated).inspect(host)
    assert d.blocked and [(f.label, f.source) for f in d.findings] == [("IPV4", "rules")]


def test_unknown_or_non_boolean_postprocessing_settings_are_rejected():
    with pytest.raises(ValueError):
        dataclasses.replace(POLICY, postprocessing={"iban_requires_checksum": True})
    with pytest.raises(ValueError):
        dataclasses.replace(POLICY, postprocessing={"ipv4_requires_valid_address": "yes"})
