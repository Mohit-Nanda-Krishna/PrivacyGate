"""NER clean-up and the per-document name registry sweep.

spaCy tags many business terms as PERSON/LOCATION ("Trigger", "Tier 2", "Optiv")
and misses later mentions of a person it did find ("M. Achebe" after "Miriam
T. Achebe"). This module:

1. trims and filters NER PERSON/LOCATION spans with a configurable allowlist
   and simple name-shape rules,
2. builds a registry of people named in the document (multi-token NER names,
   e-mail local parts such as m.achebe -> Achebe, and Mr/Ms/Dr + surname), and
3. sweeps every block for each registered name and its variants (full name,
   "First Last", "F. Last", "F. M. Last", surname, first name).

The registry holds names only for the lifetime of one pipeline run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Iterable, Sequence

from privacygate.detection.common import make_entity
from privacygate.models import ContentBlock, PIIEntity

# Words that are never personal names in this domain. Extend per deployment
# via detect_pii(document, allowlist=...). Matching is case-insensitive.
DEFAULT_ALLOWLIST: frozenset[str] = frozenset("""
optiv cadence email e-mail tier workflow workflows trigger triggers vendor vendors assessment assessments
questionnaire questionnaires template templates admin administrator approver approvers description descriptions
tprm onetrust ironclad privacy shield appendix apendix contract contracts notify ownership control controls name
names approved elevated critical high moderate low group groups committee board risk risks policy policies chair
dashboard lead head officer chief director manager owner owners created completed change changes data cloud
database databases legal finance compliance security background artificial intelligence metadata key type types
contains reassessment diligence due nerdwallet securegrc secureid torii cursor days mobile phone role roles
division activity internal confidential default status submitted assessment's response responses action actions
task tasks assignee collaborators operator condition conditions rule rules section sections inventory library
engagement engagements setup automation recycle bin attribute attributes results result question questions
procurement revenue marketing staffing international partners services provider providers service intake
intake approval approvals offboarding onboarding rejecting rejected published draft final review reviewer
reviewers inherent residual target issue issues incident incidents loss event events scenario scenarios
indicator indicators register registers framework process processes standard standards forum forums
street st lane ln avenue ave road rd court ct crescent drive boulevard blvd way place terrace parkway
holder directory monthly quarterly annual annually weekly daily biennial lagging leading continuous known
generative operations medium minor non-material consistency requesting contingent withheld securty unlicaty
fessible acommon substantiated investigate investigating escalated restated attested signature emerging
velocity treatment acceptance exception exceptions waiver waivers appetite tolerance limit limits
the a an this that these those and or of for to in on at by with from see figure table note step part page
""".split())

# Short surnames that are also common English words are only redacted with a
# first name or initial attached, never alone.
COMMON_WORDS: frozenset[str] = frozenset("""
read white brown green black young king park may will mark rose case wood hill field long short bell lane page
hall ward cook baker rich grant hope joy faith grace frank bush lee kim chen ott smith
""".split())

_TOKEN = re.compile(r"[A-Za-z][A-Za-z'’.-]*")
_INITIAL = re.compile(r"^[A-Z]\.(?:-?[A-Z]\.)*$")
# Hyphenated parts must be capitalised (Okonkwo-Bell, Lars-Erik); "Co-branding" is not a name.
_NAME_WORD = re.compile(r"^[A-Z][a-z]+(?:-[A-Z][a-z]+)*(?:['’][A-Z]?[a-z]+)?$")
# "First M. Last": a middle initial between two capitalised words is a strong person signal.
NAME_WITH_INITIAL = re.compile(
    r"(?<![\w.-])[A-Z][a-z]+(?:-[A-Z][a-z]+)?[ \t]+[A-Z]\.[ \t]+[A-Z][a-z]+(?:-[A-Z][a-z]+)?(?![\w-])"
)
_EMAIL = re.compile(r"(?<![\w.%+-])([A-Za-z0-9._%+-]+)@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
_HONORIFIC = re.compile(r"\b(?:Mr|Ms|Mrs|Miss|Mx|Dr|Prof)\.?\s+([A-Z][a-z]+(?:-[A-Z][a-z]+)?)\b")


def _is_allowed_word(word: str, allowlist: frozenset[str]) -> bool:
    return word.strip(".'’").lower() in allowlist


def _is_name_token(token: str, allowlist: frozenset[str]) -> bool:
    if _INITIAL.match(token):
        return True
    return bool(_NAME_WORD.match(token)) and not _is_allowed_word(token, allowlist)


def clean_ner_entity(
    block: ContentBlock, entity: PIIEntity, allowlist: frozenset[str],
) -> list[PIIEntity]:
    """Trim/split one NER PERSON or LOCATION span; return zero or more spans.

    Spans are split at line breaks (table cells often list several people),
    trimmed of leading/trailing tokens that are not name-shaped, and dropped if
    any remaining token is allowlisted, contains digits, or is an acronym.
    """
    if entity.entity_type not in ("PERSON", "LOCATION"):
        return [entity]
    results = []
    text = block.text
    for piece in re.finditer(r"[^\n]+", text[entity.start:entity.end]):
        base = entity.start + piece.start()
        tokens = [(base + m.start(), base + m.end(), m.group()) for m in _TOKEN.finditer(piece.group())]
        segment = text[base:base + len(piece.group())]
        if re.search(r"\d|@|/", segment):
            continue
        def name_like(token: str) -> bool:
            return _is_name_token(token if _INITIAL.match(token) else token.rstrip("."), allowlist)

        original_count = len(tokens)
        while tokens and not name_like(tokens[0][2]):
            tokens.pop(0)
        while tokens and not name_like(tokens[-1][2]):
            tokens.pop()
        if not tokens or not all(name_like(t[2]) for t in tokens):
            continue
        if len(tokens) == 1 and original_count > 1:
            continue  # one word left after trimming business terms is a fragment, not a name
        if all(_INITIAL.match(t[2]) for t in tokens):
            continue
        start, end = tokens[0][0], tokens[-1][1]
        if text[end - 1:end] == "." and not _INITIAL.match(tokens[-1][2]):
            end -= 1
        results.append(make_entity(block, entity.entity_type, start, end, entity.confidence, entity.detector))
    return results


@dataclass(repr=False)
class _Person:
    first: str | None
    last: str
    middles: tuple[str, ...] = ()
    initial: str | None = None  # first-name initial known from an e-mail local part


@dataclass
class NameRegistry:
    """People named in one document, with a compiled sweep pattern."""

    people: list[_Person] = field(default_factory=list, repr=False)
    _pattern: re.Pattern[str] | None = field(default=None, repr=False)

    def __len__(self) -> int:
        return len(self.people)

    @property
    def pattern(self) -> re.Pattern[str] | None:
        if self._pattern is None and self.people:
            alternatives = sorted({alt for person in self.people for alt in _variant_patterns(person)},
                                  key=len, reverse=True)
            self._pattern = re.compile(r"(?<![\w-])(?:" + "|".join(alternatives) + r")(?![\w-])")
        return self._pattern

    def find(self, text: str) -> list[tuple[int, int]]:
        """Spans of registered names in text; placeholders never match."""
        if not self.pattern or not text:
            return []
        return [match.span() for match in self.pattern.finditer(text)]

    def resolve_person(self, value: str) -> int | None:
        """Return a per-registry index only when one person matches the whole value."""
        tokens = _TOKEN.findall(value)
        observed_middles = tuple(tokens[1:-1]) if len(tokens) >= 3 else ()
        matches = [
            index for index, person in enumerate(self.people)
            if any(re.fullmatch(pattern, value) for pattern in _variant_patterns(person))
            and _compatible_middles(person.middles, observed_middles)
        ]
        return matches[0] if len(matches) == 1 else None


def _flex(word: str) -> str:
    # Allow OCR/PDF spacing around hyphens: "Okonkwo-Bell", "Okonkwo - Bell".
    return r"\s?-\s?".join(re.escape(part) for part in word.split("-"))


def _compatible_middles(known: tuple[str, ...], observed: tuple[str, ...]) -> bool:
    """Reject contradictory middle evidence; missing or initial-only evidence stays ambiguous."""
    for left, right in zip(known, observed):
        left, right = left.rstrip(".").casefold(), right.rstrip(".").casefold()
        if left == right:
            continue
        if not left or not right or left[0] != right[0]:
            return False
        if len(left) > 1 and len(right) > 1:
            return False
    return True


def _variant_patterns(person: _Person, single_words: bool = True) -> list[str]:
    """Regex variants of a person's name.

    single_words=False keeps only multi-word forms with dotted initials
    ("Quentin R. Abernathy", "Q. Abernathy", "Q. R. Abernathy"): no bare
    surname, no bare first name and no dotless OCR initials, so a name
    learned in another file can never match an ordinary word ("read").
    """
    last = _flex(person.last)
    if single_words:
        # Initials with or without dots ("M. T.", "L.-E.", OCR "CA", "PS."), same line only.
        initials = r"(?:[A-Z]\.?[ \t]?-?){1,3}"
    else:
        initials = r"(?:[A-Z]\.[ \t]?-?){1,3}"
    patterns = [rf"{initials}[ \t]*{last}"]
    if person.first:
        first = _flex(person.first)
        middle = r"(?:[ \t]+(?:[A-Z]\.|[A-Z][a-z]+))?"
        patterns.append(rf"{first}{middle}\s+{last}")
        if single_words and len(person.first) >= 5 and person.first.lower() not in COMMON_WORDS:
            patterns.append(rf"{first}(?=['’]s\b|\b)")
    elif person.initial:
        # Surname known from "p.raghunathan@...": absorb a first name with that initial.
        patterns.append(rf"{person.initial}[a-z]+(?:-[A-Z][a-z]+)?(?:[ \t]+[A-Z]\.)?[ \t]+{last}")
    if single_words and (len(person.last) >= 5 or "-" in person.last) and person.last.lower() not in COMMON_WORDS:
        patterns.append(last)
    return patterns


def _email_names(texts: Iterable[str]) -> dict[str, str | None]:
    """Surname (letters only, lower case) -> first initial, from e-mail local parts."""
    names: dict[str, str | None] = {}
    for text in texts:
        for match in _EMAIL.finditer(text):
            parts = [part for part in re.split(r"[._-]", match.group(1)) if part.isalpha()]
            if len(parts) >= 2 and len(parts[-1]) >= 3:
                names.setdefault(parts[-1].lower(), parts[0][0].upper())
    return names


def build_name_registry(
    blocks: Sequence[ContentBlock], person_spans: Iterable[tuple[str, int, int]],
    allowlist: frozenset[str] = DEFAULT_ALLOWLIST, identifier_blocks: Iterable[str] | None = None,
) -> NameRegistry:
    """Collect people to sweep for, accepting only names with corroboration.

    person_spans are (block_id, start, end) of cleaned PERSON detections. A
    span is registered only if it is corroborated: it has a middle initial, its
    surname matches an e-mail local part, it follows an honorific, or it sits in
    a block that also holds an identifier (identifier_blocks). Uncorroborated
    NER names are still detected where they occur; they are just not swept.
    Surnames from e-mail local parts (m.achebe -> Achebe) and Mr/Ms/Dr +
    surname are added when that word appears capitalised in the document.
    """
    texts = {block.block_id: block.text for block in blocks}
    email_names = _email_names(texts.values())
    honorific_surnames = {m.group(1).replace("-", "").lower() for t in texts.values() for m in _HONORIFIC.finditer(t)}
    with_identifiers = set(identifier_blocks or ())
    people: dict[tuple[str | None, str, tuple[str, ...]], _Person] = {}

    def add(first: str | None, last: str, middles: tuple[str, ...] = (), initial: str | None = None) -> None:
        if last.lower() in allowlist or len(last) < 2:
            return
        key = (first.lower() if first else None, last.lower(),
               tuple(middle.rstrip(".").casefold() for middle in middles))
        if key not in people:
            people[key] = _Person(first, last, middles, initial)

    for block_id, start, end in person_spans:
        tokens = _TOKEN.findall(texts.get(block_id, "")[start:end])
        words = [t for t in tokens if not _INITIAL.match(t)]
        if len(tokens) < 2 or not words or not _NAME_WORD.match(words[-1]):
            continue
        last_key = words[-1].replace("-", "").lower()
        corroborated = (
            any(_INITIAL.match(t) for t in tokens) or last_key in email_names
            or last_key in honorific_surnames or block_id in with_identifiers
        )
        if not corroborated:
            continue
        first = tokens[0] if _NAME_WORD.match(tokens[0]) and tokens[0] != words[-1] else None
        add(first, words[-1], tuple(t for t in tokens[1:-1]))

    capitalised: dict[str, str] = {}
    for text in texts.values():
        for word in re.findall(r"\b[A-Z][a-z]+(?:-[A-Z][a-z]+)*\b", text):
            capitalised.setdefault(word.replace("-", "").lower(), word)
    known_last = {person.last.replace("-", "").lower() for person in people.values()}
    for surname, initial in email_names.items():
        if surname not in known_last and surname in capitalised:
            add(None, capitalised[surname], initial=initial)
    for surname in honorific_surnames:
        if surname not in known_last and surname in capitalised:
            add(None, capitalised[surname])
    for person in people.values():
        # "E. Bertucci" registered from NER still learns the initial from e.bertucci@...
        if person.first is None and person.initial is None:
            person.initial = email_names.get(person.last.replace("-", "").lower())
    # A surname-only entry next to exactly one named person with that surname
    # ("Q. Abernathy" beside "Quentin R. Abernathy") is the same person; keeping
    # both made resolve_person() ambiguous, so variants got different tokens.
    return merge_registries([NameRegistry(list(people.values()))])


def merge_registries(registries: Iterable[NameRegistry]) -> NameRegistry:
    """One registry for a batch of documents; the same person appears once.

    People with the same first name and surname and compatible middle names
    (per _compatible_middles) are merged, keeping the most specific middles and
    any known initial. Different middle names stay separate people, as within
    one document. A surname-only entry is dropped when exactly one named person
    with that surname exists in the batch, so resolve_person() can still map
    the bare surname to that person.
    """
    merged: list[_Person] = []
    for registry in registries:
        for person in registry.people:
            for existing in merged:
                same_name = (
                    existing.last.casefold() == person.last.casefold()
                    and (existing.first or "").casefold() == (person.first or "").casefold()
                )
                if same_name and _compatible_middles(existing.middles, person.middles):
                    if len(person.middles) > len(existing.middles):
                        existing.middles = person.middles
                    existing.initial = existing.initial or person.initial
                    break
            else:
                merged.append(_Person(person.first, person.last, person.middles, person.initial))
    named_by_last: dict[str, int] = {}
    for person in merged:
        if person.first:
            key = person.last.replace("-", "").casefold()
            named_by_last[key] = named_by_last.get(key, 0) + 1
    return NameRegistry([
        person for person in merged
        if person.first or named_by_last.get(person.last.replace("-", "").casefold(), 0) != 1
    ])


def sweep_names(
    blocks: Sequence[ContentBlock], registry: NameRegistry, full_names_only: bool = False,
) -> list[PIIEntity]:
    """Emit PERSON entities (detector="name_sweep") for every registered name occurrence.

    full_names_only=True (used for names learned from other files in a batch)
    matches only multi-word forms with dotted initials, never a bare surname
    or first name.
    """
    if full_names_only:
        alternatives = sorted({alt for person in registry.people for alt in _variant_patterns(person, False)},
                              key=len, reverse=True)
        if not alternatives:
            return []
        pattern = re.compile(r"(?<![\w-])(?:" + "|".join(alternatives) + r")(?![\w-])")
        finder = lambda text: [m.span() for m in pattern.finditer(text)]  # noqa: E731
    else:
        finder = registry.find
    entities = []
    for block in blocks:
        for start, end in finder(block.text):
            entities.append(make_entity(block, "PERSON", start, end, 0.85, "name_sweep"))
    return entities
