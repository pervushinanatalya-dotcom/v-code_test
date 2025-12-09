"""Скрипт для выгрузки данных о спектаклях из API KudaGo."""
import sys
import csv
import logging
from pathlib import Path
from datetime import datetime, timezone

# Добавляем корневую директорию проекта в путь
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.kudago_api import KudaGoAPI

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def fetch_moscow_shows(output_file: str = None):
    """
    Выгружает данные о спектаклях из Москвы и сохраняет в CSV.
    
    Args:
        output_file: Путь к выходному CSV файлу (по умолчанию data/shows_catalog.csv)
    """
    # Определяем путь к файлу
    if output_file is None:
        output_file = project_root / "data" / "shows_catalog.csv"
    
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Инициализируем API клиент
    api = KudaGoAPI()
    
    logger.info("Получение ID города Москва...")
    cities = api.get_cities()
    logger.info(f"Получено городов: {len(cities)}")
    
    # Ищем Москву по разным вариантам названия
    city_id = None
    city_slug = None
    for city in cities[:10]:  # Показываем первые 10 для отладки
        logger.debug(f"Город: {city}")
        city_name = city.get('name', '').lower()
        if 'москв' in city_name or city.get('slug') == 'msk':
            city_id = city.get('id')
            city_slug = city.get('slug', 'msk')
            logger.info(f"Найден город: {city.get('name')} (ID: {city_id}, slug: {city_slug})")
            break
    
    if not city_id:
        logger.error("Город Москва не найден в API")
        logger.info("Доступные города (первые 10):")
        for city in cities[:10]:
            logger.info(f"  - {city.get('name')} (slug: {city.get('slug')}, id: {city.get('id')})")
        # Используем slug напрямую
        city_slug = 'msk'
        logger.info(f"Используем slug города: {city_slug}")
    
    # Используем категорию "театр" (ID=2, slug="theater")
    # API принимает slug категории, а не ID
    theater_category_slug = "theater"
    logger.info(f"Используем категорию 'Спектакли' (slug: {theater_category_slug}, ID: 2)")
    
    # Получаем все события (спектакли) - только предстоящие
    logger.info("Загрузка спектаклей из API...")
    
    # Используем slug города (msk для Москвы)
    location_slug = city_slug if city_slug else "msk"
    logger.info(f"Используем location: {location_slug}")
    
    # Используем slug категории (theater для категории "Спектакли" с ID=2)
    logger.info(f"Используем категорию slug: {theater_category_slug}")
    
    # Получаем текущую дату в формате Unix timestamp
    current_timestamp = int(datetime.now(timezone.utc).timestamp())
    logger.info(f"Фильтруем события с даты: {datetime.fromtimestamp(current_timestamp).strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Запрашиваем поля: id, short_title, place, dates, location
    # expand=place,dates,location - для получения детальной информации
    # actual_since - только предстоящие события с текущей даты
    events = api.get_all_events(
        location=location_slug,
        categories=theater_category_slug,
        fields="id,short_title,place,dates,location",
        expand="place,dates,location",  # Получаем детальную информацию
        max_pages=None,  # Загружаем все страницы
        actual_since=current_timestamp  # Только предстоящие события
    )
    
    logger.info(f"Загружено {len(events)} событий")
    
    # Извлекаем информацию о спектаклях
    shows = []
    processed = 0
    debug_printed = False
    for event in events:
        # Отладочный вывод для первого события
        if not debug_printed and processed == 0:
            import json
            logger.debug(f"Структура первого события: {json.dumps(event, ensure_ascii=False, indent=2)[:1000]}")
            debug_printed = True
        
        show_info = api.extract_show_info(event)
        if show_info:
            shows.append(show_info)
        processed += 1
        if processed % 50 == 0:
            logger.info(f"Обработано {processed}/{len(events)} событий...")
    
    logger.info(f"Обработано {len(shows)} спектаклей")
    
    # Сохраняем в CSV
    if shows:
        with open(output_path, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['id', 'short_title', 'place', 'dates', 'location']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            
            writer.writeheader()
            for show in shows:
                writer.writerow(show)
        
        logger.info(f"Данные сохранены в {output_path}")
        logger.info(f"Всего записей: {len(shows)}")
    else:
        logger.warning("Нет данных для сохранения")


def main():
    """Главная функция."""
    try:
        fetch_moscow_shows()
    except Exception as e:
        logger.error(f"Ошибка при выполнении скрипта: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

