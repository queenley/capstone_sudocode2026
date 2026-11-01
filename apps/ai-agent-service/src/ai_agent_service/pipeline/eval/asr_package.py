"""Lossless adapter for a supplied montage manifest. No labels, audio or source scorer are edited."""
from __future__ import annotations

import json
from pathlib import Path

from . import asr


def prepare(source: Path, out: Path, *, unit: str, only: set[str] | None = None) -> Path:
    import soundfile as sf
    if unit not in {'segments', 'montage'}:
        raise ValueError('Package unit must be segments or montage')
    source = source.resolve()
    manifest_path = source / 'manifest.json'
    manifest = asr._read(manifest_path)
    if not isinstance(manifest, dict) or not isinstance(manifest.get('files'), list):
        raise ValueError('Package requires manifest.json with files[]')
    records, hashes = [], {}
    planned = []
    seen, files = set(), set()
    for item in manifest['files']:
        required = ('file_id', 'audio_file', 'reference_file', 'segments_file', 'audio_sha256', 'reference_sha256')
        if not isinstance(item, dict) or any(not isinstance(item.get(key), str) or not item[key] for key in required):
            raise ValueError('Each package file requires nonempty file_id, paths and checksums')
        file_id = item['file_id']
        if not asr.re.fullmatch(r'[\w-]+', file_id) or file_id in files:
            raise ValueError('Package file IDs must be unique safe file names')
        files.add(file_id)
        def child(name):
            path = (source / name).resolve()
            if not path.is_relative_to(source):
                raise ValueError('Manifest paths must stay inside package')
            return path
        audio = child(item['audio_file'])
        reference = child(item['reference_file'])
        segments_path = child(item['segments_file'])
        for path, expected in [(audio, item['audio_sha256']), (reference, item['reference_sha256'])]:
            digest = asr._sha(path)
            if digest != expected:
                raise ValueError(f'Package checksum mismatch: {path.name}')
            hashes[path.relative_to(source).as_posix()] = digest
        rows = [asr._loads(line) for line in segments_path.read_text(encoding='utf-8').splitlines() if line.strip()]
        if not rows or any(not isinstance(row, dict) or not isinstance(row.get('reference_text'), str)
                           or any(key not in row for key in ('start_sample', 'end_sample', 'segment_id')) for row in rows):
            raise ValueError('Each package segment requires reference_text, sample boundaries and segment_id')
        hashes[segments_path.relative_to(source).as_posix()] = asr._sha(segments_path)
        if ' '.join(' '.join(row['reference_text'].split()) for row in rows) != ' '.join(reference.read_text(encoding='utf-8').split()):
            raise ValueError('Segment references do not match full reference')
        info = sf.info(audio)
        if info.samplerate != 16000 or info.channels != 1:
            raise ValueError('Montage segment sample indices require mono 16 kHz')
        previous = 0
        for row in rows:
            start, end = row['start_sample'], row['end_sample']
            if type(start) is not int or type(end) is not int or not previous <= start < end <= info.frames:
                raise ValueError('Invalid or overlapping segment sample boundaries')
            previous = end
            key = row['segment_id']
            if not isinstance(key, str) or not asr.re.fullmatch(r'[\w-]+', key) or key in seen:
                raise ValueError('Segment IDs must be unique safe file names')
            seen.add(key)
            if unit == 'segments' and (not only or key in only):
                records.append({'id': key, 'full_text': row['reference_text'], 'audio': f'audio/{key}.wav',
                                'customer_region': row.get('source_accent_label'), 'condition': row.get('source_recording_condition_label'),
                                'source_file': item['file_id'], 'reference_status': row.get('reference_status'),
                                'provenance': {k: row.get(k) for k in ['source_utterance_id', 'source_revision', 'source_speaker_id']}})
                planned.append((audio, start, end, key))
        if unit == 'montage':
            records.append({'id': item['file_id'], 'full_text': reference.read_text(encoding='utf-8'), 'audio': str(audio),
                            'reference_status': 'publisher_reference_not_independently_audited'})
    ids = {r['id'] for r in records}
    if only and not only.issubset(ids):
        raise ValueError('Unknown package --only ID')
    if unit == 'montage' and only:
        records = [r for r in records if r['id'] in only]
    if not records:
        raise ValueError('Empty package selection')
    asr.private_output(out)
    for audio, start, end, key in planned:
        samples, rate = sf.read(audio, start=start, stop=end, dtype='float32')
        (out / 'audio').mkdir(exist_ok=True)
        sf.write(out / 'audio' / f'{key}.wav', samples, rate, subtype='FLOAT')
    conversion = {'adapter_version': 'asr-montage-v1', 'source_manifest_sha256': asr._sha(manifest_path),
                  'source_revision': manifest.get('source_revision'), 'source_hashes': hashes, 'unit': unit,
                  'reference_changed': False, 'official_gt_approved': False,
                  'segmentation': 'provided publisher clip boundaries (oracle)' if unit == 'segments' else 'waveform energy only; no reference boundary input',
                  'note': 'This user-supplied medical montage is diagnostic; no canonical entities, natural turn/DER gold or clean signal is inferred.'}
    (out / 'ground_truth.json').write_text(json.dumps({'dialogues': records, 'provenance': conversion}, ensure_ascii=False, indent=2), encoding='utf-8')
    (out / 'conversion-report.json').write_text(json.dumps(conversion, ensure_ascii=False, indent=2), encoding='utf-8')
    return out
