"""Explicit spoken commerce facts, using the catalogue, never scenario answers.

Types/meaning follow contracts/scenario/scenario-keys.yaml and SpokenEntities
in evaluation/data-generation/src/schemas/asr.py. The ASR names stay distinct
from memory slots (sku vs product_advised, size_old/new vs size).
"""
from __future__ import annotations

from datetime import date, datetime
from functools import lru_cache
from decimal import Decimal
from pathlib import Path
import hashlib
import json
import re

import yaml

from ...config.config_manager import ROOT, btc_data_dir, get_models_config
from . import itn
from .lexicon import lexicon
from .pii import normalise_phone
from .text import plain
from . import spoken

VERSION = 'scenario-commerce-v11'
CATALOG_PATH = 'catalog/products.json'
CONTRACT_PATH = (ROOT.parents[1] / 'contracts/scenario/scenario-keys.yaml'
                 if (ROOT.parents[1] / 'contracts/scenario/scenario-keys.yaml').is_file()
                 else ROOT / 'contracts/scenario/scenario-keys.yaml')
# Only the ASR scoring boundary uses these aliases. Canonical output uses the contract.
ASR_ALIASES = {'sku': 'product_advised', 'size_new': 'size', 'phone': 'phone_provided'}
ASR_ONLY = {'size_old', 'min_free_ship_vnd', 'bulky_fee_vnd', 'paid_price_vnd', 'id_number', 'bank_account'}


@lru_cache(maxsize=1)
def contract() -> dict:
    document = yaml.safe_load(_asset_snapshot(str(CONTRACT_PATH.resolve()))[0])
    return {**document['slots'], **document['ground_truth_facts'],
            'superseded': document['memory_expectation']['superseded']}


def _validate(values: dict) -> dict:
    for key, value in values.items():
        spec = contract()[key]
        kinds = spec['type'].split('|')
        valid = any((kind == 'int' and type(value) is int) or (kind == 'bool' and type(value) is bool)
                    or (kind in {'str', 'sku', 'date', 'datetime'} and isinstance(value, str))
                    or (kind == 'object' and isinstance(value, dict)) for kind in kinds)
        if not valid or ('values' in spec and value not in spec['values']):
            raise ValueError(f'Invalid extracted value for scenario field {key}')
        if spec['type'] == 'date':
            date.fromisoformat(value)
    return values


@lru_cache(maxsize=None)
def _asset_snapshot(path: str) -> tuple[bytes, str]:
    content = Path(path).read_bytes()
    return content, hashlib.sha256(content).hexdigest()


@lru_cache(maxsize=8)
def _catalogue_at(path: str) -> dict:
    return json.loads(_asset_snapshot(path)[0])


def _catalogue() -> dict:
    return _catalogue_at(str((btc_data_dir() / CATALOG_PATH).resolve()))


def _index_keys() -> tuple[str, str]:
    return (json.dumps(_catalogue(), sort_keys=True, ensure_ascii=False),
            json.dumps(get_models_config().voice.lexicon.get('corrections') or {}, sort_keys=True, ensure_ascii=False))


def metadata() -> dict:
    dictionary = lexicon()
    rules = [(p.pattern, r) for p, r in dictionary._rules]
    return {'version': VERSION, 'contract_fields': sorted(contract()),
            'contract_sha256': _asset_snapshot(str(CONTRACT_PATH.resolve()))[1],
            'asr_aliases': ASR_ALIASES, 'asr_only_fields': sorted(ASR_ONLY),
            'catalogue_sha256': _asset_snapshot(str((btc_data_dir() / CATALOG_PATH).resolve()))[1],
            'asset_lifetime': 'immutable per resolved path for this process; restart to reload replaced files',
            'lexicon_sha256': hashlib.sha256(json.dumps(rules, ensure_ascii=False).encode()).hexdigest(),
            'default_date': _catalogue()['reference_date'],
            'sku_policy': 'catalogue-derived names and complete alphanumeric model codes; existing brand lexicon; spacing tolerant; fuzzy brand only with intact full model; v8: a name misheard after its kind of product matched by sound, a part not taken for the product its name begins, a model alone resolved against the brand and kind just named (dialogue), the last product named wins (dialogue); ambiguous matches omitted',
            'policy': 'surface mentions only; no memory writes or verified business truth; ambiguous values omitted; no catalogue prices/stock inferred'}


def _surface(text: str) -> str:
    text = re.sub(r'(?<=\d)[.,](?=\d)', ' phẩy ', text)
    return re.sub(r'[^\w]+', ' ', plain(text)).strip()


def _identity_pattern(value: str, *, left_boundary: bool = True) -> re.Pattern:
    # ASR can join or split an identifier; outer word boundaries still protect unknown models.
    compact = _surface(value).replace(' ', '')
    number_tail = ''
    last = _surface(value).split()[-1]
    number_words = {_surface(word) for word in (itn.NUMBER_WORDS | {'phẩy'}) - {'không'}}
    if last.isdigit() or (last in number_words and last != 'k'):
        number_tail = r'(?!\s+(?:' + '|'.join(sorted(number_words, key=len, reverse=True)) + r'|khong\s+tram|\d+)\b)'
    return re.compile((r'(?<!\w)' if left_boundary else '') + r'\s*'.join(map(re.escape, compact)) + r'(?!\w)' + number_tail)


def _forms(name: str) -> tuple[str, ...]:
    return name, spoken.catalogue_numbers(name), spoken.catalogue_spoken(name)


def _brand_aliases(brand: str, corrections: dict | None = None) -> set[str]:
    corrections = corrections if corrections is not None else get_models_config().voice.lexicon.get('corrections') or {}
    return {brand} | {key for key, value in corrections.items() if _surface(value) == _surface(brand)}


@lru_cache(maxsize=8)
def _product_patterns(catalogue_json: str | None = None, corrections_json: str | None = None) -> list[tuple[re.Pattern, frozenset[str]]]:
    aliases: dict[str, set[str]] = {}
    catalogue = json.loads(catalogue_json) if catalogue_json is not None else _catalogue()
    corrections = json.loads(corrections_json) if corrections_json is not None else None
    for product in catalogue['products']:
        names = [product['name'], product['sku']]
        # A brand plus its complete model is useful; a brand alone is not an ID.
        brand = product.get('brand', '')
        start = product['name'].lower().find(brand.lower()) if brand else -1
        if start >= 0 and not product['name'].lower().startswith('combo'):
            names.append(product['name'][start:])
            model = product['name'][start + len(brand):].strip()
            # Full model codes can identify a product without its brand. A bare size/unit or X/Pro cannot.
            if re.search(r'\b[A-Za-z]{2,}[- ]?\d', model):
                names.append(model)
        names += [re.sub(re.escape(brand), alias, name, flags=re.IGNORECASE)
                  for name in list(names) for alias in _brand_aliases(brand, corrections) if brand]
        for name in names:
            for form in _forms(name):
                key = _surface(form)
                if key:
                    aliases.setdefault(key, set()).add(product['sku'])
        for variant in product.get('variants', []):
            for form in (variant['variant_sku'], spoken.code_words(variant['variant_sku'])):
                aliases.setdefault(_surface(form), set()).add(variant['variant_sku'])
    return [(_identity_pattern(alias), frozenset(skus))
            for alias, skus in sorted(aliases.items(), key=lambda x: -len(x[0]))]


