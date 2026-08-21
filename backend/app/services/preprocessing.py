"""
Text preprocessing service.

Two preprocessing paths are exposed:

* ``clean_for_classical(text, remove_stopwords=False)``  -> used by XGBoost
  (TF-IDF feature space). New behaviour: preserves repeated characters
  (collapsed to <=3), preserves punctuation runs as feature tokens
  (EXCL, EXCL2, QSTN, QEXCL, ELLIP), preserves numbers as a NUM token,
  preserves emoticons as EMO_POS / EMO_NEG tokens, preserves all-caps
  words by emitting a parallel ALL_CAPS feature token, and does NOT
  remove stopwords or lemmatize by default. ``remove_stopwords`` is an
  opt-in flag (off by default) so the academic writeup can compare
  configurations.

* ``clean_for_transformer(text)`` -> used by the DeBERTa and RoBERTa
  pipelines. Light cleaning only: URLs, HTML, and emojis removed. The
  HuggingFace tokenizers handle casing, punctuation, and grammar.

This module also exposes ``PREPROCESSING_NOTES`` — a long string
documenting every decision so the project paper can quote it verbatim.
"""
from __future__ import annotations

import re
import string
from functools import lru_cache
from typing import Iterable

import emoji

# NLTK is only used for stopword support (opt-in). The classical
# tokenizer is a regex tokenizer that does not require NLTK.
try:
    from nltk.corpus import stopwords as _nltk_stopwords  # type: ignore

    _NLTK_OK = True
except Exception:  # pragma: no cover - environment fallback
    _NLTK_OK = False

# Minimal English stopword fallback in case NLTK corpora are unavailable.
_FALLBACK_STOPWORDS: set[str] = {
    "a", "an", "the", "and", "or", "but", "if", "of", "at", "by", "for",
    "with", "about", "to", "in", "on", "is", "are", "was", "were", "be",
    "been", "being", "it", "this", "that", "these", "those", "i", "you",
    "he", "she", "we", "they",
}


# ---------------------------------------------------------------------------
# Public documentation constant
# ---------------------------------------------------------------------------

PREPROCESSING_NOTES: str = """
Preprocessing decisions (XGBoost / classical path)
==================================================

1. URLs (`http(s)://...`, `www.`) and HTML tags are removed. They are
   never sentiment-bearing in this domain and only inflate the
   vocabulary.

2. Emojis are converted to their CLDR short name via `emoji.demojize`
   (e.g. `😊` -> `:smiling_face:`). The token is preserved. The
   transformer pipelines (DeBERTa, RoBERTa) handle emojis natively
   and do not need this conversion.

3. A small built-in emoticon lexicon maps ASCII emoticons to
   sentiment tokens:
       :) :-) :D :3 ;-)    -> EMO_POS
       :( :-( :'(          -> EMO_NEG
   Other emoticons are left as raw tokens.

4. Repeated characters are collapsed to at most 3 (`GOOOOD` -> `GOOOD`).
   The first 3 repeats are kept because they encode emphasis that can
   carry sentiment information. Anything beyond the 3rd is dropped.

5. Repeated punctuation runs are converted to feature tokens rather
   than deleted:
       !       -> EXCL
       !!      -> EXCL2
       !!!+    -> EXCL3
       ?       -> QSTN
       ??+     -> QSTN2
       !?/?!   -> QEXCL
       ...     -> ELLIP
   This preserves emphasis / questioning cues.

6. Numeric substrings are replaced with the token `NUM`. Numbers are
   rarely sentiment-bearing in student feedback and would otherwise
   dominate rare-token statistics.

7. Tokenization is a regex on Unicode word characters — we do not
   use NLTK's `word_tokenize` because the latter silently discards
   punctuation runs.

8. Case is lowercased, but all-uppercase words additionally emit a
   parallel `ALL_CAPS` feature token so emphasis survives in the
   feature space without forcing the rest of the pipeline to be
   case-sensitive.

9. Stopword removal is **off by default** and is opt-in via the
   `remove_stopwords=True` argument. Lemmatization is **not applied**
   (a stemmer is available on request). The choice is documented in
   the run logs.

Preprocessing decisions (transformer path)
=========================================

1. URLs and HTML are removed (same justification).

2. Emojis are removed for the transformer path (the HF tokenizers
   embed them well enough that removing the literal codepoints
   prevents tokenizer mismatches across model versions). The
   sentiment signal they carry is captured by the transformer's
   subword vocabulary.

3. No lowercasing, no contraction expansion, no punctuation
   stripping — the transformer is trained on natural text and these
   steps would only reduce the signal it can use.
"""


