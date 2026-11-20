"""Génère 2 PDF de démonstration réalistes dans ``data/docs/`` si le dossier est vide.

    * SDRIF_E_Synthese_IleDeFrance.pdf      (aménagement durable, trame verte, ZAN, mobilités)
    * PCAET_Guide_Transition_Energetique.pdf (rénovation thermique, EnR, îlots de chaleur)

Ces documents sont des SYNTHÈSES PÉDAGOGIQUES FICTIVES à des fins de démonstration :
ils s'inspirent des grands principes des documents officiels mais ne s'y substituent pas.
L'annexe du PCAET contient volontairement une contribution d'usager avec des données
personnelles FICTIVES afin de démontrer le filtrage RGPD à l'indexation.

Usage : python -m src.create_sample_docs [--force]
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    ListFlowable, ListItem, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from .config import settings, setup_logging

logger = logging.getLogger(__name__)

BLEU = colors.HexColor("#000091")  # bleu institutionnel
GRIS = colors.HexColor("#3A3A3A")

Section = dict[str, Any]

# ---------------------------------------------------------------------------
# Contenus
# ---------------------------------------------------------------------------
SDRIF_E: dict[str, Any] = {
    "filename": "SDRIF_E_Synthese_IleDeFrance.pdf",
    "title": "SDRIF-E — Synthèse à l'usage des collectivités",
    "subtitle": "Schéma Directeur de la Région Île-de-France Environnemental — Horizon 2040",
    "header": "SDRIF-E · Synthèse pédagogique (document de démonstration)",
    "sections": [
        {"h": "1. Objet et portée du SDRIF-E", "p": [
            "Le Schéma Directeur de la Région Île-de-France Environnemental (SDRIF-E) est le document "
            "de planification stratégique qui fixe, à l'horizon 2040, les grandes orientations "
            "d'aménagement du territoire francilien. Il succède au SDRIF de 2013 et intègre désormais "
            "pleinement les enjeux environnementaux : sobriété foncière, adaptation au changement "
            "climatique, préservation de la biodiversité et réduction des émissions de gaz à effet de serre.",
            "Les documents d'urbanisme locaux — schémas de cohérence territoriale (SCoT), plans locaux "
            "d'urbanisme intercommunaux (PLUi) et communaux (PLU) — doivent être compatibles avec les "
            "orientations réglementaires du SDRIF-E. En l'absence de SCoT, la compatibilité du PLUi "
            "s'apprécie directement au regard du schéma régional.",
            "Le projet s'articule autour de trois ambitions : un environnement de qualité et résilient, "
            "une région attractive et polycentrique, et une organisation des mobilités et des réseaux au "
            "service de la sobriété.",
        ]},
        {"h": "2. Sobriété foncière et trajectoire ZAN", "p": [
            "Conformément à la loi Climat et Résilience du 22 août 2021, la Région s'engage dans une "
            "trajectoire de Zéro Artificialisation Nette (ZAN) à l'horizon 2050. Sur la période "
            "2021-2031, l'objectif est de réduire de moitié la consommation d'espaces naturels, "
            "agricoles et forestiers (ENAF) par rapport à la décennie 2011-2021.",
            "Le SDRIF-E territorialise cette trajectoire : les capacités d'urbanisation nouvelle sont "
            "réservées en priorité aux secteurs desservis par les transports collectifs structurants, "
            "et chaque collectivité doit justifier, dans son PLUi, l'épuisement préalable des capacités "
            "de renouvellement urbain (friches, dents creuses, surélévation, reconversion de bureaux).",
        ], "bullets": [
            "Prioriser la densification autour des gares (rayon indicatif de 1 km).",
            "Mobiliser les friches industrielles et commerciales avant toute extension.",
            "Compenser toute artificialisation résiduelle par des opérations de renaturation.",
            "Suivre annuellement la consommation foncière via l'observatoire régional.",
        ]},
        {"h": "3. Densités minimales et renouvellement urbain", "p": [
            "Les secteurs à fort potentiel de densification doivent accueillir une augmentation "
            "significative de la densité humaine (habitants + emplois). Le PLUi traduit cette "
            "orientation par des règles de hauteur, d'emprise et de coefficient de pleine terre "
            "adaptées, en conciliant intensification urbaine et qualité du cadre de vie.",
            "La reconversion des bureaux obsolètes en logements et la mixité fonctionnelle des "
            "quartiers de gare sont encouragées afin de limiter les déplacements contraints.",
        ], "table": [
            ["Type de secteur", "Orientation de densité", "Traduction PLUi attendue"],
            ["Quartier de gare", "Densification prioritaire", "Hauteurs majorées, mixité"],
            ["Tissu pavillonnaire", "Densification douce", "Divisions parcellaires encadrées"],
            ["Franges rurales", "Urbanisation limitée", "Fronts urbains d'intérêt régional"],
        ], "page_break": True},
        {"h": "4. Trame verte et bleue et armature écologique", "p": [
            "La trame verte et bleue (TVB) constitue l'armature écologique régionale. Elle relie les "
            "réservoirs de biodiversité (forêts domaniales, vallées de la Seine, de la Marne et de "
            "l'Oise, zones humides) par des continuités écologiques qui doivent être préservées et "
            "restaurées dans les documents d'urbanisme locaux.",
            "Les PLUi doivent identifier les continuités écologiques à l'échelle parcellaire, les "
            "protéger par un zonage adapté (zones N ou A, espaces boisés classés, orientations "
            "d'aménagement et de programmation thématiques) et intégrer une trame noire limitant la "
            "pollution lumineuse nocturne.",
            "Les lisières des massifs boisés de plus de 100 hectares sont protégées : en dehors des "
            "sites urbains constitués, toute nouvelle urbanisation est proscrite dans une bande de "
            "50 mètres.",
        ], "bullets": [
            "Réservoirs de biodiversité : protection stricte.",
            "Corridors écologiques : maintien de la fonctionnalité, passages à faune.",
            "Trame bleue : renaturation des berges, désimperméabilisation des cours d'eau.",
            "Nature en ville : coefficient de pleine terre et végétalisation des cours d'école.",
        ]},
        {"h": "5. Mobilités douces et organisation des réseaux", "p": [
            "Le SDRIF-E accompagne la mise en service progressive du Grand Paris Express et le "
            "renforcement des lignes existantes. Il fixe l'objectif d'un report modal massif vers les "
            "transports collectifs, le vélo et la marche, en cohérence avec le plan des mobilités en "
            "Île-de-France.",
            "Les collectivités sont invitées à développer un réseau cyclable continu, sécurisé et "
            "jalonné, connecté au réseau express vélo régional, ainsi qu'à généraliser le stationnement "
            "vélo sécurisé dans les pôles d'échanges et les constructions neuves.",
            "Les PLUi doivent limiter les normes de stationnement automobile à proximité des gares et "
            "prévoir des cheminements piétons apaisés, accessibles aux personnes à mobilité réduite.",
        ], "page_break": True},
        {"h": "6. Adaptation au changement climatique", "p": [
            "Face à l'intensification des vagues de chaleur et des épisodes de pluies intenses, le "
            "schéma impose de réduire la vulnérabilité des territoires : désimperméabilisation des sols, "
            "gestion des eaux pluviales à la parcelle, préservation des champs d'expansion des crues et "
            "développement d'îlots de fraîcheur accessibles à tous.",
            "Les nouvelles opérations d'aménagement doivent intégrer une gestion des eaux pluviales "
            "sans rejet au réseau pour les pluies courantes, sauf impossibilité technique démontrée.",
        ]},
        {"h": "7. Mise en compatibilité et calendrier", "p": [
            "Les SCoT, PLUi et PLU disposent d'un délai pour se mettre en compatibilité avec le "
            "SDRIF-E et intégrer la trajectoire de sobriété foncière. Les services de l'État et de la "
            "Région accompagnent les collectivités dans cette démarche via un porter-à-connaissance et "
            "des outils de suivi partagés.",
            "Avertissement : la présente synthèse est un document de démonstration produit pour un "
            "prototype d'assistant documentaire. Seuls les documents officiels publiés par la Région "
            "Île-de-France font foi.",
        ]},
    ],
}

PCAET: dict[str, Any] = {
    "filename": "PCAET_Guide_Transition_Energetique.pdf",
    "title": "PCAET — Guide de la transition énergétique territoriale",
    "subtitle": "Plan Climat-Air-Énergie Territorial — Fiches actions pour les intercommunalités franciliennes",
    "header": "PCAET · Guide opérationnel (document de démonstration)",
    "sections": [
        {"h": "1. Cadre réglementaire du PCAET", "p": [
            "Le Plan Climat-Air-Énergie Territorial (PCAET) est obligatoire pour les établissements "
            "publics de coopération intercommunale (EPCI) à fiscalité propre de plus de 20 000 habitants "
            "depuis la loi relative à la transition énergétique pour la croissance verte de 2015. "
            "Il est établi pour six ans et fait l'objet d'un bilan à mi-parcours.",
            "Le PCAET comprend un diagnostic (émissions de gaz à effet de serre, consommations "
            "énergétiques, qualité de l'air, vulnérabilité climatique), une stratégie territoriale, un "
            "programme d'actions et un dispositif de suivi et d'évaluation. Il doit prendre en compte "
            "le SDRIF-E et le schéma régional climat-air-énergie.",
        ]},
        {"h": "2. Rénovation thermique des bâtiments publics", "p": [
            "Le patrimoine bâti des collectivités (écoles, gymnases, mairies, équipements culturels) "
            "représente souvent la majeure partie de leur consommation d'énergie. Le dispositif "
            "Éco Énergie Tertiaire (« décret tertiaire ») impose aux bâtiments tertiaires de plus de "
            "1 000 m² une réduction de leur consommation d'énergie finale de 40 % en 2030, 50 % en 2040 "
            "et 60 % en 2050 par rapport à une année de référence.",
            "La démarche recommandée suit quatre étapes : inventaire et audit énergétique du "
            "patrimoine, priorisation des bâtiments les plus énergivores, programmation pluriannuelle "
            "des travaux, puis suivi des consommations via la plateforme nationale OPERAT.",
        ], "bullets": [
            "Isolation de l'enveloppe (toitures, murs, menuiseries) avant tout changement de système.",
            "Remplacement des chaudières fioul et gaz par des pompes à chaleur ou un raccordement au réseau de chaleur.",
            "Pilotage et régulation (gestion technique du bâtiment, sous-comptage).",
            "Sensibilisation des usagers et des agents aux écogestes.",
        ], "table": [
            ["Échéance", "Réduction de consommation", "Référence"],
            ["2030", "- 40 %", "Année de référence ≥ 2010"],
            ["2040", "- 50 %", "Année de référence ≥ 2010"],
            ["2050", "- 60 %", "Année de référence ≥ 2010"],
        ], "page_break": True},
        {"h": "3. Développement des énergies renouvelables et de récupération", "p": [
            "L'Île-de-France dispose d'un potentiel important en géothermie profonde (nappe du "
            "Dogger) et de surface, qui alimente déjà de nombreux réseaux de chaleur urbains. Le PCAET "
            "doit identifier les zones favorables au développement de ces réseaux et prévoir leur "
            "extension et leur verdissement.",
            "Le solaire photovoltaïque sur toitures publiques, ombrières de parkings et friches "
            "constitue un levier rapide. Les collectivités peuvent recourir à l'autoconsommation "
            "collective ou à des sociétés de projet citoyennes pour associer les habitants.",
            "La récupération de chaleur fatale (data centers, stations d'épuration, unités de "
            "valorisation énergétique) et la méthanisation des biodéchets complètent le mix local.",
        ], "bullets": [
            "Cadastre solaire intercommunal et appel à projets sur le patrimoine public.",
            "Schéma directeur des réseaux de chaleur et de froid.",
            "Zones d'accélération des énergies renouvelables (loi APER de 2023).",
        ]},
        {"h": "4. Adaptation aux îlots de chaleur urbains", "p": [
            "Les îlots de chaleur urbains (ICU) se traduisent par des écarts de température nocturne "
            "pouvant dépasser plusieurs degrés entre le cœur dense de l'agglomération et les espaces "
            "ruraux voisins. Les populations vulnérables (personnes âgées, jeunes enfants, personnes "
            "isolées) y sont particulièrement exposées lors des épisodes caniculaires.",
            "Le PCAET doit cartographier les zones les plus exposées et programmer des actions de "
            "rafraîchissement : végétalisation massive, désimperméabilisation, revêtements à fort "
            "albédo, ombrage des espaces publics, présence de l'eau et création d'îlots de fraîcheur.",
            "La transformation des cours d'école en « cours oasis » (sols perméables, arbres, jeux "
            "d'eau) est une action emblématique et ouverte au public hors temps scolaire.",
        ], "bullets": [
            "Plan canopée : objectif chiffré de plantation d'arbres et indice de canopée par quartier.",
            "Coefficient de pleine terre minimal dans le règlement du PLUi.",
            "Réseau d'îlots de fraîcheur accessibles à moins de 10 minutes à pied.",
            "Plan canicule coordonné avec les centres communaux d'action sociale (CCAS).",
        ], "page_break": True},
        {"h": "5. Qualité de l'air et mobilité", "p": [
            "Le volet air du PCAET vise la réduction des émissions de polluants atmosphériques "
            "(oxydes d'azote, particules fines). Il s'articule avec la zone à faibles émissions "
            "mobilité (ZFE-m) de la métropole et avec le développement des mobilités actives.",
        ]},
        {"h": "6. Gouvernance, suivi et évaluation", "p": [
            "Le PCAET est suivi par un comité de pilotage associant élus, services, partenaires "
            "(ADEME, Région, syndicats d'énergie) et représentants de la société civile. Des "
            "indicateurs annuels sont publiés en données ouvertes.",
            "La concertation publique recueille les contributions des habitants. Ces contributions "
            "peuvent contenir des données personnelles : elles doivent être pseudonymisées avant toute "
            "exploitation analytique ou indexation dans un outil d'intelligence artificielle.",
        ]},
        {"h": "Annexe — Exemple de contribution citoyenne (données FICTIVES)", "p": [
            "Contribution n° 2025-0142 reçue lors de la concertation publique :",
            "Bonjour, je m'appelle Sophie MARTIN et j'habite au 12 rue des Lilas, 93200 Saint-Denis. "
            "La cour de l'école de mon quartier devient une fournaise en juin. Serait-il possible de "
            "la transformer en cour oasis ? Vous pouvez me joindre au 06 12 34 56 78 ou par courriel à "
            "sophie.martin@exemple.fr. Mon voisin, M. Bernard Lefèvre, soutient également cette demande.",
            "Réponse du service : la demande a été transmise au service patrimoine bâti pour étude "
            "dans le cadre du programme pluriannuel de transformation des cours d'école.",
            "Avertissement : ce guide est un document de démonstration produit pour un prototype "
            "d'assistant documentaire ; les identités et coordonnées de l'annexe sont fictives.",
        ]},
    ],
}


# ---------------------------------------------------------------------------
# Rendu PDF
# ---------------------------------------------------------------------------
def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("T", parent=base["Title"], textColor=BLEU, fontSize=20, leading=24),
        "subtitle": ParagraphStyle("ST", parent=base["Normal"], textColor=GRIS, fontSize=11,
                                   leading=15, spaceAfter=18),
        "h": ParagraphStyle("H", parent=base["Heading2"], textColor=BLEU, spaceBefore=12, spaceAfter=6),
        "p": ParagraphStyle("P", parent=base["BodyText"], fontSize=10.5, leading=14.5,
                            alignment=TA_JUSTIFY, spaceAfter=7),
    }


def _on_page(header: str):
    def draw(canvas, doc) -> None:  # type: ignore[no-untyped-def]
        canvas.saveState()
        canvas.setFillColor(BLEU)
        canvas.rect(0, A4[1] - 0.6 * cm, A4[0], 0.6 * cm, stroke=0, fill=1)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(GRIS)
        canvas.drawString(2 * cm, A4[1] - 1.2 * cm, header)
        canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"Page {doc.page}")
        canvas.restoreState()
    return draw


def build_pdf(spec: dict[str, Any], out_dir: Path) -> Path:
    st = _styles()
    path = out_dir / spec["filename"]
    story: list[Any] = [Paragraph(spec["title"], st["title"]), Paragraph(spec["subtitle"], st["subtitle"])]
    for sec in spec["sections"]:
        story.append(Paragraph(sec["h"], st["h"]))
        story.extend(Paragraph(p, st["p"]) for p in sec.get("p", []))
        if sec.get("bullets"):
            story.append(ListFlowable(
                [ListItem(Paragraph(b, st["p"]), leftIndent=12) for b in sec["bullets"]],
                bulletType="bullet", start="•", leftIndent=14))
        if sec.get("table"):
            t = Table(sec["table"], hAlign="LEFT", colWidths=[4.5 * cm, 5 * cm, 6.5 * cm])
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), BLEU),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CECECE")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F5FE")]),
            ]))
            story.extend([Spacer(1, 6), t, Spacer(1, 8)])
        if sec.get("page_break"):
            story.append(PageBreak())
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm,
                            topMargin=2 * cm, bottomMargin=2 * cm, title=spec["title"],
                            author="POC Assistant IA souverain - démonstration", subject=spec["subtitle"])
    cb = _on_page(spec["header"])
    doc.build(story, onFirstPage=cb, onLaterPages=cb)
    return path


def create_sample_docs(force: bool = False, out_dir: Path | None = None) -> list[Path]:
    """Crée les PDF de démonstration si ``out_dir`` ne contient aucun PDF (ou si ``force``)."""
    out_dir = out_dir or settings.docs_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    if not force and any(p.suffix.lower() == ".pdf" for p in out_dir.iterdir()):
        logger.info("Des PDF existent déjà dans %s : génération ignorée.", out_dir)
        return []
    created = []
    for spec in (SDRIF_E, PCAET):
        try:
            created.append(build_pdf(spec, out_dir))
            logger.info("Document de démonstration créé : %s", created[-1].name)
        except Exception as exc:  # noqa: BLE001
            logger.error("Échec de génération de %s : %s", spec["filename"], exc)
    return created


def main() -> None:
    setup_logging()
    parser = argparse.ArgumentParser(description="Génère les PDF de démonstration.")
    parser.add_argument("--force", action="store_true", help="Régénérer même si des PDF existent")
    args = parser.parse_args()
    for p in create_sample_docs(force=args.force):
        print(f"✔ {p}")


if __name__ == "__main__":
    main()