def _distance(left: str, right: str) -> int:
    row = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        current = [i]
        for j, b in enumerate(right, 1):
            current.append(min(row[j] + 1, current[-1] + 1, row[j - 1] + (a != b)))
        row = current
    return row[-1]


@lru_cache(maxsize=8)
def _model_patterns(catalogue_json: str | None = None, corrections_json: str | None = None) -> list[tuple[str, re.Pattern, frozenset[str]]]:
    result = []
    catalogue = json.loads(catalogue_json) if catalogue_json is not None else _catalogue()
    corrections = json.loads(corrections_json) if corrections_json is not None else None
    for product in catalogue['products']:
        brand = product.get('brand', '')
        start = product['name'].lower().find(brand.lower()) if brand else -1
        if start < 0 or product['name'].lower().startswith('combo'):
            continue
        model = product['name'][start + len(brand):].strip()
        if not model:
            continue
        aliases = frozenset(_surface(alias).replace(' ', '') for alias in _brand_aliases(brand, corrections))
        result.extend((product['sku'], _identity_pattern(form, left_boundary=False), aliases) for form in _forms(model))
    return result


def _fuzzy_brand_product(surface: str) -> str | None:
    codes = set()
    for sku, model, aliases in _model_patterns(*_index_keys()):
        for match in model.finditer(surface):
            before = surface[:match.start()].split()[-4:]
            candidates = {''.join(before[-n:]) for n in range(1, len(before) + 1)}
            if any(len(candidate) >= 3 and abs(len(candidate) - len(alias)) <= 2
                   and _distance(candidate, alias) <= min(2, int(max(len(candidate), len(alias)) * .30))
                   for candidate in candidates for alias in aliases):
                codes.add(sku)
    return next(iter(codes)) if len(codes) == 1 else None


def _sound(text: str) -> str:
    """A rough sound key of toneless text, so ASR spellings of a foreign name compare close ("compi" ~ "combi")."""
    key = text.replace(' ', '')
    for written, heard in (('ph', 'f'), ('th', 't'), ('ch', 'c'), ('tr', 'c'), ('kh', 'k'), ('gi', 'z'), ('qu', 'k'),
                           ('ng', 'n'), ('nh', 'n')):
        key = key.replace(written, heard)
    key = key.translate(str.maketrans('cqbdrjwyx', 'kkpzzzuis')).replace('h', '')
    return re.sub(r'(.)\1+', r'\1', key)


def _kind_and_name(product: dict) -> tuple[str, str]:
    """"Máy lọc không khí AirPure X" -> ("may loc khong khi", "AirPure X"): the kind of product and what names it."""
    words, brand = product['name'].split(), plain(product.get('brand', '')).lower()
    kind = []
    for i, word in enumerate(words):
        if (i and (not word[:1].islower() or not word.isalpha())) or (brand and plain(word).lower() == brand):
            break
        kind.append(word)
    return _surface(' '.join(kind)), re.split(r'\s*[+(]', ' '.join(words[len(kind):]))[0].strip()


@lru_cache(maxsize=8)
def _kinds(catalogue_json: str | None = None, corrections_json: str | None = None) -> dict[str, list[tuple[str, frozenset[str]]]]:
    """Per kind of product, each product's sound keys: its name, spoken, with the brand's known spoken forms."""
    catalogue = json.loads(catalogue_json) if catalogue_json is not None else _catalogue()
    corrections = json.loads(corrections_json) if corrections_json is not None else None
    groups: dict[str, list[tuple[str, str, str]]] = {}
    for product in catalogue['products']:
        if 'NGỪNG BÁN' in product['name'].upper():
            continue  # A discontinued product is named only by its exact name ("bản 2024").
        kind, name = _kind_and_name(product)
        if kind and name:
            groups.setdefault(kind, []).append((product['sku'], product.get('brand', ''), name))
    def keys(names: set[str]) -> frozenset[str]:
        return frozenset({_sound(_surface(form)) for each in names for form in _forms(each) if not re.search(r'\d', form)} - {''})

    out = {}
    for kind, items in groups.items():
        entries = []
        for sku, brand, name in items:
            names = {name}
            if brand and brand.lower() in name.lower():
                names |= {re.sub(re.escape(brand), alias, name, flags=re.IGNORECASE) for alias in _brand_aliases(brand, corrections)}
            if brand and sum(other == brand for _, other, _ in items) == 1:
                names |= {brand} | _brand_aliases(brand, corrections)  # The brand's only one of its kind: the brand names it.
            entries.append((sku, keys(names)))
        # A brand with several products of this kind, said without a model, names none of them ("máy lọc không khí e pia").
        for brand in sorted({brand for _, brand, _ in items if brand and sum(other == brand for _, other, _ in items) > 1}):
            entries.append(('', keys({brand} | _brand_aliases(brand, corrections))))
        out[kind] = entries
    return out


#: Words that end the name after a kind of product ("máy lọc không khí AirPure Pro và ...").
NAME_ENDS = frozenset({'va', 'voi', 'hay', 'hoac', 'con', 'cong', 'nhung', 'thay'})
#: Words that start no product name: "máy lọc không khí cho phòng ...", "xe đẩy của anh".
NOT_A_NAME = frozenset({'cho', 'cua', 'nay', 'do', 'ay', 'kia', 'nao', 'ma', 'em', 'anh', 'chi', 'co', 'chu', 'bac', 'o',
                        'thi', 'la', 'khong', 'nhe', 'nha', 'day', 'a', 'ha', 'nua', 'roi', 'gi', 'tren', 'duoi', 'loai',
                        'nhu', 'de', 'tai', 'ben', 'trong', 'ngoai', 'dang', 'da', 'se', 'van', 'cung', 'moi', 'tot',
                        'nhat', 'gia', 'hang', 'mot', 'hai', 'ba'})
#: Similarity a heard name needs: alone of its kind, among several, and ahead of the next candidate.
SOUND_ALONE, SOUND_AMONG, SOUND_MARGIN = .6, .5, .1


