# Bigdata-clustering-spark-vs-sklearn
TP Big Data Clustering – Comparaison K-means scikit-learn vs Apache Spark MLlib – Évry 2025
===================================================================
Date            : 03 Décembre 2025
Objectif        : Comparaison scikit-learn vs Spark MLlib (K-means)
===================================================================

CONTENU DU DOSSIER
-------------------
- Rapport_final_data_science.ipynb    → Notebook complet (exécutable)
- README.md                        → Ce fichier (vous êtes ici)
- Datasets      → Les 3 types de datasets utilisés

EXÉCUTION LA PLUS SIMPLE (recommandée – 0 installation)
--------------------------------------------------------
1. Ouvrir Google Colab : https://colab.research.google.com
2. Glisser-déposer le fichier .ipynb dans Colab
   OU
   Fichier → Importer un notebook → choisir le fichier
3. Runtime → Run all (ou Ctrl+F9)
→ Temps total : 6 à 8 minutes maximum
→ Tout est téléchargé et installé automatiquement (Spark 3.5, Java 8, etc.)

EXÉCUTION LOCALE (si vous préférez)
-----------------------------------
Prérequis :
- Python 3.10+
- Java 8 (OpenJDK 8) installé et JAVA_HOME configuré
- Au moins 12 Go de RAM libres (16 Go recommandé)

Commandes à exécuter une seule fois dans un terminal :

python -m venv tp_env
source tp_env/bin/activate          # Linux/Mac
# tp_env\Scripts\activate           # Windows

pip install --upgrade pip
pip install numpy pandas scikit-learn matplotlib seaborn plotly psutil
pip install pyspark==3.5.0 findspark
pip install kneed gap-stat yellowbrick

Puis lancer :
jupyter notebook "TP_BigData_Clustering_FINAL.ipynb"

STRUCTURE DU NOTEBOOK (exécuter dans l’ordre)
---------------------------------------------
1. Setup Spark + toutes les librairies
2. Chargement automatique des 3 datasets
   • Wine Quality      (6 497 lignes  – small)
   • Adult Census      (48 842 lignes – medium)
   • HIGGS             (1 000 000 lignes – large)
3. EDA + Feature Engineering poussé
4. Choix du k optimal : 6 méthodes + vote majoritaire
   (Elbow, Silhouette, Calinski-Harabasz, Davies-Bouldin, Gap Statistic, ARI)
5. Clustering scikit-learn vs Spark MLlib
   → Mesure temps, mémoire, silhouette
6. Visualisations finales des 3 datasets (PCA 2D + hexbin pour HIGGS)
7. Rapport complet + recommandations

TEMPS D’EXÉCUTION ESTIMÉS (Colab GPU T4)
----------------------------------------
Setup + imports                  : ~1 min 30
Chargement + preprocessing       : ~1 min
Choix du k (les 3 datasets)      : 2–3 min
Clustering + visualisations      : ~2 min
TOTAL                            : 6 à 8 minutes

PROBLÈMES COURANTS & SOLUTIONS
-------------------------------
• Erreur Java → installer Java 8 (pas 11 ou 17)
• Mémoire insuffisante → Colab : Runtime → Factory reset
• Gap Statistic lente → normal, échantillonnage automatique activé
• Téléchargement HIGGS échoue → réessayer, le lien est stable

RÉSULTATS OBTENUS (exemple moyen)
---------------------------------
Dataset      k retenu   scikit-learn   Spark MLlib   Gain Spark
Wine (6k)      2        1,52 s         3,27 s         -
Adult (48k)    9        16,73 s        7,14 s         ≈ égal
HIGGS (1M)     2        145 s         56,59 s         ×41 !

Le notebook génère automatiquement :
• Tableau comparatif complet
• Visualisations des 3 jeux de données
• Rapport final rédigé avec conclusions.

