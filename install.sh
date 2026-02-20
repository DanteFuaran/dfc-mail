#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# DFC Mail Bot — Автоматический установщик
# Стиль: dfc-tg-shop
# ═══════════════════════════════════════════════════════════════

set -euo pipefail

# ═══════════════════════════════════════════════
# ПЕРЕМЕННЫЕ
# ═══════════════════════════════════════════════
PROJECT_DIR="/opt/dfc-mail"
ENV_FILE="$PROJECT_DIR/.env"
REPO_URL="https://github.com/DanteFuaran/dfc-mail.git"
REPO_BRANCH="main"
SYSTEM_INSTALL_DIR="/usr/local/lib/dfc-mail"
SCRIPT_CWD="$(cd "$(dirname "$0")" && pwd)"

INSTALL_STARTED=false
INSTALL_COMPLETED=false
SOURCE_DIR=""
CLONE_DIR=""

# Читаем ветку из version
for _uf in "$PROJECT_DIR/version" "$SCRIPT_CWD/version"; do
    if [ -f "$_uf" ]; then
        _br=$(grep '^branch:' "$_uf" | cut -d: -f2 | tr -d ' \n')
        _ru=$(grep '^repo:'   "$_uf" | cut -d: -f2- | tr -d ' \n')
        [ -n "$_br" ] && REPO_BRANCH="$_br"
        [ -n "$_ru" ] && REPO_URL="$_ru"
        break
    fi
done

# ═══════════════════════════════════════════════
# ЦВЕТА
# ═══════════════════════════════════════════════
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[1;34m'
WHITE='\033[1;37m'
GRAY='\033[0;37m'
DARKGRAY='\033[1;30m'
NC='\033[0m'

# ═══════════════════════════════════════════════
# ВОССТАНОВЛЕНИЕ ТЕРМИНАЛА
# ═══════════════════════════════════════════════
cleanup_terminal() {
    stty sane 2>/dev/null || true
    tput cnorm 2>/dev/null || true
}

handle_interrupt() {
    cleanup_terminal
    echo
    echo -e "${RED}⚠️  Скрипт был остановлен пользователем${NC}"
    echo
    exit 130
}

trap cleanup_terminal EXIT
trap handle_interrupt INT TERM

# ═══════════════════════════════════════════════
# УТИЛИТЫ ВЫВОДА
# ═══════════════════════════════════════════════
print_error()   { printf "${RED}✖ %b${NC}\n" "$1"; }
print_success() { printf "${GREEN}✅${NC} %b\n" "$1"; }

show_spinner() {
    local pid=$!
    local delay=0.08
    local spin=('⠋' '⠙' '⠹' '⠸' '⠼' '⠴' '⠦' '⠧' '⠇' '⠏')
    local i=0 msg="$1"
    tput civis 2>/dev/null || true
    while kill -0 $pid 2>/dev/null; do
        printf "\r${GREEN}%s${NC}  %s" "${spin[$i]}" "$msg"
        i=$(( (i+1) % 10 ))
        sleep $delay
    done
    wait $pid 2>/dev/null
    local exit_code=$?
    if [ $exit_code -eq 0 ]; then
        printf "\r${GREEN}✅${NC} %s\n" "$msg"
    else
        printf "\r${RED}✖${NC}  %s\n" "$msg"
    fi
    tput cnorm 2>/dev/null || true
    return $exit_code
}

show_spinner_timer() {
    local seconds=$1
    local msg="$2"
    local done_msg="${3:-$msg}"
    local spin=('⠋' '⠙' '⠹' '⠸' '⠼' '⠴' '⠦' '⠧' '⠇' '⠏')
    local i=0
    local delay=0.08
    local elapsed=0
    tput civis 2>/dev/null || true
    while [ $elapsed -lt $seconds ]; do
        local remaining=$((seconds - elapsed))
        for ((j=0; j<12; j++)); do
            printf "\r\033[K${GREEN}%s${NC}  %s (%d сек)" "${spin[$i]}" "$msg" "$remaining"
            sleep $delay
            i=$(( (i+1) % 10 ))
        done
        ((elapsed++)) || true
    done
    printf "\r\033[K${GREEN}✅${NC} %s\n" "$done_msg"
    tput cnorm 2>/dev/null || true
}

show_spinner_until_log() {
    local container="$1"
    local pattern="$2"
    local msg="$3"
    local timeout=${4:-90}
    local spin=('⠋' '⠙' '⠹' '⠸' '⠼' '⠴' '⠦' '⠧' '⠇' '⠏')
    local i=0 elapsed=0 delay=0.08
    local check_interval=1
    local loops_per_check=$((check_interval * 12))
    local loop_count=0

    tput civis 2>/dev/null || true

    while [ $elapsed -lt $timeout ]; do
        printf "\r${GREEN}%s${NC}  %s (%d/%d сек)" "${spin[$i]}" "$msg" "$elapsed" "$timeout"
        i=$(( (i+1) % 10 ))
        sleep $delay
        loop_count=$((loop_count + 1))

        if [ $((loop_count % loops_per_check)) -eq 0 ]; then
            elapsed=$((elapsed + 1))
            local logs
            logs=$(docker logs "$container" 2>&1 | tail -100)

            if echo "$logs" | grep -q "$pattern"; then
                printf "\r${GREEN}✅${NC} %s\n" "$msg"
                tput cnorm 2>/dev/null || true
                return 0
            fi

            if echo "$logs" | grep -E "^\s*(ERROR|CRITICAL|Traceback)" >/dev/null 2>&1; then
                printf "\r${RED}❌${NC} %s (ошибка)\n" "$msg"
                tput cnorm 2>/dev/null || true
                return 2
            fi
        fi
    done

    printf "\r${YELLOW}⚠️${NC}  %s (таймаут)\n" "$msg"
    tput cnorm 2>/dev/null || true
    return 1
}

# ═══════════════════════════════════════════════
# МЕНЮ СО СТРЕЛОЧКАМИ
# ═══════════════════════════════════════════════
show_arrow_menu() {
    local title="$1"
    shift
    local options=("$@")
    local num_options=${#options[@]}
    local selected=0

    tput civis 2>/dev/null || true
    stty -echo 2>/dev/null || true

    while true; do
        # Очистка
        printf "\033[2J\033[H"
        echo -e "${BLUE}══════════════════════════════════════${NC}"
        echo -e "${WHITE}  $title${NC}"
        echo -e "${BLUE}══════════════════════════════════════${NC}"
        echo

        for i in "${!options[@]}"; do
            if [ "$i" -eq "$selected" ]; then
                echo -e "  ${GREEN}▸ ${options[$i]}${NC}"
            else
                echo -e "    ${GRAY}${options[$i]}${NC}"
            fi
        done

        echo
        echo -e "${DARKGRAY}↑↓ — выбор  |  Enter — подтвердить${NC}"

        read -rsn1 key
        case "$key" in
            $'\x1b')
                read -rsn2 key2
                case "$key2" in
                    '[A') selected=$(( (selected - 1 + num_options) % num_options )) ;;
                    '[B') selected=$(( (selected + 1) % num_options )) ;;
                esac
                ;;
            '') break ;;
        esac
    done

    stty echo 2>/dev/null || true
    tput cnorm 2>/dev/null || true
    return $selected
}

