import importlib.util
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
import wave

from text_processing import entities, normalize, spoken, extract, callback_date, integer_words
from run_eval import preflight, validate_hypotheses, coverage, entity_accuracy, read, timing_summary

ROOT = Path(__file__).resolve().parent


class TextProcessingTest(unittest.TestCase):
    def test_voicemaker_script_contract(self):
        from prepare_audio import voicemaker_scripts
        data = voicemaker_scripts()
        dev = [d for d in data if d['split'] == 'dev']
        evaluation = [d for d in data if d['split'] == 'eval']
        self.assertEqual((len(dev), len(evaluation)), (6,20))
        self.assertFalse({d['customer_id'] for d in dev} & {d['customer_id'] for d in evaluation})
        for cohort, counts in ((dev, {'north':2,'central':2,'south':2}), (evaluation, {'north':8,'central':6,'south':6})):
            self.assertEqual({region: sum(d['planned_customer_region']==region for d in cohort) for region in counts}, counts)
        self.assertEqual(sum(d['noisy'] for d in evaluation), 4)
        for d in data:
            self.assertEqual(callback_date(d['full_text'], d['call_date'])[0], d['supplemental_entities'])
            self.assertEqual(entities(d['full_text'])['phone'], d['entities']['phone'])
            self.assertIsNone(d['voice_plan']['customer_voice_id'])
    def test_phone_variants_are_diagnostic_and_keep_other_turns(self):
        from prepare_audio import phone_variant_scripts
        original = read(ROOT/'datasets/synthetic-v1/eval/ground_truth.json')
        sources = {d['id']: d for d in original['dialogues']}
        variants = phone_variant_scripts()
        self.assertEqual(len(variants), 8)
        for d in variants:
            source = sources[d['source_id']]
            self.assertNotEqual(d['entities']['phone'], source['entities']['phone'])
            self.assertEqual(entities(d['full_text'])['phone'], d['entities']['phone'])
            self.assertEqual(d['noisy'], source['noisy'])
            self.assertEqual([t for t in d['turns'] if 'điện thoại' not in t['text']],
                             [t for t in source['turns'] if 'điện thoại' not in t['text']])
    def test_catalog_script_inventory_and_split_isolation(self):
        from prepare_audio import catalog_scripts
        data = list(catalog_scripts())
        dev = [d for d in data if d['split'] == 'dev']
        evaluation = [d for d in data if d['split'] == 'eval']
        self.assertEqual((len(dev), len(evaluation)), (4, 20))
        self.assertFalse({d['customer_id'] for d in dev} & {d['customer_id'] for d in evaluation})
        self.assertEqual(len({d['id'] for d in data}), 24)
        self.assertGreaterEqual(sum(d['noisy'] for d in evaluation), 4)
        for d in data:
            self.assertEqual(d['entities']['price_vnd'], d['quote_evidence']['final_price_vnd'])
            self.assertEqual(callback_date(d['full_text'], d['call_date'])[0], d['supplemental_entities'])
            self.assertEqual(d['region'], 'unverified')

    def test_exact_numeric_money_is_not_colloquial(self):
        self.assertEqual(entities('Giá 4.000.890 đồng'), {'price_vnd': 4000890})
        self.assertEqual(entities('Giá 4000890 VND'), {'price_vnd': 4000890})
        self.assertEqual(integer_words(spoken(4000890)), 4000890)

    def test_callback_dates_and_missing_context(self):
        self.assertEqual(callback_date('Hẹn gọi lại ngày mai.', '2026-12-31')[0], {'callback_date': '2027-01-01'})
        self.assertEqual(callback_date('Gọi lại ngày kia.', '2026-10-31')[0], {'callback_date': '2026-11-02'})
        self.assertEqual(callback_date('Hẹn gọi lại 22/10.', '2026-10-15')[0], {'callback_date': '2026-10-22'})
        self.assertEqual(callback_date('Hẹn gọi lại ngày hai mươi hai tháng mười.', '2026-10-15')[0], {'callback_date': '2026-10-22'})
        self.assertFalse(callback_date('Gọi lại 31/02/2026.')[0])
        self.assertFalse(callback_date('Gọi lại mai hoặc ngày kia.', '2026-10-15')[0])
        self.assertFalse(callback_date('Gọi lại ngày mai.')[0])
        self.assertEqual(callback_date('Khuyến mãi đến ngày mai.', '2026-10-15'), ({}, []))

    def test_warmup_timing_keeps_quality_samples(self):
        samples = [{'audio_seconds': 60, 'elapsed_seconds': 8, 'warmup': True},
                   {'audio_seconds': 60, 'elapsed_seconds': 2, 'warmup': False}]
        result = timing_summary(samples)
        self.assertEqual(result['raw_sample_count'], 2)
        self.assertEqual(result['effective_sample_count'], 1)
        self.assertEqual(result['asr_seconds_per_audio_minute'], 2)
        self.assertIsNone(timing_summary(samples[:1])['asr_seconds_per_audio_minute'])

    def test_unknown_audio_and_invalid_entity_gt(self):
        with tempfile.TemporaryDirectory() as folder:
            dataset = Path(folder)
            (dataset/'audio').mkdir()
            (dataset/'audio/UNKNOWN.wav').touch()
            gt = {'dialogues': [{'id': 'A', 'full_text': 'xin chào', 'entities': {}}]}
            target = dataset/'ground_truth.json'
            target.write_text(json.dumps(gt), encoding='utf-8')
            _, _, _, issues = preflight(dataset)
            self.assertTrue(any(i['kind'] == 'UNEXPECTED_AUDIO' for i in issues))
            for value in ([], {'wrong': 'object'}, float('inf')):
                gt['dialogues'][0]['entities'] = {'price_vnd': value}
                target.write_text(json.dumps(gt), encoding='utf-8')
                with self.assertRaises(ValueError):
                    preflight(dataset)
    def test_money_and_budget(self):
        for text in ('Giá bốn triệu tám trăm chín mươi nghìn đồng', 'Giá 4.890.000 đồng', 'Giá 4,890,000 VND'):
            self.assertEqual(entities(text), {'price_vnd': 4890000})
        self.assertEqual(entities('Giá ba triệu. Giá bốn triệu. Ngân sách là năm triệu đồng'),
                         {'price_vnd': 4000000, 'budget_vnd': 5000000})
        self.assertEqual(entities('Giá 4 triệu đồng. Đây là giá minh họa trong cuộc gọi thử nghiệm.'), {'price_vnd':4000000})
        self.assertEqual(entities('Giá bốn triệu tám trăm chín mươi đồng'), {'price_vnd':4890000})
        self.assertEqual(entities('Giá hai trăm bốn chín k'), {'price_vnd':249000})
        self.assertEqual(entities('Giá 249k'), {'price_vnd':249000})
        self.assertNotIn('price_vnd', entities('Giá từ ba đến năm triệu'))
        self.assertNotIn('price_vnd', entities('Giá bốn phẩy năm triệu đồng'))
        self.assertNotIn('price_vnd', entities('Giá ba triệu. Giá bốn triệu đến năm triệu'))

    def test_invalid_phone_never_padded_or_sliced(self):
        for phone in ('09000001', '09000000001'):
            result, diagnostics = extract('Số điện thoại là ' + phone)
            self.assertNotIn('phone', result)
            self.assertTrue(diagnostics)
        self.assertEqual(entities('SĐT không chín không không không không một hai ba bốn'), {'phone':'0900001234'})

    def test_missing_invalid_and_unknown_coverage(self):
        raw = {'A': {'text':'', 'entities':{}}, 'B': {'text':'xin chào', 'entities':{}},
               'X': {'text':'x', 'entities':[]}}
        valid, errors = validate_hypotheses(raw)
        report = coverage(['A','B','C'], raw, valid, errors)
        self.assertEqual(report['status'], 'INCOMPLETE')
        self.assertEqual(report['missing_ids'], ['A','C'])
        self.assertEqual(report['unknown_ids'], ['X'])
        self.assertEqual(entity_accuracy({'dialogues':[
            {'id':'A','entities':{'phone':'0900001234'}},
            {'id':'B','entities':{'phone':'0900001234'}}]},
            {'B':{'text':'','entities':{'phone':'0900001234'}}})['phone']['accuracy'], 50.0)

    def test_preflight_corrupt_missing_and_duplicate(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p/'audio').mkdir()
            with wave.open(str(p/'audio/A.wav'), 'wb') as f:
                f.setparams((1,2,16000,0,'NONE','not compressed'))
                f.writeframes(b'\0\0' * 160)
            gt = {'dialogues':[{'id':'A','full_text':'xin chào','entities':{}},
                               {'id':'B','full_text':'tạm biệt','entities':{}}]}
            (p/'ground_truth.json').write_text(json.dumps(gt), encoding='utf-8')
            _, expected, audio, issues = preflight(p)
            self.assertEqual(expected, ['A','B'])
            self.assertEqual(len(audio), 1)
            self.assertEqual(issues[0]['id'], 'B')
            contents = (p/'audio/A.wav').read_bytes()
            (p/'audio/A.wav').write_bytes(contents[:-2])
            _, _, audio, issues = preflight(p)
            self.assertEqual(len(audio), 0)
            self.assertTrue(any('Truncated' in x['detail'] for x in issues))
            gt['dialogues'][1]['id'] = 'A'
            (p/'ground_truth.json').write_text(json.dumps(gt), encoding='utf-8')
            with self.assertRaises(ValueError): preflight(p)

    def test_duplicate_json_and_nonfinite_numbers_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'input.json'
            for content in ('{"A":1,"A":2}', '{"value":NaN}', '{"value":Infinity}'):
                p.write_text(content,encoding='utf-8')
                with self.assertRaises(ValueError): read(p)

    def test_cli_missing_audio_cannot_be_complete_even_with_perfect_text(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p/'ground_truth.json').write_text(json.dumps({'dialogues':[
                {'id':'A', 'full_text':'xin chào', 'entities':{}}]}),encoding='utf-8')
            (p/'hyp.json').write_text(json.dumps({'A':{'text':'xin chào','entities':{}}}),encoding='utf-8')
            result = subprocess.run([sys.executable, str(ROOT/'run_eval.py'), '--dataset',str(p),
                                     '--hypotheses',str(p/'hyp.json'), '--out',str(p/'run')],capture_output=True,text=True)
            self.assertEqual(result.returncode,2,result.stderr)
            report = read(p/'run/report.json')
            self.assertEqual(report['normalized_metrics']['WER'],0)
            self.assertEqual(report['acceptance'],'INCOMPLETE')
            self.assertFalse(report['coverage']['complete'])
            self.assertIsNone(report['timing']['asr_seconds_per_audio_minute'])
    def test_numbers_and_phone(self):
        raw = 'Giá 5.000.000 đồng. Số 0900-001-234.'
        self.assertEqual(normalize(raw),
                         'giá năm triệu đồng số không chín không không không không một hai ba bốn')
        self.assertEqual(entities(raw), {'phone': '0900001234', 'price_vnd': 5000000})
        self.assertEqual(spoken(4890000), 'bốn triệu tám trăm chín mươi nghìn')

    def test_scorer_missing_hypothesis_needs_wrapper_coverage(self):
        sys.dont_write_bytecode = True
        spec = importlib.util.spec_from_file_location('btc_asr', ROOT.parent / 'evaluation-contracts/sources/btc/eval/reference_eval.py')
        scorer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(scorer)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / 'ground_truth.json').write_text(json.dumps({'dialogues': [
                {'id': 'A', 'full_text': 'xin chào', 'entities': {}, 'noisy': False},
                {'id': 'B', 'full_text': 'tạm biệt', 'entities': {}, 'noisy': False}]}), encoding='utf-8')
            (p / 'hypotheses.json').write_text(json.dumps({'A': {'text': 'xin chào', 'entities': {}}}), encoding='utf-8')
            result = scorer.wer_cer(str(p))
            self.assertEqual(result['WER'], 0.0)
            self.assertEqual(result['n_dialogues'], 1)  # proves why run_eval coverage gate is required


if __name__ == '__main__':
    unittest.main()
