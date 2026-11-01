from ai_agent_service.components.intake import entities
from datetime import datetime
import pytest


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


def test_scenario_names_types_and_private_phone_follow_contract():
    from ai_agent_service.components.intake.commerce import scenario_entities, contract
    result = scenario_entities('Đổi size 37 sang 44 màu trắng. Số điện thoại 0912345678.')
    assert result == {'size': 44, 'superseded': {'size': 37}, 'color': 'trang', 'phone_provided': True}
    assert result.keys() <= contract().keys()
    assert entities.commerce('Đổi size 37 sang 44 màu trắng.') == {
        'size_old': 37, 'size_new': 44, 'color': 'trang'}


@pytest.mark.parametrize(('text', 'expected'), [
    ('Thanh toán bằng cê ô đê.', {'payment': 'COD'}),
    ('Không dùng COD, tôi chuyển khoản.', {'payment': 'bank'}),
    ('COD hay chuyển khoản?', {}),
    ('Không cần hỏi chồng nữa.', {}),
    ('Tôi phải bàn với bà xã.', {'blocker': 'can hoi vo'}),
    ('Chờ nhận lương rồi mua.', {'blocker': 'cho luong'}),
    ('Để suy nghĩ thêm đã.', {'blocker': 'can suy nghi them'}),
    ('Nhà tôi không có trẻ nhỏ.', {'has_children': False}),
    ('Sản phẩm có khóa trẻ em.', {}),
    ('Giá chỗ khác là 7,3 triệu đồng.', {'competitor_price_vnd': 7_300_000}),
    ('Ngân sách 8 triệu. Giá bán 7 triệu.', {'budget_vnd': 8_000_000, 'price_vnd': 7_000_000}),
    ('Giá rẻ hơn 200 nghìn đồng.', {}),
    ('Phí đổi hàng miễn phí.', {'exchange_fee_vnd': 0}),
    ('Phí hàng cồng kềnh là 90 nghìn đồng.', {'bulky_fee_vnd': 90_000}),
    ('Đơn từ 850 nghìn đồng được miễn phí giao hàng.', {'min_free_ship_vnd': 850_000}),
    ('Hoàn lại 175 nghìn đồng.', {'refund_vnd': 175_000}),
    ('Bảo hành ba năm.', {'warranty_months': 36}),
    ('Đổi trả trong mười bốn ngày.', {'return_days': 14}),
    ('Giao hàng trong sáu ngày.', {'delivery_days': 6}),
    ('Hết hàng. Hiện còn hàng.', {'in_stock': True}),
    ('Mã đơn ô đê tám trăm mười hai nghìn ba trăm bốn mươi lăm.', {'order_id': 'OD812345'}),
    ('Số điện thoại không chín một hai ba bốn năm sáu bảy tám.', {'phone': '0912345678'}),
])
def test_schema_facts_on_independent_business_examples(text, expected):
    assert entities.commerce(text) == expected


def test_dates_are_explicit_valid_and_resolve_against_declared_call_clock():
    assert entities.commerce('Ưu đãi hết hạn ngày 26 tháng 11 năm 2033.', now=datetime(2033, 1, 1)) == {
        'promo_expiry': '2033-11-26'}
    assert entities.commerce('Hàng về ngày 4 tháng 2.', now=datetime(2034, 1, 1)) == {'restock_date': '2034-02-04'}
    assert 'promo_expiry' not in entities.commerce('Ưu đãi hết hạn ngày 31 tháng 2 năm 2034.')