# ═══════════════════════════════════════════════
# ВВОД ПОЛЬЗОВАТЕЛЯ
# ═══════════════════════════════════════════════
reading_inline() {
    local prompt="$1"
    local var_name="$2"
    tput cnorm 2>/dev/null || true
    stty echo 2>/dev/null || true
    echo -ne "${WHITE}${prompt} ${NC}"
    read -r "$var_name"
}

update_env_var() {
    local file="$1" key="$2" val="$3"
    if grep -q "^${key}=" "$file" 2>/dev/null; then
        sed -i "s|^${key}=.*|${key}=${val}|" "$file"
    else
        echo "${key}=${val}" >> "$file"
    fi
}

generate_password() {
    openssl rand -hex 32 | tr -d '\n'
}

# ═══════════════════════════════════════════════
# ПРОВЕРКА: УСТАНОВЛЕН ЛИ УЖЕ БОТ
# ═══════════════════════════════════════════════
is_installed() {
    [ -d "$PROJECT_DIR" ] && [ -f "$PROJECT_DIR/docker-compose.yml" ] && [ -f "$PROJECT_DIR/.env" ]
}

# ═══════════════════════════════════════════════
# УПРАВЛЕНИЕ БОТОМ (если установлен)
# ═══════════════════════════════════════════════
manage_restart() {
    cd "$PROJECT_DIR" || return
    (
        docker compose down >/dev/null 2>&1
        docker compose up -d >/dev/null 2>&1
    ) &
    show_spinner "Перезапуск бота"
    echo
    echo -e "${GREEN}✅ Бот перезапущен${NC}"
    echo
    echo -e "${DARKGRAY}Нажмите Enter для продолжения${NC}"
    read -p ""
}

