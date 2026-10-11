"""Return counts and null for missing evidence, rather than fabricated success."""


def ratio(numerator, denominator):
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": numerator / denominator if denominator else None,
    }


def edit_distance(reference, hypothesis):
    row = list(range(len(hypothesis) + 1))
    for i, left in enumerate(reference, 1):
        new = [i]
        for j, right in enumerate(hypothesis, 1):
            new.append(min(new[-1] + 1, row[j] + 1, row[j - 1] + (left != right)))
        row = new
    return row[-1]


def speech_metrics(reference, hypothesis, entities):
    return {
        "wer": ratio(
            edit_distance(reference.split(), hypothesis.split()), len(reference.split())
        ),
        "cer": ratio(edit_distance(reference, hypothesis), len(reference)),
        "entity_accuracy": ratio(
            sum(entity in hypothesis for entity in entities), len(entities)
        ),
    }


def percentile(values, p=0.95):
    import math

    return sorted(values)[max(0, math.ceil(len(values) * p) - 1)] if values else None