def _heard_product(surface: str) -> str | None:
    """A product named after its kind ("máy lọc không khí epi pro") whose name the ASR misspelled.

    The kind is ordinary Vietnamese, which the recogniser hears well; the name after it is compared by sound
    with each product of that kind. Ambiguous or weak matches are omitted.
    """
    found: dict[str, float] = {}
    surface = _surface(spoken.catalogue_numbers(surface))
    for kind, entries in _kinds(*_index_keys()).items():
        for match in re.finditer(r'(?<!\w)' + re.escape(kind) + r'(?!\w)', surface):
            window = surface[match.end():].split()[:6]
            window = window[:next((i for i, word in enumerate(window) if word in NAME_ENDS), len(window))]
            if not window or window[0] in NOT_A_NAME:
                continue
            heard = [_sound(' '.join(window[:n])) for n in range(1, len(window) + 1)]
            scores = sorted(((max((1 - _distance(said, key) / max(len(said), len(key)) for said in heard for key in keys),
                                  default=0), sku) for sku, keys in entries), reverse=True)
            best, sku = scores[0]
            runner_up = scores[1][0] if len(scores) > 1 else 0
            if sku and best >= (SOUND_ALONE if len(entries) == 1 else SOUND_AMONG) and best - runner_up >= SOUND_MARGIN:
                found[sku] = max(found.get(sku, 0), best)
    return next(iter(found)) if len(found) == 1 else None


def _part_without_its_kind(sku: str, surface: str) -> bool:
    """A part whose name begins another product's ("Màng lọc Xiaomi Smart 4" in "Xiaomi Smart 4 Lite"), its kind unsaid."""
    products = [p for p in _catalogue()['products'] if 'NGỪNG BÁN' not in p['name'].upper()]
    product = next((p for p in products if p['sku'] == sku), None)
    if product is None:
        return False
    kind, name = _kind_and_name(product)
    longer = any(other['sku'] != sku and _kind_and_name(other)[1].lower().startswith(name.lower() + ' ') for other in products)
    return longer and bool(kind) and not re.search(r'(?<!\w)' + re.escape(kind.split()[0]) + r'(?!\w)', surface)


def _model_in_context(text: str, previous: str) -> str | None:
    """"Mẫu X" after AirPure Y was named: the product of the same brand and kind whose model is X."""
    products = [p for p in _catalogue()['products'] if 'NGỪNG BÁN' not in p['name'].upper()]
    before = next((p for p in products if p['sku'] == previous), None)
    if before is None or not before.get('brand'):
        return None
    kind = _kind_and_name(before)[0]
    surface = _surface(text)
    found = set()
    for product in products:
        if product.get('brand') != before['brand'] or _kind_and_name(product)[0] != kind:
            continue
        model = re.sub(re.escape(product['brand']), '', _kind_and_name(product)[1], flags=re.IGNORECASE).strip()
        for form in (_forms(model) if model else ()):
            key = _surface(form)
            if key and re.search(r'\b(?:mau|con|loai|dong|ban|may|cai|doi|chiec)\s+' + r'\s*'.join(map(re.escape, key.replace(' ', '')))
                                 + r'(?!\w)', surface):
                found.add(product['sku'])
    return next(iter(found)) if len(found) == 1 else None


def _product(text: str) -> str | None:
    explicit = {re.sub(r'\s+', '', match.group()) for match in
                re.finditer(r'\bSKU\s*-\s*[A-Z0-9]+(?:\s*-\s*[A-Z0-9]+)*\b', text.upper())}
    if explicit:
        known = {p['sku'] for p in _catalogue()['products']}
        known.update(v['variant_sku'] for p in _catalogue()['products'] for v in p.get('variants', []))
        if not explicit <= known:
            return None
        return next(iter(explicit)) if len(explicit) == 1 else _selected_product(text)
    codes = _named_products(text)
    if codes:
        return next(iter(codes)) if len(codes) == 1 else _selected_product(text)
    return _fuzzy_brand_product(_surface(text)) or _heard_product(text)


def _named_products(text: str) -> set[str]:
    """Every catalogue product *text* names by its exact (spoken) name, parts named without their kind left out."""
    hits = []
    surface = _surface(text)
    for pattern, codes in _product_patterns(*_index_keys()):
        for match in pattern.finditer(surface):
            for i, (start, end, existing) in enumerate(hits):
                if match.span() == (start, end):
                    hits[i] = (start, end, existing | codes)
                    break
                if match.start() < end and start < match.end():
                    break
            else:
                hits.append((*match.span(), codes))
    codes = set().union(*(codes for _, _, codes in hits)) if hits else set()
    return {code for code in codes if not _part_without_its_kind(code, surface)}


def _clauses(text: str) -> list[str]:
    # A question can still state a budget, size or identifier. Decide ambiguity per field.
    sentences = re.findall(r'.+?(?:[!?;\n]|(?<!\d)\.|\.(?!\d)|$)', text)
    return [part for sentence in sentences
            for part in re.split(r',\s*(?!\d)|\b(?:nhưng|tuy nhiên)\b', sentence)
            if part.strip()]


