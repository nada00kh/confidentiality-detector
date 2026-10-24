from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def tiny_checkpoint(tmp_path_factory) -> Path:
    """A tiny BERT token classifier saved in the real checkpoint format, with the mBERT
    tokenizer. Its classifier bias favours "O", so model findings never appear on their own:
    decisions on it are driven by the deterministic rules, which makes CLI tests predictable."""
    transformers = pytest.importorskip("transformers")
    torch = pytest.importorskip("torch")
    from confidentiality_detector.labels import ID2LABEL, LABEL2ID

    try:
        tok = transformers.AutoTokenizer.from_pretrained("google-bert/bert-base-multilingual-cased")
    except Exception as exc:
        pytest.skip(f"tokenizer unavailable: {exc}")
    cfg = transformers.BertConfig(vocab_size=tok.vocab_size, hidden_size=32, num_hidden_layers=1, num_attention_heads=2,
                                  intermediate_size=64, max_position_embeddings=512, num_labels=len(LABEL2ID),
                                  id2label=ID2LABEL, label2id=LABEL2ID)
    model = transformers.BertForTokenClassification(cfg)
    with torch.no_grad():
        model.classifier.bias[LABEL2ID["O"]] = 20.0
    path = tmp_path_factory.mktemp("tiny_checkpoint")
    model.save_pretrained(path)
    tok.save_pretrained(path)
    return path