manage_stop() {
    cd "$PROJECT_DIR" || return
    (
        docker compose down >/dev/null 2>&1
    ) &
    show_spinner "Остановка бота"
    echo
    echo -e "${GREEN}✅ Бот остановлен${NC}"
    echo
    echo -e "${DARKGRAY}Нажмите Enter для продолжения${NC}"
    read -p ""
}

manage_start() {
    cd "$PROJECT_DIR" || return
    (
        docker compose up -d >/dev/null 2>&1
    ) &
    show_spinner "Запуск бота"
    echo
    echo -e "${GREEN}✅ Бот запущен${NC}"
    echo
    echo -e "${DARKGRAY}Нажмите Enter для продолжения${NC}"
    read -p ""
}

manage_logs() {
    cd "$PROJECT_DIR" || return
    echo -e "${BLUE}══════════════════════════════════════${NC}"
    echo -e "${WHITE}  📋 ЛОГИ БОТА (последние 50 строк)${NC}"
    echo -e "${BLUE}══════════════════════════════════════${NC}"
    echo
    docker compose logs --tail 50 dfc-mail 2>&1
    echo
    echo -e "${DARKGRAY}Нажмите Enter для продолжения${NC}"
    read -p ""
}

manage_logs_follow() {
    cd "$PROJECT_DIR" || return
    echo -e "${YELLOW}Для выхода нажмите Ctrl+C${NC}"
    echo
    docker compose logs -f dfc-mail
}

manage_edit_env() {
    if command -v nano &>/dev/null; then
        nano "$ENV_FILE"
    elif command -v vi &>/dev/null; then
        vi "$ENV_FILE"
    else
        echo -e "${RED}Редактор не найден. Установите nano: apt install nano${NC}"
        echo -e "${DARKGRAY}Нажмите Enter для продолжения${NC}"
        read -p ""
    fi
}

manage_update() {
    echo
    local TEMP_REPO
    TEMP_REPO=$(mktemp -d)

    (
        git clone -b "$REPO_BRANCH" --depth 1 "$REPO_URL" "$TEMP_REPO" >/dev/null 2>&1
    ) &
    show_spinner "Загрузка обновлений"

    if [ ! -f "$TEMP_REPO/docker-compose.yml" ]; then
        print_error "Ошибка загрузки обновлений"
        rm -rf "$TEMP_REPO"
        echo -e "${DARKGRAY}Нажмите Enter для продолжения${NC}"
        read -p ""
        return
    fi

    # Копируем конфигурационные файлы
    (
        cp -f "$TEMP_REPO/docker-compose.yml" "$PROJECT_DIR/"
        [ -f "$TEMP_REPO/version" ] && cp -f "$TEMP_REPO/version" "$PROJECT_DIR/version"

        # Обновляем install.sh в системной папке
        sudo mkdir -p "$SYSTEM_INSTALL_DIR" 2>/dev/null || true
        sudo cp -f "$TEMP_REPO/install.sh" "$SYSTEM_INSTALL_DIR/install.sh" 2>/dev/null || true
        sudo chmod +x "$SYSTEM_INSTALL_DIR/install.sh" 2>/dev/null || true
    ) &
    show_spinner "Копирование файлов"

    # Пересборка образа
    (
        cd "$TEMP_REPO" || return
        docker build --no-cache -t dfc-mail:local \
            --build-arg BUILD_TIME="$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
            --build-arg BUILD_BRANCH="$REPO_BRANCH" \
            --build-arg BUILD_COMMIT="$(git rev-parse --short HEAD 2>/dev/null || echo 'unknown')" \
            --build-arg BUILD_TAG="$(grep '^version:' version 2>/dev/null | cut -d: -f2 | tr -d ' \n' || echo 'unknown')" \
            . >/dev/null 2>&1
    ) &
    show_spinner "Сборка Docker образа"

    # Перезапуск
    (
        cd "$PROJECT_DIR" || return
        docker compose down >/dev/null 2>&1
        docker compose up -d >/dev/null 2>&1
    ) &
    show_spinner "Перезапуск бота"

    rm -rf "$TEMP_REPO"

    echo
    show_spinner_until_log "dfc-mail" "Bot starting up" "Запуск бота" 90 && BOT_OK=0 || BOT_OK=$?

    if [ "${BOT_OK:-1}" -eq 0 ]; then
        echo -e "${GREEN}✅ Обновление завершено успешно!${NC}"
    else
        echo -e "${YELLOW}⚠️  Бот не успел запуститься. Проверьте логи.${NC}"
    fi

    echo
    echo -e "${DARKGRAY}Нажмите Enter для продолжения${NC}"
    read -p ""
}