MONEY_CUES = {
    'budget_vnd': r'ngân sách|tài chính|(?:chi|trả) tối đa|(?:có|dành|chi) (?:tầm|khoảng)|lên (?:đến|tới)',
    # v6: where a shopper saw another price ("trên mạng có chỗ bán", "bên ngoài ghi giá").
    'competitor_price_vnd': r'bên kia|bên khác|chỗ khác|nơi khác|đối thủ|shop khác|cửa hàng khác|trên mạng|'
                            r'(?:có )?chỗ bán|bên ngoài|ngoài (?:chợ|siêu thị|cửa hàng)|shopee|lazada|tiki',
    # v6: the shop's own price in a comparison ("sao bên mình lại", "bên em lại") or as quoted ("em báo là").
    'price_vnd': r'giá(?: bán)?|báo giá|(?:em|bên em|shop|cửa hàng) báo(?: là)?|bên (?:mình|em)(?: sao)?(?: lại)?(?: là| bán| giá)?',
    'min_free_ship_vnd': r'(?:đơn|đơn hàng|mua)(?: tối thiểu)? từ|tối thiểu.*?(?:miễn phí|freeship)',
    # v11: "hàng cồng kềnh ngoài nội thành phụ thu 30.000đ": the bulky item named, then what it costs extra.
    'bulky_fee_vnd': r'(?:phụ )?phí (?:hàng )?cồng kềnh|cồng kềnh[^.!?;]{0,40}?(?:phụ thu|phụ phí|thu thêm|tính thêm|cộng thêm)',
    'exchange_fee_vnd': r'phí (?:đổi|đổi trả)(?: hàng)?',
    'refund_vnd': r'(?:hoàn|hoàn lại|hoàn trả)(?: tiền)?',
    # v7: the order's total, and what the customer paid before (neither is a selling or competitor price).
    'total_vnd': r'tổng(?: tiền| cộng| đơn| cả| hóa đơn)?|tất cả là|cả thảy',
    'paid_price_vnd': r'(?:đã|đợt trước|lần trước|hồi trước|trước đây)(?:\s+\w+){0,2}\s+mua(?: (?:là|với giá|giá|hết))?',
}
DURATION_CUES = {
    'warranty_months': r'bảo hành', 'return_days': r'đổi trả|trả hàng',
    # v11: any delivery verb ("giao nội thành", "ship", "nhận được hàng"), not only "giao hàng".
    'delivery_days': r'\bgiao\b|vận chuyển|nhận(?: được)? hàng|\bship\b',
}
BLOCKERS = {
    'can hoi chong': r'(?:hỏi|bàn|trao đổi|tham khảo|xin ý kiến)(?:\s+\w+){0,3}\s+(?:chồng|ông xã)',
    'can hoi vo': r'(?:hỏi|bàn|trao đổi|tham khảo|xin ý kiến)(?:\s+\w+){0,3}\s+(?:vợ|bà xã)',
    # v9: family named by its members ("hỏi ý kiến con cháu", "bàn với bố mẹ").
    'can hoi nguoi nha': r'(?:hỏi|bàn|trao đổi|tham khảo|xin ý kiến|hỏi ý kiến)(?:\s+\w+){0,3}\s+'
                         r'(?:người nhà|gia đình|con cháu|con cái|bố mẹ|ba mẹ|cả nhà)',
    # v9: the shop's price said to be above another's ("giá bên em vẫn cao hơn chỗ khác", "cân nhắc chỗ khác").
    'so sanh gia': r'so sánh (?:giá|thêm)|(?:xem|tham khảo|khảo) giá (?:thêm|chỗ khác|bên khác)|'
                   r'(?:cao|đắt|mắc) hơn (?:chỗ|bên|nơi|shop) khác|cân nhắc (?:thêm )?(?:chỗ|bên|nơi|shop) khác',
    # v9: a price over what was planned ("hơi cao so với dự kiến").
    'vuot ngan sach': r'vượt (?:quá )?ngân sách|quá ngân sách|(?:không|chưa) đủ (?:tiền|ngân sách)|'
                      r'(?:cao|đắt|mắc|vượt) (?:hơn |quá )?(?:so với )?(?:dự kiến|dự tính|khả năng)',
    # v9: up to six words between the wait and the pay ("chờ đến cuối tháng mới nhận lương").
    'cho luong': r'(?:chờ|đợi|đến khi|tới khi|khi nào)(?:\s+\w+){0,6}\s+(?:lương|lĩnh lương|nhận lương)',
    # The same everyday intents documented by MemoryAgent's independent rule fallback; v9: "nghĩ thêm".
    'can suy nghi them': r'suy nghĩ (?:thêm|đã|lại)|cân nhắc (?:thêm|đã|lại)|(?:cần|muốn|để (?:chị|anh|em|mình|tôi)) suy nghĩ|'
                         r'để (?:chị|anh|em|mình|tôi) (?:xem|nghĩ|tính)\b|(?<!suy )nghĩ thêm',
}
SIZE = r'(?:\d{1,3}|xxxl|xxl|xxs|xl|xs|s|m|l)'


def _negated(prefix: str) -> bool:
    return bool(re.search(r'\b(?:không|chẳng|chưa)(?:\s+(?:cần|muốn|chọn|lấy|mua|đặt|chốt|đổi|dùng|phải|là|có|còn|định|thanh toán|trả tiền|qua|bằng|tư vấn))*\s*$', prefix))


def _selected_product(text: str) -> str | None:
    selected = []
    for cue in re.finditer(r'\b(?:chọn|lấy|đặt|mua|chốt|đổi sang)\s+', text, re.IGNORECASE):
        if _negated(text[:cue.start()].lower()):
            continue
        tail = text[cue.end():]
        end = re.search(r'[,;.!?\n]|\b(?:thay vì|chứ không|hay|hoặc|và|nhưng)\b', tail, re.IGNORECASE)
        if end and end.group().lower() in {'hay', 'hoặc', 'và'}:
            continue
        candidate = _product(tail[:end.start()] if end else tail)
        if candidate:
            selected.append(candidate)
    return selected[-1] if selected else None


def _yes_no_tail(text: str) -> bool:
    return bool(re.match(r'\s*(?:hay chưa|không)(?:\s+(?:em|anh|chị|ạ|nhỉ))?\s*[?!.]*\s*$', text))


def _uncertain(prefix: str) -> bool:
    return bool(re.search(r'\b(?:nếu|giả sử|có thể|có lẽ|chưa chắc|không chắc|không biết)\b', prefix))


def _conditional(prefix: str) -> bool:
    """Inside an unfinished "nếu ..." (no "thì" yet): "nếu chị cần suy nghĩ thêm" states nothing.

    v9: a blocker is itself hesitation, so "chưa chắc, cần suy nghĩ thêm" and "nếu không có thì chị sẽ cân
    nhắc thêm" still state it; a payment asked as "có thể thanh toán qua chuyển khoản không" still names it.
    """
    return bool(re.search(r'\b(?:nếu|giả sử)\b(?:(?!\bthì\b)[^.!?;])*$', prefix))


def _resolved(clause: str, start: int, end: int) -> bool:
    """A completed consultation is no longer a pending purchase blocker."""
    before, after = clause[:start], clause[end:]
    pending = re.search(r'\b(?:cần|phải|sẽ|định|đợi|chờ|chưa)\b[^.!?;]*$', before)
    return not pending and bool(re.search(r'\bđã\b[^.!?;]*$', before) or re.match(r'\s+xong\b', after))


def _children(clause: str) -> bool | None:
    if re.search(r'\bnếu\b', clause):
        return None
    noun = r'(?:trẻ nhỏ|trẻ em|con nhỏ|em bé|bé(?: nhỏ)?)'
    mentions = list(re.finditer(r'\bcó\s+(?:(?:\d+|một|hai|ba)\s+)?(?:đứa\s+)?' + noun + r'\b', clause))
    if mentions:
        match = mentions[-1]
        if not _yes_no_tail(clause[match.end():]):
            return not _negated(clause[:match.start()])
    if re.search(r'(?:bé|con)\s+(?:nhà |của )?(?:tôi|mình|anh|chị|em|cô|chú|bác)\s+\d+\s*(?:tháng|tuổi)\b', clause):
        return True
    return None