def test_catalogue_identity_does_not_supply_unspoken_price_stock_or_policy(monkeypatch):
    from ai_agent_service.components.intake import commerce as module
    monkeypatch.setattr(module, '_catalogue', lambda: {
        'reference_date': '2032-04-05', 'products': [
            {'sku': 'SKU-TEST-A', 'name': 'Máy lọc Zephyr 7', 'brand': 'Zephyr', 'list_price_vnd': 19_000_000,
             'stock': 0, 'attributes': {'warranty_months': 17}, 'variants': []},
            {'sku': 'SKU-TEST-B', 'name': 'Máy lọc Zephyr 8', 'brand': 'Zephyr', 'variants': []}]})
    module._product_patterns.cache_clear()
    module._model_patterns.cache_clear()
    try:
        assert entities.scenario_entities('Em tư vấn Zephyr bảy.') == {'product_advised': 'SKU-TEST-A'}
        assert entities.scenario_entities('Tôi đang dùng Zephyr 7.') == {'owned_sku': 'SKU-TEST-A'}
        assert entities.scenario_entities('Zephyr 7.') == {}
        assert entities.commerce('Tôi chọn Zephyr 7.') == {'sku': 'SKU-TEST-A'}
        assert entities.commerce('Zephyr 7 hoặc Zephyr 8.') == {}
        assert entities.commerce('Zephyr 999.') == {}
        assert entities.commerce('Mã SKU-TEST-UNKNOWN.') == {}
    finally:
        module._product_patterns.cache_clear()
        module._model_patterns.cache_clear()


def test_main_metric_extractor_declares_contract_and_catalogue_versions():
    from ai_agent_service.components.intake.commerce import metadata
    instrument = metadata()
    assert instrument['version'] == 'scenario-commerce-v5'
    assert len(instrument['contract_sha256']) == len(instrument['catalogue_sha256']) == 64


def test_canonical_contract_supports_fields_outside_legacy_asr_schema():
    assert entities.scenario_entities('Tôi mua 9 chiếc. Bé 18 tháng tuổi. Nhắn qua zalo nhé.') == {
        'quantity': 9, 'child_age_months': 18, 'preferred_channel': 'zalo_oa'}
    assert entities.scenario_entities('Thanh toán bằng momo.') == {'payment': 'momo'}
    assert entities.commerce('Thanh toán bằng momo.') == {}


def test_uncertainty_and_catalogue_code_boundaries_do_not_become_facts():
    assert entities.commerce('Bảo hành bao nhiêu tháng? Giao hàng 3 đến 5 ngày.') == {}
    assert entities.commerce('SKU-AP-X-UNKNOWN') == {}
    assert entities.commerce('Size cũ 36.') == {'size_old': 36}


@pytest.mark.parametrize(('text', 'expected'), [
    ('Thanh toán bằng xê ô đê.', {'payment': 'COD'}),
    ('Size em mờ màu đỏ.', {'size_new': 'M', 'color': 'do'}),
    ('Đổi size e lờ sang size ích e lờ.', {'size_old': 'L', 'size_new': 'XL'}),
    ('Nhà tôi có bé.', {'has_children': True}),
    ('Nhà chị không có bé.', {'has_children': False}),
    ('Số liên hệ là không, chín, hai, ba, bốn, năm, sáu, bảy, tám, một.', {'phone': '0923456781'}),
    ('Điện thoại 0923 456 781.', {'phone': '0923456781'}),
    ('Mã đơn là OD 712349.', {'order_id': 'OD712349'}),
    ('Mã đơn o dê bảy trăm mười hai nghìn ba trăm bốn mươi chín.', {'order_id': 'OD712349'}),
])
def test_spoken_identifiers_without_any_test_labels(text, expected):
    assert entities.commerce(text) == expected


def test_spoken_calendar_dates_disambiguate_month_five_and_year_marker():
    assert entities.commerce('Khuyến mãi hết hạn ngày hai mươi tám tháng năm năm hai nghìn không trăm ba mươi sáu.') == {
        'promo_expiry': '2036-05-28'}
    assert entities.commerce('Hàng về ngày mười ba tháng mười một.', now=datetime(2037, 2, 1)) == {
        'restock_date': '2037-11-13'}
    assert entities.commerce('Ưu đãi hết hạn ngày ba mươi tháng hai năm hai nghìn không trăm ba mươi sáu.') == {}


