"""Language/format invariants built without benchmark examples or labels."""
import unicodedata

import pytest

from ai_agent_service.components.intake import spoken


@pytest.mark.parametrize(('number', 'expected'), [
    ('0', 'không'), ('7', 'bảy'), ('14', 'mười bốn'),
    ('205', 'hai trăm linh năm'), ('1005', 'một nghìn không trăm linh năm'),
    ('1000006', 'một triệu không trăm linh sáu'), ('-17', 'âm mười bảy'),
])
def test_integer_reading_preserves_value_and_sign(number, expected):
    assert spoken.number_words(number) == expected


@pytest.mark.parametrize('invalid', ['1.2', '1,2', 'unknown', '', True])
def test_integer_renderer_does_not_truncate_or_guess(invalid):
    with pytest.raises(ValueError):
        spoken.number_words(invalid)


def test_identifier_zeroes_are_digits_not_an_integer_prefix():
    assert spoken.code_words('Q-007') == 'quy không không bảy'
    assert spoken.code_words('Q-7') == 'quy bảy'
    assert spoken.code_words('A001B') == 'a không không một bê'


@pytest.mark.parametrize(('text', 'expected'), [
    ('0.05', 'không phẩy không năm'),
    ('2,015', 'hai phẩy không một năm'),
    ('8.40', 'tám phẩy bốn không'),
    ('1.234.567', 'một triệu hai trăm ba mươi bốn nghìn năm trăm sáu mươi bảy'),
    ('1.2.3', '1.2.3'), ('1..2', '1..2'),
])
def test_decimal_and_group_boundaries_do_not_drop_digit_values(text, expected):
    assert spoken.catalogue_numbers(text) == expected


def test_catalogue_units_render_a_complete_numeric_token():
    assert spoken.catalogue_spoken('Bình Vela 0.05L') == 'Bình Vela không phẩy không năm lít'
    assert spoken.catalogue_spoken('Pin Vela 1.234.567mAh') == (
        'Pin Vela một triệu hai trăm ba mươi bốn nghìn năm trăm sáu mươi bảy mi li am pe giờ')
    assert spoken.catalogue_spoken('Bình Vela 1..2L') == 'Bình Vela 1..2L'


def test_uppercase_codes_are_not_confused_with_lowercase_si_units():
    assert spoken.catalogue_spoken('Router 5G') == 'Router năm giê'
    assert spoken.catalogue_spoken('Cuộn 3M') == 'Cuộn ba em mờ'
    assert spoken.catalogue_spoken('Radio 2.5G') == 'Radio hai phẩy năm giê'
    assert spoken.catalogue_spoken('Dây 3m') == 'Dây ba mét'
    assert spoken.catalogue_spoken('Gói 5g') == 'Gói năm gam'


@pytest.mark.parametrize(('text', 'year', 'expected'), [
    ('Ngày 29 tháng 2 năm 2040', 2039, '2040-02-29'),
    ('Mùng hai tháng ba', 2041, '2041-03-02'),
    ('ngày hai lăm tháng tám', 2042, '2042-08-25'),
    ('ngày hai mươi tư tháng năm năm hai nghìn không trăm bốn mươi ba', 2044, '2043-05-24'),
    ('ngày một tháng một năm ba nghìn linh tám', 2044, '3008-01-01'),
    ('Ngày 29 tháng 2 năm 2039', 2040, 'Ngày 29 tháng 2 năm 2039'),
    ('ngày 30 tháng 2', 2040, 'ngày 30 tháng 2'),
    ('ngày 7 tháng 13 năm 2040', 2040, 'ngày 7 tháng 13 năm 2040'),
    ('ngày 7 tháng 9 năm 20405', 2040, 'ngày 7 tháng 9 năm 20405'),
    ('ngày 7 tháng 9 năm 2040abc', 2040, 'ngày 7 tháng 9 năm 2040abc'),
    ('ngày 7 tháng 9 năm 2040.5', 2040, 'ngày 7 tháng 9 năm 2040.5'),
    ('ngày 7 tháng 9,5', 2040, 'ngày 7 tháng 9,5'),
    ('ngày 7 tháng 9 năm 2040.', 2039, '2040-09-07.'),
    ('ngày 7 tháng 9 năm chưa rõ', 2040, 'ngày 7 tháng 9 năm chưa rõ'),
    ('ngày 7 tháng 9 năm hai nghìn 40', 2040, 'ngày 7 tháng 9 năm hai nghìn 40'),
])
def test_calendar_validation_never_fills_over_an_explicit_invalid_year(text, year, expected):
    assert spoken.dates(text, year) == expected


def test_date_nfc_and_case_normalization_are_independent_of_callers():
    text = unicodedata.normalize('NFD', 'NGÀY BẢY THÁNG CHÍN NĂM 2046')
    assert spoken.dates(text, 2040) == '2046-09-07'


@pytest.mark.parametrize('text', [
    'Điện thoại là không bảy tám chín tám sáu bốn một hai ba.',
    'SĐT: 0789 864 123',
    'Số điện thoại của anh là: 0789.864.123',
    'Điện thoại +84 789 864 123',
    'Số liên hệ cộng tám bốn bảy tám chín tám sáu bốn một hai ba',
    'Điện thoại ０７８９８６４１２３',
])
def test_explicit_phone_formats_preserve_the_number(text):
    assert spoken.phones(unicodedata.normalize('NFD', text)) == {'0789864123'}


@pytest.mark.parametrize('text', [
    'Điện thoại 789864123',  # Missing trunk zero without an explicit country code.
    'Điện thoại 078986412345',
    'Số tài khoản 0789864123',
    'CCCD 0789864123',
    'Điện thoại +12 789864123',
    'Điện thoại 0789 864 123 45',
])
def test_phone_parser_does_not_complete_truncate_or_relabel_other_ids(text):
    assert spoken.phones(text) == set()


def test_spoken_phone_alternatives_are_not_silently_resolved_to_the_first():
    text = 'SĐT không bảy tám chín tám sáu bốn một hai ba hoặc không chín sáu một hai ba bốn năm sáu bảy'
    assert spoken.phones(text) == {'0789864123', '0961234567'}


def test_letter_sizes_do_not_capture_a_prefix_of_an_unknown_code():
    assert spoken.size_letters('SIZE ÍCH ÍCH ÍCH E LỜ') == 'SIZE xxxl'
    assert spoken.size_letters('cỡ ích ích ét') == 'cỡ xxs'
    assert spoken.size_letters('size em mờ e lờ') == 'size em mờ e lờ'
    assert spoken.size_letters('size ích e lờ bê') == 'size ích e lờ bê'
    assert spoken.size_letters('e lờ') == 'e lờ'