def _size_cues(text: str) -> str:
    if not re.search(r'giày|áo|quần|váy|đầm|mặc|mang|đôi|cỡ', text):
        return text
    def replace(match):
        word = match[1]
        sound = re.sub(r'c(?=[iey])', 's', word).replace('z', 's').replace('y', 'i')
        # v9: "side", "sies", "site", "cit", "cy" are how the recogniser writes "size" before a size.
        if sound == 'sise' or re.fullmatch(r'sai[sz]?', word) or re.fullmatch(r'si(?:[ds]e?|te?|es)?', sound):
            return 'size ' + match[2]
        return match.group()
    return re.sub(r'\b([a-z]{3,5})\s+(' + SIZE + r')\b(?!\s*(?:ngày|giờ|lần|đồng|triệu|tháng)\b)', replace, text)


def _payment(clause: str) -> str | None:
    choices = {kind for kind, pattern in [
        # v9: "c o d" / "ceo d" as the recogniser splits it; cash on delivery ("tiền mặt khi giao hàng").
        # "thanh toán qua ngân hàng và giao hàng ở ..." names a delivery place, not cash on delivery: "giao" needs "khi/lúc".
        ('COD', r'\bc+o+d+\b|\b(?:c|ce|xe)\s*[oô]\s+(?:d|đê|dê)\b|\bceo\s+d\b|thu hộ|nhận hàng[^.!?;]{0,35}trả tiền|'
                r'(?:tiền mặt|trả tiền|thanh toán)[^.!?;]{0,35}(?:khi )?nhận hàng|(?:khi|lúc) giao hàng[^.!?;]{0,20}trả tiền|'
                r'(?:trả tiền|thanh toán)[^.!?;]{0,20}(?:khi|lúc) giao hàng|tiền mặt'),
        # v9: "hình thức thanh toán là qua ngân hàng".
        ('bank', r'chuyển khoản|\bbanking\b|\bbank\b|(?:thanh toán|trả tiền)[^.!?;]{0,20}(?:qua|bằng)\s+ngân hàng'),
        ('momo', r'\bmomo\b'), ('zalopay', r'\bzalopay\b')]
        for m in re.finditer(pattern, clause)
        if not _negated(clause[:m.start()]) and not _conditional(clause[:m.start()])
        and not re.search(r'\b(?:có lẽ|chưa chắc|không chắc|không biết)\b', clause[:m.start()])}
    return next(iter(choices)) if len(choices) == 1 else None


def _money(clause: str, found: dict, active_field: str | None = None) -> str | None:
    clause = clause.lower()
    correction = r'\s*(?:à\s+không|ờ\s+không|mà\s+là|chứ\s+là|xin lỗi|đính chính|sửa lại|đổi thành|giảm (?:còn|xuống)|tăng lên|nâng lên|hạ xuống|mà\s+(?:hôm nay|bây giờ|giờ|nay)(?:\s+lại)?(?:\s+là)?)\b'
    negation = r'\b(?:không|chẳng|chưa)(?:\s+(?:phải|là|có|đủ|được|cần|muốn|chi|trả|dành|giá|ngân sách|tài chính|báo|bán|mất|thu|tính|phí|cho))*\s*$'
    connector = r'(?:đến|tới|[-–—]|hoặc|hay)'
    amounts = itn.money_spans(clause)
    for match in re.finditer(r'(?<![\w.,])(\d{1,3})\s*(?:đồng|đ|vnđ|vnd)(?![a-zà-ỹ])', clause):
        if all(match.end() <= span.start or match.start() >= span.end for span in amounts):
            amounts.append(itn.Span(match.start(), match.end(), match.group(), int(match[1])))
    amounts.sort()
    if not amounts:
        active_field = None
    previous_end = 0
    for index, amount in enumerate(amounts):
        segment = clause[previous_end:amount.start]
        after = clause[amount.end:]
        previous_end = amount.end
        candidates = [(m.end(), key) for key, pattern in MONEY_CUES.items()
                      for m in re.finditer(pattern, segment)
                      if len(segment) - m.end() < 85]
        correcting = bool(re.match(correction, segment) or
                          (re.match(r'\s*mà\b', segment) and re.search(r'\b(?:không|chẳng|chưa)\s+phải\b', clause[:amount.start])))
        range_end = bool(re.search(r'\d+(?:[.,]\d+)?\s*' + connector + r'\s*$', segment))
        range_start = bool(re.match(r'\s*' + connector + r'\s*\d', after))
        if index and re.fullmatch(r'\s*' + connector + r'\s*', segment):
            range_end = True
        if re.match(r'\s*(?:đồng\s+)?(?:ngân sách|tài chính)\b', after) or (
                not candidates and re.search(r'(?:tầm|khoảng|có|chi|dành)\s*$', segment)
                and re.match(r'\s*(?:thôi|là đủ|là được|trở xuống|đổ lại)\b', after)):
            # The cue after the amount names it; "chỉ có X thôi" after a competitor or price cue stays theirs.
            candidates.append((len(segment) + 1, 'budget_vnd'))
        if candidates:
            _, key = max(candidates)
            # Ownership qualifies a price; a later explicit budget/fee starts a new purpose.
            owners = [end for end, name in candidates if name == 'competitor_price_vnd']
            purposes = [end for end, name in candidates if name not in {'price_vnd', 'competitor_price_vnd', 'paid_price_vnd'}]
            if key == 'price_vnd' and owners and max(owners) > max(purposes, default=-1):
                key = 'competitor_price_vnd'
            active_field = key
        elif active_field and (correcting or range_end):
            key = active_field
        else:
            active_field = None
            continue
        if range_start or range_end:
            found.pop(key, None)  # An interval/alternative cannot become an exact scalar.
            continue
        if re.search(r'\b(?:nếu|giả sử|có thể|có lẽ|chưa chắc|không chắc|không biết)\b', segment) and not (
                key == 'budget_vnd' and re.search(r'có thể (?:chi |trả )?lên (?:đến|tới)\s*$', segment)):
            continue  # "có thể lên đến X" states a ceiling, not a guess.
        if not correcting and re.search(negation, segment):
            if found.get(key) == amount.value:
                found.pop(key)
            continue
        if key not in {'budget_vnd', 'min_free_ship_vnd'} and re.search(r'\b(?:hơn|dưới|trên|từ|ít nhất|tối thiểu|tối đa|không quá|không dưới|không vượt quá)\s*$', segment):
            continue
        if re.search(r'(?:rẻ|đắt|cao|thấp)(?: hơn| kém)?\s*$|(?:giảm|chênh(?: lệch)?)(?: hơn)?\s*$', segment):
            continue  # A price difference is not a selling/competitor price.
        if key == 'min_free_ship_vnd' and not re.search(r'miễn phí (?:giao|vận chuyển)|miễn phí ship|freeship', clause):
            continue
        found[key] = amount.value
    free = r'miễn phí|không (?:mất|thu|tính) phí'
    for key, cue in [('exchange_fee_vnd', r'đổi(?: trả)?(?: hàng)?'),
                     ('bulky_fee_vnd', r'(?:hàng )?cồng kềnh')]:
        for match in re.finditer(r'(?:' + cue + r')(?P<gap>[^.!?;\d]{0,25})(?P<free>' + free + r')|(?P<before>' + free + r')\s+(?:cho\s+)?(?:' + cue + r')', clause):
            start = match.start('free') if match['free'] else match.start('before')
            if not re.search(negation, clause[:start]) and not _uncertain(clause) and not re.search(r'giao hàng|vận chuyển|ship', match['gap'] or ''):
                found[key] = 0
                active_field = key
    return active_field


