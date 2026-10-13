"""VNI-Windows (old VNI fonts, e.g. ``VNI-Times``) text -> Unicode (NFC). Pure; no Auto Short imports.

VNI writes a Vietnamese letter as a base Latin vowel followed by one modifier character from the Latin-1 range:

* tone after a plain vowel (also after ``ô`` = ơ and ``ö`` = ư): ``ù`` acute, ``ø`` grave, ``û`` hook, ``õ`` tilde,
  ``ï`` dot;
* ``â`` after a / e / o = circumflex (â ê ô); after a / e / o the circumflex+tone letters ``á à å ã ä``;
* ``ê`` after a = breve (ă); after a the breve+tone letters ``é è ú ü ë``;
* single characters: ``ô`` = ơ, ``ö`` = ư, ``ñ`` = đ, ``æ`` = ỉ, ``ó`` = ĩ, ``ò`` = ị, ``î`` = ỵ.

Case follows the character it modifies (``Ñ`` = Đ, ``PHAÄT`` = PHẬT); the modifier itself is matched ignoring case.
"""

from __future__ import annotations

import unicodedata

_ACUTE, _GRAVE, _HOOK, _TILDE, _DOT = "́", "̀", "̉", "̃", "̣"
_CIRC, _BREVE = "̂", "̆"
_TONE = {"ù": _ACUTE, "ø": _GRAVE, "û": _HOOK, "õ": _TILDE, "ï": _DOT}
_CIRC_TONE = {"á": _ACUTE, "à": _GRAVE, "å": _HOOK, "ã": _TILDE, "ä": _DOT}
_BREVE_TONE = {"é": _ACUTE, "è": _GRAVE, "ú": _HOOK, "ü": _TILDE, "ë": _DOT}
_SINGLE = {"ô": "ơ", "ö": "ư", "ñ": "đ", "æ": "ỉ", "ó": "ĩ", "ò": "ị", "î": "ỵ"}
_TONED_SINGLE = frozenset("ôö")  # ơ / ư take a tone character after them


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def convert(s: str) -> str:
    """VNI-Windows text -> Unicode NFC. Characters that are not part of a VNI pair are kept."""
    out: list[str] = []
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        lc = c.lower()
        ln = s[i + 1].lower() if i + 1 < n else ""
        if lc in _SINGLE:
            base = _SINGLE[lc]
            if c.isupper():
                base = base.upper()
            if lc in _TONED_SINGLE and ln in _TONE:
                out.append(_nfc(base + _TONE[ln]))
                i += 2
            else:
                out.append(base)
                i += 1
            continue
        if ln:
            if lc in "aeo":
                if ln == "â":
                    out.append(_nfc(c + _CIRC))
                    i += 2
                    continue
                if ln in _CIRC_TONE:
                    out.append(_nfc(c + _CIRC + _CIRC_TONE[ln]))
                    i += 2
                    continue
            if lc == "a":
                if ln == "ê":
                    out.append(_nfc(c + _BREVE))
                    i += 2
                    continue
                if ln in _BREVE_TONE:
                    out.append(_nfc(c + _BREVE + _BREVE_TONE[ln]))
                    i += 2
                    continue
            if lc in "aeiouy" and ln in _TONE:
                out.append(_nfc(c + _TONE[ln]))
                i += 2
                continue
        out.append(c)
        i += 1
    return "".join(out)
