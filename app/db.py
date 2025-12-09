"""Работа с SQLite базой данных."""
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple
from app.config import DB_PATH


def get_connection():
    """Создает и возвращает соединение с базой данных."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Инициализирует базу данных, создает таблицы если их нет."""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Таблица пользователей
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Таблица спектаклей
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS shows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            city TEXT NOT NULL,
            theatre TEXT NOT NULL,
            show_name TEXT NOT NULL,
            show_date TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    """)
    
    # Добавляем новые поля, если их нет (миграция)
    try:
        cursor.execute("ALTER TABLE shows ADD COLUMN source TEXT DEFAULT 'manual'")
    except sqlite3.OperationalError:
        pass  # Колонка уже существует
    
    try:
        cursor.execute("ALTER TABLE shows ADD COLUMN external_id INTEGER")
    except sqlite3.OperationalError:
        pass
    
    try:
        cursor.execute("ALTER TABLE shows ADD COLUMN url TEXT")
    except sqlite3.OperationalError:
        pass
    
    try:
        cursor.execute("ALTER TABLE shows ADD COLUMN datetime TEXT")
    except sqlite3.OperationalError:
        pass
    
    # Добавляем поля для напоминаний
    try:
        cursor.execute("ALTER TABLE shows ADD COLUMN notify_at TEXT")
    except sqlite3.OperationalError as e:
        # Колонка уже существует
        pass
    
    try:
        cursor.execute("ALTER TABLE shows ADD COLUMN notified INTEGER DEFAULT 0")
    except sqlite3.OperationalError as e:
        # Колонка уже существует
        pass
    
    # Удаляем колонку city, если она существует (миграция)
    try:
        # SQLite не поддерживает DROP COLUMN напрямую, используем пересоздание таблицы
        cursor.execute("PRAGMA foreign_keys = OFF")
        cursor.execute("""
            CREATE TEMPORARY TABLE shows_backup(
                id, user_id, theatre, show_name, show_date, created_at, 
                source, external_id, url, datetime, notify_at, notified
            )
        """)
        cursor.execute("""
            INSERT INTO shows_backup 
            SELECT id, user_id, theatre, show_name, show_date, created_at,
                   COALESCE(source, 'manual'), external_id, url, datetime, notify_at, notified
            FROM shows
        """)
        cursor.execute("DROP TABLE shows")
        cursor.execute("""
            CREATE TABLE shows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                theatre TEXT NOT NULL,
                show_name TEXT NOT NULL,
                show_date TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                source TEXT DEFAULT 'manual',
                external_id INTEGER,
                url TEXT,
                datetime TEXT,
                notify_at TEXT,
                notified INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        cursor.execute("""
            INSERT INTO shows 
            SELECT id, user_id, theatre, show_name, show_date, created_at,
                   source, external_id, url, datetime, notify_at, notified
            FROM shows_backup
        """)
        cursor.execute("DROP TABLE shows_backup")
        cursor.execute("PRAGMA foreign_keys = ON")
    except sqlite3.OperationalError as e:
        # Если ошибка не связана с отсутствием city, игнорируем
        if "no such column: city" not in str(e).lower():
            pass
    
    conn.commit()
    conn.close()


def add_user(user_id: int, username: Optional[str] = None, first_name: Optional[str] = None):
    """Добавляет или обновляет пользователя в базе данных."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT OR REPLACE INTO users (user_id, username, first_name, created_at)
        VALUES (?, ?, ?, ?)
    """, (user_id, username, first_name, datetime.now()))
    
    conn.commit()
    conn.close()