def _dates(clause: str, year: int, found: dict) -> None:
    candidates = []
    for m in re.finditer(r'\b(\d{4})-(\d{2})-(\d{2})\b(?![.,]\d)', clause):
        candidates.append((m.start(), (int(m[1]), int(m[2]), int(m[3]))))
    for m in re.finditer(r'\b(?:ngày\s+)?(\d{1,2})(?:\s+tháng\s+|/)(\d{1,2})(?:(?:\s+năm\s*:?\s*|/)(\d{4}))?\b', clause):
        if (not m[3] and re.match(r'\s*(?:năm\b|/)', clause[m.end():])) or re.match(r'\d|/|[.,]\d|\s+\d', clause[m.end():]):
            continue  # An explicitly malformed year is not an omitted year.
        candidates.append((m.start(), (int(m[3]) if m[3] else year, int(m[2]), int(m[1]))))
    for start, parts in sorted(candidates):
        prefix = clause[:start]
        keys = [(m.end(), key) for key, cue in [('promo_expiry', r'khuyến mãi|ưu đãi|hết hạn|hạn chót'),
                                               ('restock_date', r'nhập (?:lại )?hàng|hàng về|về hàng|có hàng (?:lại|vào)')]
                for m in re.finditer(cue, prefix)]
        if keys:
            try:
                found[max(keys)[1]] = date(*parts).isoformat()
            except ValueError:
                pass


