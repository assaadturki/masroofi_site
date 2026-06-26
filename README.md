# Masroofi — Site web (Gumroad)

## 1. Crée ton/tes produit(s) sur Gumroad
1. https://gumroad.com → Sign up (gratuit, accepte les vendeurs Tunisie/Qatar)
2. New Product → "Digital product" → nomme-le ex. "Masroofi — 1 an"
3. Note le **permalink** affiché dans l'URL : `gumroad.com/l/CE-TEXTE-ICI`
4. Fais pareil pour le plan "À vie"
5. Dans chaque produit → Settings → Advanced :
   - "Generate a unique license key per sale" → NON (on génère la nôtre, compatible Masroofi)
   - "Redirect to URL after purchase" = `http://localhost:5000/success`
     (Gumroad ajoute automatiquement `?sale_id=...`)
   - Ping (webhook) URL = `http://localhost:5000/gumroad-webhook`
     → en local, Gumroad ne peut pas atteindre `localhost`, utilise ngrok (étape 4)

## 2. Renseigne les permalinks dans app.py
Ouvre `app.py`, dans `PLANS`, remplace :
```python
"gumroad_url": "https://gumroad.com/l/REPLACE_WITH_YOUR_PERMALINK",
```
par tes vraies URLs Gumroad pour chaque plan.

## 3. Récupère ton Access Token Gumroad (pour vérifier les ventes côté serveur)
Gumroad → Settings → Advanced → Applications → "Create application"
→ copie l'Access Token généré.

```
set GUMROAD_ACCESS_TOKEN=ton_token_ici
```

## 4. Installer ngrok (pour que Gumroad puisse t'atteindre en local)
Télécharge : https://ngrok.com/download
```
ngrok http 5000
```
Il affiche une URL du type `https://abcd1234.ngrok-free.app`.
Mets `https://abcd1234.ngrok-free.app/gumroad-webhook` comme Ping URL
et `https://abcd1234.ngrok-free.app/success` comme Redirect URL dans
les paramètres de chaque produit Gumroad (étape 1).

## 5. Lancer le site
```
pip install -r requirements.txt
python app.py
```
Ouvre http://localhost:5000

## 6. Tester un achat
1. Clique "Acheter sur Gumroad" → tu arrives sur la page Gumroad du produit
2. Active "Enable test purchases" dans Settings du produit pour payer 0.00 QAR
3. Achète → Gumroad appelle ton webhook ngrok → la clé est générée
4. Tu es redirigé vers /success avec la clé affichée

## 7. Vérifier que la clé fonctionne dans Masroofi
Copie la clé affichée → Masroofi → Help → Activate License → colle.
Même algorithme HMAC que `_validate_key()` dans Masroofi.py — testé et compatible.

## 8. Avant la mise en ligne (production)
- Héberge le site (PythonAnywhere, Render, Railway...) avec une vraie URL HTTPS publique
- Remplace les URLs `localhost:5000` par ton vrai domaine dans Gumroad
- Désactive "Enable test purchases"
- Garde `GUMROAD_ACCESS_TOKEN` secret (jamais dans Git)
- Le SECRET dans `licensing.py` doit toujours être identique à `_LIC_SECRET` dans Masroofi.py
