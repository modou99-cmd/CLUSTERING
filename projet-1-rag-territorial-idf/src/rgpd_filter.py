"""Filtre RGPD : détection et pseudonymisation des données personnelles (PII).

Appliqué AVANT toute indexation (ingest.py) et AVANT toute requête envoyée au
modèle (rag_engine.py), conformément au principe de minimisation (art. 5.1.c RGPD)
et de protection des données dès la conception (art. 25 RGPD).

Catégories traitées (ordre d'application significatif) :
    EMAIL       adresses électroniques
    NIR         numéro de sécurité sociale (15 chiffres, clé incluse)
    FISCAL      numéro fiscal / SPI (13 chiffres commençant par 0-3)
    IBAN        IBAN français
    TELEPHONE   numéros français (+33, 0033, 0X XX XX XX XX)
    ADRESSE     adresses postales exactes (n° + type de voie + nom [+ CP + ville])
    NOM         noms propres de personnes (civilité + nom, prénom + nom, signatures)

Deux modes :
    * ``pseudonymize`` (défaut) : jeton déterministe ``[NOM_3f9a1c]`` calculé par
      HMAC-SHA256 avec un sel secret → une même personne garde le même jeton dans
      tout le corpus (utile pour l'analyse) sans qu'aucune table de correspondance
      ne soit stockée. Ré-identification impossible sans le sel.
    * ``mask`` : remplacement irréversible par ``[NOM]``, ``[EMAIL]``, etc.

Limites assumées (documentées dans GOVERNANCE_RGPD.md) : la détection des noms
repose sur des heuristiques (civilités, dictionnaire de prénoms, signatures) et
non sur un modèle NER ; un contrôle humain reste requis pour les documents sensibles.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
from collections import Counter
from typing import Callable, Literal

from pydantic import BaseModel, Field

from .config import settings

logger = logging.getLogger(__name__)

Mode = Literal["pseudonymize", "mask"]

# ---------------------------------------------------------------------------
# Expressions régulières
# ---------------------------------------------------------------------------
_UP = "A-ZÀÂÄÇÉÈÊËÎÏÔÖÙÛÜŸ"
_LOW = "a-zàâäçéèêëîïôöùûüÿœæ"
_CAP_WORD = rf"[{_UP}][{_LOW}]+(?:[-'’][{_UP}]?[{_LOW}]+)*"  # Dupont, Saint-Martin, d'Arc
_UPPER_WORD = rf"[{_UP}]{{2,}}(?:[-'’][{_UP}]{{2,}})*"  # DUPONT, LE-GALL
_SURNAME = rf"(?:{_UPPER_WORD}|{_CAP_WORD})"
_PARTICLE = r"(?:(?:de|du|des|d'|d’|le|la|van|von|ben|el)\s?)"

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")

# NIR : sexe(1|2) aa mm dept(2 chiffres|2A|2B) commune(3) ordre(3) [clé(2)]
NIR_RE = re.compile(
    r"(?<!\d)[12][\s.]?\d{2}[\s.]?(?:0[1-9]|1[0-2]|[2-9]\d)[\s.]?(?:\d{2}|2[AaBb])"
    r"[\s.]?\d{3}[\s.]?\d{3}(?:[\s.]?\d{2})?(?!\d)"
)

# Numéro fiscal (SPI) : 13 chiffres, premier chiffre 0 à 3, groupements usuels.
FISCAL_RE = re.compile(
    r"(?<!\d)(?:[0-3]\d{12}|[0-3]\d\s\d{2}\s\d{3}\s\d{3}\s\d{3})(?!\d)"
)

IBAN_RE = re.compile(r"\bFR\d{2}(?:\s?[A-Z0-9]{4}){5}\s?[A-Z0-9]{3}\b", re.IGNORECASE)

PHONE_RE = re.compile(
    r"(?:(?:\+|00)33[\s.\-]?\(?0?\)?[\s.\-]?[1-9]|(?<!\d)0[1-9])(?:[\s.\-]?\d{2}){4}(?!\d)"
)

_VOIE = (
    r"(?i:rue|avenue|av\.|boulevard|bd|place|pl\.|allée|allee|impasse|chemin|quai|cours|"
    r"route|square|villa|passage|cité|cite|sentier|ruelle|voie|rond-point|esplanade|"
    r"promenade|parvis|hameau|résidence|residence|faubourg)"
)
_CITY = (
    rf"[{_UP}][{_LOW}'’]+(?:[\s\-](?:(?:sur|sous|en|lès|les|le|la|de|du|des|d')[\s\-]?)?"
    rf"[{_UP}][{_LOW}'’]+){{0,4}}"
)
ADDRESS_RE = re.compile(
    rf"\b\d{{1,4}}(?:\s?(?i:bis|ter|quater|[a-d])\b)?,?\s+{_VOIE}\s+"
    rf"(?:[{_UP}{_LOW}0-9'’\-]+\s?){{1,6}}?"  # nom de la voie (court, non gourmand)
    rf"(?=[,.;\n)]|\s+\d{{5}}\b|$)"
    rf"(?:,?\s*\d{{5}}\s+{_CITY})?",
    re.MULTILINE,
)
# Code postal + ville isolés immédiatement après une adresse déjà masquée
POSTAL_AFTER_TOKEN_RE = re.compile(rf"(\[ADRESSE[^\]]*\]),?\s*\d{{5}}\s+{_CITY}")

_CIVILITE = (
    r"(?:M\.|MM\.|Mme|Mmes|Mlle|Monsieur|Madame|Mademoiselle|Messieurs|Dr\.?|Docteur|"
    r"Maître|Me|Pr\.?|Professeur)"
)
# Civilité + [Prénom] + Nom : on conserve la civilité, on masque l'identité.
CIVILITE_NAME_RE = re.compile(
    rf"\b(?P<civ>{_CIVILITE})\s+(?P<name>(?:{_CAP_WORD}\s+)?{_PARTICLE}?{_SURNAME}"
    rf"(?:[\s\-]{_UPPER_WORD})?)"
)

# Dictionnaire (non exhaustif) de prénoms courants en France.
_PRENOMS = {
    "adam", "adrien", "agnès", "alain", "alexandre", "alexandra", "alice", "amandine",
    "amélie", "anaïs", "andré", "anne", "annie", "antoine", "arnaud", "arthur", "audrey",
    "aurélie", "aurélien", "axel", "baptiste", "benjamin", "benoît", "bernard", "brigitte",
    "bruno", "camille", "caroline", "catherine", "cécile", "céline", "chantal", "charles",
    "charlotte", "chloé", "christian", "christine", "christophe", "claire", "claude",
    "clément", "corinne", "cyril", "damien", "daniel", "david", "delphine", "denis",
    "didier", "dominique", "eléonore", "élise", "élodie", "emma", "emmanuel", "emmanuelle",
    "éric", "estelle", "étienne", "fabien", "fabrice", "fatima", "florence", "florian",
    "francis", "françois", "françoise", "frédéric", "gabriel", "gaëlle", "georges",
    "gérard", "gilles", "guillaume", "hélène", "henri", "hugo", "inès", "isabelle",
    "jacques", "jean", "jeanne", "jérôme", "joël", "jonathan", "joseph", "julie", "julien",
    "justine", "karim", "kevin", "laetitia", "laura", "laurence", "laurent", "léa", "léo",
    "lina", "louis", "louise", "luc", "lucas", "lucie", "manon", "marc", "marie",
    "marine", "martin", "martine", "mathieu", "mathilde", "maxime", "mélanie", "michel",
    "michèle", "mohamed", "monique", "nadia", "nathalie", "nicolas", "noah", "olivier",
    "pascal", "patricia", "patrick", "paul", "pauline", "philippe", "pierre", "quentin",
    "raphaël", "rémi", "romain", "sabrina", "samuel", "sandrine", "sarah", "sébastien",
    "serge", "sophie", "stéphane", "stéphanie", "sylvie", "thierry", "thomas", "valérie",
    "véronique", "vincent", "virginie", "xavier", "yannick", "yasmine", "yves", "zoé",
}
_PRENOM_TOKEN = rf"(?:{_CAP_WORD})"
PRENOM_NOM_RE = re.compile(
    rf"\b(?P<first>{_PRENOM_TOKEN})(?:[\s\-](?P<first2>{_PRENOM_TOKEN}))?\s+"
    rf"(?P<last>{_PARTICLE}?{_SURNAME})\b"
)

# Formules d'auto-identification et signatures de courrier.
SELF_ID_RE = re.compile(
    rf"(?P<lead>\b(?i:je m'appelle|je m’appelle|je soussignée?|signé|nom\s*:|"
    rf"nom et prénom\s*:|prénom et nom\s*:|demandeur\s*:|requérant\s*:)\s*)"
    rf"(?P<name>(?:{_CAP_WORD}|{_UPPER_WORD})(?:\s+{_PARTICLE}?(?:{_CAP_WORD}|{_UPPER_WORD})){{0,2}})"
)
SIGNATURE_RE = re.compile(
    rf"(?P<lead>\b(?:Cordialement|Bien cordialement|Salutations distinguées|"
    rf"Respectueusement|Bien à vous)[,.]?\s*\n\s*)"
    rf"(?P<name>(?:{_CAP_WORD}|{_UPPER_WORD})(?:[\s\-]+(?:{_CAP_WORD}|{_UPPER_WORD})){{0,2}})"
)

# Termes institutionnels jamais considérés comme des noms de personnes.
_WHITELIST = {
    "île-de-france", "ile-de-france", "paris", "seine", "marne", "essonne", "yvelines",
    "hauts-de-seine", "val-de-marne", "val-d'oise", "seine-saint-denis", "seine-et-marne",
    "grand paris", "région", "sdrif", "sdrif-e", "pcaet", "plui", "plu", "zan", "ademe",
    "cerema", "insee", "état", "france", "europe",
}


# ---------------------------------------------------------------------------
# Modèles de résultat
# ---------------------------------------------------------------------------
class PIIEntity(BaseModel):
    """Entité détectée (la valeur en clair n'est conservée qu'en mémoire)."""

    category: str
    start: int
    end: int
    replacement: str


class FilterResult(BaseModel):
    """Résultat d'un filtrage RGPD."""

    text: str
    entities: list[PIIEntity] = Field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        return dict(Counter(e.category for e in self.entities))

    @property
    def total(self) -> int:
        return len(self.entities)


