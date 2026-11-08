"""scenario-commerce-v9: blockers and payments the extractor used to omit, and how ASR splits "size"/"COD".

Synthetic sentences, not dataset text.
"""
import pytest

from ai_agent_service.components.intake import commerce as module


@pytest.mark.parametrize('text, value', [
    ('anh chưa chắc lắm, cần suy nghĩ thêm', 'can suy nghi them'),          # hesitation is the blocker
    ('nếu không còn màu đó thì em sẽ cân nhắc thêm', 'can suy nghi them'),   # after "thì", not inside the if
    ('để tôi nghĩ thêm rồi gọi lại', 'can suy nghi them'),
    ('tôi phải hỏi ý kiến bố mẹ trước', 'can hoi nguoi nha'),
    ('để bàn với con cái đã', 'can hoi nguoi nha'),
    ('đợi tới tuần sau công ty trả lương rồi mua', 'cho luong'),
    ('mức này cao hơn dự tính của tôi', 'vuot ngan sach'),
    ('giá ở đây đắt hơn chỗ khác', 'so sanh gia'),
    ('tôi còn cân nhắc bên khác', 'so sanh gia'),
])
def test_stated_blockers(text, value):
    assert module.commerce(text).get('blocker') == value


@pytest.mark.parametrize('text', [
    'nếu anh cần suy nghĩ thêm thì cứ báo em',   # inside the condition
    'tôi đã suy nghĩ xong rồi, lấy luôn',
    'không cần hỏi bố mẹ đâu',
])
def test_blockers_not_stated(text):
    assert 'blocker' not in module.commerce(text)


@pytest.mark.parametrize('text, value', [
    ('tôi trả tiền mặt lúc giao hàng', 'COD'),
    ('trả bằng tiền mặt nhé', 'COD'),
    ('cho tôi thanh toán c o d', 'COD'),
    ('thanh toán ceo d được không', 'COD'),
    ('có thể thanh toán qua chuyển khoản không em', 'bank'),
    ('hình thức thanh toán của tôi là qua ngân hàng', 'bank'),
])
def test_payments(text, value):
    assert module.commerce(text).get('payment') == value


@pytest.mark.parametrize('text', ['nếu thanh toán c o d thì có phí không', 'tôi không biết có chuyển khoản được không'])
def test_payments_not_chosen(text):
    assert 'payment' not in module.commerce(text)


@pytest.mark.parametrize('heard', ['side', 'sies', 'site', 'cit', 'cice', 'sai'])
def test_how_the_recogniser_writes_size(heard):
    assert module.commerce(f'tôi lấy đôi giày đó {heard} bốn mươi mốt').get('size_new') == 41


def test_a_size_like_word_needs_a_garment_and_a_size():
    assert 'size_new' not in module.commerce('em gửi site bốn mươi mốt trang')


def test_a_delivery_place_is_not_cash_on_delivery():
    assert module.commerce('tôi thanh toán qua ngân hàng và giao hàng ở quận một')['payment'] == 'bank'
    assert module.commerce('tôi trả tiền khi giao hàng')['payment'] == 'COD'