manage_reinstall() {
    echo
    echo -e "${YELLOW}⚠️  Переустановка удалит текущую конфигурацию и данные!${NC}"
    echo -ne "${WHITE}Вы уверены? (y/N): ${NC}"
    read -n 1 -r confirm
    echo

    if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
        echo -e "${GRAY}Отмена${NC}"
        echo -e "${DARKGRAY}Нажмите Enter для продолжения${NC}"
        read -p ""
        return
    fi

    # Остановить и удалить
    if [ -d "$PROJECT_DIR" ]; then
        (
            cd "$PROJECT_DIR" && docker compose down -v >/dev/null 2>&1 || true
        ) &
        show_spinner "Остановка контейнеров"
    fi

    (
        docker volume rm dfc-mail-db-data >/dev/null 2>&1 || true
        rm -rf "$PROJECT_DIR"
    ) &
    show_spinner "Удаление данных"

    echo -e "${GREEN}✅ Данные удалены. Запускаю установку...${NC}"
    sleep 1

    # Перезапускаем скрипт в режиме установки
    exec "$0" --install "$SCRIPT_CWD"
}

manage_uninstall() {
    echo
    echo -e "${RED}⚠️  ВНИМАНИЕ: Это действие удалит бота, базу данных и все настройки!${NC}"
    echo -ne "${WHITE}Вы уверены? (y/N): ${NC}"
    read -n 1 -r confirm
    echo

    if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
        echo -e "${GRAY}Отмена${NC}"
        echo -e "${DARKGRAY}Нажмите Enter для продолжения${NC}"
        read -p ""
        return
    fi

    (
        if [ -d "$PROJECT_DIR" ]; then
            cd "$PROJECT_DIR" && docker compose down -v >/dev/null 2>&1 || true
            cd /opt
        fi
        docker volume rm dfc-mail-db-data >/dev/null 2>&1 || true
        rm -rf "$PROJECT_DIR"
    ) &
    show_spinner "Удаление бота и данных"

    (
        sudo rm -f /usr/local/bin/dfc-mail 2>/dev/null || true
        sudo rm -rf "$SYSTEM_INSTALL_DIR" 2>/dev/null || true
    ) &
    show_spinner "Удаление ярлыка команды"

    echo
    echo -e "${GREEN}✅ Бот успешно удален!${NC}"
    echo
    echo -e "${DARKGRAY}Нажмите Enter для продолжения${NC}"
    read -p ""
    clear
    exit 0
}

# ═══════════════════════════════════════════════
# ГЛАВНОЕ МЕНЮ (если бот установлен)
# ═══════════════════════════════════════════════
show_full_menu() {
    while true; do
        local ver="unknown"
        [ -f "$PROJECT_DIR/version" ] && ver=$(grep '^version:' "$PROJECT_DIR/version" | cut -d: -f2 | tr -d ' ')

        local status_text="${RED}остановлен${NC}"
        if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^dfc-mail$"; then
            status_text="${GREEN}работает${NC}"
        fi

        local menu_title="📧 DFC MAIL BOT v${ver}  |  ${status_text}"

        show_arrow_menu "$menu_title" \
            "🔄 Перезапуск" \
            "▶️  Запуск" \
            "⏹  Остановка" \
            "📋 Логи (последние 50)" \
            "📋 Логи (в реальном времени)" \
            "✏️  Редактировать .env" \
            "🔄 Обновление" \
            "🔁 Переустановка" \
            "🗑  Удаление бота" \
            "🚪 Выход"

        local choice=$?
        case $choice in
            0)  manage_restart ;;
            1)  manage_start ;;
            2)  manage_stop ;;
            3)  manage_logs ;;
            4)  manage_logs_follow ;;
            5)  manage_edit_env ;;
            6)  manage_update ;;
            7)  manage_reinstall ;;
            8)  manage_uninstall ;;
            9)  clear; exit 0 ;;
        esac
    done
}

