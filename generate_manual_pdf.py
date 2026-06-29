"""
generate_manual_pdf.py — Build static/manual.pdf from the same content as
templates/manual.html. Run once (or whenever the manual content changes):
    python generate_manual_pdf.py
"""
import os
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                 PageBreak, ListFlowable, ListItem, HRFlowable)

OUT_PATH = os.path.join(os.path.dirname(__file__), "static", "manual.pdf")

styles = getSampleStyleSheet()
NAVY = colors.HexColor("#05225f")
ACCENT = colors.HexColor("#2563eb")

title_style = ParagraphStyle("title2", parent=styles["Title"], textColor=NAVY, fontSize=24)
h1 = ParagraphStyle("h1c", parent=styles["Heading1"], textColor=NAVY, spaceBefore=18, spaceAfter=8)
h2 = ParagraphStyle("h2c", parent=styles["Heading2"], textColor=ACCENT, spaceBefore=10, spaceAfter=4, fontSize=12)
body = ParagraphStyle("bodyc", parent=styles["Normal"], fontSize=10, leading=15, spaceAfter=6)
tip = ParagraphStyle("tipc", parent=body, backColor=colors.HexColor("#f0fdf4"),
                      borderPadding=6, leftIndent=4)
warn = ParagraphStyle("warnc", parent=body, backColor=colors.HexColor("#fff7ed"),
                       borderPadding=6, leftIndent=4)

story = []
story.append(Paragraph("📖 Manuel d'utilisation — Masroofi", title_style))
story.append(Paragraph("Guide complet de toutes les fonctionnalités", body))
story.append(HRFlowable(width="100%", color=NAVY, spaceAfter=10))


def section(title, *flowables):
    story.append(Paragraph(title, h1))
    for f in flowables:
        story.append(f)


def bullets(items):
    return ListFlowable(
        [ListItem(Paragraph(i, body)) for i in items],
        bulletType="bullet", start="•", leftIndent=14)


def numbered(items):
    return ListFlowable(
        [ListItem(Paragraph(i, body)) for i in items],
        bulletType="1", leftIndent=14)


# ── Démarrage ──────────────────────────────────────────────────────────
section("🔑 Installation et activation",
    Paragraph("Télécharge l'installeur depuis la page d'accueil du site, lance-le, "
               "puis ouvre Masroofi.", body),
    Paragraph("Au premier lancement, un formulaire d'inscription apparaît "
               "(Nom + Email) :", body),
    bullets([
        "Laisser le champ <b>License Key</b> vide → un essai gratuit de 30 jours démarre automatiquement",
        "Coller une clé déjà achetée → activation immédiate",
    ]),
    Paragraph("Pour activer ou changer de clé plus tard : menu <b>Help → Activate License</b>.", body),
    Paragraph("💡 Le compte est lié à la machine (CPU/disque) — réinstaller l'app ne réinitialise pas l'essai.", tip),
)

section("⚙️ Réglages",
    Paragraph("Bouton ⚙️ Settings en bas de l'écran (ou menu Tools → Settings) :", body),
    bullets([
        "<b>Langue</b> : Arabe / Anglais / Français — l'app redémarre pour appliquer",
        "<b>Devise</b> : 16 devises disponibles, appliquée partout",
        "<b>Convertisseur de devises</b> intégré, taux en temps réel",
        "<b>Chemin de la base de données</b> — OneDrive/Google Drive pour synchroniser entre PC",
        "<b>Alertes au démarrage</b> — stock bas et avertissement budget",
    ]),
)

# ── Dépenses ─────────────────────────────────────────────────────────────
section("💸 Ajouter une dépense",
    Paragraph("Onglet Expenses → remplis le formulaire à gauche : code (ou scan), "
               "description, montant, catégorie, magasin, date, devise.", body),
    Paragraph("Tu peux aussi assigner la dépense à un membre de la famille via l'onglet Family.", body),
)

section("⚖️ Produits vendus au poids (tomates, fromage…)",
    numbered([
        "Dans Inventory, configure une fois : \"Sold by\" = kg/litre, et le prix au kilo",
        "Dans Expenses, entre le montant total payé et le poids indiqué sur le ticket",
        "L'app calcule automatiquement le prix au kilo et le stocke pour comparer dans le temps",
    ]),
    Paragraph("💡 Dans la liste de courses, indique le poids prévu pour obtenir une estimation avant d'aller au magasin.", tip),
)

section("🧾 Session de scan — \"ticket de caisse\"",
    Paragraph("Bouton 🛒 Scan Purchase Session (Expenses) : choisis le magasin une fois, "
               "puis scanne tous tes produits sans interruption. Double-clique sur une "
               "ligne pour corriger nom/prix/poids/quantité avant de confirmer.", body),
)

