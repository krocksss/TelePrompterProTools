#!/usr/bin/env bash
# Gera o Prompter para macOS: dist/Prompter.app + dist/Prompter-<versao>-mac-<arch>.dmg
# Requer: python3.12 com requirements.txt instalados + pyinstaller. Sem assinatura Apple: na 1a abertura
# o usuario clica com o botao direito > Abrir (ou Ajustes > Privacidade e Seguranca > Abrir mesmo assim).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
VER=$(grep -oE 'VERSION = "[^"]+"' app.py | cut -d'"' -f2)
ARCH=$(uname -m)
echo "Prompter $VER ($ARCH)"
rm -rf dist/Prompter dist/Prompter.app
python3 -m PyInstaller --noconfirm --clean --distpath dist --workpath build/work build/prompter.spec
find dist/Prompter.app -type d \( -name tests -o -name test -o -name __pycache__ \) -prune -exec rm -rf {} + 2>/dev/null || true
# remove a "quarentena" do proprio bundle e assina ad-hoc (evita "app danificado")
xattr -cr dist/Prompter.app || true
codesign --force --deep --sign - dist/Prompter.app || true
STAGE=build/work/dmg; rm -rf "$STAGE"; mkdir -p "$STAGE"
cp -R dist/Prompter.app "$STAGE/"
ln -s /Applications "$STAGE/Applications"
cat > "$STAGE/LEIA-ME.txt" <<EOF
Prompter $VER - teleprompter sincronizado com o Pro Tools
Feito por Marllon Machado - https://github.com/krocksss

1. Arraste o Prompter para a pasta Aplicativos.
2. Na PRIMEIRA vez: clique com o botao direito no Prompter > Abrir > Abrir (o app nao e assinado pela Apple).
3. O Prompter abre o Pro Tools junto e a tela do teleprompter no navegador (http://localhost:8797).
MTC (opcional, precisao maxima): o Prompter cria sozinho a porta MIDI virtual "Pro Tools MTC";
no Pro Tools: Setup > Peripherals > Synchronization > MTC Generator Port = Pro Tools MTC, e Gen MTC aceso.
EOF
OUT="dist/Prompter-$VER-mac-$ARCH.dmg"; rm -f "$OUT"
hdiutil create -volname "Prompter $VER" -srcfolder "$STAGE" -ov -format UDZO "$OUT"
ls -la "$OUT"
