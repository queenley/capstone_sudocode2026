"""Specification and metamorphic fixtures; independent of benchmark labels."""
from copy import deepcopy
from datetime import datetime
import hashlib
import json

import pytest

from ai_agent_service.components.intake import commerce as module


@pytest.fixture
def catalogue(monkeypatch):
    products = {'reference_date': '2040-01-02', 'products': [
        {'sku': 'SKU-SENTINEL-K', 'brand': 'Zephyr', 'name': 'Máy Zephyr K', 'variants': []},
        {'sku': 'SKU-SENTINEL-X', 'brand': 'Zephyr', 'name': 'Máy Zephyr X', 'variants': []},
        {'sku': 'SKU-SENTINEL-SHOE', 'brand': 'Nimbus', 'name': 'Giày Nimbus Trail 17', 'variants': [
            {'variant_sku': 'SKU-SENTINEL-SHOE-46-DEN', 'size': 46, 'color': 'den', 'stock': 0,
             'price_delta_vnd': 123000}]}]}
    monkeypatch.setattr(module, '_catalogue', lambda: products)
    return products


@pytest.mark.parametrize('text', [
    'Không lấy Zephyr K, tôi chọn Zephyr X.',
    'Tôi chọn Zephyr X thay vì Zephyr K.',
    'Chọn SKU-SENTINEL-X thay vì SKU-SENTINEL-K.',
])
def test_explicit_selection_beats_rejected_alternative(catalogue, text):
    assert module.commerce(text) == {'sku': 'SKU-SENTINEL-X'}


@pytest.mark.parametrize('text', ['Zephyr K hay Zephyr X?', 'Chọn Zephyr K hoặc Zephyr X.',
                                 'Chọn Zephyr K và Zephyr X.', 'Zephyr Q.', 'SKU-SENTINEL-X-UNKNOWN.'])
def test_scalar_identity_abstains_on_ambiguity_and_unknowns(catalogue, text):
    assert 'sku' not in module.commerce(text)


@pytest.mark.parametrize('text', ['Tôi muốn được tư vấn Zephyr K.', 'Nhờ em tư vấn Zephyr K.',
                                 'Không tư vấn Zephyr K.', 'Anh đang dùng Zephyr K không?'])
def test_named_identity_is_not_automatically_advice_or_ownership(catalogue, text):
    observed = module.observe(text)
    assert observed['asr_entities']['sku'] == 'SKU-SENTINEL-K'
    assert not observed['scenario_entities']


def test_variant_identity_uses_only_explicit_selection_and_attributes(catalogue):
    values = module.observe('Chọn Nimbus Trail 17 size 46 màu đen.')
    assert values['asr_entities'] == {'sku': 'SKU-SENTINEL-SHOE', 'size_new': 46, 'color': 'den'}
    assert values['scenario_entities'] == {'size': 46, 'color': 'den', 'variant_sku': 'SKU-SENTINEL-SHOE-46-DEN'}
    assert module.scenario_entities('Chọn SKU-SENTINEL-SHOE-46-DEN.') == {'variant_sku': 'SKU-SENTINEL-SHOE-46-DEN'}
    assert 'variant_sku' not in module.scenario_entities('Nimbus Trail 17 size 46 màu đen.')
    assert 'variant_sku' not in module.scenario_entities('Chọn Nimbus Trail 17 size 47 màu đen.')


def test_speaker_provenance_controls_quote_mapping(catalogue):
    assert module.observe('Giá bán 8 triệu.', speaker='A')['scenario_entities'] == {
        'price_vnd': 8000000, 'price_quoted_vnd': 8000000}
    for speaker in (None, 'C', 'caller'):
        assert module.observe('Giá bán 8 triệu.', speaker=speaker)['scenario_entities'] == {'price_vnd': 8000000}


