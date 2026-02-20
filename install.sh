#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# DFC Mail Bot — Автоматический установщик
# Стиль: dfc-remna-install
# ═══════════════════════════════════════════════════════════════

set -euo pipefail

# Защита от запуска из удалённой директории
cd /tmp 2>/dev/null || cd / 2>/dev/null || true

# ═══════════════════════════════════════════════
# ПЕРЕМЕННЫЕ
# ═══════════════════════════════════════════════
PROJECT_DIR="/opt/dfc-mail"
ENV_FILE="$PROJECT_DIR/.env"
REPO_URL="https://github.com/DanteFuaran/dfc-mail.git"
REPO_BRANCH="main"
SYSTEM_INSTALL_DIR="/usr/local/lib/dfc-mail"
SCRIPT_CWD="$(cd "$(dirname "$0")" 2>/dev/null && pwd)"

INSTALL_STARTED=false
INSTALL_COMPLETED=false
SOURCE_DIR=""
CLONE_DIR=""

SCRIPT_VERSION="1.0.0"

# Читаем ветку/версию из version
for _uf in "$PROJECT_DIR/version" "$SCRIPT_CWD/version"; do
    if [ -f "$_uf" ]; then
        _br=$(grep '^branch:' "$_uf" | cut -d: -f2 | tr -d ' \n')
        _ru=$(grep '^repo:'   "$_uf" | cut -d: -f2- | tr -d ' \n')
        _sv=$(grep '^version:' "$_uf" | cut -d: -f2 | tr -d ' \n')
        [ -n "$_br" ] && REPO_BRANCH="$_br"
        [ -n "$_ru" ] && REPO_URL="$_ru"
        [ -n "$_sv" ] && SCRIPT_VERSION="$_sv"
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
ORIGINAL_STTY=$(stty -g 2>/dev/null || echo "")

cleanup_terminal() {
    tput cnorm 2>/dev/null || true
    tput sgr0 2>/dev/null || true
    printf "\033[0m\033[?25h" 2>/dev/null || true
    if [ -n "$ORIGINAL_STTY" ]; then
        stty "$ORIGINAL_STTY" 2>/dev/null || stty sane 2>/dev/null || true
    else
        stty sane 2>/dev/null || true
    fi
}

handle_interrupt() {
    cleanup_terminal
    clear
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
        printf "\r${DARKGRAY}%s  %s (%d/%d сек)${NC}" "${spin[$i]}" "$msg" "$elapsed" "$timeout"
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
# МЕНЮ СО СТРЕЛОЧКАМИ (стиль dfc-remna-install)
# ═══════════════════════════════════════════════
show_arrow_menu() {
    set +e
    local title="$1"
    shift
    local options=("$@")
    local num_options=${#options[@]}
    local selected=0
    local original_stty=""
    original_stty=$(stty -g 2>/dev/null || echo "")

    tput civis 2>/dev/null || true
    stty -icanon -echo min 1 time 0 2>/dev/null || true

    _restore_term() {
        if [ -n "${original_stty:-}" ]; then
            stty "$original_stty" 2>/dev/null || stty sane 2>/dev/null || true
        else
            stty sane 2>/dev/null || true
        fi
        tput cnorm 2>/dev/null || true
    }
    trap "_restore_term" RETURN

    while true; do
        clear
        echo -e "${BLUE}══════════════════════════════════════${NC}"
        echo -e "${GREEN}   $title${NC}"
        echo -e "${BLUE}══════════════════════════════════════${NC}"
        echo

        for i in "${!options[@]}"; do
            if [[ "${options[$i]}" =~ ^[─━═[:space:]]*$ ]]; then
                echo -e "${DARKGRAY}${options[$i]}${NC}"
            elif [ $i -eq $selected ]; then
                echo -e "${BLUE}▶${NC} ${YELLOW}${options[$i]}${NC}"
            else
                echo -e "  ${options[$i]}"
            fi
        done

        echo
        echo -e "${BLUE}══════════════════════════════════════${NC}"
        echo -e "${DARKGRAY}Используйте ↑↓ для навигации, Enter для выбора${NC}"
        echo

        local key
        read -rsn1 key 2>/dev/null || key=""

        if [[ "$key" == $'\e' ]]; then
            local seq1="" seq2=""
            read -rsn1 -t 0.1 seq1 2>/dev/null || seq1=""
            if [[ "$seq1" == '[' ]]; then
                read -rsn1 -t 0.1 seq2 2>/dev/null || seq2=""
                case "$seq2" in
                    'A')
                        ((selected--))
                        [ $selected -lt 0 ] && selected=$((num_options - 1))
                        while [[ "${options[$selected]}" =~ ^[─═[:space:]]*$ ]]; do
                            ((selected--))
                            [ $selected -lt 0 ] && selected=$((num_options - 1))
                        done
                        ;;
                    'B')
                        ((selected++))
                        [ $selected -ge $num_options ] && selected=0
                        while [[ "${options[$selected]}" =~ ^[─═[:space:]]*$ ]]; do
                            ((selected++))
                            [ $selected -ge $num_options ] && selected=0
                        done
                        ;;
                esac
            fi
        else
            local key_code
            if [ -n "$key" ]; then
                key_code=$(printf '%d' "'$key" 2>/dev/null || echo 0)
            else
                key_code=13
            fi
            if [ "$key_code" -eq 10 ] || [ "$key_code" -eq 13 ]; then
                _restore_term
                return $selected
            fi
        fi
    done
}

