"""Interface Streamlit — Assistant IA Souverain & Gouvernance Documentaire (IDF).

Lancement : streamlit run app.py
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import streamlit as st

from src.config import settings, setup_logging
from src.create_sample_docs import create_sample_docs
from src.ingest import run_ingestion
from src.ollama_client import OllamaClient, OllamaUnavailableError
from src.rag_engine import RAGAnswer, RAGEngine
from src.rgpd_filter import RGPDFilter
from src.vector_store import collection_stats

setup_logging()
logger = logging.getLogger("app")

st.set_page_config(
    page_title="Assistant IA souverain — Territoires IDF",
    page_icon="🏛️",
    layout="wide",
    menu_items={"About": "POC LLM/RAG 100 % local et open source — aucune API cloud."},
)

# --- Charte sobre et institutionnelle --------------------------------------
st.markdown(
    """
    <style>
      .bandeau {border-left: 6px solid #000091; padding: .6rem 1rem; background: #F5F5FE;
                margin-bottom: 1rem;}
      .bandeau h1 {color:#000091; font-size:1.6rem; margin:0;}
      .bandeau p {margin:.2rem 0 0 0; color:#3A3A3A;}
      .source-tag {display:inline-block; background:#E3E3FD; color:#000091; border-radius:4px;
                   padding:1px 8px; font-size:.82rem; font-weight:600;}
      div[data-testid="stMetricValue"] {color:#000091;}
    </style>
    <div class="bandeau">
      <h1>🏛️ Assistant IA souverain — Gouvernance documentaire territoriale</h1>
      <p>Interrogation des documents réglementaires franciliens (SDRIF-E, PLUi, PCAET) ·
         Traitement 100 % local (Ollama + ChromaDB) · Pseudonymisation RGPD systématique</p>
    </div>
    """,
    unsafe_allow_html=True,
)


# --- Ressources mises en cache ---------------------------------------------
@st.cache_resource(show_spinner=False)
def get_engine() -> RAGEngine:
    return RAGEngine()


@st.cache_data(ttl=10, show_spinner=False)
def get_health() -> dict:
    return OllamaClient().health()


def safe_filename(name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(name).stem).strip("._") or "document"
    return f"{stem[:80]}.pdf"


# --- Barre latérale : état de la plateforme ---------------------------------
with st.sidebar:
    st.header("État de la plateforme")
    health = get_health()
    if health["server"]:
        st.success(f"Ollama joignable · `{settings.ollama_host}`")
        st.write(("✅" if health["llm"] else "❌") + f" Génération : `{settings.llm_model}`")
        st.write(("✅" if health["embed"] else "❌") + f" Embeddings : `{settings.embedding_model}`")
        missing = [m for m, ok in ((settings.llm_model, health["llm"]),
                                   (settings.embedding_model, health["embed"])) if not ok]
        if missing:
            st.code("\n".join(f"docker exec ollama ollama pull {m}" for m in missing), language="bash")
    else:
        st.error("Ollama non démarré — mode dégradé (recherche lexicale, sans génération).")
        st.code("docker compose up -d", language="bash")
    if st.button("↻ Rafraîchir l'état", width="stretch"):
        get_health.clear()
        st.rerun()

    st.divider()
    stats = collection_stats()
    st.metric("Extraits indexés", stats["chunks"])
    for doc, n in stats["documents"].items():
        st.caption(f"📄 {doc} — {n} extraits")

    st.divider()
    st.caption("🔒 Aucune donnée ne quitte l'infrastructure. Télémétrie ChromaDB désactivée. "
               "Journaux sans données personnelles.")

tab_ask, tab_index, tab_rgpd, tab_gouv = st.tabs(
    ["💬 Assistant", "📥 Indexation documentaire", "🛡️ Filtre RGPD", "📋 Gouvernance"]
)

# --- Onglet 1 : Assistant ---------------------------------------------------
MODE_LABELS = {
    "llm": ("success", "Réponse générée localement par le modèle `{m}` à partir des seuls extraits cités."),
    "fallback_lexical": ("warning", "Mode dégradé : Ollama indisponible — recherche lexicale locale, sans génération."),
    "fallback_extractive": ("warning", "Mode dégradé : modèle de génération indisponible — extraits restitués verbatim."),
    "empty_index": ("info", "Index vide : indexez d'abord des documents."),
    "no_match": ("info", "Aucun extrait pertinent trouvé dans le corpus."),
}

with tab_ask:
    st.subheader("Poser une question métier")
    examples = [
        "Quels sont les objectifs ZAN fixés pour l'Île-de-France ?",
        "Quelles obligations de réduction de consommation pour les bâtiments publics ?",
        "Comment le PLUi doit-il protéger la trame verte et bleue ?",
        "Quelles actions pour lutter contre les îlots de chaleur urbains ?",
    ]
    choice = st.selectbox("Exemples de questions", ["—"] + examples, index=0)
    with st.form("ask_form", clear_on_submit=False):
        question = st.text_area(
            "Votre question",
            value="" if choice == "—" else choice,
            height=90,
            placeholder="Ex. : Quelles sont les règles de densification autour des gares ?",
        )
        col1, col2 = st.columns([1, 3])
        k = col1.slider("Extraits à mobiliser", 2, 10, settings.top_k)
        submitted = st.form_submit_button("Interroger l'assistant", type="primary")

    if submitted:
        if not question.strip():
            st.warning("Saisissez une question.")
        else:
            with st.spinner("Recherche dans le corpus et génération locale…"):
                try:
                    res: RAGAnswer = get_engine().ask(question, k=k)
                except Exception as exc:  # noqa: BLE001 - message clair pour l'agent
                    logger.exception("Erreur moteur RAG")
                    st.error(f"Erreur inattendue du moteur : {exc}")
                    st.stop()

            if res.pii_in_question:
                st.info("🛡️ Données personnelles détectées et pseudonymisées dans la question avant "
                        f"traitement : {res.pii_in_question}\n\nQuestion transmise : « {res.filtered_question} »")
            level, msg = MODE_LABELS[res.mode]
            getattr(st, level)(msg.format(m=settings.llm_model))

            st.markdown("#### Réponse")
            st.markdown(res.answer)

            if res.sources:
                st.markdown("#### Extraits sources utilisés")
                for i, s in enumerate(res.sources, start=1):
                    with st.expander(f"Extrait {i} — {s.source} · page {s.page} · pertinence {s.score:.0%}",
                                     expanded=(i == 1)):
                        st.markdown(f'<span class="source-tag">{s.citation}</span>', unsafe_allow_html=True)
                        st.write(s.text)

# --- Onglet 2 : Indexation --------------------------------------------------
with tab_index:
    st.subheader("Ajouter des documents réglementaires")
    st.caption(f"Formats acceptés : PDF texte (≤ {settings.max_upload_mb} Mo). Chaque document est "
               "pseudonymisé puis découpé en extraits de "
               f"{settings.chunk_size} caractères (chevauchement {settings.chunk_overlap}).")

    uploads = st.file_uploader("Déposer des PDF (SDRIF-E, PLUi, PCAET, délibérations…)",
                               type=["pdf"], accept_multiple_files=True)
    c1, c2, c3 = st.columns(3)
    do_index = c1.button("📥 Enregistrer et indexer", type="primary", width="stretch")
    do_reindex = c2.button("🔄 Ré-indexer tout le corpus", width="stretch")
    do_samples = c3.button("🧪 Générer les documents de démonstration", width="stretch")

    if do_samples:
        created = create_sample_docs(force=True)
        if created:
            st.success("Documents créés : " + ", ".join(p.name for p in created))
        else:
            st.error("Échec de génération (voir journaux).")

    targets: list[str] | None = None
    if do_index:
        if not uploads:
            st.warning("Aucun fichier sélectionné.")
        else:
            settings.docs_dir.mkdir(parents=True, exist_ok=True)
            targets = []
            for up in uploads:
                data = up.getvalue()
                if len(data) > settings.max_upload_mb * 1024 * 1024:
                    st.error(f"{up.name} : dépasse {settings.max_upload_mb} Mo, ignoré.")
                    continue
                if not data.startswith(b"%PDF"):
                    st.error(f"{up.name} : n'est pas un PDF valide, ignoré.")
                    continue
                name = safe_filename(up.name)
                (settings.docs_dir / name).write_bytes(data)
                targets.append(name)

    if (do_index and targets) or do_reindex:
        bar = st.progress(0.0, text="Préparation…")
        try:
            report = run_ingestion(only=targets if do_index else None,
                                   reset=do_reindex,
                                   progress=lambda msg, p: bar.progress(min(p, 1.0), text=msg))
        except OllamaUnavailableError as exc:
            bar.empty()
            st.error(f"Indexation impossible : {exc}")
        else:
            st.success(f"{len(report.files)} document(s) traité(s) · {report.total_chunks} extraits indexés · "
                       f"{report.total_pii} donnée(s) personnelle(s) pseudonymisée(s).")
            st.dataframe(
                [{"Document": f.source, "Pages": f.pages, "Extraits": f.chunks,
                  "PII masquées": ", ".join(f"{k}:{v}" for k, v in f.pii_masked.items()) or "—",
                  "Statut": f.status if not f.error else f"erreur : {f.error}"} for f in report.files],
                width="stretch", hide_index=True)
            get_health.clear()

    st.divider()
    st.markdown("**Documents présents dans `data/docs/`**")
    pdfs = sorted(settings.docs_dir.glob("*.pdf")) if settings.docs_dir.exists() else []
    if pdfs:
        indexed = collection_stats()["documents"]
        st.dataframe([{"Fichier": p.name, "Taille (Ko)": round(p.stat().st_size / 1024, 1),
                       "Indexé": "✅" if p.name in indexed else "⏳"} for p in pdfs],
                     width="stretch", hide_index=True)
    else:
        st.info("Aucun document. Générez les documents de démonstration ou déposez vos PDF.")

# --- Onglet 3 : Filtre RGPD -------------------------------------------------
with tab_rgpd:
    st.subheader("Tester le filtre de pseudonymisation")
    st.caption("Ce filtre est appliqué automatiquement avant toute indexation et avant toute requête au modèle. "
               "Le texte saisi ici n'est ni stocké ni journalisé.")
    demo = ("Bonjour, je m'appelle Sophie MARTIN et j'habite au 12 rue des Lilas, 93200 Saint-Denis.\n"
            "Mon numéro : 06 12 34 56 78, mon courriel : sophie.martin@exemple.fr.\n"
            "NIR : 2 85 07 93 066 123 45 — numéro fiscal : 0123456789012.\n"
            "M. Bernard Lefèvre, mon voisin, souhaite que la cour d'école devienne une cour oasis "
            "conformément au PCAET d'Île-de-France.\n\nCordialement,\nSophie Martin")
    raw = st.text_area("Texte contenant des données personnelles", value=demo, height=200)
    mode = st.radio("Mode", ["pseudonymize", "mask"], horizontal=True,
                    format_func=lambda m: "Pseudonymisation (jetons HMAC stables)" if m == "pseudonymize"
                    else "Masquage irréversible")
    if st.button("Appliquer le filtre", type="primary"):
        result = RGPDFilter(mode=mode).filter(raw)  # type: ignore[arg-type]
        a, b = st.columns(2)
        a.markdown("**Texte d'origine**")
        a.text(raw)
        b.markdown("**Texte filtré (seul transmis au moteur IA)**")
        b.text(result.text)
        if result.total:
            st.success(f"{result.total} donnée(s) personnelle(s) traitée(s).")
            st.bar_chart(result.counts, horizontal=True)
        else:
            st.info("Aucune donnée personnelle détectée.")

# --- Onglet 4 : Gouvernance -------------------------------------------------
with tab_gouv:
    gov = Path(__file__).parent / "GOVERNANCE_RGPD.md"
    if gov.exists():
        st.markdown(gov.read_text(encoding="utf-8"))
    else:
        st.info("Registre de traitement introuvable (GOVERNANCE_RGPD.md).")
