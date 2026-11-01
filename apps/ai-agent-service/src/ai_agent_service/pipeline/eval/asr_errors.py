"""Text alignment diagnostics alongside (never in place of) the pinned main scorer."""
from __future__ import annotations
from collections import Counter
from .asr import normalize

NEGATION = {'không', 'chưa', 'chẳng', 'đừng', 'chả'}
NUMBER_LIKE = {'không', 'một', 'hai', 'ba', 'bốn', 'tư', 'năm', 'sáu', 'bảy', 'tám', 'chín',
               'mười', 'mươi', 'trăm', 'nghìn', 'ngàn', 'triệu', 'tỷ', 'phẩy', 'lăm', 'mốt'}


def align(reference: str, hypothesis: str) -> list[dict]:
    """Levenshtein backtrace, ties substitute/delete/insert, same policy as edits()."""
    ref, hyp = normalize(reference).split(), normalize(hypothesis).split()
    width = len(hyp) + 1
    trace = bytearray((len(ref) + 1) * width)
    for j in range(1, width):
        trace[j] = 3
    row = list(range(width))
    for i, word in enumerate(ref, 1):
        current = [i] + [0] * len(hyp)
        trace[i * width] = 2
        for j, other in enumerate(hyp, 1):
            if word == other:
                current[j] = row[j-1]
            else:
                choices = (row[j-1] + 1, row[j] + 1, current[j-1] + 1)
                cost = min(choices)
                current[j] = cost
                trace[i*width+j] = choices.index(cost) + 1
        row = current
    i, j, operations = len(ref), len(hyp), []
    while i or j:
        action = trace[i*width+j]
        if action == 0:
            i -= 1; j -= 1
        elif action == 1:
            i -= 1; j -= 1
            operations.append({'op': 'S', 'reference': ref[i], 'hypothesis': hyp[j], 'ref_index': i, 'hyp_index': j})
        elif action == 2:
            i -= 1
            operations.append({'op': 'D', 'reference': ref[i], 'hypothesis': '', 'ref_index': i, 'hyp_index': j})
        else:
            j -= 1
            operations.append({'op': 'I', 'reference': '', 'hypothesis': hyp[j], 'ref_index': i, 'hyp_index': j})
    return list(reversed(operations))


def analyze(rows: list[dict]) -> dict:
    confusions, operations = Counter(), Counter()
    categories = {'negation': Counter(), 'number_like_lexical': Counter()}
    details = []
    for row in rows:
        errors = align(row['reference_text'], row['raw_text'])
        for error in errors:
            op, left, right = error['op'], error['reference'], error['hypothesis']
            operations[op] += 1
            confusions[(op, left, right)] += 1
            if left in NEGATION or right in NEGATION:
                categories['negation'][op] += 1
            if left in NUMBER_LIKE or right in NUMBER_LIKE or any(c.isdecimal() for c in left + right):
                categories['number_like_lexical'][op] += 1
        words = normalize(row['reference_text']).split()
        repeats = [(i, word) for i, word in enumerate(words) if i and words[i-1] == word]
        details.append({'id': row['id'], 'wer': row['scores']['raw']['wer'], 'errors': errors,
                        'reference_negation_tokens': sum(w in NEGATION for w in words),
                        'reference_adjacent_repetitions': len(repeats),
                        'deleted_repeated_tokens': sum(e['op'] == 'D' and (e['ref_index'], e['reference']) in repeats for e in errors)})
    return {'version': 'asr-alignment-v1', 'normalization': 'same as main; no ITN', 'operations': dict(operations),
            'top_confusions': [{'op': k[0], 'reference': k[1], 'hypothesis': k[2], 'count': count} for k, count in confusions.most_common(40)],
            'lexical_categories': {k: dict(v) for k, v in categories.items()},
            'worst_samples': sorted(details, key=lambda r: r['wer'] if r['wer'] is not None else -1, reverse=True),
            'note': 'Alignment is one optimal path; ambiguous repeats can align differently. Number-like tokens are not canonical entity labels. No judge or reference-based correction is used.'}
