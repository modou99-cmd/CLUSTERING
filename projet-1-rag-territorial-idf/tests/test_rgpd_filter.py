"""Tests du filtre RGPD — exécuter avec : pytest -q"""

from __future__ import annotations

import pytest

from src.rgpd_filter import RGPDFilter


@pytest.fixture()
def f() -> RGPDFilter:
    return RGPDFilter(mode="pseudonymize", salt="test-salt")


@pytest.fixture()
def m() -> RGPDFilter:
    return RGPDFilter(mode="mask")


@pytest.mark.parametrize("text", [
    "Écrivez à jean.dupont@example.fr pour plus d'infos.",
    "Contact : prenom.nom+urba@mairie-exemple.gouv.fr",
])
def test_email(m: RGPDFilter, text: str) -> None:
    res = m.filter(text)
    assert "@" not in res.text and "[EMAIL]" in res.text


@pytest.mark.parametrize("phone", [
    "06 12 34 56 78", "0612345678", "01.45.67.89.10", "+33 6 12 34 56 78", "0033 1 45 67 89 10",
    "+33 (0)1 45 67 89 10",
])
def test_phone(m: RGPDFilter, phone: str) -> None:
    res = m.filter(f"Appelez le {phone} demain.")
    assert "[TELEPHONE]" in res.text and phone not in res.text


@pytest.mark.parametrize("nir", ["1 85 07 75 115 423 57", "285072A11542357", "2 92 11 2B 123 456"])
def test_nir(m: RGPDFilter, nir: str) -> None:
    assert m.filter(f"NIR : {nir}").text == "NIR : [NIR]"


def test_fiscal(m: RGPDFilter) -> None:
    assert m.filter("Numéro fiscal 0123456789012.").text == "Numéro fiscal [FISCAL]."
    assert "[FISCAL]" in m.filter("SPI : 30 12 345 678 901").text


def test_iban(m: RGPDFilter) -> None:
    assert "[IBAN]" in m.filter("IBAN FR76 3000 6000 0112 3456 7890 189").text


def test_address(m: RGPDFilter) -> None:
    out = m.filter("J'habite au 12 rue des Lilas, 93200 Saint-Denis et la cour est chaude.").text
    assert "Lilas" not in out and "93200" not in out and "[ADRESSE]" in out
    assert out.endswith("et la cour est chaude.")


def test_names(m: RGPDFilter) -> None:
    out = m.filter(
        "Bonjour, je m'appelle Sophie MARTIN et M. Bernard Lefèvre soutient la demande.\n"
        "Cordialement,\nPaul Durand"
    ).text
    for leak in ("Sophie", "MARTIN", "Lefèvre", "Durand"):
        assert leak not in out
    assert "M. [NOM]" in out and " et " in out


def test_no_false_positive_on_regulatory_text(f: RGPDFilter) -> None:
    text = (
        "Le SDRIF-E fixe une trajectoire ZAN en Île-de-France d'ici 2050. Le décret tertiaire "
        "impose -40 % en 2030 pour les bâtiments de plus de 1 000 m². Voir la page 12 du PLUi "
        "de Seine-Saint-Denis et le PCAET de Grand Paris Sud."
    )
    res = f.filter(text)
    assert res.text == text and res.total == 0


def test_pseudonyms_are_deterministic_and_salted() -> None:
    a = RGPDFilter(salt="s1").filter("Madame Sophie Martin").text
    b = RGPDFilter(salt="s1").filter("Madame Sophie MARTIN").text
    c = RGPDFilter(salt="s2").filter("Madame Sophie Martin").text
    assert a == b  # même personne → même jeton (insensible à la casse)
    assert a != c  # sel différent → jeton différent


def test_invalid_mode() -> None:
    with pytest.raises(ValueError):
        RGPDFilter(mode="clear")  # type: ignore[arg-type]
