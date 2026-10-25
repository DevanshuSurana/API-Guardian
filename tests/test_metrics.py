from mlops.metrics import detection_metrics, patch_metrics


def test_detection_metrics():
    result = detection_metrics([True, True, False, False], [True, False, True, False])
    assert result["true_positives"] == 1
    assert result["false_positives"] == 1
    assert result["false_negatives"] == 1
    assert result["precision"] == 0.5
    assert result["recall"] == 0.5
    assert result["f1"] == 0.5

def test_patch_metrics():
    result = patch_metrics([
        {"patch_generated": True, "tests_passed": True, "regression_detected": False},
        {"patch_generated": True, "tests_passed": False, "regression_detected": True},
    ])
    assert result["patch_success_rate"] == 0.5
    assert result["patch_generation_rate"] == 1.0
    assert result["regression_rate"] == 0.5
