"""Maintained candidate-language catalogs and schema-free profile projections.

The catalogs are deliberately application-owned instead of browser- or locale-
dependent.  That keeps existing Compass checkpoints deterministic, gives the UI
an explicit empty state, and lets matching use the same canonical names that the
candidate selected.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re
import unicodedata

from .profile import CandidateProfile, ProfileFact


SPOKEN_LANGUAGE_FACT_KEY = "language.spoken"
PROGRAMMING_LANGUAGE_FACT_KEY = "skill.programming_language"
LANGUAGE_EDITOR_NOTE_PREFIX = "Set with the Compass language editor"


class PracticalProficiency(StrEnum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    PROFESSIONAL = "professional"
    NATIVE = "native"


@dataclass(frozen=True, slots=True)
class LanguageSelection:
    name: str
    proficiency: PracticalProficiency


# ISO 639-1 is the baseline, supplemented with widely used macrolanguages,
# regional languages, creoles, and signed languages that candidates commonly
# need to represent separately.  Names are stable storage/display identifiers;
# aliases below handle common English, German, and endonym variants.
SPOKEN_LANGUAGES: tuple[str, ...] = (
    "Abkhazian",
    "Acehnese",
    "Afar",
    "Afrikaans",
    "Akan",
    "Albanian",
    "Amharic",
    "Arabic",
    "Aragonese",
    "Armenian",
    "Assamese",
    "Avaric",
    "Aymara",
    "Azerbaijani",
    "Balinese",
    "Balochi",
    "Bambara",
    "Bashkir",
    "Basque",
    "Belarusian",
    "Bengali",
    "Bhojpuri",
    "Bislama",
    "Bosnian",
    "Breton",
    "Bulgarian",
    "Burmese",
    "Cantonese",
    "Catalan",
    "Cebuano",
    "Chamorro",
    "Chechen",
    "Chichewa",
    "Chinese (Mandarin)",
    "Chuvash",
    "Cornish",
    "Corsican",
    "Crimean Tatar",
    "Croatian",
    "Czech",
    "Danish",
    "Dari",
    "Divehi",
    "Dogri",
    "Dutch",
    "Dzongkha",
    "English",
    "Estonian",
    "Ewe",
    "Faroese",
    "Fijian",
    "Filipino (Tagalog)",
    "Finnish",
    "French",
    "Friulian",
    "Fulani",
    "Galician",
    "Ganda",
    "Georgian",
    "German",
    "Greek",
    "Greenlandic",
    "Guarani",
    "Gujarati",
    "Haitian Creole",
    "Hausa",
    "Hawaiian",
    "Hebrew",
    "Herero",
    "Hindi",
    "Hiri Motu",
    "Hmong",
    "Hungarian",
    "Icelandic",
    "Igbo",
    "Ilocano",
    "Indonesian",
    "Irish",
    "Italian",
    "Japanese",
    "Javanese",
    "Kannada",
    "Kanuri",
    "Kashmiri",
    "Kazakh",
    "Khmer",
    "Kikuyu",
    "Kinyarwanda",
    "Kirghiz",
    "Kirundi",
    "Konkani",
    "Korean",
    "Krio",
    "Kurdish",
    "Lao",
    "Latvian",
    "Limburgish",
    "Lingala",
    "Lithuanian",
    "Low German",
    "Luxembourgish",
    "Macedonian",
    "Maithili",
    "Malagasy",
    "Malay",
    "Malayalam",
    "Maltese",
    "Manx",
    "Māori",
    "Marathi",
    "Marshallese",
    "Meitei (Manipuri)",
    "Min Nan (Hokkien)",
    "Mongolian",
    "Montenegrin",
    "Mossi",
    "Nauruan",
    "Navajo",
    "Ndonga",
    "Nepali",
    "Northern Ndebele",
    "Northern Sami",
    "Norwegian",
    "Norwegian Bokmål",
    "Norwegian Nynorsk",
    "Occitan",
    "Odia",
    "Oromo",
    "Ossetian",
    "Pashto",
    "Persian",
    "Polish",
    "Portuguese",
    "Punjabi",
    "Quechua",
    "Romanian",
    "Romansh",
    "Russian",
    "Samoan",
    "Sango",
    "Sardinian",
    "Scottish Gaelic",
    "Serbian",
    "Shona",
    "Sicilian",
    "Sindhi",
    "Sinhala",
    "Slovak",
    "Slovenian",
    "Somali",
    "Southern Ndebele",
    "Southern Sotho",
    "Spanish",
    "Sundanese",
    "Swahili",
    "Swati",
    "Swedish",
    "Sylheti",
    "Tajik",
    "Tamil",
    "Tatar",
    "Telugu",
    "Tetum",
    "Thai",
    "Tibetan",
    "Tigrinya",
    "Tongan",
    "Tsonga",
    "Tswana",
    "Turkish",
    "Turkmen",
    "Twi",
    "Ukrainian",
    "Urdu",
    "Uyghur",
    "Uzbek",
    "Venda",
    "Vietnamese",
    "Welsh",
    "Western Frisian",
    "Wolof",
    "Wu Chinese",
    "Xhosa",
    "Yiddish",
    "Yoruba",
    "Zazaki",
    "Zulu",
    "American Sign Language",
    "British Sign Language",
    "German Sign Language",
    "International Sign",
)


# General-purpose, systems, scientific, data, smart-contract, hardware-
# description, automation, and PLC languages are all represented.  Markup and
# tools are intentionally not mixed in merely because they often appear beside
# programming languages in CVs.
PROGRAMMING_LANGUAGES: tuple[str, ...] = (
    "ABAP",
    "ActionScript",
    "Ada",
    "Agda",
    "ALGOL",
    "Apex",
    "APL",
    "AppleScript",
    "Assembly",
    "AutoHotkey",
    "AutoIt",
    "Awk",
    "Ballerina",
    "BASIC",
    "Batch",
    "C",
    "C#",
    "C++",
    "Clojure",
    "COBOL",
    "CoffeeScript",
    "Common Lisp",
    "Crystal",
    "CUDA",
    "Cython",
    "D",
    "Dart",
    "Delphi (Object Pascal)",
    "Elixir",
    "Elm",
    "Erlang",
    "F#",
    "Factor",
    "Forth",
    "Fortran",
    "GDScript",
    "Gleam",
    "Go",
    "Groovy",
    "Hack",
    "Haskell",
    "Haxe",
    "HCL",
    "Idris",
    "Instruction List (IEC 61131-3)",
    "Io",
    "J",
    "Java",
    "JavaScript",
    "Julia",
    "Kotlin",
    "LabVIEW G",
    "Ladder Logic (IEC 61131-3)",
    "Lisp",
    "Logo",
    "Lua",
    "MATLAB",
    "Mojo",
    "Nim",
    "Nix",
    "Objective-C",
    "OCaml",
    "Odin",
    "OpenCL C",
    "Pascal",
    "Perl",
    "PHP",
    "PL/I",
    "PL/SQL",
    "PostScript",
    "PowerShell",
    "Processing",
    "Prolog",
    "PureScript",
    "Python",
    "Q (KDB+)",
    "R",
    "Racket",
    "ReasonML",
    "RPG",
    "Ruby",
    "Rust",
    "SAS",
    "Scala",
    "Scheme",
    "Scratch",
    "Shell",
    "Solidity",
    "SQL",
    "Standard ML",
    "Structured Text (IEC 61131-3)",
    "Swift",
    "SystemVerilog",
    "Tcl",
    "TypeScript",
    "V",
    "VBA",
    "VB.NET",
    "Verilog",
    "VHDL",
    "Visual Basic",
    "WebAssembly",
    "Wolfram Language",
    "XSLT",
    "Zig",
)


_SPOKEN_ALIASES: dict[str, tuple[str, ...]] = {
    "Bengali": ("Bangla",),
    "Burmese": ("Myanmar language",),
    "Chinese (Mandarin)": ("Chinese", "Mandarin", "Mandarin Chinese"),
    "Czech": ("Čeština", "Tschechisch"),
    "Dutch": ("Nederlands", "Niederländisch", "Niederlaendisch"),
    "English": ("Englisch",),
    "Filipino (Tagalog)": ("Filipino", "Tagalog"),
    "French": ("Français", "French language", "Französisch", "Franzoesisch"),
    "German": ("Deutsch", "German language"),
    "Greek": ("Modern Greek", "Ελληνικά"),
    "Hebrew": ("עברית",),
    "Kirghiz": ("Kyrgyz",),
    "Low German": ("Low Saxon", "Plattdeutsch"),
    "Māori": ("Maori",),
    "Meitei (Manipuri)": ("Meitei", "Manipuri"),
    "Min Nan (Hokkien)": ("Min Nan", "Hokkien", "Taiwanese Hokkien"),
    "Norwegian Bokmål": ("Bokmal", "Bokmål"),
    "Odia": ("Oriya",),
    "Persian": ("Farsi",),
    "Portuguese": ("Português", "Portugiesisch"),
    "Romanian": ("Moldovan", "Română"),
    "Scottish Gaelic": ("Gaelic",),
    "Sinhala": ("Sinhalese",),
    "Spanish": ("Español", "Castilian", "Spanisch"),
    "Swahili": ("Kiswahili",),
    "Uyghur": ("Uighur",),
    "Welsh": ("Cymraeg",),
    "American Sign Language": ("ASL",),
    "British Sign Language": ("BSL",),
    "German Sign Language": ("DGS", "Deutsche Gebärdensprache"),
}


_PROGRAMMING_ALIASES: dict[str, tuple[str, ...]] = {
    "Assembly": ("Assembler", "ASM"),
    "C#": ("C Sharp", "C-Sharp"),
    "C++": ("CPP", "C Plus Plus"),
    "Delphi (Object Pascal)": ("Delphi", "Object Pascal"),
    "F#": ("F Sharp", "F-Sharp"),
    "Go": ("Golang",),
    "Instruction List (IEC 61131-3)": ("Instruction List", "IL"),
    "JavaScript": ("JS", "ECMAScript"),
    "LabVIEW G": ("LabVIEW", "G language"),
    "Ladder Logic (IEC 61131-3)": ("Ladder Logic", "Ladder Diagram", "LD"),
    "MATLAB": ("Matlab",),
    "Objective-C": ("Objective C", "Obj-C", "ObjC"),
    "Q (KDB+)": ("KDB+ Q", "Q language"),
    "Shell": ("Bash", "Zsh", "POSIX shell", "shell scripting"),
    "Structured Text (IEC 61131-3)": ("Structured Text", "IEC 61131-3 ST", "SCL"),
    "TypeScript": ("TS",),
    "VB.NET": ("VB Net",),
    "Visual Basic": ("VB",),
    "WebAssembly": ("Wasm",),
    "Wolfram Language": ("Mathematica",),
}


def language_fact_value(name: str, proficiency: PracticalProficiency) -> str:
    """Return the stable, human-readable value stored in a ProfileFact."""

    return f"{name} · {proficiency.value}"


def parse_language_fact_value(value: object) -> LanguageSelection | None:
    """Read current editor values and the parenthesized form used by old facts."""

    material = " ".join(str(value).split())
    direct = re.fullmatch(
        r"(?P<name>.+?)\s*(?:·|—|-|\()\s*"
        r"(?P<level>beginner|intermediate|professional|native)\)?",
        material,
        flags=re.IGNORECASE,
    )
    if direct is None:
        return None
    try:
        proficiency = PracticalProficiency(direct.group("level").casefold())
    except ValueError:  # pragma: no cover - regex is the same closed set
        return None
    return LanguageSelection(name=direct.group("name").strip(), proficiency=proficiency)


_PROFICIENCY_MARKERS: tuple[tuple[PracticalProficiency, tuple[str, ...]], ...] = (
    (PracticalProficiency.NATIVE, ("native", "mother tongue", "c2")),
    (PracticalProficiency.PROFESSIONAL, ("professional", "fluent", "business fluent", "c1")),
    (PracticalProficiency.INTERMEDIATE, ("intermediate", "conversational", "b1", "b2")),
    (PracticalProficiency.BEGINNER, ("beginner", "basic", "a1", "a2")),
)


def _explicit_proficiency_near_name(
    material: str,
    name: str,
    aliases: dict[str, tuple[str, ...]],
) -> PracticalProficiency | None:
    normalized = _catalog_normalize(material)
    for candidate in (name, *aliases.get(name, ())):
        token = _catalog_normalize(candidate)
        if not token:
            continue
        for match in re.finditer(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", normalized):
            nearby = normalized[max(0, match.start() - 34) : match.end() + 34]
            for proficiency, markers in _PROFICIENCY_MARKERS:
                if any(
                    re.search(rf"(?<![a-z0-9]){re.escape(marker)}(?![a-z0-9])", nearby)
                    for marker in markers
                ):
                    return proficiency
    return None


def canonical_catalog_name(value: str, *, programming: bool) -> str | None:
    """Resolve one submitted catalog value without accepting arbitrary text."""

    catalog = PROGRAMMING_LANGUAGES if programming else SPOKEN_LANGUAGES
    aliases = _PROGRAMMING_ALIASES if programming else _SPOKEN_ALIASES
    lookup = {
        _catalog_normalize(alias): name
        for name in catalog
        for alias in (name, *aliases.get(name, ()))
    }
    return lookup.get(_catalog_normalize(value))


def profile_language_selections(
    profile: CandidateProfile,
    *,
    programming: bool,
) -> dict[str, PracticalProficiency]:
    """Project active editor facts into a template-friendly canonical mapping."""

    key = PROGRAMMING_LANGUAGE_FACT_KEY if programming else SPOKEN_LANGUAGE_FACT_KEY
    catalog = PROGRAMMING_LANGUAGES if programming else SPOKEN_LANGUAGES
    names = {_catalog_normalize(name): name for name in catalog}
    selections: dict[str, PracticalProficiency] = {}
    aliases = _PROGRAMMING_ALIASES if programming else _SPOKEN_ALIASES
    for fact in profile.confirmed_candidate_evidence:
        parsed = parse_language_fact_value(fact.value)
        if fact.key == key and parsed is not None:
            canonical = names.get(_catalog_normalize(parsed.name))
            if canonical is not None:
                selections[canonical] = parsed.proficiency
            continue
        material = f"{fact.value} {fact.source.text}"
        mentioned = (
            mentioned_programming_languages(material)
            if programming
            else mentioned_spoken_languages(material)
        )
        for name in mentioned:
            proficiency = _explicit_proficiency_near_name(material, name, aliases)
            if proficiency is not None:
                selections[name] = proficiency
    return selections


def profile_language_mentions(
    profile: CandidateProfile,
    *,
    programming: bool,
) -> set[str]:
    """Return catalog names found in guided, CV, or widget evidence.

    A mention without an explicit level is shown by the widget but is not
    silently promoted to an invented proficiency.
    """

    found: set[str] = set()
    for fact in profile.confirmed_candidate_evidence:
        material = f"{fact.value} {fact.source.text}"
        found.update(
            mentioned_programming_languages(material)
            if programming
            else mentioned_spoken_languages(material)
        )
    return found


def is_language_editor_fact(fact: ProfileFact) -> bool:
    return bool((fact.user_note or "").startswith(LANGUAGE_EDITOR_NOTE_PREFIX))


def mentioned_spoken_languages(value: object) -> set[str]:
    return _mentioned_catalog_names(value, SPOKEN_LANGUAGES, _SPOKEN_ALIASES)


def mentioned_programming_languages(value: object) -> set[str]:
    return _mentioned_catalog_names(value, PROGRAMMING_LANGUAGES, _PROGRAMMING_ALIASES)


def spoken_language_aliases(name: str) -> tuple[str, ...]:
    """Return canonical and maintained matching aliases for one catalog name."""

    if name not in SPOKEN_LANGUAGES:
        return ()
    return (name, *_SPOKEN_ALIASES.get(name, ()))


def _mentioned_catalog_names(
    value: object,
    catalog: tuple[str, ...],
    aliases: dict[str, tuple[str, ...]],
) -> set[str]:
    material = _catalog_normalize(value)
    found: set[str] = set()
    # Longest aliases first prevent a generic name from hiding a more specific
    # one. Exact token boundaries keep C distinct from C++ and R from Rust.
    candidates = sorted(
        (
            (_catalog_normalize(alias), name)
            for name in catalog
            for alias in (name, *aliases.get(name, ()))
        ),
        key=lambda item: len(item[0]),
        reverse=True,
    )
    for alias, name in candidates:
        if not alias:
            continue
        if re.search(rf"(?<![a-z0-9+#]){re.escape(alias)}(?![a-z0-9+#])", material):
            found.add(name)
    return found


def _catalog_normalize(value: object) -> str:
    material = unicodedata.normalize("NFKD", str(value).casefold())
    material = "".join(character for character in material if not unicodedata.combining(character))
    return " ".join(re.findall(r"[a-z0-9+#]+", material))
