# Confiance Windows & antivirus — SlimeDeals Launcher

Windows Defender et SmartScreen signalent souvent les launchers PyInstaller **non signés** qui embarquent des outils Steam tiers. Voici comment réduire les faux positifs et être **reconnu comme éditeur** par Windows.

## Ce qui est déjà fait dans le build

| Mesure | Effet |
|--------|--------|
| Distribution **onedir** (`dist2\SteaMidra_GUI\`) | Moins de compression opaque qu’un onefile |
| **UPX désactivé** | Évite les heuristiques « packer » |
| **Métadonnées PE** (`BUILDER/version_info.py`) | Nom éditeur, description, version dans Propriétés du fichier |
| **Manifeste UAC `asInvoker`** | Pas de demande admin au démarrage (sauf actions explicites) |
| Mode **`public`** du build | Exclut VBS.cmd, GreenLuma.rar, SlimeDealsBPRG du ZIP distribué |

## Étape indispensable : certificat Authenticode

Sans signature, **SmartScreen affichera toujours** « Éditeur inconnu », même avec un binaire propre.

1. Acheter un certificat **Code Signing** (OV ~200 €/an, EV ~400 €/an — EV accélère la réputation SmartScreen).
2. Fournisseurs : DigiCert, Sectigo, GlobalSign, SSL.com.
3. Signer après chaque build :

```bat
set SLIMEDEALS_SIGN_PFX=C:\certs\slimedeals.pfx
set SLIMEDEALS_SIGN_PASSWORD=***
BUILDER\build_launcher.bat public
BUILDER\sign_release.bat
```

4. Vérifier : clic droit sur `SteaMidra_GUI.exe` → **Propriétés → Signatures numériques**.

## Build « public » (moins de faux positifs)

```bat
BUILDER\build_launcher.bat public
```

Exclut du package distribué :
- `third_party/hv/VBS.cmd` (script système — très signalé par l’AV)
- `greenlumafix.rar` (GreenLuma — installation manuelle ou release interne)
- `SlimeDealsBPRG/` (outil bypass Rockstar)

Le build **complet** (GreenLuma, SlimeDealsBPRG, tout embarqué) :

```bat
BUILDER\build_launcher_full.bat
```

Ou depuis la racine `launcher\SFF\` :

```bat
build_full.bat
```

Équivalent : `BUILDER\build_launcher.bat full`

## Soumission à Microsoft (gratuit)

Après signature, soumettez chaque release :

1. [Microsoft Security Intelligence — soumission de fichier](https://www.microsoft.com/en-us/wdsi/filesubmission)
2. Choisir **Software developer**, indiquer que c’est un **false positive**
3. Joindre le **ZIP signé** ou l’exe + SHA256

Répéter pour les autres moteurs si besoin (VirusTotal → liens des éditeurs AV).

## Réputation SmartScreen

- Les **premiers téléchargements** d’un exe nouveau seront filtrés même signé (OV).
- Un certificat **EV** donne une réputation initiale plus rapide.
- Publier toujours depuis le **même domaine** (slimedeals.fr) avec le **même certificat**.
- Ne pas changer le nom de l’exe à chaque release (`SteaMidra_GUI.exe` stable).

## Exclusions utilisateur (dernier recours)

Documenter dans le README utilisateur :

```
Windows Sécurité → Protection contre les virus → Exclusions
→ Dossier : dist2\SteaMidra_GUI\
```

## Limites honnêtes

SlimeDeals modifie Steam, télécharge des archives et peut installer GreenLuma. **Certains AV continueront à alerter** sur des comportements réels (pas seulement des faux positifs). La signature + build public + soumission Microsoft réduisent fortement les alertes au **téléchargement et à la première exécution**.