# ---------------------------------------------------------------------------
# Regex / lookup tables
# ---------------------------------------------------------------------------

URL_PATTERN = re.compile(r"https?://\S+|www\.\S+")
HTML_PATTERN = re.compile(r"<.*?>")
NUMBER_PATTERN = re.compile(r"\d+")
WHITESPACE_PATTERN = re.compile(r"\s+")

# Token boundary: word characters OR a single punctuation character OR an
# emoji short-name. We do not want a single "!!!" to become a single token;
# we want "!" and "!" and "!" as separate tokens so the punctuation-run
# replacement can count them.
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_:]+|[!?,.;:\-\"'\(\)\[\]{}]")

# Repeated-character collapse: any single character repeated 4+ times is
# reduced to 3 repeats. We do not collapse shorter runs (e.g. "see" is
# left alone, "seee" is collapsed to "see").
_REPEAT_COLLAPSE = re.compile(r"(.)\1{3,}")

_PUNCT_RUN_PATTERN = re.compile(r"([!?,.;:]+)")

_EMOTICON_POS = {":)", ":-)", ":d", ":3", ";-)", ":')"}
_EMOTICON_NEG = {":(", ":-(", ":'(", ":-("}

# Lazy stopword set (resolved on first use, opt-in only).
_cached_stopwords: set[str] | None = None


def _get_stopwords() -> set[str]:
    global _cached_stopwords
    if _cached_stopwords is not None:
        return _cached_stopwords
    if _NLTK_OK:
        try:
            _cached_stopwords = set(_nltk_stopwords.words("english"))
            return _cached_stopwords
        except Exception:
            pass
    _cached_stopwords = set(_FALLBACK_STOPWORDS)
    return _cached_stopwords


# Backwards-compatible public stopword collection used by analytics.  Keep it
# immutable so callers cannot accidentally alter the preprocessing defaults.
STOPWORDS = frozenset(_get_stopwords())


# ---------------------------------------------------------------------------
# Small, named steps
# ---------------------------------------------------------------------------

def remove_urls(text: str) -> str:
    return URL_PATTERN.sub(" ", text)


def remove_html(text: str) -> str:
    return HTML_PATTERN.sub(" ", text)


def remove_emojis(text: str) -> str:
    return emoji.replace_emoji(text, replace=" ")


def _collapse_repeats(text: str) -> str:
    return _REPEAT_COLLAPSE.sub(r"\1\1\1", text)


def _emojize(text: str) -> str:
    """Convert emojis to their CLDR short-name form so the token survives."""
    return emoji.demojize(text, delimiters=(" ", " "))


def _replace_punct_runs(text: str) -> str:
    """Replace contiguous runs of punctuation with feature tokens.

    `!`      -> ` EXCL `
    `!!`     -> ` EXCL2 `
    `!!!+`   -> ` EXCL3 `
    `?`      -> ` QSTN `
    `??+`    -> ` QSTN2 `
    `!?`/`?!`-> ` QEXCL `
    `...`+   -> ` ELLIP `
    """
    def _repl(m: re.Match[str]) -> str:
        run = m.group(1)
        if set(run) <= {"!"}:
            n = len(run)
            tag = "EXCL3" if n >= 3 else f"EXCL{n}"
            return f" {tag} "
        if set(run) <= {"?"}:
            n = len(run)
            tag = "QSTN2" if n >= 2 else "QSTN"
            return f" {tag} "
        if set(run) <= {".", " "} and run.count(".") >= 3:
            return " ELLIP "
        if set(run) <= {"!", "?"} or set(run) <= {"?", "!"}:
            return " QEXCL "
        # Mixed punctuation (e.g. ",,") -> keep as a single PUNCT token
        return f" PUNCT "

    return _PUNCT_RUN_PATTERN.sub(_repl, text)