def _mentions(text: str, *, now: datetime | None = None, previous_size: int | str | None = None) -> dict:
    """Return only explicit scalar ASR-schema values; never fill from catalogue facts."""
    now = now or datetime.fromisoformat(_catalogue()['reference_date'])
    corrected, _ = lexicon().correct(text)
    corrected = spoken.dates(corrected.lower(), now.year)
    corrected = spoken.size_letters(corrected)
    corrected = re.sub(r'\b(?:cê|xê)\s+(?:ô|o)\s+(?:đê|dê)\b', 'cod', corrected)
    corrected = re.sub(r'\b(?:ô|o)\s+(?:đê|dê|d)\s+', 'ô đê ', corrected)
    spoken_phones = spoken.phones(corrected)
    # Keep the year marker outside the spoken-number run (năm also means five).
    corrected = re.sub(r'\bnăm\s+(?=(?:hai|một)\s+(?:nghìn|ngàn))', 'năm: ', corrected.lower())
    words = '|'.join(sorted((itn.NUMBER_WORDS - itn.SCALES.keys()), key=len, reverse=True))
    def counted(match):
        if match[2] == 'năm' and re.match(r'\s+(?:mươi|trăm|nghìn|ngàn|triệu|tỷ|tỉ|phẩy)\b', match.string[match.end():]):
            return match.group()  # "năm" inside a money/count phrase means five, not years.
        value = itn.parse_number(match[1].split())
        return f'{value} {match[2]}' if value is not None else match.group()
    corrected = re.sub(r'\b((?:(?:' + words + r')\s+)+)(năm|tháng|ngày)\b', counted, corrected)
    written = spoken.size_letters(_size_cues(itn.normalise(corrected, now)))
    found = {}
    money_role = None
    earlier_size = previous_size
    for clause in _clauses(written):
        money_role = _money(clause, found, money_role)
        _dates(clause, now.year, found)
        # v11: a room's size without "vuông" ("phòng hai mươi lăm mét", "diện tích 20 m").
        for m in re.finditer(r'(?<![\w.,])([0-9]+(?:[.,][0-9]+)?)\s*(?:mét vuông|m2|m²)\b|'
                             r'(?:phòng|diện tích|rộng)(?:\s+(?:khoảng|tầm|chừng|cỡ|chị|anh|em|mình|tôi|nhà|ngủ|khách|của))*\s+'
                             r'([0-9]+(?:[.,][0-9]+)?)\s*(?:mét|m)\b(?!\s*(?:vuông|khối|dài|cao)\b)', clause):
            value = Decimal((m[1] or m[2]).replace(',', '.'))
            if value == value.to_integral_value() and not _negated(clause[:m.start()]):
                found['room_area_m2'] = int(value)
        children = _children(clause)
        if children is not None:
            found['has_children'] = children
        payment = _payment(clause)
        if payment in {'COD', 'bank'}:
            found['payment'] = payment
        for start, end, value in sorted((m.start(), m.end(), value) for value, pattern in BLOCKERS.items()
                                    for m in re.finditer(pattern, clause)):
            consultation_done = (value.startswith('can hoi') or value == 'can suy nghi them') and _resolved(clause, start, end)
            if _negated(clause[:start]) or consultation_done:
                if found.get('blocker') == value:
                    found.pop('blocker')
            elif not _conditional(clause[:start]):
                found['blocker'] = value
        sizes = [m for m in re.finditer(r'\b(?:size|cỡ)\s+(?:(cũ|đang mặc|hiện tại|đang dùng|từ)\s+)?(' + SIZE + r')\b', clause)
                 if not _negated(clause[:m.start()])]
        target = re.search(r'\b(?:sang|thành|lên|xuống)\s+(?:(?:size|cỡ)\s+)?(' + SIZE + r')\b', clause)
        # v11: a change said without the word size ("đổi lên bốn mươi mốt") is still a size when the verb is a change.
        changed = target if target and (re.search(r'\b(?:size|cỡ)\b', target.group())
                                        or re.search(r'\b(?:đổi|chuyển|thay)\b(?:\s+\w+){0,2}\s*$', clause[:target.start()])) else None
        if changed and re.search(r'\b(?:không|chưa|chẳng)\b[^.!?;]*$', clause[:changed.start()]):
            changed = None  # "Không đổi size 46 sang 47" changes nothing.
        if sizes and re.search(r'\b(?:hay|hoặc|đến)\b', clause[sizes[0].end():]) and not target:
            sizes = []
        value = lambda raw: int(raw) if raw.isdigit() else raw.upper()
        if sizes or changed:
            if target and (sizes or changed):
                if sizes and sizes[0].start() < target.start():
                    found['size_old'] = value(sizes[0][2])
                elif earlier_size is not None and earlier_size != value(target[1]):
                    # v11: the size said in an earlier clause or turn is the one being changed from.
                    found['size_old'] = earlier_size
                found['size_new'] = value(target[1])
            else:
                old = (sizes[-1][1] or re.search(r'(?:đang mặc|đang mang|đang dùng|hiện tại)\s*$', clause[:sizes[-1].start()])
                       # v11: a size that does not fit is the one the customer has ("size 40 hơi chật").
                       or re.match(r'\s*(?:\w+\s+){0,2}(?:hơi |quá |bị |khá |rất )?(?:chật|rộng|nhỏ|to|bó|lỏng|không vừa|chưa vừa)\b',
                                   clause[sizes[-1].end():]))
                found['size_old' if old else 'size_new'] = value(sizes[-1][2])
            earlier_size = found.get('size_new', found.get('size_old'))
        colors = list(re.finditer(r'\bmàu\s+(xanh navy|xanh than|xanh dương|xanh lá|đen|trắng|xám|ghi|navy|be|đỏ|hồng|nâu|vàng|black|white|gray)\b', clause))
        if colors and re.search(r'\b(?:hay|hoặc)\b', clause[colors[0].end():]):
            colors = []
        for m in colors:
            color = {'xanh navy': 'navy', 'xanh than': 'navy', 'ghi': 'xam',
                     'black': 'den', 'white': 'trang', 'gray': 'xam'}.get(m[1], plain(m[1]).replace(' ', '_'))
            if _negated(clause[:m.start()]):
                if found.get('color') == color:
                    found.pop('color')
            else:
                found['color'] = color
        for key, cue in DURATION_CUES.items():
            # v11: a range ("một đến 2 ngày", "2-3 ngày") counts by its upper bound.
            for m in re.finditer('(?:' + cue + r')[^.!?;\d]{0,45}?(?:\d+\s*(?:đến|tới|-|–|hoặc|hay)\s*)?(\d+)\s*(ngày|tháng|năm)\b', clause):
                if key == 'warranty_months' and m[2] in {'tháng', 'năm'}:
                    found[key] = int(m[1]) * (12 if m[2] == 'năm' else 1)
                elif key != 'warranty_months' and m[2] == 'ngày':
                    found[key] = int(m[1])
        stocks = list(re.finditer(r'chưa hết hàng|không hết hàng|không còn hàng|chưa có hàng|hết hàng|tạm hết|còn hàng|có sẵn hàng', clause))
        if stocks:
            stock = stocks[-1]
            if not _yes_no_tail(clause[stock.end():]) and not _uncertain(clause[:stock.start()]):
                found['in_stock'] = stock.group() in {'chưa hết hàng', 'không hết hàng', 'còn hàng', 'có sẵn hàng'}
    phones = set()
    for m in re.finditer(r'(?<![\w])(?:\+84|0)\d[\d .()-]{7,15}\d(?!\w)', written):
        markers = list(re.finditer(r'điện thoại|sđt|số liên hệ|tài khoản|cccd|căn cước|cmnd|mã (?:đơn|giao dịch|vận đơn)',
                                   written[max(0, m.start() - 60):m.start()]))
        if markers and markers[-1].group() not in {'điện thoại', 'sđt', 'số liên hệ'}:
            continue
        if number := normalise_phone(m.group()):
            phones.add(number)
    phones |= spoken_phones
    for kind, number in spoken.identifiers(corrected).items():
        found[kind] = number  # Never a phone: ID card and bank account numbers are their own fields.
        phones.discard(number)
    if len(phones) == 1:
        found['phone'] = next(iter(phones))
    orders = set(re.findall(r'\bOD\d{3,12}\b', re.sub(r'\bod\s+(\d+)', r'OD\1', written, flags=re.IGNORECASE), re.IGNORECASE))
    if len(orders) == 1:
        found['order_id'] = next(iter(orders)).upper()
    sku = _product(corrected)
    if sku:
        found['sku'] = sku
        if 'price_vnd' in found:
            paired = _priced_products(written)
            if len(set(paired.values())) > 1 and sku in paired:
                found['price_vnd'] = paired[sku]  # "Y thì 5.200.000, còn X là 4.800.000": Y's price, not the last one.
    return found


def _priced_products(written: str) -> dict[str, int]:
    """Each product named in a clause with the first amount that follows it, when a clause names several."""
    out: dict[str, int] = {}
    for clause in _clauses(written):
        start = 0
        for span in itn.money_spans(clause):
            product = _product(clause[start:span.start])
            if product and product not in out:
                out[product] = span.value
            start = span.end
    return out


def scenario_entities(text: str, *, now: datetime | None = None) -> dict:
    """Contract-named surface observations, not approved facts or memory writes."""
    return observe(text, now=now)['scenario_entities']


def _scenario(mentions: dict, text: str, *, speaker: str | None = None) -> dict:
    values = {ASR_ALIASES.get(key, key): value for key, value in mentions.items() if key not in ASR_ONLY | {'sku'}}
    if 'sku' in mentions:
        # Roles must be attached to the same mention, never a different product in the dialogue.
        for clause in _clauses(text.lower()):
            if _product(clause) != mentions['sku']:
                continue
            for key, cue in [('owned_sku', r'đã mua|đang dùng|đang sử dụng|sở hữu'),
                             ('alt_suggested', r'(?:gợi ý|đề xuất)(?: thêm)?(?: mẫu)? thay thế|gợi ý thêm'),
                             ('product_advised', r'tư vấn|giới thiệu|đề xuất')]:
                role = re.search(cue, clause)
                if role and not (_negated(clause[:role.start()]) or _uncertain(clause[:role.start()])
                                 or re.search(r'\b(?:muốn|cần|nhờ|hãy|xin|được)(?:\s+\w+){0,3}\s*$', clause[:role.start()])
                                 or re.search(r'\b(?:không|chưa)(?:\s+ạ)?\s*[?!]*\s*$', clause)):
                    values[key] = mentions['sku']
                    break
        variants = {v['variant_sku'] for p in _catalogue()['products'] for v in p.get('variants', [])}
        selected = _selected_product(text)
        if selected == mentions['sku']:
            if selected in variants:
                values['variant_sku'] = selected
            else:
                product = next((p for p in _catalogue()['products'] if p['sku'] == selected), None)
                # Resolve an identity only from explicitly stated size and colour, not stock/price.
                if product and 'size_new' in mentions and 'color' in mentions:
                    matching = [v['variant_sku'] for v in product.get('variants', [])
                                if str(v.get('size')) == str(mentions['size_new']) and v.get('color') == mentions['color']]
                    if len(matching) == 1:
                        values['variant_sku'] = matching[0]
    if 'price_vnd' in mentions and (speaker or '').lower() in {'a', 'agent', 'assistant', 'advisor'}:
        values['price_quoted_vnd'] = mentions['price_vnd']
    if 'phone_provided' in values:
        values['phone_provided'] = True  # The team's contract forbids raw phones in memory.
    if 'size_old' in mentions:
        values['superseded'] = {'size': mentions['size_old']}
    return _validate(values)


