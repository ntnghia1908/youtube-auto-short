"""SR1.5: VNI-Windows -> Unicode table (S5a). Spec written out letter by letter, checked against Unicode NFC."""

import unicodedata

from auto_short.sutra import pdf, vni

# (VNI spelling, Unicode letter), lower case. Tone order everywhere: acute, grave, hook, tilde, dot.
LOWER = [
    # a, ă, â
    ("aù", "á"), ("aø", "à"), ("aû", "ả"), ("aõ", "ã"), ("aï", "ạ"),
    ("aê", "ă"), ("aé", "ắ"), ("aè", "ằ"), ("aú", "ẳ"), ("aü", "ẵ"), ("aë", "ặ"),
    ("aâ", "â"), ("aá", "ấ"), ("aà", "ầ"), ("aå", "ẩ"), ("aã", "ẫ"), ("aä", "ậ"),
    # e, ê
    ("eù", "é"), ("eø", "è"), ("eû", "ẻ"), ("eõ", "ẽ"), ("eï", "ẹ"),
    ("eâ", "ê"), ("eá", "ế"), ("eà", "ề"), ("eå", "ể"), ("eã", "ễ"), ("eä", "ệ"),
    # i
    ("iù", "í"), ("iø", "ì"), ("æ", "ỉ"), ("ó", "ĩ"), ("ò", "ị"),
    # o, ô, ơ
    ("où", "ó"), ("oø", "ò"), ("oû", "ỏ"), ("oõ", "õ"), ("oï", "ọ"),
    ("oâ", "ô"), ("oá", "ố"), ("oà", "ồ"), ("oå", "ổ"), ("oã", "ỗ"), ("oä", "ộ"),
    ("ô", "ơ"), ("ôù", "ớ"), ("ôø", "ờ"), ("ôû", "ở"), ("ôõ", "ỡ"), ("ôï", "ợ"),
    # u, ư
    ("uù", "ú"), ("uø", "ù"), ("uû", "ủ"), ("uõ", "ũ"), ("uï", "ụ"),
    ("ö", "ư"), ("öù", "ứ"), ("öø", "ừ"), ("öû", "ử"), ("öõ", "ữ"), ("öï", "ự"),
    # y, đ
    ("yù", "ý"), ("yø", "ỳ"), ("yû", "ỷ"), ("yõ", "ỹ"), ("î", "ỵ"),
    ("ñ", "đ"),
]


def test_table_covers_every_vietnamese_letter():
    got = {u for _, u in LOWER}
    wanted = set(pdf._VOWELS) | {"đ"}
    plain = set("aeiouy")
    assert wanted - plain <= got
    assert all(unicodedata.is_normalized("NFC", u) for u in got)


def test_every_lower_case_letter():
    for src, want in LOWER:
        assert vni.convert(src) == want, (src, want)


def test_every_upper_case_letter_either_modifier_case():
    for src, want in LOWER:
        assert vni.convert(src.upper()) == want.upper(), (src, want)
        mixed = src[0].upper() + src[1:]  # capital letter, modifier as typed in lower case
        assert vni.convert(mixed) == want.upper(), (mixed, want)


def test_letters_inside_words_and_nfc_output():
    assert vni.convert("Vieät Nam") == "Việt Nam"
    assert vni.convert("Nhö vaäy") == "Như vậy"
    assert vni.convert("ÑAÏO VIEÄT") == "ĐẠO VIỆT"
    assert vni.convert("thöôøng") == "thường"
    assert vni.convert("quoác khaùnh, 12 nam!") == "quốc khánh, 12 nam!"
    out = vni.convert("Phaät Xaù Lôïi Phaát")
    assert out == "Phật Xá Lợi Phất"
    assert unicodedata.is_normalized("NFC", out)


def test_unmodified_and_foreign_characters_are_kept():
    assert vni.convert("") == ""
    assert vni.convert("abc xyz 123 .,;") == "abc xyz 123 .,;"
    assert vni.convert("a") == "a"  # last character with nothing after it
    assert vni.convert("ùø") == "ùø"  # a tone character with no vowel before it
    assert vni.convert("中文 a") == "中文 a"
    assert vni.convert("bu") == "bu"
