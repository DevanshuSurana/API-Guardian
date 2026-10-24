"""Metrics for API Guardian detection and migration evaluation."""
from __future__ import annotations
from typing import Iterable

def detection_metrics(y_true: Iterable[bool], y_pred: Iterable[bool]) -> dict[str, float | int]:
    true = list(y_true)
    pred = list(y_pred)
    if len(true) != len(pred):
        raise ValueError("y_true and y_pred must have the same length")
    tp = sum(t and p for t, p in zip(true, pred))
    fp = sum((not t) and p for t, p in zip(true, pred))
    fn = sum(t and (not p) for t, p in zip(true, pred))
    tn = sum((not t) and (not p) for t, p in zip(true, pred))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    accuracy = (tp + tn) / len(true) if true else 0.0
    return {
        "true_positives": tp, "false_positives": fp,
        "false_negatives": fn, "true_negatives": tn,
        "precision": precision, "recall": recall,
        "f1": f1, "accuracy": accuracy, "cases": len(true),
    }

def patch_metrics(patch_results: Iterable[dict]) -> dict[str, float | int]:
    rows = list(patch_results)
    total = len(rows)
    passed = sum(bool(row.get("tests_passed", False)) for row in rows)
    attempted = sum(bool(row.get("patch_generated", False)) for row in rows)
    regressions = sum(bool(row.get("regression_detected", False)) for row in rows)
    return {
        "patch_cases": total,
        "patches_generated": attempted,
        "patches_passing": passed,
        "patch_success_rate": passed / total if total else 0.0,
        "patch_generation_rate": attempted / total if total else 0.0,
        "regression_cases": regressions,
        "regression_rate": regressions / total if total else 0.0,
    }