# ═══════════════════════════════════════════════
# ВВОД ТЕКСТА (стиль dfc-remna-install)
# ═══════════════════════════════════════════════
reading_inline() {
    local prompt="$1"
    local var_name="$2"
    local input=""
    local char
    echo -en "${BLUE}➜${NC}  ${YELLOW}${prompt}${NC} "
    while IFS= read -r -s -n1 char; do
        if [[ -z "$char" ]]; then
            break
        elif [[ "$char" == $'\x7f' ]] || [[ "$char" == $'\x08' ]]; then
            if [[ -n "$input" ]]; then
                input="${input%?}"
                echo -en "\b \b"
            fi
        elif [[ "$char" == $'\x1b' ]]; then
            local _seq=""
            while IFS= read -r -s -n1 -t 0.1 _sc; do
                _seq+="$_sc"
                [[ "$_sc" =~ [A-Za-z~] ]] && break
            done
        else
            input+="$char"
            echo -en "$char"
        fi
    done
    echo
    printf -v "$var_name" '%s' "$input"
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
# ПРОВЕРКА УСТАНОВКИ
# ═══════════════════════════════════════════════
is_installed() {
    [ -d "$PROJECT_DIR" ] && [ -f "$PROJECT_DIR/docker-compose.yml" ] && [ -f "$PROJECT_DIR/.env" ]
}

# ═══════════════════════════════════════════════
# УПРАВЛЕНИЕ БОТОМ
# ═══════════════════════════════════════════════
manage_restart() {
    cd "$PROJECT_DIR" || return
    (docker compose down >/dev/null 2>&1; docker compose up -d >/dev/null 2>&1) &
    show_spinner "Перезапуск бота"
    echo -e "\n${GREEN}✅ Бот перезапущен${NC}\n"
    echo -e "${DARKGRAY}Enter: Продолжить${NC}"; read -rsn1
}

manage_stop() {
    cd "$PROJECT_DIR" || return
    (docker compose down >/dev/null 2>&1) &
    show_spinner "Остановка бота"
    echo -e "\n${GREEN}✅ Бот остановлен${NC}\n"
    echo -e "${DARKGRAY}Enter: Продолжить${NC}"; read -rsn1
}

manage_start() {
    cd "$PROJECT_DIR" || return
    (docker compose up -d >/dev/null 2>&1) &
    show_spinner "Запуск бота"
    echo -e "\n${GREEN}✅ Бот запущен${NC}\n"
    echo -e "${DARKGRAY}Enter: Продолжить${NC}"; read -rsn1
}

manage_logs() {
    cd "$PROJECT_DIR" || return
    clear
    echo -e "${BLUE}══════════════════════════════════════${NC}"
    echo -e "${GREEN}   📋 ЛОГИ БОТА (последние 50 строк)${NC}"
    echo -e "${BLUE}══════════════════════════════════════${NC}"
    echo
    docker compose logs --tail 50 dfc-mail 2>&1
    echo
    echo -e "${DARKGRAY}Enter: Продолжить${NC}"; read -rsn1
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
        echo -e "${DARKGRAY}Enter: Продолжить${NC}"; read -rsn1
    fi
}

manage_update() {
    echo
    local TEMP_REPO
    TEMP_REPO=$(mktemp -d)

    (git clone -b "$REPO_BRANCH" --depth 1 "$REPO_URL" "$TEMP_REPO" >/dev/null 2>&1) &
    show_spinner "Загрузка обновлений"

    if [ ! -f "$TEMP_REPO/docker-compose.yml" ]; then
        print_error "Ошибка загрузки обновлений"
        rm -rf "$TEMP_REPO"
        echo -e "${DARKGRAY}Enter: Продолжить${NC}"; read -rsn1
        return
    fi

    (
        cp -f "$TEMP_REPO/docker-compose.yml" "$PROJECT_DIR/"
        [ -f "$TEMP_REPO/version" ] && cp -f "$TEMP_REPO/version" "$PROJECT_DIR/version"
        sudo mkdir -p "$SYSTEM_INSTALL_DIR" 2>/dev/null || true
        sudo cp -f "$TEMP_REPO/install.sh" "$SYSTEM_INSTALL_DIR/install.sh" 2>/dev/null || true
        sudo chmod +x "$SYSTEM_INSTALL_DIR/install.sh" 2>/dev/null || true
    ) &
    show_spinner "Копирование файлов"

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

    (cd "$PROJECT_DIR" || return; docker compose down >/dev/null 2>&1; docker compose up -d >/dev/null 2>&1) &
    show_spinner "Перезапуск бота"

    rm -rf "$TEMP_REPO"

    echo
    show_spinner_until_log "dfc-mail" "Bot starting up" "Запуск бота" 90 && BOT_OK=0 || BOT_OK=$?

    if [ "${BOT_OK:-1}" -eq 0 ]; then
        echo -e "\n${GREEN}✅ Обновление завершено успешно!${NC}"
    else
        echo -e "\n${YELLOW}⚠️  Бот не успел запуститься. Проверьте логи.${NC}"
    fi
    echo
    echo -e "${DARKGRAY}Enter: Продолжить${NC}"; read -rsn1
}

manage_reinstall() {
    echo
    echo -e "${YELLOW}⚠️  Переустановка удалит текущую конфигурацию и данные!${NC}"
    echo -e "${DARKGRAY}Enter: Подтвердить     Esc: Отмена${NC}"
    tput civis 2>/dev/null || true
    local key
    while true; do
        read -s -n 1 key
        if [[ "$key" == $'\x1b' ]]; then
            tput cnorm 2>/dev/null || true
            return
        elif [[ "$key" == "" ]]; then
            tput cnorm 2>/dev/null || true
            break
        fi
    done

    if [ -d "$PROJECT_DIR" ]; then
        (cd "$PROJECT_DIR" && docker compose down -v >/dev/null 2>&1 || true) &
        show_spinner "Остановка контейнеров"
    fi

    (docker volume rm dfc-mail-db-data >/dev/null 2>&1 || true; rm -rf "$PROJECT_DIR") &
    show_spinner "Удаление данных"

    echo -e "\n${GREEN}✅ Данные удалены. Запускаю установку...${NC}"
    sleep 1
    exec "$0" --install "$SCRIPT_CWD"
}

manage_uninstall() {
    echo
    echo -e "${RED}⚠️  ВНИМАНИЕ: Это действие удалит бота, базу данных и все настройки!${NC}"
    echo -e "${DARKGRAY}Enter: Подтвердить     Esc: Отмена${NC}"
    tput civis 2>/dev/null || true
    local key
    while true; do
        read -s -n 1 key
        if [[ "$key" == $'\x1b' ]]; then
            tput cnorm 2>/dev/null || true
            return
        elif [[ "$key" == "" ]]; then
            tput cnorm 2>/dev/null || true
            break
        fi
    done

    (
        if [ -d "$PROJECT_DIR" ]; then
            cd "$PROJECT_DIR" && docker compose down -v >/dev/null 2>&1 || true
            cd /opt
        fi
        docker volume rm dfc-mail-db-data >/dev/null 2>&1 || true
        docker network rm dfc-mail-network >/dev/null 2>&1 || true
        rm -rf "$PROJECT_DIR"
    ) &
    show_spinner "Удаление бота и данных"

    (
        sudo rm -f /usr/local/bin/dfc-mail 2>/dev/null || true
        sudo rm -rf "$SYSTEM_INSTALL_DIR" 2>/dev/null || true
    ) &
    show_spinner "Удаление команды dfc-mail"

    echo -e "\n${GREEN}✅ Бот успешно удалён!${NC}\n"
    echo -e "${DARKGRAY}Enter: Продолжить${NC}"; read -rsn1
    clear
    exit 0
}

# ═══════════════════════════════════════════════
# ГЛАВНОЕ МЕНЮ (стиль dfc-remna-install)
# ═══════════════════════════════════════════════
show_full_menu() {
    while true; do
        local ver="$SCRIPT_VERSION"
        [ -f "$PROJECT_DIR/version" ] && ver=$(grep '^version:' "$PROJECT_DIR/version" | cut -d: -f2 | tr -d ' ')

        local status_text="${RED}остановлен${NC}"
        if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^dfc-mail$"; then
            status_text="${GREEN}работает${NC}"
        fi

        local menu_title="    📧 DFC MAIL BOT v${ver}  |  ${status_text}"

        local -a items=() actions=()

        items+=("▶️   Запуск");             actions+=("start")
        items+=("⏹️   Остановка");          actions+=("stop")
        items+=("🔄  Перезапуск");          actions+=("restart")
        items+=("──────────────────────────────────────"); actions+=("sep")
        items+=("📋  Логи (последние 50)"); actions+=("logs")
        items+=("📋  Логи (реальное время)"); actions+=("logs_follow")
        items+=("──────────────────────────────────────"); actions+=("sep")
        items+=("✏️   Редактировать .env");  actions+=("edit_env")
        items+=("🔄  Обновление");          actions+=("update")
        items+=("──────────────────────────────────────"); actions+=("sep")
        items+=("🔁  Переустановка");       actions+=("reinstall")
        items+=("🗑️   Удаление бота");       actions+=("uninstall")
        items+=("──────────────────────────────────────"); actions+=("sep")
        items+=("❌  Выход");               actions+=("exit")

        show_arrow_menu "$menu_title" "${items[@]}"
        local choice=$?
        local action="${actions[$choice]:-}"

        case "$action" in
            start)       manage_start ;;
            stop)        manage_stop ;;
            restart)     manage_restart ;;
            logs)        manage_logs ;;
            logs_follow) manage_logs_follow ;;
            edit_env)    manage_edit_env ;;
            update)      manage_update ;;
            reinstall)   manage_reinstall ;;
            uninstall)   manage_uninstall ;;
            sep)         continue ;;
            exit)        cleanup_terminal; exit 0 ;;
            *)           continue ;;
        esac
    done
}

