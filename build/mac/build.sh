#!/usr/bin/env bash
# Gera o Prompter para macOS: dist/Prompter.app + dist/Prompter-<versao>-mac-<arch>.dmg
# Requer: python3.12 com requirements.txt instalados + pyinstaller.
# Assinatura: se SIGN_IDENTITY estiver definida (ex.: "Developer ID Application: Nome (TEAMID)"), assina tudo com
# Hardened Runtime + timestamp (pronto para notarizar; a notarizacao em si e feita pelo workflow com notarytool).
# Sem SIGN_IDENTITY: assinatura ad-hoc e, na 1a abertura, o usuario clica com o botao direito > Abrir.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
VER=$(grep -oE 'VERSION = "[^"]+"' app.py | cut -d'"' -f2)
ARCH=$(uname -m)
SIGN_IDENTITY="${SIGN_IDENTITY:-}"
echo "Prompter $VER ($ARCH) ${SIGN_IDENTITY:+assinado: $SIGN_IDENTITY}"
rm -rf dist/Prompter dist/Prompter.app
python3 -m PyInstaller --noconfirm --clean --distpath dist --workpath build/work build/prompter.spec
find dist/Prompter.app -type d \( -name tests -o -name test -o -name __pycache__ \) -prune -exec rm -rf {} + 2>/dev/null || true
xattr -cr dist/Prompter.app || true

if [ -n "$SIGN_IDENTITY" ]; then
  ENT="$ROOT/build/mac/entitlements.plist"
  # 1) todo binario Mach-O de dentro para fora (dylib, .so, executaveis soltos), 2) o bundle. --deep nao e confiavel p/ PyInstaller.
  while IFS= read -r -d '' f; do
    if file "$f" | grep -q "Mach-O"; then
      codesign --force --options runtime --timestamp --entitlements "$ENT" --sign "$SIGN_IDENTITY" "$f" 2>/dev/null \
        || codesign --force --options runtime --timestamp --sign "$SIGN_IDENTITY" "$f"
    fi
  done < <(find dist/Prompter.app/Contents -type f \( -name "*.dylib" -o -name "*.so" -o -perm -u+x \) ! -path "*/MacOS/Prompter" -print0)
  codesign --force --options runtime --timestamp --entitlements "$ENT" --sign "$SIGN_IDENTITY" dist/Prompter.app
  codesign --verify --strict --verbose=2 dist/Prompter.app
else
  codesign --force --deep --sign - dist/Prompter.app || true
fi

STAGE=build/work/dmg; rm -rf "$STAGE"; mkdir -p "$STAGE"
cp -R dist/Prompter.app "$STAGE/"
ln -s /Applications "$STAGE/Applications"
if [ -z "$SIGN_IDENTITY" ]; then
cat > "$STAGE/Instalar Prompter.command" <<'CMDEOF'
#!/bin/bash
# Copia o Prompter para Aplicativos, tira a quarentena (app sem assinatura da Apple) e abre.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
echo "Instalando o Prompter em /Applications..."
rm -rf "/Applications/Prompter.app"
cp -R "$DIR/Prompter.app" "/Applications/"
xattr -dr com.apple.quarantine "/Applications/Prompter.app" 2>/dev/null || true
echo "Abrindo o Prompter..."
open -a "/Applications/Prompter.app"
echo "Pronto. Pode fechar esta janela."
CMDEOF
chmod +x "$STAGE/Instalar Prompter.command"
cat > "$STAGE/LEIA-ME.txt" <<EOF
Prompter $VER - teleprompter sincronizado com o Pro Tools
Feito por Marllon Machado - https://github.com/krocksss

JEITO FACIL: clique com o botao direito em "Instalar Prompter" > Abrir > Abrir.
   Ele copia o app para Aplicativos, libera a abertura e ja abre o Prompter.
JEITO MANUAL: arraste o Prompter para Aplicativos e, na primeira vez, botao direito > Abrir > Abrir.
   (Se o macOS disser que nao pode verificar: Ajustes > Privacidade e Seguranca > "Abrir mesmo assim".)
Depois, o Prompter abre o Pro Tools junto e a tela do teleprompter no navegador (http://localhost:8797).
MTC (opcional, precisao maxima): o Prompter cria sozinho a porta MIDI virtual "Pro Tools MTC";
no Pro Tools: Setup > Peripherals > Synchronization > MTC Generator Port = Pro Tools MTC, e Gen MTC aceso.
EOF
else
cat > "$STAGE/LEIA-ME.txt" <<EOF
Prompter $VER - teleprompter sincronizado com o Pro Tools
Feito por Marllon Machado - https://github.com/krocksss

Arraste o Prompter para Aplicativos e abra. (App assinado e notarizado pela Apple: abre direto.)
O Prompter abre o Pro Tools junto e a tela do teleprompter no navegador (http://localhost:8797).
MTC (opcional, precisao maxima): o Prompter cria sozinho a porta MIDI virtual "Pro Tools MTC";
no Pro Tools: Setup > Peripherals > Synchronization > MTC Generator Port = Pro Tools MTC, e Gen MTC aceso.
EOF
fi
OUT="dist/Prompter-$VER-mac-$ARCH.dmg"; rm -f "$OUT"
hdiutil create -volname "Prompter $VER" -srcfolder "$STAGE" -ov -format UDZO "$OUT"
if [ -n "$SIGN_IDENTITY" ]; then
  codesign --force --timestamp --sign "$SIGN_IDENTITY" "$OUT"
fi
ls -la "$OUT"