def test_catalogue_model_and_code_readings_are_generated_without_scenario_aliases(monkeypatch):
    from ai_agent_service.components.intake import commerce as module
    monkeypatch.setattr(module, '_catalogue', lambda: {'reference_date': '2035-03-01', 'products': [
        {'sku': 'SKU-ZQ-K', 'name': 'Máy lọc Zephyr K', 'brand': 'Zephyr', 'variants': []},
        {'sku': 'SKU-ZQ-240', 'name': 'Máy lọc Zephyr 240', 'brand': 'Zephyr', 'variants': []}]})
    module._product_patterns.cache_clear()
    module._model_patterns.cache_clear()
    try:
        assert entities.commerce('Tôi muốn Zephyr ca.') == {'sku': 'SKU-ZQ-K'}
        assert entities.commerce('Zephyr hai trăm bốn mươi.') == {'sku': 'SKU-ZQ-240'}
        assert entities.commerce('ét ca u dét quy ca.') == {'sku': 'SKU-ZQ-K'}
        assert entities.commerce('Zephyr ca hoặc Zephyr hai trăm bốn mươi.') == {}
        assert entities.commerce('Zephyr bê.') == {}
        assert entities.commerce('Zephyr hai trăm bốn mươi mốt.') == {}
        assert entities.commerce('Zephyr 240 phẩy năm.') == {}
    finally:
        module._product_patterns.cache_clear()
        module._model_patterns.cache_clear()


def test_number_renderer_is_generic_and_preserves_zero_groups():
    from ai_agent_service.components.intake.spoken import number_words
    assert number_words('240') == 'hai trăm bốn mươi'
    assert number_words('1037') == 'một nghìn không trăm ba mươi bảy'


@pytest.mark.parametrize('amount', [4_150_000, 7_354_000, 8_560_000, 12_050_000, 48_539_000])
def test_five_inside_money_is_not_the_year_unit(amount):
    from ai_agent_service.components.intake.spoken import number_words
    assert entities.commerce('Ngân sách ' + number_words(str(amount)) + ' đồng.') == {'budget_vnd': amount}
    assert entities.commerce('Bảo hành năm năm.') == {'warranty_months': 60}


@pytest.mark.parametrize(('text', 'expected'), [
    ('Ngân sách 9 triệu, có máy nào phù hợp không?', {'budget_vnd': 9_000_000}),
    ('Giá bao nhiêu vậy? Ngân sách 9 triệu.', {'budget_vnd': 9_000_000}),
    ('Giày size 45 màu xám có hàng không?', {'size_new': 45, 'color': 'xam'}),
    ('Máy còn hàng không?', {}),
    ('Nhà có trẻ nhỏ không?', {}),
    ('Nếu nhà có trẻ nhỏ thì cần chọn mẫu nào?', {}),
    ('Tôi có hai đứa con nhỏ.', {'has_children': True}),
    ('Con tôi 14 tháng tuổi.', {'has_children': True}),
    ('Em có một bé ở nhà.', {'has_children': True}),
    ('Thanh toán qua ngân hàng.', {'payment': 'bank'}),
    ('Tôi trả tiền mặt khi nhận hàng.', {'payment': 'COD'}),
    ('Chọn COOOD nhé.', {'payment': 'COD'}),
    ('Số tài khoản ngân hàng của tôi 123456789012.', {}),
    ('Giá bên em 9 triệu bên khác có giá 8 triệu.', {'price_vnd': 9_000_000, 'competitor_price_vnd': 8_000_000}),
    ('Tôi đang mặc size 37.', {'size_old': 37}),
    ('Đổi size từ 37 sang 45 được không?', {'size_old': 37, 'size_new': 45}),
    ('Giày cice 40 màu trắng.', {'size_new': 40, 'color': 'trang'}),
    ('Áo sais 40.', {'size_new': 40}),
    ('Tôi đã làm sai 40 lần khi buộc giày.', {}),
    ('Phần code của ứng dụng bị lỗi.', {}),
])
def test_explicit_values_survive_questions_but_unknown_answers_are_not_invented(text, expected):
    assert entities.commerce(text) == expected