# ── Shopping ──────────────────────────────────────────────────────────────
section("🛍️ Liste de courses",
    Paragraph("Onglet Shopping : ajoute des articles manuellement, depuis l'inventaire, "
               "ou par scan. Code couleur : 🟢 essentiel, 🔴 luxe, blanc = normal.", body),
)

section("📷 Mode caisse enregistreuse (scan avec le téléphone)",
    Paragraph("Utilise une app de scan sur ton téléphone (type \"BT Scanner\") connectée "
               "en Bluetooth à ton PC.", body),
    numbered([
        "Clique sur l'onglet Shopping (ou Inventory/Expenses) → une fenêtre scanner flottante s'ouvre automatiquement",
        "Scanne un produit → ajouté instantanément, quantité +1 si déjà présent",
        "Produit inconnu → recherche automatique en ligne (Open Food Facts, UPC, Open Library...)",
    ]),
    Paragraph("⚠️ La fenêtre scanner s'adapte à l'onglet actif : jamais Shopping et Inventory en même temps.", warn),
)

section("📧 Envoyer la liste de courses",
    Paragraph("Bouton Email List : page HTML interactive avec vraies cases à cocher, à "
               "ouvrir sur ton téléphone. Chaque article affiche son code-barres pour "
               "vérifier prix/disponibilité aux bornes en magasin.", body),
    Paragraph("Le bouton PDF génère une version imprimable avec cases ☐ à cocher à la main.", body),
    Paragraph("Plusieurs destinataires peuvent être choisis depuis le carnet de Contacts, "
               "en plus d'adresses tapées manuellement.", body),
)

story.append(PageBreak())

# ── Inventaire ──────────────────────────────────────────────────────────
section("📦 Gérer l'inventaire",
    Paragraph("Formulaire d'ajout à gauche, liste au centre (Code + Nom), fiche "
               "détaillée à droite (photo, marque, catégorie, stock, prix).", body),
    Paragraph("Boutons : Edit Item, Delete Selected (admin), Quick Edit Price, Adjust "
               "Stock, Stock Movements, Low Stock Alert, Add to Shopping, From Expenses, "
               "Import/Export Excel, PDF Catalog.", body),
)

section("🏷️ Catégories à profondeur illimitée",
    Paragraph("Chaque catégorie peut avoir autant de sous-niveaux que nécessaire.", body),
    Paragraph("Gestion : Tools → Manage Categories → Product Categories — arbre complet "
               "avec import/export Excel par chemin (ex: Alimentation > Épicerie > Pâtes).", body),
)

section("📊 Codes-barres dynamiques (produits pesés en magasin)",
    Paragraph("Masroofi décode les codes-barres encodant un prix, et utilise un "
               "identifiant stable indépendant du prix scanné pour toujours retrouver "
               "le bon produit.", body),
)

section("🖼️ Photos des produits",
    Paragraph("Boutons Add Picture / Delete Picture dans la fiche détail. Survole "
               "l'image pour un aperçu agrandi.", body),
)

section("🟢🟡🔴 Classer essentiel / normal / luxe",
    Paragraph("Bouton 🏷️ Classify : classe tes produits en masse pour repérer où "
               "réduire les dépenses dans la liste de courses.", body),
)

# ── Famille ───────────────────────────────────────────────────────────────
section("👨‍👩‍👧 Comptes et budgets des membres",
    Paragraph("Onglet Family : budget mensuel par membre, intégré au Budget Summary "
               "et aux alertes salaire.", body),
    Paragraph("Assigner une dépense : sélectionne-la dans Expenses, puis dans Family "
               "choisis le membre → ✔ Assign.", body),
)

section("🔐 Connexion et accès limité enfants",
    bullets([
        "👑 <b>Admin</b> — accès complet",
        "👤 <b>Parent</b> — tout sauf gestion des membres",
        "👦 <b>Child</b> — Shopping + inventaire (consultation/ajout liste) + son propre tableau de bord budget",
    ]),
    Paragraph("Configurer le mot de passe : Family → double-clic sur le membre → Edit.", body),
)

story.append(PageBreak())

# ── Salaire & Revenus ───────────────────────────────────────────────────
section("💼 Salaire & Revenus — sources récurrentes",
    Paragraph("Onglet protégé par mot de passe, fusionné en 3 sous-onglets.", body),
    Paragraph("Sources de revenus récurrentes : ajoute autant de sources que nécessaire "
               "(Salaire, Freelance, Loyer perçu...), chacune avec son montant, sa devise "
               "et son jour de paiement (1-28). Chaque source est créditée automatiquement "
               "et indépendamment des autres.", body),
    bullets([
        "⏸ Pause/Reprendre une source sans la supprimer",
        "Historique de tous les versements passés, par source",
        "Graphique d'évolution mensuelle (12 derniers mois)",
    ]),
)

section("💵 Revenus ponctuels",
    Paragraph("Pour les rentrées d'argent non récurrentes. Formulaire simple : description, "
               "montant, catégorie/source, avec un camembert de répartition par source.", body),
)