# ═══════════════════════════════════════════════
# ОЧИСТКА ПРИ ОШИБКЕ
# ═══════════════════════════════════════════════
cleanup_on_error() {
    local exit_code=$?
    tput cnorm >/dev/null 2>&1 || true
    stty echo 2>/dev/null || true

    if [ "$INSTALL_STARTED" = "true" ] && [ "$INSTALL_COMPLETED" != "true" ]; then
        clear
        if [ $exit_code -eq 130 ]; then
            echo -e "${BLUE}══════════════════════════════════════${NC}"
            echo -e "${YELLOW}  ⚠️  УСТАНОВКА ПРЕРВАНА ПОЛЬЗОВАТЕЛЕМ${NC}"
            echo -e "${BLUE}══════════════════════════════════════${NC}"
        else
            echo -e "${RED}══════════════════════════════════════${NC}"
            echo -e "${RED}  ⚠️  ОШИБКА УСТАНОВКИ${NC}"
            echo -e "${RED}══════════════════════════════════════${NC}"
        fi
        echo

        if [ -n "$SOURCE_DIR" ] && [ "$SOURCE_DIR" != "$PROJECT_DIR" ] && [ "$SOURCE_DIR" != "/" ] && [ -d "$SOURCE_DIR" ]; then
            rm -rf "$SOURCE_DIR" 2>/dev/null || true
        fi

        if command -v docker &>/dev/null && [ -d "$PROJECT_DIR" ]; then
            cd "$PROJECT_DIR" 2>/dev/null && docker compose down >/dev/null 2>&1 || true
        fi

        if [ -d "$PROJECT_DIR" ]; then
            rm -rf "$PROJECT_DIR" 2>/dev/null || true
        fi

        echo -e "${GREEN}✅ Очистка временных файлов${NC}"
        echo

        if [ $exit_code -ne 130 ]; then
            echo -e "${WHITE}Попробуйте запустить установку снова${NC}"
            echo
        fi
    fi

    if [ -n "$CLONE_DIR" ] && [ -d "$CLONE_DIR" ]; then
        cd /opt 2>/dev/null || true
        rm -rf "$CLONE_DIR" 2>/dev/null || true
    fi

    exit $exit_code
}

trap cleanup_on_error EXIT
trap handle_interrupt INT TERM

# ═══════════════════════════════════════════════
# ТОЧКА ВХОДА
# ═══════════════════════════════════════════════

# Если бот установлен и скрипт запущен без аргументов — показать меню
if [ "${1:-}" != "--install" ]; then
    if is_installed; then
        show_full_menu
        exit 0
    fi

    # Бот не установлен — клонируем и запускаем установку
    CLONE_DIR=$(mktemp -d)
    trap "cd /opt 2>/dev/null || true; rm -rf '$CLONE_DIR' 2>/dev/null || true" EXIT

    echo -e "${BLUE}⏳ Подготовка установки...${NC}"
    if ! git clone -b "$REPO_BRANCH" --depth 1 "$REPO_URL" "$CLONE_DIR" >/dev/null 2>&1; then
        echo "❌ Ошибка при клонировании репозитория"
        exit 1
    fi

    chmod +x "$CLONE_DIR/install.sh"
    cd "$CLONE_DIR"
    exec "$CLONE_DIR/install.sh" --install "$CLONE_DIR"
else
    CLONE_DIR="${2:-$SCRIPT_CWD}"
fi

# ═══════════════════════════════════════════════
# УСТАНОВКА
# ═══════════════════════════════════════════════

# Автоправа
chmod +x "$0" 2>/dev/null || true
tput civis >/dev/null 2>&1 || true

# Удаляем старые временные файлы
find /tmp -maxdepth 1 -type d -name "tmp.*" -mmin +60 -exec rm -rf {} \; 2>/dev/null || true

clear
echo -e "${BLUE}══════════════════════════════════════${NC}"
echo -e "${GREEN}       📧 УСТАНОВКА DFC MAIL BOT${NC}"
echo -e "${BLUE}══════════════════════════════════════${NC}"
echo

# 1. Проверки
(
    if ! command -v docker &>/dev/null; then
        print_error "Docker не установлен!"
        exit 1
    fi
    if ! command -v openssl &>/dev/null; then
        print_error "OpenSSL не установлен!"
        exit 1
    fi
) &
show_spinner "Проверка установленных компонентов"

INSTALL_STARTED=true

# 2. Docker log rotation
(
    if [ ! -f /etc/docker/daemon.json ]; then
        cat > /etc/docker/daemon.json <<'DJSON'
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
DJSON
    fi
) &
show_spinner "Настройка системы"

