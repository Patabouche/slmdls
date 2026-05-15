ROCKSTAR BYPASS (outil annexe)
==============================

Emplacement dans le dépôt
--------------------------
Dossier : launcher\SFF\SlimeDealsBPRG\
  SlimeDealsBPRG.exe
  Assets\blob.png   (logo — copié avec le projet ; recommandé)

Build du launcher (SteaMidra_GUI / SlimeDeals)
----------------------------------------------
- En lançant build_simple_gui.bat : si le projet test est présent au chemin habituel,
  dotnet build Release est exécuté puis l’exe + Assets sont copiés ici ; PyInstaller
  les inclut dans le dossier dist (souvent sous _internal\SlimeDealsBPRG\).
- Sinon : compilez à la main puis copiez bin\Release\ ici avant pyinstaller.

À l’exécution, le launcher cherche l’exe à côté de SteaMidra_GUI.exe puis dans le
bundle PyInstaller (_internal), donc pas besoin de copie manuelle après install.

Origine du code : steamprojet\test\Nightlight-Game-Launcher\V4\SlimeDealsBPRG

Lancement : bouton « ROCKSTAR BYPASS » dans Accueil → Outils rapides (interface moderne).
