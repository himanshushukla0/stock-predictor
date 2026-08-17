"""
Finance-tuned sentiment scoring.

Why not an off-the-shelf sentiment library: general-purpose models
(VADER, TextBlob) systematically misread financial language. "Apple beats
estimates" is strongly bullish but contains no generically positive word;
"volatile" is near-neutral in everyday English and negative in markets;
"cuts" is bad for guidance and good for costs. VADER also needs a lexicon
downloaded at first run, which breaks offline use.

So this module ships a hand-curated finance lexicon with:
  - single words AND multi-word phrases (phrases score first and consume
    their words, so "profit warning" isn't scored as bullish "profit")
  - negation flipping within a 3-token window
  - intensifier scaling ("sharply higher" > "higher")
  - recency weighting, so a headline from an hour ago counts for more
    than one from three days ago

It is still a keyword model. It cannot read sarcasm, nuance, or a number
in a table, and it will misjudge headlines whose meaning lives in
context. Treat the score as a rough tone gauge, not comprehension.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

# --------------------------------------------------------------------------
# Lexicon
# --------------------------------------------------------------------------

# Multi-word phrases are matched BEFORE single words and mask their span,
# so the component words can't be double-counted with the wrong sign.
PHRASES = {
    "beats estimates": 0.8, "beat estimates": 0.8, "beats expectations": 0.8,
    "beat expectations": 0.8, "tops estimates": 0.8, "topped estimates": 0.8,
    "better than expected": 0.7, "raises guidance": 0.85, "raised guidance": 0.85,
    "raises outlook": 0.8, "record high": 0.7, "all time high": 0.75,
    "price target raised": 0.7, "buy rating": 0.6, "strong demand": 0.6,
    "return to growth": 0.6, "cost savings": 0.35, "share buyback": 0.55,
    "dividend increase": 0.6, "up sharply": 0.7, "sharply higher": 0.7,

    "misses estimates": -0.8, "missed estimates": -0.8, "misses expectations": -0.8,
    "missed expectations": -0.8, "worse than expected": -0.7,
    "cuts guidance": -0.85, "cut guidance": -0.85, "lowers guidance": -0.85,
    "lowers outlook": -0.8, "profit warning": -0.85, "job cuts": -0.6,
    "price target cut": -0.7, "sell rating": -0.6, "weak demand": -0.6,
    "record low": -0.7, "class action": -0.6, "short seller": -0.6,
    "accounting irregularities": -0.9, "down sharply": -0.7, "sharply lower": -0.7,
    "sell off": -0.6, "selloff": -0.6, "bear market": -0.7, "bull market": 0.65,
}

POSITIVE_WORDS = {
    "beat": 0.7, "beats": 0.7, "beating": 0.7, "surge": 0.8, "surges": 0.8,
    "surged": 0.8, "soar": 0.8, "soars": 0.8, "soared": 0.8, "rally": 0.6,
    "rallies": 0.6, "rallied": 0.6, "gain": 0.5, "gains": 0.5, "gained": 0.5,
    "jump": 0.6, "jumps": 0.6, "jumped": 0.6, "climb": 0.5, "climbs": 0.5,
    "climbed": 0.5, "rise": 0.5, "rises": 0.5, "rising": 0.5, "rose": 0.5,
    "record": 0.4, "strong": 0.5, "strength": 0.4, "optimistic": 0.6,
    "optimism": 0.6, "bullish": 0.8, "upgrade": 0.7, "upgrades": 0.7,
    "upgraded": 0.7, "outperform": 0.6, "growth": 0.4, "expand": 0.4,
    "expands": 0.4, "expansion": 0.4, "profit": 0.5, "profits": 0.5,
    "profitable": 0.5, "exceed": 0.6, "exceeds": 0.6, "exceeded": 0.6,
    "boost": 0.5, "boosts": 0.5, "boosted": 0.5, "positive": 0.4,
    "breakthrough": 0.6, "recovery": 0.4, "recovers": 0.4, "rebound": 0.5,
    "rebounds": 0.5, "steady": 0.2, "stable": 0.2, "confident": 0.4,
    "confidence": 0.4, "raise": 0.4, "raised": 0.4, "raises": 0.4,
    "momentum": 0.35, "accelerate": 0.45, "accelerating": 0.45,
    "milestone": 0.4, "approval": 0.5, "approved": 0.5, "wins": 0.5,
    "won": 0.4, "partnership": 0.3, "innovation": 0.3, "innovative": 0.3,
    "robust": 0.5, "resilient": 0.4, "upbeat": 0.55, "outperformed": 0.6,
}

NEGATIVE_WORDS = {
    "miss": -0.6, "misses": -0.6, "missed": -0.6, "plunge": -0.8,
    "plunges": -0.8, "plunged": -0.8, "crash": -0.9, "crashes": -0.9,
    "crashed": -0.9, "tumble": -0.7, "tumbles": -0.7, "tumbled": -0.7,
    "slump": -0.6, "slumps": -0.6, "slumped": -0.6, "fall": -0.5,
    "falls": -0.5, "fell": -0.5, "falling": -0.5, "drop": -0.5,
    "drops": -0.5, "dropped": -0.5, "decline": -0.5, "declines": -0.5,
    "declined": -0.5, "sink": -0.6, "sinks": -0.6, "weak": -0.5,
    "weakness": -0.5, "bearish": -0.8, "downgrade": -0.7, "downgrades": -0.7,
    "downgraded": -0.7, "underperform": -0.6, "sued": -0.6, "lawsuit": -0.5,
    "investigation": -0.5, "probe": -0.5, "scrutiny": -0.4, "recall": -0.6,
    "layoff": -0.6, "layoffs": -0.6, "loss": -0.5, "losses": -0.5,
    "concern": -0.3, "concerns": -0.3, "worry": -0.4, "worries": -0.4,
    "volatile": -0.3, "volatility": -0.3, "risk": -0.2, "risks": -0.2,
    "warns": -0.5, "warning": -0.5, "warned": -0.5, "shortage": -0.4,
    "delay": -0.3, "delays": -0.3, "delayed": -0.3, "fraud": -0.9,
    "scandal": -0.8, "penalty": -0.5, "fine": -0.4, "fined": -0.5,
    "slowdown": -0.5, "slows": -0.4, "negative": -0.4, "default": -0.7,
    "bankruptcy": -0.9, "recession": -0.6, "halted": -0.5, "resign": -0.45,
    "resigns": -0.45, "resigned": -0.45, "stepping down": -0.4,
    "disappointing": -0.65, "disappoints": -0.65, "sluggish": -0.5,
    "headwinds": -0.45, "pressure": -0.3, "struggles": -0.55, "struggling": -0.55,
}

NEGATORS = {"not", "no", "never", "without", "isnt", "wasnt", "doesnt",
            "didnt", "wont", "cant", "fails", "failed", "unlikely"}

INTENSIFIERS = {"sharply": 1.4, "surges": 1.3, "significantly": 1.3, "steeply": 1.35,
                "slightly": 0.6, "marginally": 0.55, "modestly": 0.7,
                "massively": 1.5, "hugely": 1.4, "slight": 0.6}

_TOKEN_RE = re.compile(r"[a-z']+")


def _parse_published(value) -> datetime | None:
    """RSS dates arrive in several formats; try the common ones."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(value)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        pass
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def recency_weight(published, half_life_hours: float = 36.0) -> float:
    """
    Exponential decay by age: a headline from now weighs 1.0, one at the
    half-life weighs 0.5. Unparseable dates get 0.7 -- a middling weight,
    so a bad timestamp neither dominates nor gets silently discarded.
    Floored at 0.15 so old news still counts a little.
    """
    dt = _parse_published(published)
    if dt is None:
        return 0.7
    age_h = (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0
    if age_h < 0:
        return 1.0
    return max(0.15, 0.5 ** (age_h / half_life_hours))


def score_text(text: str) -> float:
    """Sentiment in [-1, 1] for one headline/snippet."""
    if not text:
        return 0.0
    low = text.lower()

    hits = []
    consumed = []  # char spans already claimed by a phrase match

    for phrase, weight in PHRASES.items():
        start = low.find(phrase)
        while start != -1:
            consumed.append((start, start + len(phrase)))
            hits.append(weight)
            start = low.find(phrase, start + len(phrase))

    def is_consumed(pos: int) -> bool:
        return any(s <= pos < e for s, e in consumed)

    for m in _TOKEN_RE.finditer(low):
        if is_consumed(m.start()):
            continue
        tok = m.group().replace("'", "")
        weight = POSITIVE_WORDS.get(tok)
        if weight is None:
            weight = NEGATIVE_WORDS.get(tok)
        if weight is None:
            continue

        # Negation only makes sense looking backward ("did not rise").
        prefix = low[:m.start()]
        prev_tokens = [t.replace("'", "") for t in _TOKEN_RE.findall(prefix)][-3:]
        if any(p in NEGATORS for p in prev_tokens):
            weight = -weight

        # Intensifiers attach on either side in headline English:
        # "sharply lower" and "falls sharply" are both idiomatic.
        suffix = low[m.end():]
        next_tokens = [t.replace("'", "") for t in _TOKEN_RE.findall(suffix)][:2]
        for p in prev_tokens[-2:] + next_tokens:
            if p in INTENSIFIERS:
                weight *= INTENSIFIERS[p]
                break

        hits.append(weight)

    if not hits:
        return 0.0

    raw = sum(hits) / len(hits)
    # Headlines with a single keyword get damped: one word is weak evidence.
    damp = min(1.0, 0.55 + 0.15 * len(hits))
    return max(-1.0, min(1.0, raw * damp))


def label_for_score(score: float) -> str:
    if score >= 0.30:
        return "positive"
    if score <= -0.30:
        return "negative"
    return "neutral"


def aggregate(headlines: list) -> dict:
    """
    Score every headline, then combine into a recency-weighted overall
    score. Returns per-headline scores plus the aggregate.
    """
    scored = []
    pos = neg = neu = 0
    weighted_sum = 0.0
    weight_total = 0.0

    for h in headlines:
        text = (h.get("title", "") + " " + (h.get("summary") or "")).strip()
        s = score_text(text)

        hint = h.get("_demo_sentiment_hint")
        if hint is not None:  # demo mode: keep synthetic headlines coherent
            s = round((s + hint) / 2, 3) if s else hint

        w = recency_weight(h.get("published"))
        label = label_for_score(s)

        h2 = {k: v for k, v in h.items() if k != "_demo_sentiment_hint"}
        h2["sentiment"] = round(s, 3)
        h2["sentiment_label"] = label
        h2["weight"] = round(w, 3)
        scored.append(h2)

        weighted_sum += s * w
        weight_total += w
        if label == "positive":
            pos += 1
        elif label == "negative":
            neg += 1
        else:
            neu += 1

    overall = round(weighted_sum / weight_total, 3) if weight_total else 0.0
    overall_label = (
        "bullish lean" if overall >= 0.15 else
        "bearish lean" if overall <= -0.15 else
        "mixed / neutral"
    )
    return {
        "headlines": scored,
        "score": overall,
        "label": overall_label,
        "positive_count": pos,
        "negative_count": neg,
        "neutral_count": neu,
        "sample_size": len(scored),
    }