# ═══════════════════════════════════════════════
# ОЧИСТКА ПРИ ОШИБКЕ
# ═══════════════════════════════════════════════
cleanup_on_error() {
    local exit_code=$?
    cleanup_terminal

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
        docker network rm dfc-mail-network >/dev/null 2>&1 || true

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
    # Сеть создаётся автоматически через docker compose
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
    (cp "$SOURCE_DIR/.env.example" "$ENV_FILE") &
    show_spinner "Инициализация конфигурации"
else
    print_success "Конфигурация уже существует"
fi

echo
echo -e "${BLUE}══════════════════════════════════════${NC}"
echo -e "${GREEN}    ⚙️  НАСТРОЙКА КОНФИГУРАЦИИ БОТА${NC}"
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

# BOT_NAME — автоопределение через Telegram API
BOT_NAME=""
_tg_response=$(curl -sf "https://api.telegram.org/bot${BOT_TOKEN}/getMe" 2>/dev/null || true)
if [ -n "$_tg_response" ]; then
    _detected=$(echo "$_tg_response" | grep -o '"username":"[^"]*"' | cut -d'"' -f4)
    if [ -n "$_detected" ]; then
        BOT_NAME="$_detected"
        print_success "Username бота определён автоматически: @${BOT_NAME}"
    fi
fi
if [ -z "$BOT_NAME" ]; then
    reading_inline "Введите username бота (без @, напр. my_mail_bot):" BOT_NAME
    if [ -z "$BOT_NAME" ]; then
        print_error "BOT_NAME не может быть пустым!"
        exit 1
    fi
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
echo -e "${GREEN}    💳 ПЛАТЕЖНЫЕ СИСТЕМЫ (опционально)${NC}"
echo -e "${BLUE}══════════════════════════════════════${NC}"
echo
echo -e "${DARKGRAY}Нажмите Enter чтобы пропустить${NC}"
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
    CURRENT_DB_PASS=$(grep "^DATABASE_PASSWORD=" "$ENV_FILE" | cut -d'=' -f2 | tr -d ' ')
    if [ -z "$CURRENT_DB_PASS" ]; then
        DATABASE_PASSWORD=$(generate_password)
        update_env_var "$ENV_FILE" "DATABASE_PASSWORD" "$DATABASE_PASSWORD"
    else
        DATABASE_PASSWORD="$CURRENT_DB_PASS"
    fi

    update_env_var "$ENV_FILE" "POSTGRES_PASSWORD" "$DATABASE_PASSWORD"
    DATABASE_USER=$(grep "^DATABASE_USER=" "$ENV_FILE" | cut -d'=' -f2 | tr -d ' ')
    [ -n "$DATABASE_USER" ] && update_env_var "$ENV_FILE" "POSTGRES_USER" "$DATABASE_USER"
    DATABASE_NAME=$(grep "^DATABASE_NAME=" "$ENV_FILE" | cut -d'=' -f2 | tr -d ' ')
    [ -n "$DATABASE_NAME" ] && update_env_var "$ENV_FILE" "POSTGRES_DB" "$DATABASE_NAME"
) &
show_spinner "Создание конфигурации"