# ---------------------------------------------------------------------------
# Filtre
# ---------------------------------------------------------------------------
class RGPDFilter:
    """Pseudonymiseur de données personnelles pour textes en français."""

    def __init__(self, mode: Mode = "pseudonymize", salt: str | None = None) -> None:
        if mode not in ("pseudonymize", "mask"):
            raise ValueError(f"Mode RGPD inconnu : {mode!r}")
        self.mode: Mode = mode
        self._salt = (salt if salt is not None else settings.rgpd_salt).encode("utf-8")

    # -- jetons -----------------------------------------------------------
    def _token(self, category: str, value: str) -> str:
        if self.mode == "mask":
            return f"[{category}]"
        normalized = re.sub(r"[\s.\-]", "", value).lower()
        digest = hmac.new(self._salt, f"{category}:{normalized}".encode(), hashlib.sha256)
        return f"[{category}_{digest.hexdigest()[:6]}]"

    # -- passes -----------------------------------------------------------
    def _sub(
        self,
        text: str,
        pattern: re.Pattern[str],
        category: str,
        entities: list[PIIEntity],
        group: str | None = None,
        accept: Callable[[re.Match[str]], bool] | None = None,
    ) -> str:
        """Remplace les correspondances ; si ``group`` est fourni, seul ce groupe est masqué."""

        def repl(m: re.Match[str]) -> str:
            if accept is not None and not accept(m):
                return m.group(0)
            value = m.group(group) if group else m.group(0)
            if not value or value.startswith("["):
                return m.group(0)
            token = self._token(category, value)
            entities.append(
                PIIEntity(category=category, start=m.start(), end=m.end(), replacement=token)
            )
            if group:
                s, e = m.start(group) - m.start(), m.end(group) - m.start()
                full = m.group(0)
                return full[:s] + token + full[e:]
            return token

        return pattern.sub(repl, text)

    @staticmethod
    def _is_person(m: re.Match[str]) -> bool:
        first = m.group("first").lower()
        last = m.group("last").lower()
        if first not in _PRENOMS:
            return False
        return last not in _WHITELIST and first not in _WHITELIST

    @staticmethod
    def _not_whitelisted(m: re.Match[str]) -> bool:
        return m.group("name").strip().lower() not in _WHITELIST

    def filter(self, text: str) -> FilterResult:
        """Détecte et remplace toutes les PII d'un texte."""
        if not text:
            return FilterResult(text=text or "")
        entities: list[PIIEntity] = []
        out = text
        try:
            out = self._sub(out, EMAIL_RE, "EMAIL", entities)
            out = self._sub(out, IBAN_RE, "IBAN", entities)
            out = self._sub(out, NIR_RE, "NIR", entities)
            out = self._sub(out, FISCAL_RE, "FISCAL", entities)
            out = self._sub(out, PHONE_RE, "TELEPHONE", entities)
            out = self._sub(out, ADDRESS_RE, "ADRESSE", entities)
            out = POSTAL_AFTER_TOKEN_RE.sub(r"\1", out)
            out = self._sub(out, SELF_ID_RE, "NOM", entities, group="name",
                            accept=self._not_whitelisted)
            out = self._sub(out, SIGNATURE_RE, "NOM", entities, group="name",
                            accept=self._not_whitelisted)
            out = self._sub(out, CIVILITE_NAME_RE, "NOM", entities, group="name",
                            accept=self._not_whitelisted)
            out = self._sub(out, PRENOM_NOM_RE, "NOM", entities, accept=self._is_person)
        except re.error as exc:  # pragma: no cover - garde-fou
            logger.exception("Erreur d'expression régulière dans le filtre RGPD : %s", exc)
            raise
        result = FilterResult(text=out, entities=entities)
        if result.total:
            # Journalisation agrégée uniquement : aucune valeur personnelle.
            logger.debug("Filtre RGPD : %d entité(s) traitée(s) %s", result.total, result.counts)
        return result

    def __call__(self, text: str) -> str:
        return self.filter(text).text


