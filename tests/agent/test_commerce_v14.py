"""scenario-commerce-v14: a combo named by its first item, and a part sharing a product's name.

Synthetic sentences in the organisers' catalogue, not dataset sentences.
"""
import pytest

from ai_agent_service.components.intake import commerce as module


@pytest.mark.parametrize('text, sku', [
    ('anh muốn hỏi giá combo Spectra S1 với máy hâm sữa', 'SKU-BDL-MOM'),
    ('chị lấy cái combo AirPure Y nhé', 'SKU-BDL-AIR'),
    ('chị lấy máy hút sữa Spectra S1 nhé', 'SKU-MB-PUMP1'),        # no "combo": the item itself
    ('chị lấy cái AirPure Y nhé', 'SKU-AP-Y'),                      # the combo's name alone is not the combo
])
def test_combo_is_named_by_combo_and_its_first_item(text, sku):
    assert module.commerce(text).get('sku') == sku


@pytest.mark.parametrize('text, sku', [
    ('giá máy AirPure Pro là bao nhiêu em', 'SKU-AP-PRO'),            # the machine's kind said
    ('đừng quên màng lọc thay thế cho AirPure Pro nhé', 'SKU-AP-FLT-P'),  # the part's kind said
])
def test_a_part_and_the_product_it_fits(text, sku):
    assert module.commerce(text).get('sku') == sku


def test_a_part_is_not_heard_for_its_product_by_the_fuzzy_match():
    # "Màng lọc thay thế Xiaomi Smart 4" fits "Xiaomi Smart 4 Lite": with no "màng", the part is not the answer.
    assert module.commerce('em ơi máy lọc không khí xiao mi smart bốn lai giá sao').get('sku') != 'SKU-XM-FLT'
