from ai_agent_service.components.intake import entities


def test_existing_btc_entities_use_runtime_itn_without_reference():
    assert entities.commerce('phòng hai mươi lăm mét vuông không có trẻ nhỏ ngân sách năm triệu') == {
        'room_area_m2': 25, 'has_children': False, 'budget_vnd': 5_000_000}
    assert entities.commerce('thanh toán cod')['payment'] == 'COD'


def test_measurements_are_canonical_but_do_not_rewrite_wer_text():
    a = entities.measurement_entities('mười phần trăm và không phẩy một phần trăm năm mươi lăm tuổi một ngàn miligam')
    b = entities.measurement_entities('10% và 0,1% 55 tuổi 1000 mg')
    assert a == b == {'percent_1': '10', 'percent_2': '0.1', 'age_years_1': '55', 'mass_mg_1': '1000'}
    assert entities.measurement_entities('hai bảy tuổi năm tháng tuổi') == {'age_years_1': '27', 'age_months_1': '5'}


def test_missing_units_and_ambiguous_repeats_are_not_invented():
    assert entities.measurement_entities('không không năm rồi năm nay') == {}
    assert entities.measurement_entities('hai hai tuổi') == {}
    assert entities.measurement_entities('tám mươi đến chín mươi phần trăm') == {'percent_range_1': '80..90'}
    assert entities.measurement_entities('80 đến 90%') == {'percent_range_1': '80..90'}


def test_replaying_v1_entity_instrument_keeps_approved_range_scope():
    from ai_agent_service.pipeline.eval.asr_entities import predict
    text = 'tám mươi đến chín mươi phần trăm'
    assert predict(text, [], version='asr-entities-v1+closed-clinical-v1') == {'percent_1': '90'}
    assert predict(text, [], version='asr-entities-v2+closed-clinical-v1') == {'percent_range_1': '80..90'}


def test_clinical_closed_vocabulary_uses_longest_mentions_and_keeps_negation_separate():
    from ai_agent_service.pipeline.eval.asr_entities import predict
    vocabulary = [{'type': 'disease', 'canonical': term, 'aliases': [term]} for term in ['huyết khối', 'thuyên tắc huyết khối tĩnh mạch']]
    result = predict('không bị thuyên tắc huyết khối tĩnh mạch và huyết khối', vocabulary)
    assert result == {'disease_1': 'thuyên tắc huyết khối tĩnh mạch', 'disease_2': 'huyết khối'}
