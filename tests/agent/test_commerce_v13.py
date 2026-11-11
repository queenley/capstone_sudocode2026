"""scenario-commerce-v13: product names the recogniser spells many ways, matched by sound.

Synthetic sentences, not dataset sentences; the misheard spellings are the recogniser's own, heard on the
data/dev customer clips.
"""
import pytest

from ai_agent_service.components.intake import commerce as module
from ai_agent_service.components.intake.lexicon import correct


def sku(text):
    return module.commerce(correct(text)).get('sku')


@pytest.mark.parametrize('text', [
    'chị muốn đặt xe đẩy gấp gọn drap back cho con',
    'anh hỏi xe đẩy gấp gọn dray park còn hàng không',
    'chị lấy xe đẩy gấp gọn ruapack nhé',
])
def test_spellings_near_a_heard_whole_name_are_that_product(text):
    # "drapark: Joie Pact" in the lexicon is a sound key, so the spellings near it are Joie Pact too.
    assert sku(text) == 'SKU-MB-STR1'


@pytest.mark.parametrize('text', [
    'anh muốn mua giày chạy bộ run light hy pro size bốn mươi',
    'chị đặt giày chạy bộ jun like hypro màu đen',
    'em ơi giày chạy bộ RunLite hy pro còn size bốn mốt không',
])
def test_two_pro_as_the_recogniser_writes_it(text):
    assert sku(text) == 'SKU-SN-RUN2'


def test_a_misheard_kind_of_product():
    assert sku('chị hỏi máy tiệc trùng sấy khô moaz bê bê') == 'SKU-MB-STER'


@pytest.mark.parametrize('text', ['anh hy vọng giày chạy bộ giao sớm', 'xe đẩy cho bé nhà chị có loại nào nhẹ'])
def test_no_product_is_made_up(text):
    assert sku(text) is None


@pytest.fixture
def catalogue(monkeypatch):
    products = {'reference_date': '2040-01-02', 'products': [
        {'sku': 'SKU-T-TWO', 'brand': 'Zebo', 'name': 'Xe đẩy 2 chiều Zebo Lumo', 'variants': []},
        {'sku': 'SKU-T-FOLD', 'brand': 'Kivo', 'name': 'Xe đẩy gấp gọn Kivo Lite', 'variants': []}]}
    monkeypatch.setattr(module, '_catalogue', lambda: products)
    return products


def test_a_number_inside_the_kind_belongs_to_it(catalogue):
    assert module._kind_and_name(catalogue['products'][0]) == ('xe day hai chieu', 'Zebo Lumo')
    assert module.commerce('anh hỏi xe đẩy hai chiều zebo lumo cho bé').get('sku') == 'SKU-T-TWO'
