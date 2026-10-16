from evaluation.metrics import evaluate


def test_evaluation_with_synthetic_data():
    text = "بريدي test@example.com"

    start = text.index("test@example.com")
    end = start + len("test@example.com")

    samples = [
        {
            "text": text,
            "entities": [
                {
                    "label": "private_email",
                    "start": start,
                    "end": end
                }
            ]
        },
        {
            "text": "السلام عليكم",
            "entities": []
        }
    ]

    results = evaluate(samples)

    assert results["samples"] == 2
    assert results["entity_micro"]["f1"] == 1.0
    assert results["message"]["accuracy"] == 1.0

def test_false_positive_is_counted():
    samples = [
        {
            "text": "رقم الطلب 1234567890",
            "entities": []
        }
    ]

    results = evaluate(samples)

    assert results["message"]["FP"] == 1
    assert results["message"]["accuracy"] == 0.0