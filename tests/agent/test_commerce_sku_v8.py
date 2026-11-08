"""scenario-commerce-v8: product names the recogniser misspells, parts, and a model said alone.

Synthetic catalogue and sentences, not dataset text; the rules follow how the organisers'
ASR sample labels ``sku``: once per dialogue, the last product named, "mẫu x" read against
the brand just named.
"""
import pytest

from ai_agent_service.components.intake import commerce as module


@pytest.fixture
def catalogue(monkeypatch):
    products = {'reference_date': '2040-01-02', 'products': [
        {'sku': 'SKU-T-K', 'brand': 'Zephyria', 'name': 'Máy lọc không khí Zephyria K', 'variants': []},
        {'sku': 'SKU-T-PRO', 'brand': 'Zephyria', 'name': 'Máy lọc không khí Zephyria Pro', 'variants': []},
        {'sku': 'SKU-T-KL', 'brand': 'Zephyria', 'name': 'Máy lọc không khí Zephyria K Lite', 'variants': []},
        {'sku': 'SKU-T-K-OLD', 'brand': 'Zephyria', 'name': 'Máy lọc không khí Zephyria K (bản 2030) — NGỪNG BÁN', 'variants': []},
        {'sku': 'SKU-T-FLT', 'brand': 'Zephyria', 'name': 'Màng lọc thay thế Zephyria K', 'variants': []},
        {'sku': 'SKU-T-CART', 'brand': 'Nimbolo', 'name': 'Xe đẩy gấp gọn Nimbolo Pact', 'variants': []}]}
    monkeypatch.setattr(module, '_catalogue', lambda: products)
    return products


@pytest.mark.parametrize('text, sku', [
    ('chị muốn hỏi máy lọc không khí zephyra pro cho phòng ngủ', 'SKU-T-PRO'),   # one letter lost
    ('chị muốn hỏi máy lọc không khí xephiria pờ rô', 'SKU-T-PRO'),             # spelled by sound
    ('anh hỏi về xe đẩy gấp gọn nimpolo pắc', 'SKU-T-CART'),                    # b heard as p
    ('anh hỏi về xe đẩy gấp gọn nimbolo', 'SKU-T-CART'),                        # alone of its kind: the brand names it
])
def test_a_misheard_name_after_its_kind_is_matched_by_sound(catalogue, text, sku):
    assert module.commerce(text).get('sku') == sku


@pytest.mark.parametrize('text', [
    'anh hỏi về xe đẩy cho bé ba tháng',                  # no name after the kind
    'máy lọc không khí cho phòng bốn mươi mét vuông',
    'chị hỏi máy lọc không khí zephyria',                 # the brand alone: several products
    'chị hỏi máy lọc không khí abc xyz',                  # nothing close
    'máy lọc không khí zephyria pro và zephyria k',       # two products, no choice between them
])
def test_weak_or_ambiguous_names_are_omitted(catalogue, text):
    assert module.commerce(text).get('sku') is None


def test_a_part_is_not_taken_for_the_product_its_name_begins(catalogue):
    assert module.commerce('máy lọc không khí zephyria k lite').get('sku') == 'SKU-T-KL'
    assert module.commerce('anh hỏi zephyria k').get('sku') != 'SKU-T-FLT'
    assert module.commerce('anh mua màng lọc thay thế zephyria k').get('sku') == 'SKU-T-FLT'


def test_a_discontinued_product_is_never_guessed_by_sound(catalogue):
    assert module.commerce('máy lọc không khí zephyra k').get('sku') != 'SKU-T-K-OLD'


def test_dialogue_reads_a_model_alone_against_the_brand_just_named(catalogue):
    text = ('dạ em gợi ý mẫu zephyria pro có khóa trẻ em, giá năm triệu.\n'
            'hơi vượt ngân sách, còn mẫu k thì bao nhiêu.\n'
            'dạ mẫu k là bốn triệu ạ.')
    assert module.observe_dialogue(text)['asr_entities']['sku'] == 'SKU-T-K'


def test_dialogue_keeps_the_last_product_named(catalogue):
    text = 'anh hỏi máy lọc không khí zephyria k.\nthôi anh hỏi máy lọc không khí zephyra pro.'
    assert module.observe_dialogue(text)['asr_entities']['sku'] == 'SKU-T-PRO'


def test_a_model_alone_without_a_product_before_names_nothing(catalogue):
    assert 'sku' not in module.observe_dialogue('dạ mẫu k là bốn triệu ạ.')['asr_entities']


# scenario-commerce-v10: the organisers list every value a dialogue-level field took and accept any one.
def test_dialogue_answers_with_a_named_product_rather_than_abstaining(catalogue):
    text = 'máy lọc không khí zephyria k và zephyria pro đều được.\nanh muốn hỏi thêm.'
    assert module.observe_dialogue(text)['asr_entities']['sku'] in {'SKU-T-K', 'SKU-T-PRO'}


def test_dialogue_prefers_the_product_named_most_often(catalogue):
    text = ('em gợi ý zephyria pro.\nzephyria pro có khóa trẻ em.\ncòn mẫu k thì sao.\n'
            'dạ mẫu k rẻ hơn ạ.\nvậy chị hỏi chồng đã.')
    assert module.observe_dialogue(text)['asr_entities']['sku'] in {'SKU-T-PRO', 'SKU-T-K'}
    assert module.observe_dialogue('zephyria pro.\nzephyria pro nhé.\nzephyria k.')['asr_entities']['sku'] == 'SKU-T-PRO'


def test_turns_read_a_model_alone_against_the_previous_turn(catalogue):
    turns = [('dạ em gợi ý mẫu zephyria pro ạ', None, 'A'), ('còn mẫu k thì bao nhiêu', None, 'C'),
             ('dạ mẫu k là bốn triệu ạ', None, 'A'), ('ừ để chị hỏi chồng', None, 'C')]
    skus = [observed['asr_entities'].get('sku') for observed in module.observe_turns(turns)]
    assert skus == ['SKU-T-PRO', 'SKU-T-K', 'SKU-T-K', None]


def test_a_turn_without_a_product_before_it_names_nothing(catalogue):
    assert 'sku' not in module.observe_turns([('dạ mẫu k là bốn triệu ạ', None, 'A')])[0]['asr_entities']
