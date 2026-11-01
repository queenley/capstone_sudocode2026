import hashlib
import json
from pathlib import Path

import pytest

from ai_agent_service.pipeline.eval import asr, cli
from ai_agent_service.config.config_manager import btc_data_dir


def fixture(tmp_path, records, predictions):
    folder = tmp_path / "inputs"
    folder.mkdir()
    (folder / "ground_truth.json").write_text(json.dumps({"dialogues": records}, ensure_ascii=False))
    (folder / "hypotheses.json").write_text(json.dumps(predictions, ensure_ascii=False))
    return folder


def test_asr_replay_uses_main_scorer_unchanged_and_micro_aggregation(tmp_path):
    folder = fixture(tmp_path, [{"id": "one", "full_text": "xin chào", "noisy": True},
                               {"id": "two", "full_text": "máy lọc không khí", "noisy": False}],
                     {"one": {"text": "xin chào", "seconds": .2, "audio_seconds": 2},
                      "two": {"text": "máy lọc", "seconds": .1, "audio_seconds": 1}})
    before = (folder / "ground_truth.json").read_bytes()
    scorer = btc_data_dir() / "eval/reference_eval.py"
    digest = hashlib.sha256(scorer.read_bytes()).hexdigest()
    report = asr.evaluate(folder, None, tmp_path / "out")
    assert report["status"] == "COMPLETE"
    assert report["main_scorer"]["raw"]["WER"] == 33.3
    assert report["diagnostics"]["word_alignment"]["raw"]["deletions"] == 2
    assert report["diagnostics"]["word_alignment"]["raw"]["wer"] == 2 / 6
    assert report["diagnostics"]["rtf"]["p95"] == .1
    assert report["manifest"]["main_scorer_sha256"] == digest
    assert (folder / "ground_truth.json").read_bytes() == before


def test_missing_predictions_remain_in_coverage_and_return_failure(tmp_path):
    folder = fixture(tmp_path, [{"id": "one", "full_text": "xin"}, {"id": "two", "full_text": "chào"}],
                     {"one": {"text": "xin"}})
    report = asr.evaluate(folder, None, tmp_path / "out")
    assert report["status"] == "INCOMPLETE" and report["diagnostics"]["coverage"] == .5
    assert report["main_scorer"]["raw"]["WER"] == 0
    assert cli.main(["--asr", str(folder), "--out", str(tmp_path / "cli")]) == 1


def test_silence_and_echo_metrics_need_explicit_evidence(tmp_path):
    folder = fixture(tmp_path, [{"id": "silence", "full_text": "", "voice_expectation": {"accepted": False}}],
                     {"silence": {"text": "Xin mời anh chọn mẫu", "context": {"busy": True, "echo_text": "Xin mời anh chọn mẫu"}}})
    report = asr.evaluate(folder, None, tmp_path / "out")
    assert report["diagnostics"]["word_alignment"]["raw"]["wer"] is None
    assert report["diagnostics"]["silence"]["nonempty_hypotheses"] == 1
    assert report["diagnostics"]["voice_decisions"]["false_accept_rate"] == 0
    assert report["diagnostics"]["voice_decisions"]["missed_accept_rate"] is None
    assert report["status"] == "INCOMPLETE"  # main's mean of undefined per-dialogue WER is unavailable


def test_invalid_data_rejected_before_creating_artifacts_or_loading_models(tmp_path):
    folder = fixture(tmp_path, [{"id": "same", "full_text": "a"}, {"id": "same", "full_text": "b"}], {})
    with pytest.raises(ValueError, match="unique"):
        asr.evaluate(folder, None, tmp_path / "out")
    assert not (tmp_path / "out").exists()
    assert cli.main(["--asr-transcribe"]) == 2


def test_alignment_and_unicode_normalization():
    assert asr.edits(["a", "b"], ["a", "x", "y"])["errors"] == 2
    assert asr.normalize("CHA\u0300O, chị! 5 triệu.") == "chào chị 5 triệu"


def test_audio_reader_resamples_real_stereo_pcm_and_unlabelled_quality_stays_unknown(tmp_path, monkeypatch):
    import numpy as np
    import soundfile as sf
    waveform = np.stack([np.sin(np.arange(8000) * .1) * .1] * 2, axis=1)
    path = tmp_path / "synthetic.wav"
    sf.write(path, waveform, 8000)
    samples, info = asr._audio(path)
    assert samples.shape == (16000,) and info["channels"] == 2 and info["sample_rate"] == 8000
    assert info["signal"]["snr_db"] is None
    monkeypatch.setattr(asr, "decode", lambda *args: {"text": "xin chào", "seconds": .1, **info})
    report = asr.audio_smoke(path, tmp_path / "out", "fixture")
    assert report["WER"] is None and report["CER"] is None and report["status"] == "UNLABELLED"


