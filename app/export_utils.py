"""Утилиты для экспорта спектаклей в TXT файлы."""
from pathlib import Path
from typing import List, Optional
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from app.config import EXPORT_DIR

# Часовой пояс пользователя (Москва UTC+3)
MOSCOW_TZ = ZoneInfo("Europe/Moscow")

def format_datetime_for_user(dt: datetime) -> str:
    """Форматирует datetime для отображения пользователю в московском времени."""
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    moscow_dt = dt.astimezone(MOSCOW_TZ)
    return moscow_dt.strftime('%d.%m.%Y %H:%M')


def generate_txt(shows: List[dict], user_id: int, single_show: Optional[dict] = None) -> Path:
    """
    Генерирует TXT файл со спектаклями в читаемом формате.
    
    Args:
        shows: Список словарей со спектаклями
        user_id: ID пользователя
        single_show: Если указан, экспортирует только этот спектакль
    
    Returns:
        Path к созданному файлу
    """
    if single_show:
        shows = [single_show]
    
    if not shows:
        raise ValueError("Нет спектаклей для экспорта")
    
    # Создаем имя файла с timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if single_show:
        filename = f"show_{single_show['id']}_{timestamp}.txt"
    else:
        filename = f"shows_user_{user_id}_{timestamp}.txt"
    
    file_path = EXPORT_DIR / filename
    
    # Сортируем спектакли по дате (хронологически)
    def get_show_datetime(show):
        dt_str = show.get('datetime') or show.get('show_date', '')
        try:
            if ' ' in dt_str:
                return datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
            else:
                return datetime.strptime(dt_str, '%Y-%m-%d').replace(tzinfo=timezone.utc)
        except:
            return datetime.max.replace(tzinfo=timezone.utc)  # Спектакли без даты в конец
    
    shows_sorted = sorted(shows, key=get_show_datetime)
    
    # Генерируем содержимое TXT в читаемом формате
    lines = []
    lines.append("МОИ СПЕКТАКЛИ")
    lines.append("=" * 50)
    lines.append("")
    
    # Формируем содержимое
    for idx, show in enumerate(shows_sorted, 1):
        # Форматируем дату (конвертируем из UTC в московское время)
        show_datetime_str = show.get('datetime') or show.get('show_date', 'Не указано')
        try:
            if ' ' in show_datetime_str:
                dt = datetime.strptime(show_datetime_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
                formatted_date = format_datetime_for_user(dt)
            else:
                dt = datetime.strptime(show_datetime_str, '%Y-%m-%d').replace(tzinfo=timezone.utc)
                formatted_date = format_datetime_for_user(dt)
        except:
            formatted_date = show_datetime_str
        
        lines.append(f"{idx}. {show['show_name']}")
        lines.append(f"   Театр: {show['theatre']}")
        lines.append(f"   Дата: {formatted_date}")
        lines.append("")
    
    lines.append("=" * 50)
    lines.append(f"Всего: {len(shows)} спектаклей")
    
    # Записываем файл
    content = "\n".join(lines)
    file_path.write_text(content, encoding='utf-8')
    
    return file_path


# Для обратной совместимости
def generate_markdown(shows: List[dict], user_id: int, single_show: Optional[dict] = None) -> Path:
    """Алиас для generate_txt (обратная совместимость)."""
    return generate_txt(shows, user_id, single_show)