section("📊 Comparaison mensuelle revenus / dépenses",
    Paragraph("3ème sous-onglet : graphique barres (revenus en vert, dépenses en rouge) + "
               "ligne du net, et un tableau avec le % d'évolution du net vs le mois précédent.", body),
)

# ── Événements & Projets ─────────────────────────────────────────────────
section("🎉 Événements & Projets",
    Paragraph("Pour les budgets spéciaux : mariage, anniversaire, voyage, séjour médical, "
               "rénovation... À la création, renseigne nom, type, date, et budget + devise.", body),
    bullets([
        "Si budget &gt; 0 → une ligne one-time est créée automatiquement dans Budgets, dans la bonne devise",
        "Si \"Besoin d'un prêt\" est cochée → une entrée est créée dans les Prêts",
    ]),
    Paragraph("⚠️ Supprimer un événement supprime aussi son budget, son prêt lié et ses tâches.", warn),
)

section("🏨 Prestataires & tarification adaptée",
    Paragraph("Le formulaire de prix s'adapte selon la catégorie : Hôtel/Clinique/Hôpital "
               "(pension + prix/nuit), Restaurant (à la carte/buffet + prix/invité), Salle "
               "de fête (prix/chaise), Compagnie aérienne (classe + prix/billet), "
               "Photographe (par session ou par photo).", body),
    Paragraph("Le bouton \"= Calculer\" remplit automatiquement le prix total. Chaque "
               "prestataire peut être facturé dans sa propre devise.", body),
)

section("📋 Tâches & attribution aux contacts",
    Paragraph("Double-clique sur un événement pour ouvrir sa fenêtre de tâches.", body),
    bullets([
        "Ajoute une tâche, attribue-la à un contact, fixe une échéance",
        "Clique sur la case ☐ pour marquer une tâche terminée",
        "Double-clique une tâche pour la modifier ou la réattribuer",
        "Bouton Send Tasks by Email : chaque personne reçoit uniquement ses propres tâches",
    ]),
)

# ── Contacts ──────────────────────────────────────────────────────────────
section("👤 Carnet de contacts",
    Paragraph("Gère les personnes assignées aux tâches d'événements ou destinataires de la "
               "liste de courses. Prénom, nom, email, et autant de numéros de téléphone que "
               "nécessaire (le pays choisi remplit automatiquement l'indicatif).", body),
)

section("✂️ Photo de contact & recadrage",
    Paragraph("Outil de recadrage interactif : un carré de sélection à glisser pour le "
               "positionner, un curseur pour l'agrandir/rétrécir, puis Crop & Save.", body),
)

story.append(PageBreak())

# ── Recettes ──────────────────────────────────────────────────────────────
section("🍽️ Recettes",
    Paragraph("Ingrédients par nom générique (ex: \"Spaghetti\"), recherche tolérante "
               "aux fautes de frappe.", body),
    bullets([
        "<b>Cook This!</b> → vérifie le stock, ajoute ce qui manque à la liste de courses",
        "<b>Suggest Recipes</b> → recettes réalisables triées par % d'ingrédients disponibles",
    ]),
)

story.append(PageBreak())

section("📅 Budgets",
    Paragraph("Budgets par catégorie avec récurrence et réinitialisation automatique. "
               "Budget Summary combine catégories + budgets famille.", body),
    Paragraph("⚠️ Chaque budget peut avoir sa propre devise, mais le total combiné global "
               "n'effectue pas encore de conversion entre devises différentes.", warn),
)

section("💰 Comparer les prix entre magasins",
    Paragraph("Chaque scan/achat avec magasin sélectionné alimente l'historique de prix. "
               "Price Comparison affiche le magasin le moins cher (🟢) et le plus cher "
               "(🔴) par produit.", body),
)

section("📤 Import / Export Excel",
    Paragraph("Disponible pour Inventory, Expenses, Income, Shopping List et Catégories.", body),
)

section("☁️ Utiliser Masroofi sur plusieurs ordinateurs",
    Paragraph("Settings → chemin de la base de données → dossier synchronisé "
               "(OneDrive/Google Drive). Installe sur l'autre PC, pointe vers le même "
               "dossier → mêmes données partout.", body),
)

story.append(Spacer(1, 20))
story.append(HRFlowable(width="100%", color=NAVY))
story.append(Paragraph("© 2026 Lassaad Turki — Masroofi", body))


def build():
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    doc = SimpleDocTemplate(OUT_PATH, pagesize=A4,
                             topMargin=2*cm, bottomMargin=2*cm,
                             leftMargin=2*cm, rightMargin=2*cm,
                             title="Masroofi — Manuel d'utilisation")
    doc.build(story)
    print(f"✅ Manuel PDF généré : {OUT_PATH}")


if __name__ == "__main__":
    build()
