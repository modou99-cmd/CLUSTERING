# Gouvernance des données & conformité RGPD

> **Assistant IA souverain — POC RAG territorial Île-de-France**
> Document rédigé dans une posture de **Délégué à la Protection des Données (DPO)**.
> Il constitue la fiche du registre des activités de traitement (art. 30 RGPD) du prototype
> et doit être validée par le DPO de la collectivité avant toute mise en production.

---

## 1. Fiche du registre des activités de traitement (art. 30 RGPD)

| Rubrique | Contenu |
|---|---|
| **Nom du traitement** | Assistant documentaire IA pour l'interprétation des documents réglementaires territoriaux |
| **Responsable de traitement** | La collectivité ou l'EPCI déployant l'outil (représentée par son exécutif) |
| **DPO** | Délégué à la protection des données de la collectivité — `dpo@<collectivite>.fr` |
| **Sous-traitant(s)** | Aucun : hébergement et calcul internes (on-premise). Si recours à un hébergeur : contrat art. 28 + qualification SecNumCloud |
| **Finalité principale** | Aider les agents à rechercher et interpréter les documents de planification (SDRIF-E, PLUi, PCAET, délibérations) avec citation des sources |
| **Finalité secondaire** | Exploitation des contributions et demandes d'usagers (concertation, courriers) après pseudonymisation |
| **Finalités exclues** | Profilage des usagers, prise de décision individuelle automatisée (art. 22), réutilisation commerciale, entraînement de modèles |
| **Base légale** | Art. 6.1.e — exécution d'une mission d'intérêt public (planification, urbanisme, transition énergétique) |
| **Personnes concernées** | Usagers auteurs de demandes ou contributions ; agents et élus cités dans les documents |
| **Catégories de données** | Identité (nom, prénom), coordonnées (adresse postale, email, téléphone), identifiants (NIR, numéro fiscal, IBAN) — **toutes pseudonymisées avant indexation** |
| **Données sensibles (art. 9)** | Non collectées. Tout document en contenant doit être écarté ou expurgé manuellement avant dépôt |
| **Destinataires** | Agents habilités des services urbanisme, environnement, transition écologique |
| **Transferts hors UE** | **Aucun.** Aucune API cloud, aucune télémétrie (ChromaDB et Streamlit configurés sans collecte) |
| **Durées de conservation** | Documents réglementaires : durée de validité du document + archivage légal. Demandes d'usagers : durée de traitement de la demande + 2 ans maximum. Index vectoriel : synchronisé (ré-indexation / suppression) |
| **Mesures de sécurité** | Cf. § 4 |

---

## 2. Principes appliqués (art. 5 et 25 RGPD)

### 2.1 Minimisation des données (art. 5.1.c)
- **Filtrage à la source** : le module `src/rgpd_filter.py` est appelé **avant** tout découpage,
  tout calcul d'embedding et toute écriture dans ChromaDB (`src/ingest.py`).
- **Filtrage des requêtes** : chaque question d'agent est pseudonymisée **avant** d'être vectorisée
  ou transmise au modèle de langage (`src/rag_engine.py`).
- **Défense en profondeur** : la réponse générée par le modèle est elle-même repassée au filtre.
- **Journaux** : seuls des compteurs agrégés (ex. `{'EMAIL': 1, 'NOM': 2}`) sont journalisés,
  jamais les valeurs personnelles.