@pytest.mark.parametrize(('text', 'expected'), [
    ('Tôi đã hỏi vợ xong rồi đặt hàng.', {}),
    ('Tôi cần hỏi vợ. Tôi đã hỏi vợ xong.', {}),
    ('Tôi cần hỏi vợ. Không cần hỏi vợ nữa.', {}),
    ('Tôi đã chờ nhận lương 1 tuần.', {'blocker': 'cho luong'}),
    ('Tôi đã định hỏi vợ nhưng vẫn cần hỏi chồng.', {'blocker': 'can hoi chong'}),
    ('Không thanh toán qua chuyển khoản.', {}),
    ('COD hay momo?', {}),
    ('Chưa chắc còn hàng.', {}),
    ('Nếu còn hàng thì báo tôi.', {}),
    ('Chưa hết hàng.', {'in_stock': True}),
    ('Không hết hàng.', {'in_stock': True}),
    ('Không chọn màu đen.', {}),
    ('Chọn màu đen. Không chọn màu đen nữa.', {}),
    ('Không chọn màu đen mà chọn màu trắng.', {'color': 'trang'}),
    ('Chọn màu đen hoặc màu trắng.', {}),
    ('Size 46 hay 47?', {}),
    ('Không chọn size 46.', {}),
    ('Không đổi size 46 sang 47.', {}),
    ('Phòng 25.5 mét vuông.', {}),
    ('Phòng 25,5 mét vuông.', {}),
    ('Phòng 26.0 mét vuông.', {'room_area_m2': 26}),
    ('Hàng về ngày 4 tháng 2 năm 20400.', {}),
    ('Ưu đãi hết hạn 4/2/abc.', {}),
    ('Ưu đãi hết hạn 7/9/2040.5.', {}),
    ('Ưu đãi hết hạn 2040-09-07.5.', {}),
    ('Số tài khoản 0789864123.', {}),
    ('CCCD 0789864123.', {}),
    ('Số tài khoản 0789864123, điện thoại 0912345678.', {'phone': '0912345678'}),
])
def test_negation_resolution_and_numeric_boundaries(catalogue, text, expected):
    assert module.commerce(text) == expected


def test_dialogue_uses_actual_boundaries_without_cross_product_roles(catalogue):
    observed = module.observe_dialogue('Tôi đang dùng Zephyr K.\nEm tư vấn Zephyr X.')
    assert observed['asr_entities'] == {'sku': 'SKU-SENTINEL-X'}
    assert observed['scenario_entities'] == {'owned_sku': 'SKU-SENTINEL-K', 'product_advised': 'SKU-SENTINEL-X'}
    # Single ambiguous utterances remain ambiguous, even in dialogue mode.
    assert module.observe_dialogue('Zephyr K hay Zephyr X?')['asr_entities'] == {}


def test_dialogue_identifiers_do_not_need_reference_entity_lists(catalogue):
    observed = module.observe_dialogue('Mã đơn OD975321.\nĐơn mới OD864209. Điện thoại 0912345678.')
    assert observed['asr_entities'] == {'order_id': 'OD864209', 'phone': '0912345678'}
    assert observed['scenario_entities']['phone_provided'] is True


def test_catalogue_order_and_unspoken_business_facts_cannot_change_identity(catalogue):
    text = 'Em tư vấn Zephyr K.'
    expected = module.observe(text)
    catalogue['products'].reverse()
    for p in catalogue['products']:
        p.update(list_price_vnd=987654321, stock=999, attributes={'warranty_months': 89})
    assert module.observe(text) == expected
    catalogue['products'].append({'sku': 'SKU-AMBIGUOUS', 'brand': 'Zephyr', 'name': 'Máy Zephyr K', 'variants': []})
    assert 'sku' not in module.commerce(text)


def test_surface_variations_and_unrelated_clauses_preserve_identity(catalogue):
    for name in ('Zephyr K', 'ZEPHYR K', 'Z e p h y r K', 'ZephyrK'):
        assert module.commerce('Xin chào. Tôi chọn ' + name + '.') == {'sku': 'SKU-SENTINEL-K'}


