#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://raw.githubusercontent.com/DanteFuaran/dfc-mail/main/install.sh"
INSTALL_SCRIPT="/tmp/dfc-mail-install.sh"

echo ""
echo "  ╔══════════════════════════════════════════════╗"
echo "  ║          DFC MAIL BOT — УСТАНОВЩИК           ║"
echo "  ╚══════════════════════════════════════════════╝"
echo ""

if ! command -v curl &>/dev/null; then
    echo "⚠️  curl не найден. Устанавливаю..."
    if command -v apt-get &>/dev/null; then
        apt-get update -qq && apt-get install -y -qq curl > /dev/null 2>&1
    elif command -v yum &>/dev/null; then
        yum install -y curl > /dev/null 2>&1
    elif command -v apk &>/dev/null; then
        apk add --no-cache curl > /dev/null 2>&1
    else
        echo "❌ Не удалось установить curl. Установите его вручную."
        exit 1
    fi
fi

echo "📥 Загрузка установщика..."
if curl -fsSL "$REPO_URL" -o "$INSTALL_SCRIPT"; then
    chmod +x "$INSTALL_SCRIPT"
    bash "$INSTALL_SCRIPT" "$@"
    rm -f "$INSTALL_SCRIPT"
else
    echo "❌ Не удалось загрузить установщик."
    echo "   Проверьте подключение к интернету и попробуйте снова."
    exit 1
fi
