"""Скрипт резервного копирования базы данных DFC Mail."""
import asyncio
import os
import subprocess
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import settings


def backup_database():
    """Создание резервной копии PostgreSQL."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backups")
    os.makedirs(backup_dir, exist_ok=True)
    backup_file = os.path.join(backup_dir, f"dfc_mail_backup_{timestamp}.sql")

    env = os.environ.copy()
    env["PGPASSWORD"] = settings.DATABASE_PASSWORD

    cmd = [
        "pg_dump",
        "-h", settings.DATABASE_HOST,
        "-p", str(settings.DATABASE_PORT),
        "-U", settings.DATABASE_USER,
        "-d", settings.DATABASE_NAME,
        "-F", "c",
        "-f", backup_file,
    ]

    try:
        subprocess.run(cmd, env=env, check=True, capture_output=True, text=True)
        print(f"✅ Backup created: {backup_file}")

        # Удаляем старые бэкапы (оставляем 10 последних)
        backups = sorted(
            [f for f in os.listdir(backup_dir) if f.startswith("dfc_mail_backup_")],
            reverse=True,
        )
        for old_backup in backups[10:]:
            os.remove(os.path.join(backup_dir, old_backup))
            print(f"🗑️ Removed old backup: {old_backup}")

        return backup_file
    except subprocess.CalledProcessError as e:
        print(f"❌ Backup failed: {e.stderr}")
        return None
    except FileNotFoundError:
        print("❌ pg_dump not found. Make sure postgresql-client is installed.")
        return None


def restore_database(backup_file: str):
    """Восстановление базы данных из резервной копии."""
    if not os.path.exists(backup_file):
        print(f"❌ Backup file not found: {backup_file}")
        return False

    env = os.environ.copy()
    env["PGPASSWORD"] = settings.DATABASE_PASSWORD

    cmd = [
        "pg_restore",
        "-h", settings.DATABASE_HOST,
        "-p", str(settings.DATABASE_PORT),
        "-U", settings.DATABASE_USER,
        "-d", settings.DATABASE_NAME,
        "--clean",
        "--if-exists",
        backup_file,
    ]

    try:
        subprocess.run(cmd, env=env, check=True, capture_output=True, text=True)
        print(f"✅ Database restored from: {backup_file}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Restore failed: {e.stderr}")
        return False


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "restore":
        if len(sys.argv) < 3:
            print("Usage: python backup_db.py restore <backup_file>")
            sys.exit(1)
        restore_database(sys.argv[2])
    else:
        backup_database()