def test_waveform_windows_are_bounded_lossless_and_do_not_read_references():
    import numpy as np
    samples = np.ones(16000 * 43 + 17, dtype=np.float32) * .1
    samples[16000 * 18:16000 * 19] = 0
    windows = list(asr.audio_windows(samples))
    assert windows[0][1] < 16000 * 20
    assert all(0 < end - start <= 16000 * 20 for start, end, _ in windows)
    assert np.array_equal(np.concatenate([chunk for _, _, chunk in windows]), samples)
    assert all(a[1] == b[0] for a, b in zip(windows, windows[1:]))


def test_package_adapter_preserves_reference_and_checks_hash_before_decode(tmp_path):
    import numpy as np
    import soundfile as sf
    from ai_agent_service.pipeline.eval.asr_package import prepare
    source = tmp_path / 'supplied'
    source.mkdir()
    sf.write(source / 'one.wav', np.zeros(16000), 16000)
    (source / 'one.txt').write_text('Không không năm mươi')
    (source / 'one.jsonl').write_text(json.dumps({'segment_id': 's_1', 'start_sample': 0, 'end_sample': 16000,
                                                'reference_text': 'Không không năm mươi'}))
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    (source / 'manifest.json').write_text(json.dumps({'files': [{'file_id': 'one', 'audio_file': 'one.wav',
        'reference_file': 'one.txt', 'segments_file': 'one.jsonl', 'audio_sha256': sha(source / 'one.wav'),
        'reference_sha256': sha(source / 'one.txt')}]}))
    out = prepare(source, tmp_path / 'out', unit='segments')
    record = json.loads((out / 'ground_truth.json').read_text())['dialogues'][0]
    assert record['full_text'] == 'Không không năm mươi'
    assert sf.info(out / record['audio']).frames == 16000
    (source / 'one.txt').write_text('changed')
    with pytest.raises(ValueError, match='checksum'):
        prepare(source, tmp_path / 'corrupt', unit='montage')
    assert not (tmp_path / 'corrupt').exists()


def test_error_alignment_preserves_negation_repetition_and_numeric_differences():
    from ai_agent_service.pipeline.eval.asr_errors import align
    ref, hyp = 'không không năm mươi 50', 'không năm 15'
    operations = align(ref, hyp)
    assert len(operations) == asr.edits(asr.normalize(ref).split(), asr.normalize(hyp).split())['errors']
    assert any(e['op'] == 'D' and e['reference'] == 'không' for e in operations)
    assert any(e['reference'] == '50' and e['hypothesis'] == '15' for e in operations)


def test_entity_review_is_provisional_and_does_not_change_wer_or_input(tmp_path):
    folder = fixture(tmp_path, [{'id': 'one', 'full_text': 'mười phần trăm bị viêm đại tràng'}],
                     {'one': {'text': '10% bị viêm đại tràng'}})
    from ai_agent_service.pipeline.eval.asr_entities import predict
    vocabulary = [{'type': 'disease', 'canonical': 'viêm đại tràng', 'aliases': ['viêm đại tràng']}]
    reference = 'mười phần trăm bị viêm đại tràng'
    labels = tmp_path / 'labels.json'
    labels.write_text(json.dumps({'schema_version': 1, 'status': 'pending', 'reviewer': None, 'vocabulary': vocabulary,
                                  'records': {'one': {'reference_text': reference, 'entities': predict(reference, vocabulary)}}}))
    before = (folder / 'ground_truth.json').read_bytes()
    baseline = asr.evaluate(folder, None, tmp_path / 'baseline')
    scored = asr.evaluate(folder, None, tmp_path / 'entities', entity_review=labels)
    assert scored['main_scorer']['raw']['WER'] == baseline['main_scorer']['raw']['WER']
    assert scored['main_scorer']['raw']['entity_accuracy'] == 100
    assert scored['entity_review']['status'] == 'PENDING_HUMAN_REVIEW'
    assert scored['entity_diagnostics']['raw']['by_type']['disease']['expected'] == 1
    assert (folder / 'ground_truth.json').read_bytes() == before
    assert cli.main(['--asr-entity-review', str(labels)]) == 2