def add_show(
    user_id: int,
    theatre: str,
    show_name: str,
    show_date: str,
    source: str = "manual",
    external_id: Optional[int] = None,
    url: Optional[str] = None,
    datetime_str: Optional[str] = None,
    notify_at: Optional[str] = None
) -> int:
    """
    Добавляет спектакль в базу данных. Возвращает ID созданной записи.
    
    Args:
        user_id: ID пользователя
        theatre: Театр/место проведения
        show_name: Название спектакля
        show_date: Дата в формате YYYY-MM-DD (для обратной совместимости)
        source: Источник данных ('kudago', 'csv' или 'manual')
        external_id: ID события из внешнего источника (KudaGo)
        url: URL события
        datetime_str: Дата и время в формате YYYY-MM-DD HH:MM:SS
        notify_at: Время напоминания в формате YYYY-MM-DD HH:MM:SS
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    # Если datetime_str не указан, используем show_date
    if not datetime_str:
        datetime_str = show_date
    
    cursor.execute("""
        INSERT INTO shows (user_id, theatre, show_name, show_date, source, external_id, url, datetime, notify_at, notified)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
    """, (user_id, theatre, show_name, show_date, source, external_id, url, datetime_str, notify_at))
    
    show_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return show_id


def get_user_shows(user_id: int) -> List[dict]:
    """Получает все спектакли пользователя."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, theatre, show_name, show_date, created_at, source, external_id, url, datetime, notify_at, notified
        FROM shows
        WHERE user_id = ?
        ORDER BY COALESCE(datetime, show_date) ASC, created_at DESC
    """, (user_id,))
    
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(row) for row in rows]


def get_show_by_id(show_id: int, user_id: int) -> Optional[dict]:
    """Получает спектакль по ID, если он принадлежит пользователю."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, theatre, show_name, show_date, created_at, source, external_id, url, datetime, notify_at, notified
        FROM shows
        WHERE id = ? AND user_id = ?
    """, (show_id, user_id))
    
    row = cursor.fetchone()
    conn.close()
    
    return dict(row) if row else None


def delete_show(show_id: int, user_id: int) -> bool:
    """Удаляет спектакль, если он принадлежит пользователю. Возвращает True если удален."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        DELETE FROM shows
        WHERE id = ? AND user_id = ?
    """, (show_id, user_id))
    
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    
    return deleted


def update_show(
    show_id: int,
    user_id: int,
    theatre: Optional[str] = None,
    show_name: Optional[str] = None,
    show_date: Optional[str] = None,
    datetime_str: Optional[str] = None,
    notify_at: Optional[str] = None,
    notified: Optional[int] = None
) -> bool:
    """Обновляет данные спектакля. Возвращает True если обновлен."""
    import logging
    logger = logging.getLogger(__name__)
    
    conn = get_connection()
    cursor = conn.cursor()
    
    # Формируем запрос динамически на основе переданных параметров
    updates = []
    params = []
    
    if theatre is not None:
        updates.append("theatre = ?")
        params.append(theatre)
    
    if show_name is not None:
        updates.append("show_name = ?")
        params.append(show_name)
    
    if show_date is not None:
        updates.append("show_date = ?")
        params.append(show_date)
    
    if datetime_str is not None:
        updates.append("datetime = ?")
        params.append(datetime_str)
    
    # Обработка notify_at: если передана строка - устанавливаем, если пустая строка - удаляем
    if notify_at is not None:
        if notify_at == "":
            # Удаляем напоминание
            updates.append("notify_at = NULL")
            updates.append("notified = 0")
            logger.info(f"Удаление напоминания для спектакля {show_id}, пользователь {user_id}")
        else:
            # Устанавливаем напоминание
            updates.append("notify_at = ?")
            params.append(notify_at)
            # При обновлении notify_at сбрасываем notified
            updates.append("notified = 0")
            logger.info(f"Установка напоминания для спектакля {show_id}, пользователь {user_id}, notify_at={notify_at}")
    
    if notified is not None:
        updates.append("notified = ?")
        params.append(notified)
    
    if not updates:
        conn.close()
        logger.warning(f"Нет обновлений для спектакля {show_id}, пользователь {user_id}")
        return False
    
    params.extend([show_id, user_id])
    
    query = f"""
        UPDATE shows
        SET {', '.join(updates)}
        WHERE id = ? AND user_id = ?
    """
    
    logger.debug(f"Выполнение запроса: {query}, параметры: {params}")
    cursor.execute(query, params)
    updated = cursor.rowcount > 0
    conn.commit()
    conn.close()
    
    if updated:
        logger.info(f"Спектакль {show_id} успешно обновлен для пользователя {user_id}")
    else:
        logger.warning(f"Спектакль {show_id} не найден или не обновлен для пользователя {user_id}")
    
    return updated


def get_theatres_stats() -> List[dict]:
    """Возвращает список театров и количества спектаклей (по всем пользователям)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT theatre, COUNT(*) as cnt
        FROM shows
        GROUP BY theatre
        ORDER BY cnt DESC, theatre ASC
        LIMIT 100
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_pending_notifications(current_time: str) -> List[dict]:
    """Получает все спектакли с неотправленными напоминаниями, которые должны быть отправлены до указанного времени."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, user_id, theatre, show_name, show_date, datetime, notify_at
        FROM shows
        WHERE notify_at IS NOT NULL 
          AND notify_at <= ?
          AND notified = 0
        ORDER BY notify_at ASC
    """, (current_time,))
    
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(row) for row in rows]


def mark_notification_sent(show_id: int) -> None:
    """Отмечает напоминание как отправленное."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        UPDATE shows
        SET notified = 1
        WHERE id = ?
    """, (show_id,))
    
    conn.commit()
    conn.close()