def commerce(text: str, *, now: datetime | None = None) -> dict:
    """ASR-schema compatibility adapter; canonical names are exposed by scenario_entities."""
    return observe(text, now=now)['asr_entities']


def observe(text: str, *, now: datetime | None = None, speaker: str | None = None,
            previous_size: int | str | None = None) -> dict:
    """*previous_size*: a size an earlier turn stated, so "đổi lên 41" here makes it the size changed from."""
    mentions = _mentions(text, now=now, previous_size=previous_size)
    values = _scenario(mentions, text, speaker=speaker)
    clock = now or datetime.fromisoformat(_catalogue()['reference_date'])
    written = itn.normalise(text.lower(), clock)
    for clause in _clauses(written):
        quantity = re.search(r'(?:số lượng|(?:mua|lấy|đặt)\s+(?:thêm\s+)?)(\d+)\s*(?:cái|chiếc|đôi|bộ|sản phẩm)\b', clause)
        if quantity:
            values['quantity'] = int(quantity[1])
        age = re.search(r'(?:bé|con|trẻ)(?:\s+\w+){0,2}\s+(\d+)\s*(tháng|tuổi)\b', clause)
        if age:
            values['child_age_months'] = int(age[1]) * (12 if age[2] == 'tuổi' else 1)
        channel = re.search(r'(?:liên hệ|nhắn|gọi)(?:\s+\w+){0,3}\s+(zalo|hotline|fanpage)\b', clause)
        if channel:
            values['preferred_channel'] = {'zalo': 'zalo_oa', 'hotline': 'hotline', 'fanpage': 'chat_fanpage'}[channel[1]]
        payment = _payment(clause)
        if payment:
            values['payment'] = payment
    return {'scenario_entities': _validate(values), 'asr_entities': mentions}


#: v11: "để anh cân nhắc thêm" after the customer compared prices is the comparison, as the organisers label it.
COMPARED_THEN_HESITATED = 'so sanh gia'


def observe_turns(turns: list[tuple[str, datetime | None, str | None]]) -> list[dict]:
    """One observation per turn (text, clock, speaker), for the organisers' strict per-turn entity accuracy.

    v10: each turn is read alone, except that a model said alone ("dạ mẫu x là ...") is read against the
    brand and kind of the product a previous turn named, as a listener would.
    """
    previous, size, compared, out = None, None, False, []
    for text, now, speaker in turns:
        observed = (observe(text, now=now, speaker=speaker) if size is None
                    else observe(text, now=now, speaker=speaker, previous_size=size))
        found = observed['asr_entities']
        size = found.get('size_new', found.get('size_old', size))
        if found.get('blocker') == 'can suy nghi them' and compared:
            found['blocker'] = COMPARED_THEN_HESITATED
        compared = compared or 'competitor_price_vnd' in found or found.get('blocker') == 'so sanh gia'
        named = _named_products(text)
        if 'sku' not in observed['asr_entities'] and not named and previous:
            found = _model_in_context(text, previous)
            if found:
                observed['asr_entities']['sku'] = found
        if 'sku' in observed['asr_entities']:
            named = {observed['asr_entities']['sku']}
        if named:
            previous = sorted(named)[0]  # Context is the brand and kind; any product named carries them.
        out.append(observed)
    return out


def observe_dialogue(text: str, *, now: datetime | None = None) -> dict:
    """One value per field for a whole dialogue: the value its clauses state most often, the latest on a tie.

    v10: the organisers' dialogue-level labels keep every value a field took, in order (``entities_multi``),
    and any one of them is correct. So a dialogue that names several products or prices answers with one
    it named rather than abstaining; a clause naming two products votes for both. Only actual clause
    boundaries and explicit selection cues are used, never reference turns or labels.
    """
    result = observe(text, now=now)
    whole = dict(result['asr_entities'])
    votes: dict[str, dict] = {}   # field -> value -> [count, latest position]

    def vote(field: str, value, position: int) -> None:
        seen = votes.setdefault(field, {}).setdefault(json.dumps(value, ensure_ascii=False, sort_keys=True), [0, position, value])
        seen[0] += 1
        seen[1] = max(seen[1], position)

    for field, value in result['asr_entities'].items():
        if field != 'sku':  # Products are counted per clause below.
            vote(field, value, -1)  # The whole text sees values that span clauses; a clause's own value wins a tie.
    previous = None
    for position, clause in enumerate(_clauses(text)):
        current = observe(clause, now=now)
        for field, value in current['asr_entities'].items():
            if field != 'sku':
                vote(field, value, position)
        # v8: "dạ mẫu x là ..." after AirPure Y names AirPure X.
        named = ({current['asr_entities']['sku']} if 'sku' in current['asr_entities']
                 else _named_products(clause) or ({found} if previous and (found := _model_in_context(clause, previous)) else set()))
        for sku in sorted(named):
            vote('sku', sku, position)
        if len(named) == 1:
            previous = next(iter(named))
        for key in ('owned_sku', 'alt_suggested', 'product_advised', 'variant_sku'):
            if key in current['scenario_entities']:
                result['scenario_entities'][key] = current['scenario_entities'][key]
    for field, values in votes.items():
        result['asr_entities'][field] = max(values.values(), key=lambda item: (item[0], item[1]))[2]
    if 'size_old' in whole:
        # v11: a change of size spans clauses ("size 40 hơi chật ... đổi lên 41"); only the whole text sees both.
        result['asr_entities'].update({key: whole[key] for key in ('size_old', 'size_new') if key in whole})
    found = result['asr_entities']
    if found.get('blocker') == 'can suy nghi them' and ('competitor_price_vnd' in found
                                                        or json.dumps('so sanh gia') in votes.get('blocker', {})):
        found['blocker'] = COMPARED_THEN_HESITATED
    selected = _selected_product(text)
    if selected:
        result['asr_entities']['sku'] = selected
    if 'phone' in result['asr_entities']:
        result['scenario_entities']['phone_provided'] = True
    return result