# 3. Подготовка директории
(
    mkdir -p "$PROJECT_DIR"/{logs,backups}
    chmod 755 "$PROJECT_DIR/logs" "$PROJECT_DIR/backups"

    # Docker сеть
    if ! docker network ls | grep -q "dfc-mail-network"; then
        docker network create dfc-mail-network 2>/dev/null || true
    fi
) &
show_spinner "Подготовка целевой директории"

# 4. Определение источника файлов
SCRIPT_PATH="$(realpath "$0")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"
SOURCE_DIR="$SCRIPT_DIR"
COPY_FILES=true
if [ "$SOURCE_DIR" = "$PROJECT_DIR" ]; then
    COPY_FILES=false
fi

# 5. Копирование конфигурационных файлов
if [ "$COPY_FILES" = true ]; then
    (
        [ -f "$SOURCE_DIR/docker-compose.yml" ] && cp -f "$SOURCE_DIR/docker-compose.yml" "$PROJECT_DIR/"
        [ -f "$SOURCE_DIR/version" ] && cp -f "$SOURCE_DIR/version" "$PROJECT_DIR/version"

        sudo mkdir -p "$SYSTEM_INSTALL_DIR"
        _src="$(realpath "$SOURCE_DIR/install.sh" 2>/dev/null || echo "$SOURCE_DIR/install.sh")"
        _dst="$(realpath "$SYSTEM_INSTALL_DIR/install.sh" 2>/dev/null || echo "$SYSTEM_INSTALL_DIR/install.sh")"
        if [ "$_src" != "$_dst" ]; then
            sudo cp -f "$SOURCE_DIR/install.sh" "$SYSTEM_INSTALL_DIR/install.sh"
        fi
        sudo chmod +x "$SYSTEM_INSTALL_DIR/install.sh"
    )
    wait
fi

# 6. Создание .env из примера
if [ ! -f "$ENV_FILE" ]; then
    if [ ! -f "$SOURCE_DIR/.env.example" ]; then
        print_error "Файл .env.example не найден!"
        sudo rm -rf "$SYSTEM_INSTALL_DIR" 2>/dev/null || true
        exit 1
    fi
    (
        cp "$SOURCE_DIR/.env.example" "$ENV_FILE"
    ) &
    show_spinner "Инициализация конфигурации"
else
    print_success "Конфигурация уже существует"
fi

echo
echo -e "${BLUE}══════════════════════════════════════${NC}"
echo -e "${WHITE}    ⚙️  НАСТРОЙКА КОНФИГУРАЦИИ БОТА${NC}"
echo -e "${BLUE}══════════════════════════════════════${NC}"
echo

# ═══════════════════════════════════════════════
# СБОР ПОЛЬЗОВАТЕЛЬСКИХ ДАННЫХ
# ═══════════════════════════════════════════════

# BOT_TOKEN
reading_inline "Введите токен Telegram бота (из @BotFather):" BOT_TOKEN
if [ -z "$BOT_TOKEN" ]; then
    print_error "BOT_TOKEN не может быть пустым!"
    exit 1
fi
update_env_var "$ENV_FILE" "BOT_TOKEN" "$BOT_TOKEN"

# BOT_NAME
reading_inline "Введите username бота (без @, напр. my_mail_bot):" BOT_NAME
if [ -z "$BOT_NAME" ]; then
    print_error "BOT_NAME не может быть пустым!"
    exit 1
fi
update_env_var "$ENV_FILE" "BOT_NAME" "$BOT_NAME"

# ADMIN_IDS
reading_inline "Введите ваш Telegram ID (администратор):" ADMIN_IDS
if [ -z "$ADMIN_IDS" ]; then
    print_error "ADMIN_IDS не может быть пустым!"
    exit 1
fi
update_env_var "$ENV_FILE" "ADMIN_IDS" "$ADMIN_IDS"
update_env_var "$ENV_FILE" "DEVELOPER_IDS" "$ADMIN_IDS"

# SUPPORT_CHAT
reading_inline "Введите контакт поддержки (@username, Enter = пропуск):" SUPPORT_CHAT
echo
if [ -n "$SUPPORT_CHAT" ]; then
    update_env_var "$ENV_FILE" "SUPPORT_CHAT" "$SUPPORT_CHAT"
fi

# Платежные системы
echo
echo -e "${BLUE}══════════════════════════════════════${NC}"
echo -e "${WHITE}    💳 ПЛАТЕЖНЫЕ СИСТЕМЫ (опционально)${NC}"
echo -e "${BLUE}══════════════════════════════════════${NC}"
echo
echo -e "${GRAY}Нажмите Enter чтобы пропустить${NC}"
echo

