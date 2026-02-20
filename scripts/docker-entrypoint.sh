#!/bin/sh
set -e

echo "============================================"
echo "  DFC Mail Bot — Запуск контейнера"
echo "============================================"

echo "Waiting for database to be ready..."
for i in $(seq 1 30); do
    if pg_isready -h "$DATABASE_HOST" -p "$DATABASE_PORT" -U "$DATABASE_USER" > /dev/null 2>&1; then
        echo "Database is ready"
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "ERROR: Database did not become ready in time!"
        exit 1
    fi
    echo "Attempt $i: Database not ready yet, retrying in 2 seconds..."
    sleep 2
done

echo "Starting DFC Mail Bot..."
exec python -m src.main
