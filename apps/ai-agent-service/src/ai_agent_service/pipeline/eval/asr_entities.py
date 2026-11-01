"""Explicitly reviewed (or clearly provisional) entity labels, separate from ASR decoding."""
from __future__ import annotations

from collections import Counter
import math
import re
import unicodedata
from .asr import _read, _sha, normalize
from ...components.intake.entities import measurement_entities, EXTRACTOR_VERSION


def clinical(text: str, vocabulary: list[dict]) -> list[dict]:
    """Closed-vocabulary exact mention matching, not an open medical NER model."""
    plain = normalize(text)
    candidates = []
    for item in vocabulary:
        for alias in item.get('aliases', [item['canonical']]):
            phrase = normalize(alias)
            if not phrase:
                continue
            for match in re.finditer(r'(?<!\w)' + re.escape(phrase) + r'(?!\w)', plain):
                candidates.append({'type': item['type'], 'value': item['canonical'], 'start': match.start(),
                                   'end': match.end(), 'evidence': match.group()})
    selected = []
    for item in sorted(candidates, key=lambda x: (-(x['end']-x['start']), x['start'])):
        if not any(item['start'] < other['end'] and other['start'] < item['end'] for other in selected):
            selected.append(item)
    return sorted(selected, key=lambda x: x['start'])


def predict(text: str, vocabulary: list[dict], *, version: str | None = None) -> dict:
    result = measurement_entities(text, ranges=not (version or '').startswith('asr-entities-v1+'))
    counts = Counter()
    for item in clinical(text, vocabulary):
        counts[item['type']] += 1
        result[f"{item['type']}_{counts[item['type']]}"] = item['value']
    return result


def labels(path, selected: list[dict]) -> tuple[list[dict], dict, list[dict]]:
    document = _read(path)
    if not isinstance(document, dict) or document.get('schema_version') != 1:
        raise ValueError('Entity review requires schema_version=1')
    vocabulary = document.get('vocabulary', [])
    if not isinstance(vocabulary, list) or any(not isinstance(item, dict) or not isinstance(item.get('canonical'), str)
                                               or not item['canonical'].strip() or not isinstance(item.get('type'), str)
                                               or not item['type'].strip() or ('aliases' in item and (
                                                   not isinstance(item['aliases'], list) or any(
                                                       not isinstance(alias, str) or not alias.strip() for alias in item['aliases'])))
                                               for item in vocabulary):
        raise ValueError('Invalid entity vocabulary')
    records = document.get('records')
    if not isinstance(records, dict):
        raise ValueError('Entity review requires records keyed by sample ID')
    approved = document.get('status') == 'approved' and bool(document.get('reviewer'))
    if document.get('status') == 'approved' and (
            not isinstance(document.get('reviewer'), str) or not document['reviewer'].strip()
            or not isinstance(document.get('source'), (str, dict)) or not document['source']):
        raise ValueError('Approved entity labels require a named reviewer and source provenance')
    version = document.get('extractor_version', EXTRACTOR_VERSION + '+closed-clinical-v1')
    if version not in {'asr-entities-v1+closed-clinical-v1', 'asr-entities-v2+closed-clinical-v1'}:
        raise ValueError('Unsupported entity extractor version; replay with a declared implementation')
    result, n = [], 0
    for row in selected:
        review = records.get(row['id'])
        if not isinstance(review, dict):
            raise ValueError(f"Entity reference missing for {row['id']}")
        if not isinstance(review.get('reference_text'), str) or unicodedata.normalize('NFC', row['full_text']) != unicodedata.normalize('NFC', review['reference_text']):
            raise ValueError(f"Entity review reference mismatch: {row['id']}")
        entities = review.get('entities')
        if not isinstance(entities, dict) or any(not isinstance(k, str) or not isinstance(v, (str, int, float, bool))
                                               or (isinstance(v, float) and not math.isfinite(v))
                                               for k, v in entities.items()):
            raise ValueError('Canonical entity values must be scalars, not lists accepting any value')
        n += len(entities)
        result.append({**row, 'entities': entities})
    info = {'status': 'APPROVED' if approved else 'PENDING_HUMAN_REVIEW', 'reviewer': document.get('reviewer'),
            'sha256': _sha(path), 'extractor_version': version,
            'reference_entities': n, 'reference_samples': len(result), 'source': document.get('source'),
            'note': 'Main exact-match formula; provisional if labels unapproved. Clinical matcher uses a declared closed vocabulary, not independent medical NER. No reference or vocabulary is supplied to ASR or used to fix its text.'}
    return result, info, vocabulary


def diagnostics(records: list[dict], hypotheses: dict) -> dict:
    groups, errors = {}, []
    for row in records:
        expected = row.get('entities', {})
        actual = hypotheses.get(row['id'], {}).get('entities', {})
        for key, value in expected.items():
            kind = key.rsplit('_', 1)[0]
            bucket = groups.setdefault(kind, {'correct': 0, 'expected': 0, 'predicted': 0, 'matched_values': 0})
            bucket['expected'] += 1
            bucket['correct'] += int(str(actual.get(key)) == str(value))
            if str(actual.get(key)) != str(value):
                errors.append({'id': row['id'], 'key': key, 'expected': value, 'actual': actual.get(key),
                               'error': 'missing' if key not in actual else 'value_mismatch'})
        kinds = {key.rsplit('_', 1)[0] for key in expected.keys() | actual.keys()}
        for kind in kinds:
            bucket = groups.setdefault(kind, {'correct': 0, 'expected': 0, 'predicted': 0, 'matched_values': 0})
            left = Counter(str(v) for k, v in expected.items() if k.rsplit('_', 1)[0] == kind)
            right = Counter(str(v) for k, v in actual.items() if k.rsplit('_', 1)[0] == kind)
            bucket['predicted'] += sum(right.values())
            bucket['matched_values'] += sum((left & right).values())
    for bucket in groups.values():
        matched, expected, predicted = bucket['matched_values'], bucket['expected'], bucket['predicted']
        bucket['exact_accuracy'] = bucket['correct'] / expected if expected else None
        bucket['precision'] = matched / predicted if predicted else None
        bucket['recall'] = matched / expected if expected else None
        bucket['f1'] = 2 * matched / (expected + predicted) if expected + predicted else None
    expected = sum(b['expected'] for b in groups.values())
    predicted = sum(b['predicted'] for b in groups.values())
    matched = sum(b['matched_values'] for b in groups.values())
    return {'by_type': groups, 'errors': errors,
            'micro_precision': matched / predicted if predicted else None,
            'micro_recall': matched / expected if expected else None,
            'micro_f1': 2 * matched / (expected + predicted) if expected + predicted else None,
            'note': 'Accuracy is ordinal-key exact match as main; P/R/F1 additionally count extra and missing (type,value) mentions. Vocabulary coverage and unlabelled medical entities are unknown.'}