def test_catalogue_spacing_and_fuzzy_brand_require_an_intact_unique_model(monkeypatch):
    from ai_agent_service.components.intake import commerce as module
    monkeypatch.setattr(module, '_catalogue', lambda: {'reference_date': '2038-07-09', 'products': [
        {'sku': 'SKU-NEW-A', 'name': 'Máy lọc Zephyr K', 'brand': 'Zephyr', 'variants': []},
        {'sku': 'SKU-NEW-B', 'name': 'Máy lọc Zephyr X', 'brand': 'Zephyr', 'variants': []},
        {'sku': 'SKU-NEW-C', 'name': 'Máy lọc Zephir K', 'brand': 'Zephir', 'variants': []}]})
    module._product_patterns.cache_clear()
    module._model_patterns.cache_clear()
    try:
        assert entities.commerce('Máy lọc ZephyrK.') == {'sku': 'SKU-NEW-A'}
        assert entities.commerce('Máy lọc Z e p h y r K.') == {'sku': 'SKU-NEW-A'}
        assert entities.commerce('Tôi tìm ZepyrX.') == {'sku': 'SKU-NEW-B'}
        assert entities.commerce('Zephr K.') == {}  # Equally close brands: no guessing.
        assert entities.commerce('Zephyr.') == {}  # A lost model cannot be recovered from a brand.
        assert entities.commerce('Zephyr Q.') == {}
        assert entities.commerce('Zephyr K hoặc Zephyr X.') == {}
        assert entities.commerce('SKU-NEW-UNLISTED.') == {}
        assert entities.commerce('SKU - NEW - A - RETIRED.') == {}
        assert entities.commerce('SKU - NEW - A.') == {'sku': 'SKU-NEW-A'}
    finally:
        module._product_patterns.cache_clear()
        module._model_patterns.cache_clear()


@pytest.mark.parametrize(('text', 'expected'), [
    ('Để tôi tính lại rồi mua.', {'blocker': 'can suy nghi them'}),
    ('Tôi muốn suy nghĩ.', {'blocker': 'can suy nghi them'}),
    ('Tôi cần xin ý kiến ông xã.', {'blocker': 'can hoi chong'}),
    ('Tôi chưa đủ tiền.', {'blocker': 'vuot ngan sach'}),
    ('Tôi thanh toán khi nhận hàng.', {'payment': 'COD'}),
    ('Tôi không muốn suy nghĩ nữa.', {}),
    ('Gia đình tôi đã nhận một sản phẩm khác.', {}),
])
def test_commerce_uses_the_business_intents_not_family_words_alone(text, expected):
    assert entities.commerce(text) == expected


def test_catalogue_decimal_volume_is_not_an_integer_model(monkeypatch):
    from ai_agent_service.components.intake import commerce as module
    monkeypatch.setattr(module, '_catalogue', lambda: {'reference_date': '2039-08-10', 'products': [
        {'sku': 'SKU-VOLUME-UNIT', 'name': 'Nồi chiên Nebula 7.4L', 'brand': 'Nebula', 'variants': []}]})
    module._product_patterns.cache_clear()
    module._model_patterns.cache_clear()
    try:
        assert entities.commerce('Nebula 7,4L.') == {'sku': 'SKU-VOLUME-UNIT'}
        assert entities.commerce('Nebula bảy phẩy bốn lít.') == {'sku': 'SKU-VOLUME-UNIT'}
        assert entities.commerce('Nebula 74L.') == {}
        assert entities.commerce('Nebula bảy mươi bốn lít.') == {}
    finally:
        module._product_patterns.cache_clear()
        module._model_patterns.cache_clear()


def test_spacing_tolerance_does_not_choose_between_colliding_catalogue_names(monkeypatch):
    from ai_agent_service.components.intake import commerce as module
    monkeypatch.setattr(module, '_catalogue', lambda: {'reference_date': '2040-09-11', 'products': [
        {'sku': 'SKU-COLLIDE-A', 'name': 'Máy Zeph yr K', 'brand': 'Zeph yr', 'variants': []},
        {'sku': 'SKU-COLLIDE-B', 'name': 'Máy Zephyr K', 'brand': 'Zephyr', 'variants': []}]})
    module._product_patterns.cache_clear()
    module._model_patterns.cache_clear()
    try:
        assert entities.commerce('Máy Zephyr K.') == {}
        assert entities.commerce('SKU-COLLIDE-B.') == {'sku': 'SKU-COLLIDE-B'}
    finally:
        module._product_patterns.cache_clear()
        module._model_patterns.cache_clear()