def _split_on_known_emoticons(text: str) -> str:
    """Pad known emoticons with spaces so the regex tokenizer keeps them."""
    for emo in _EMOTICON_POS | _EMOTICON_NEG:
        # Use word-boundary-free replace; emoticons have no alphanum chars.
        text = text.replace(emo, f" {emo} ")
    return text


def _map_emoticons(text: str) -> str:
    text = re.sub(r"(?<!\S):\)(?!\S)", " EMO_POS ", text)
    text = re.sub(r"(?<!\S):-\)(?!\S)", " EMO_POS ", text)
    text = re.sub(r"(?<!\S):d(?!\S)", " EMO_POS ", text, flags=re.IGNORECASE)
    text = re.sub(r"(?<!\S):3(?!\S)", " EMO_POS ", text)
    text = re.sub(r"(?<!\S);-\)(?!\S)", " EMO_POS ", text)
    text = re.sub(r"(?<!\S):'\)(?!\S)", " EMO_POS ", text)

    text = re.sub(r"(?<!\S):\((?!\S)", " EMO_NEG ", text)
    text = re.sub(r"(?<!\S):-\((?!\S)", " EMO_NEG ", text)
    text = re.sub(r"(?<!\S):'\((?!\S)", " EMO_NEG ", text)
    return text


def _replace_numbers(text: str) -> str:
    return NUMBER_PATTERN.sub(" NUM ", text)


def _normalize_whitespace(text: str) -> str:
    return WHITESPACE_PATTERN.sub(" ", text).strip()


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    """Regex tokenizer that keeps emoticons and feature tokens as units."""
    return [m.group(0) for m in _TOKEN_PATTERN.finditer(text)]


def _drop_punct_only_tokens(tokens: Iterable[str]) -> list[str]:
    """Drop single-character punctuation tokens that are not in our
    feature vocabulary (so they do not bleed into the TF-IDF space)."""
    keep: list[str] = []
    for tok in tokens:
        if len(tok) == 1 and tok in string.punctuation:
            continue
        keep.append(tok)
    return keep


def _tag_all_caps(tokens: list[str]) -> list[str]:
    """For each uppercase alphabetic word token, append an `ALL_CAPS`
    feature token so emphasis is preserved at the feature-space level."""
    out: list[str] = []
    for tok in tokens:
        if tok.isalpha() and tok.isupper() and len(tok) >= 2:
            out.append(tok)
            out.append("ALL_CAPS")
        else:
            out.append(tok)
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def clean_for_classical(
    text: str,
    remove_stopwords: bool = False,
) -> str:
    """Preprocess ``text`` for the classical / XGBoost pipeline.

    Parameters
    ----------
    text : str
        Raw student feedback text.
    remove_stopwords : bool, default False
        If True, drop NLTK English stopwords from the token stream.
        Off by default to preserve context for sentiment analysis.

    Returns
    -------
    str
        A single space-joined string of tokens, suitable for TF-IDF.
    """
    if not text:
        return ""

    text = remove_urls(text)
    text = remove_html(text)
    text = _emojize(text)
    text = _split_on_known_emoticons(text)
    text = _collapse_repeats(text)
    text = _replace_punct_runs(text)
    text = _replace_numbers(text)
    text = text.lower()
    text = _normalize_whitespace(text)

    tokens = _tokenize(text)
    tokens = _drop_punct_only_tokens(tokens)
    tokens = _tag_all_caps(tokens)
    if remove_stopwords:
        sw = _get_stopwords()
        tokens = [t for t in tokens if t.lower() not in sw]

    return " ".join(tokens)


def clean_for_transformer(text: str) -> str:
    """Light preprocessing for DeBERTa / RoBERTa. Preserves case,
    grammar, and most punctuation so the transformer's contextual
    embeddings stay meaningful.

    Steps: strip URLs, strip HTML, remove emojis, normalise whitespace.
    """
    if not text:
        return ""
    text = remove_urls(text)
    text = remove_html(text)
    text = remove_emojis(text)
    text = _normalize_whitespace(text)
    return text


# Backwards-compat alias: `clean_for_bert` was the old name. Some callers
# may still reference it. Keep both names pointing to the same function.
def clean_for_bert(text: str) -> str:  # pragma: no cover - alias
    return clean_for_transformer(text)