reading_inline "YOOKASSA_SHOP_ID:" YOOKASSA_SHOP_ID
[ -n "$YOOKASSA_SHOP_ID" ] && update_env_var "$ENV_FILE" "YOOKASSA_SHOP_ID" "$YOOKASSA_SHOP_ID"

reading_inline "YOOKASSA_SECRET_KEY:" YOOKASSA_SECRET_KEY
[ -n "$YOOKASSA_SECRET_KEY" ] && update_env_var "$ENV_FILE" "YOOKASSA_SECRET_KEY" "$YOOKASSA_SECRET_KEY"

reading_inline "HELEKET_API_KEY:" HELEKET_API_KEY
[ -n "$HELEKET_API_KEY" ] && update_env_var "$ENV_FILE" "HELEKET_API_KEY" "$HELEKET_API_KEY"

echo

clear
echo ""
echo -e "${BLUE}══════════════════════════════════════${NC}"
echo -e "${GREEN}       🚀 ПРОЦЕСС УСТАНОВКИ${NC}"
echo -e "${BLUE}══════════════════════════════════════${NC}"
echo

# ═══════════════════════════════════════════════
# АВТОГЕНЕРАЦИЯ СЕКРЕТОВ
# ═══════════════════════════════════════════════
(
    # Пароль БД
    CURRENT_DB_PASS=$(grep "^DATABASE_PASSWORD=" "$ENV_FILE" | cut -d'=' -f2 | tr -d ' ')
    if [ -z "$CURRENT_DB_PASS" ]; then
        DATABASE_PASSWORD=$(generate_password)
        update_env_var "$ENV_FILE" "DATABASE_PASSWORD" "$DATABASE_PASSWORD"
    else
        DATABASE_PASSWORD="$CURRENT_DB_PASS"
    fi

    # Синхронизация PostgreSQL
    update_env_var "$ENV_FILE" "POSTGRES_PASSWORD" "$DATABASE_PASSWORD"
    DATABASE_USER=$(grep "^DATABASE_USER=" "$ENV_FILE" | cut -d'=' -f2 | tr -d ' ')
    [ -n "$DATABASE_USER" ] && update_env_var "$ENV_FILE" "POSTGRES_USER" "$DATABASE_USER"
    DATABASE_NAME=$(grep "^DATABASE_NAME=" "$ENV_FILE" | cut -d'=' -f2 | tr -d ' ')
    [ -n "$DATABASE_NAME" ] && update_env_var "$ENV_FILE" "POSTGRES_DB" "$DATABASE_NAME"
) &
show_spinner "Создание конфигурации"

# ═══════════════════════════════════════════════
# ПОДГОТОВКА ПАПОК
# ═══════════════════════════════════════════════
(
    mkdir -p "$PROJECT_DIR"/{logs,backups}
) &
show_spinner "Создание структуры папок"

# ═══════════════════════════════════════════════
# ОЧИСТКА СТАРЫХ ДАННЫХ
# ═══════════════════════════════════════════════
(
    cd "$PROJECT_DIR"
    docker compose down >/dev/null 2>&1 || true
    docker volume rm dfc-mail-db-data >/dev/null 2>&1 || true
) &
show_spinner "Очистка старых данных БД"

# ═══════════════════════════════════════════════
# СБОРКА DOCKER ОБРАЗА
# ═══════════════════════════════════════════════
(
    if [ "$COPY_FILES" = true ] && [ -d "$SOURCE_DIR" ]; then
        cd "$SOURCE_DIR"
        docker build -t dfc-mail:local \
            --build-arg BUILD_TIME="$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
            --build-arg BUILD_BRANCH="$REPO_BRANCH" \
            --build-arg BUILD_COMMIT="$(git rev-parse --short HEAD 2>/dev/null || echo 'unknown')" \
            --build-arg BUILD_TAG="$(grep '^version:' version 2>/dev/null | cut -d: -f2 | tr -d ' \n' || echo 'unknown')" \
            . >/dev/null 2>&1
    fi
) &
show_spinner "Сборка Docker образа"

# ═══════════════════════════════════════════════
# ЗАПУСК КОНТЕЙНЕРОВ
# ═══════════════════════════════════════════════
(
    cd "$PROJECT_DIR"
    docker compose up -d >/dev/null 2>&1
) &
show_spinner "Запуск сервисов"