_default_filter: RGPDFilter | None = None


def get_filter(mode: Mode = "pseudonymize") -> RGPDFilter:
    """Instance partagée du filtre (mode pseudonymisation par défaut)."""
    global _default_filter
    if mode != "pseudonymize":
        return RGPDFilter(mode=mode)
    if _default_filter is None:
        _default_filter = RGPDFilter(mode="pseudonymize")
    return _default_filter


def pseudonymize(text: str, mode: Mode = "pseudonymize") -> FilterResult:
    """Raccourci fonctionnel."""
    return get_filter(mode).filter(text)


if __name__ == "__main__":  # Démonstration en ligne de commande
    import sys

    from .config import setup_logging

    setup_logging()
    piped = "" if sys.stdin.isatty() else sys.stdin.read()
    sample = piped.strip() or (
        "Bonjour, je m'appelle Jean DUPONT, j'habite au 12 rue des Lilas, 93200 Saint-Denis.\n"
        "Contact : jean.dupont@example.fr ou 06 12 34 56 78. NIR : 1 85 07 75 115 423 57.\n"
        "Madame Martin, de la mairie, m'a conseillé d'écrire à la Région Île-de-France.\n"
        "Cordialement,\nJean Dupont"
    )
    res = pseudonymize(sample)
    print(res.text)
    print("\nEntités :", res.counts)