# Подготовка папок
(mkdir -p "$PROJECT_DIR"/{logs,backups}) &
show_spinner "Создание структуры папок"

# Очистка старых данных
(
    cd "$PROJECT_DIR"
    docker compose down >/dev/null 2>&1 || true
    docker volume rm dfc-mail-db-data >/dev/null 2>&1 || true
    docker network rm dfc-mail-network >/dev/null 2>&1 || true
) &
show_spinner "Очистка старых данных БД"

# Сборка Docker образа
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

# Выбор свободного порта
_wp=$(grep "^WEBHOOK_PORT=" "$ENV_FILE" | cut -d'=' -f2 | tr -d ' ')
_wp=${_wp:-8443}
while ss -tlnp 2>/dev/null | grep -q ":${_wp}[[:space:]]"; do
    _wp=$((_wp + 1))
done
update_env_var "$ENV_FILE" "WEBHOOK_PORT" "$_wp"

# Запуск контейнеров
(cd "$PROJECT_DIR"; docker compose up -d >/dev/null 2>&1) &
show_spinner "Запуск сервисов"

# Ожидание запуска
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
    echo -e "${DARKGRAY}Enter: Показать логи     Esc: Пропустить${NC}"
    tput civis 2>/dev/null || true
    local key 2>/dev/null || true
    read -s -n 1 key
    if [[ "$key" != $'\x1b' ]]; then
        echo
        docker compose -f "$PROJECT_DIR/docker-compose.yml" logs --tail 50 dfc-mail
    fi
    tput cnorm 2>/dev/null || true
else
    echo
    echo -e "${BLUE}══════════════════════════════════════${NC}"
    echo -e "${YELLOW}    ⚠️  БОТ НЕ УСПЕЛ ЗАПУСТИТЬСЯ${NC}"
    echo -e "${BLUE}══════════════════════════════════════${NC}"
    echo
    echo -e "${YELLOW}Бот установлен, но не запустился за 90 сек.${NC}"
    echo
    echo -e "${DARKGRAY}Enter: Показать логи     Esc: Пропустить${NC}"
    tput civis 2>/dev/null || true
    read -s -n 1 key
    if [[ "${key:-}" != $'\x1b' ]]; then
        echo
        docker compose -f "$PROJECT_DIR/docker-compose.yml" logs --tail 50 dfc-mail
    fi
    tput cnorm 2>/dev/null || true
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

echo -e "${DARKGRAY}Enter: Продолжить${NC}"; read -rsn1
clear

cd /opt

if [ -n "$CLONE_DIR" ] && [ -d "$CLONE_DIR" ]; then
    rm -rf "$CLONE_DIR" 2>/dev/null || true
fi

show_full_menu