# ═══════════════════════════════════════════════
# ОЖИДАНИЕ ЗАПУСКА
# ═══════════════════════════════════════════════
echo
show_spinner_until_log "dfc-mail" "Bot starting up" "Запуск бота" 90 && BOT_START_RESULT=0 || BOT_START_RESULT=$?
echo

# ═══════════════════════════════════════════════
# ЗАВЕРШЕНИЕ
# ═══════════════════════════════════════════════

if [ ${BOT_START_RESULT:-1} -eq 0 ]; then
    echo
    echo -e "${BLUE}══════════════════════════════════════${NC}"
    echo -e "${GREEN}    🎉 УСТАНОВКА ЗАВЕРШЕНА УСПЕШНО!${NC}"
    echo -e "${BLUE}══════════════════════════════════════${NC}"
    echo
    echo -e "${GREEN}✅ Бот успешно установлен и запущен${NC}"
    echo -e "${WHITE}✅ Команда вызова меню:${NC} ${YELLOW}dfc-mail${NC}"
elif [ ${BOT_START_RESULT:-1} -eq 2 ]; then
    echo
    echo -e "${BLUE}══════════════════════════════════════${NC}"
    echo -e "${RED}    ❌ ОШИБКА ПРИ ЗАПУСКЕ БОТА${NC}"
    echo -e "${BLUE}══════════════════════════════════════${NC}"
    echo
    echo -e "${RED}Бот установлен, но при запуске произошла ошибка.${NC}"
    echo
    echo -ne "${YELLOW}Показать логи? [Y/n]: ${NC}"
    read -n 1 -r show_logs_choice
    echo
    if [[ -z "$show_logs_choice" || "$show_logs_choice" =~ ^[Yy]$ ]]; then
        echo
        docker compose -f "$PROJECT_DIR/docker-compose.yml" logs --tail 50 dfc-mail
    fi
else
    echo
    echo -e "${BLUE}══════════════════════════════════════${NC}"
    echo -e "${YELLOW}    ⚠️  БОТ НЕ УСПЕЛ ЗАПУСТИТЬСЯ${NC}"
    echo -e "${BLUE}══════════════════════════════════════${NC}"
    echo
    echo -e "${YELLOW}Бот установлен, но не запустился за 90 сек.${NC}"
    echo
    echo -ne "${YELLOW}Показать логи? [Y/n]: ${NC}"
    read -n 1 -r show_logs_choice
    echo
    if [[ -z "$show_logs_choice" || "$show_logs_choice" =~ ^[Yy]$ ]]; then
        echo
        docker compose -f "$PROJECT_DIR/docker-compose.yml" logs --tail 50 dfc-mail
    fi
fi
echo

INSTALL_STARTED=false
INSTALL_COMPLETED=true

# Создание глобальной команды dfc-mail
(
    sudo mkdir -p "$SYSTEM_INSTALL_DIR"
    _src="$(realpath "$SOURCE_DIR/install.sh" 2>/dev/null || echo "$SOURCE_DIR/install.sh")"
    _dst="$(realpath "$SYSTEM_INSTALL_DIR/install.sh" 2>/dev/null || echo "$SYSTEM_INSTALL_DIR/install.sh")"
    if [ "$_src" != "$_dst" ] && [ -f "$SOURCE_DIR/install.sh" ]; then
        sudo cp "$SOURCE_DIR/install.sh" "$SYSTEM_INSTALL_DIR/install.sh"
    fi
    sudo chmod +x "$SYSTEM_INSTALL_DIR/install.sh"

    sudo tee /usr/local/bin/dfc-mail > /dev/null << 'EOF'
#!/bin/bash
if [ -f "/usr/local/lib/dfc-mail/install.sh" ]; then
    exec /usr/local/lib/dfc-mail/install.sh
else
    echo "❌ install.sh не найден. Переустановите бота."
    exit 1
fi
EOF
    sudo chmod +x /usr/local/bin/dfc-mail
) >/dev/null 2>&1

# Удаление исходной папки
if [ "$COPY_FILES" = true ] && [ "$SOURCE_DIR" != "$PROJECT_DIR" ] && [ "$SOURCE_DIR" != "/" ]; then
    cd /opt
    rm -rf "$SOURCE_DIR" 2>/dev/null || true
fi

echo -e "${DARKGRAY}Нажмите Enter для продолжения${NC}"
read -p ""
clear

cd /opt

if [ -n "$CLONE_DIR" ] && [ -d "$CLONE_DIR" ]; then
    rm -rf "$CLONE_DIR" 2>/dev/null || true
fi

show_full_menu