def test_complete_model_codes_are_catalogue_derived_and_collision_safe(catalogue):
    assert module.commerce('Trail 17.') == {'sku': 'SKU-SENTINEL-SHOE'}
    assert module.commerce('Trail mười bảy.') == {'sku': 'SKU-SENTINEL-SHOE'}
    assert module.commerce('Trail 170.') == {}
    assert module.commerce('Trail 17 phẩy năm.') == {}
    assert module.commerce('K hoặc X.') == {}
    catalogue['products'].append({'sku': 'SKU-DIFFERENT-BRAND', 'name': 'Giày Cirrus Trail 17',
                                  'brand': 'Cirrus', 'variants': []})
    assert module.commerce('Trail 17.') == {}
    assert module.commerce('Nimbus Trail 17.') == {'sku': 'SKU-SENTINEL-SHOE'}


def test_catalogue_snapshot_hash_and_index_change_together(tmp_path, monkeypatch):
    first, second = tmp_path / 'one', tmp_path / 'two'
    document = {'reference_date': '2041-05-06', 'products': [
        {'sku': 'SKU-SNAPSHOT-A', 'brand': 'Quartz', 'name': 'Máy Quartz K', 'variants': []}]}
    for directory in (first, second):
        (directory / 'catalog').mkdir(parents=True)
    path = first / module.CATALOG_PATH
    original = json.dumps(document).encode()
    path.write_bytes(original)
    monkeypatch.setattr(module, 'btc_data_dir', lambda: first)
    assert module.commerce('Quartz K.') == {'sku': 'SKU-SNAPSHOT-A'}
    original_hash = hashlib.sha256(original).hexdigest()
    assert module.metadata()['catalogue_sha256'] == original_hash
    changed = deepcopy(document)
    changed['products'][0]['sku'] = 'SKU-SNAPSHOT-B'
    path.write_text(json.dumps(changed))
    # The file may be replaced during a process: both lookup and manifest retain the same snapshot.
    assert module.commerce('Quartz K.') == {'sku': 'SKU-SNAPSHOT-A'}
    assert module.metadata()['catalogue_sha256'] == original_hash
    second_path = second / module.CATALOG_PATH
    second_path.write_text(json.dumps(changed))
    monkeypatch.setattr(module, 'btc_data_dir', lambda: second)
    assert module.commerce('Quartz K.') == {'sku': 'SKU-SNAPSHOT-B'}
    assert module.metadata()['catalogue_sha256'] == hashlib.sha256(second_path.read_bytes()).hexdigest()


def test_declared_clock_controls_missing_year_not_machine_time(catalogue):
    for year in (2039, 2044):
        assert module.commerce('Hàng về ngày 6 tháng 7.', now=datetime(year, 1, 1)) == {
            'restock_date': f'{year}-07-06'}


def test_changing_reference_answers_cannot_change_predictions(catalogue, tmp_path):
    from ai_agent_service.pipeline.eval import asr
    snapshots = []
    for index, label in enumerate(({'sku': 'WRONG-A', 'size_new': 1}, {'phone': 'WRONG-B', 'size_new': 99})):
        source = tmp_path / str(index)
        source.mkdir()
        (source / 'ground_truth.json').write_text(json.dumps({'kind': 'turns', 'dialogues': [
            {'id': 'sentinel', 'full_text': 'Unrelated reference text ' + str(index), 'entities': label,
             'turns': [{'idx': 85, 'text': 'unrelated', 'entities': label}]}]}))
        (source / 'hypotheses.json').write_text(json.dumps({'sentinel': {'text': 'Chọn Nimbus Trail 17 size 46 màu đen.'}}))
        out = tmp_path / f'out-{index}'
        report = asr.evaluate(source, None, out)
        assert report['status'] == 'COMPLETE'
        snapshots.append(json.loads((out / 'raw/hypotheses.json').read_text())['sentinel'])
    assert snapshots[0] == snapshots[1]
    assert snapshots[0]['entities'] == {'sku': 'SKU-SENTINEL-SHOE', 'size_new': 46, 'color': 'den'}