### 2.2 Protection des données dès la conception et par défaut (art. 25)
| Catégorie | Détection | Remplacement (mode par défaut) |
|---|---|---|
| Email | Expression régulière RFC simplifiée | `[EMAIL_a1b2c3]` |
| Téléphone FR | `0X XX XX XX XX`, `+33`, `0033`, séparateurs variés | `[TELEPHONE_…]` |
| NIR | 13 ou 15 chiffres, Corse (2A/2B), espaces optionnels | `[NIR_…]` |
| Numéro fiscal (SPI) | 13 chiffres commençant par 0 à 3 | `[FISCAL_…]` |
| IBAN FR | `FR76 …` | `[IBAN_…]` |
| Adresse exacte | n° + type de voie + nom (+ code postal + commune) | `[ADRESSE_…]` |
| Nom de personne | Civilités, dictionnaire de prénoms, formules (« je m'appelle », signatures) | `[NOM_…]` (civilité conservée) |

- **Pseudonymisation par HMAC-SHA256 salé** : une même personne obtient le même jeton dans tout
  le corpus (cohérence d'analyse), **sans table de correspondance stockée**. Sans le sel secret
  (`RGPD_SALT`), la ré-identification par force brute est rendue impraticable.
- **Mode masquage irréversible** (`[NOM]`, `[EMAIL]`…) disponible pour les usages les plus sensibles.

> ⚠️ **Rappel juridique** : des données pseudonymisées **restent des données personnelles**
> (considérant 26 RGPD). Le traitement demeure soumis au RGPD ; la pseudonymisation est une
> mesure de sécurité qui réduit le risque, pas une anonymisation.

### 2.3 Exactitude et transparence
- Le modèle a l'obligation de **citer `[Source : fichier - Page X]`** pour chaque affirmation ;
  à défaut, les citations sont ajoutées automatiquement. L'agent peut toujours vérifier l'extrait.
- Si les extraits ne permettent pas de répondre, l'assistant le déclare explicitement au lieu
  d'inventer (réduction des « hallucinations »).
- L'interface signale qu'il s'agit d'une **aide à la décision** : la réponse ne se substitue ni au
  document officiel ni à l'analyse juridique d'un agent.

### 2.4 Limitation de la conservation et droits des personnes
- Suppression d'un document : retirer le PDF de `data/docs/` puis lancer `python -m src.ingest --reset`
  (ou « Ré-indexer tout le corpus ») ; les chunks associés sont purgés.
- **Droits d'accès, de rectification, d'effacement, d'opposition** (art. 15 à 21) : exercés auprès
  du DPO. Le jeton HMAC permet, avec le sel détenu par le DPO, de retrouver les extraits concernant
  une personne sans conserver de table de correspondance.

---

## 3. Politique d'hébergement souverain

| Composant | Licence | Localisation | Flux sortant |
|---|---|---|---|
| Ollama (serveur de modèles) | MIT | Conteneur Docker local, port lié à `127.0.0.1` | Aucun (hors téléchargement initial des modèles) |
| Mistral 7B (`mistral`) | Apache 2.0 — éditeur français | Volume Docker local | Aucun |
| `nomic-embed-text` | Apache 2.0 | Volume Docker local | Aucun |
| ChromaDB | Apache 2.0 | Disque local `data/chroma_db/` | Télémétrie **désactivée** |
| Streamlit | Apache 2.0 | Serveur interne | `gatherUsageStats = false` |
| LangChain / pypdf / ReportLab | MIT / BSD | Bibliothèques locales | Aucun |

Exigences pour un passage en production :
1. **Hébergement** sur infrastructure de la collectivité ou chez un hébergeur **qualifié SecNumCloud
   (ANSSI)** et, pour les données de santé éventuelles, certifié HDS.
2. **Aucune API d'IA propriétaire extra-européenne** : les modèles sont exécutés localement, ce qui
   exclut l'exposition aux législations extraterritoriales.
3. **Mise à jour des modèles maîtrisée** : téléchargement depuis un poste d'administration, contrôle
   des empreintes, versions figées (`ollama/ollama:<version>`).
4. **Cloisonnement réseau** : API Ollama et interface accessibles uniquement via le réseau interne
   (reverse-proxy HTTPS + authentification SSO/annuaire de la collectivité).

---

## 4. Mesures de sécurité (art. 32)

- Chiffrement du disque hébergeant `data/` (LUKS / BitLocker) et sauvegardes chiffrées.
- Contrôle d'accès : authentification des agents, habilitations par service, journalisation des accès.
- Conteneur applicatif exécuté avec un utilisateur non privilégié ; ports exposés sur `127.0.0.1`.
- Contrôles à l'import : taille maximale, vérification de la signature PDF, nom de fichier assaini.
- Sel de pseudonymisation stocké hors dépôt (`.env` non versionné, coffre-fort de secrets en production).
- Revue périodique du filtre (tests `pytest` + échantillonnage manuel des extraits indexés).

---

## 5. Analyse des risques & conformité IA

| Risque | Mesure |
|---|---|
| Fuite de données personnelles vers un tiers | Exécution 100 % locale, aucune API cloud, télémétrie coupée |
| Données personnelles non détectées (faux négatifs du filtre) | Contrôle humain avant dépôt des courriers d'usagers ; évolution possible vers un NER local (spaCy `fr_core_news_lg`) |
| Réponse erronée présentée comme règle | Citations obligatoires, réponse « non trouvée » explicite, mention « aide à la décision » |
| Ré-identification par croisement | Sel secret, accès restreint à l'index, minimisation des métadonnées |
| Biais / opacité du modèle | Température basse, prompt système contraint, traçabilité des extraits utilisés |

- **AIPD (art. 35)** : à réaliser avant la mise en production si l'outil traite à grande échelle des
  demandes d'usagers (croisement de données, usage innovant d'IA) — outil PIA de la CNIL recommandé.
- **Règlement européen sur l'IA (AI Act)** : un assistant documentaire d'aide aux agents n'entre pas,
  a priori, dans les catégories à haut risque ; les obligations de transparence s'appliquent
  (information des utilisateurs qu'ils interagissent avec un système d'IA). À confirmer par le
  service juridique selon l'usage final.

---

## 6. Points de contrôle DPO avant mise en production

- [ ] Inscription du traitement au registre de la collectivité
- [ ] AIPD réalisée ou absence de nécessité justifiée
- [ ] Mentions d'information des usagers mises à jour (art. 13/14)
- [ ] Sel `RGPD_SALT` généré aléatoirement et stocké dans un coffre-fort
- [ ] Taux de détection du filtre mesuré sur un échantillon réel (objectif ≥ 98 % sur emails/téléphones/NIR)
- [ ] Procédure d'exercice des droits et de purge de l'index documentée
- [ ] Habilitations et authentification en place
