"""Модуль для работы с API KudaGo."""
import requests
import logging
from typing import List, Dict, Optional
from datetime import datetime
from datetime import timezone as tz

logger = logging.getLogger(__name__)

# Базовый URL API KudaGo
BASE_URL = "https://kudago.com/public-api/v1.4"


class KudaGoAPI:
    """Класс для работы с API KudaGo."""
    
    def __init__(self, base_url: str = BASE_URL):
        """
        Инициализация клиента API.
        
        Args:
            base_url: Базовый URL API (по умолчанию v1.4)
        """
        self.base_url = base_url
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'TheatreNotifyBot/1.0'
        })
    
    def get_cities(self) -> List[Dict]:
        """
        Получает список всех городов.
        
        Returns:
            Список словарей с информацией о городах
        """
        try:
            url = f"{self.base_url}/locations/"
            response = self.session.get(url, params={'lang': 'ru'})
            response.raise_for_status()
            data = response.json()
            # API может вернуть список напрямую или словарь с results
            if isinstance(data, list):
                return data
            return data.get('results', [])
        except Exception as e:
            logger.error(f"Ошибка при получении списка городов: {e}")
            return []
    
    def get_city_id(self, city_name: str) -> Optional[int]:
        """
        Получает ID города по названию.
        
        Args:
            city_name: Название города (например, "Москва")
        
        Returns:
            ID города или None если не найден
        """
        cities = self.get_cities()
        for city in cities:
            if city.get('name', '').lower() == city_name.lower():
                return city.get('id')
        return None
    
    def get_event_categories(self) -> List[Dict]:
        """
        Получает список категорий событий.
        
        Returns:
            Список словарей с информацией о категориях
        """
        try:
            url = f"{self.base_url}/event-categories/"
            response = self.session.get(url, params={'lang': 'ru'})
            response.raise_for_status()
            data = response.json()
            # API может вернуть список напрямую или словарь с results
            if isinstance(data, list):
                return data
            return data.get('results', [])
        except Exception as e:
            logger.error(f"Ошибка при получении категорий: {e}")
            return []
    
    def get_category_id(self, category_slug: str) -> Optional[int]:
        """
        Получает ID категории по slug.
        
        Args:
            category_slug: Slug категории (например, "theater")
        
        Returns:
            ID категории или None если не найдена
        """
        categories = self.get_event_categories()
        for category in categories:
            if category.get('slug') == category_slug:
                return category.get('id')
        return None
    
    def get_event_details(self, event_id: int, fields: Optional[str] = None, expand: Optional[str] = None) -> Optional[Dict]:
        """
        Получает детальную информацию о событии по ID.
        
        Args:
            event_id: ID события
            fields: Поля для включения в ответ
            expand: Поля для расширенной информации (place, location, dates, images)
        
        Returns:
            Словарь с детальной информацией о событии или None
        """
        try:
            url = f"{self.base_url}/events/{event_id}/"
            params = {'lang': 'ru'}
            
            if fields:
                params['fields'] = fields
            
            if expand:
                params['expand'] = expand
            
            response = self.session.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.debug(f"Ошибка при получении деталей события {event_id}: {e}")
            return None
    
    def get_events(
        self,
        location: Optional[str] = None,
        categories: Optional[str] = None,
        page_size: int = 100,
        page: int = 1,
        fields: Optional[str] = None,
        actual_since: Optional[int] = None,
        expand: Optional[str] = None
    ) -> Dict:
        """
        Получает список событий с фильтрацией.
        
        Args:
            location: Slug города (например, "msk" для Москвы)
            categories: ID категории или несколько через запятую
            page_size: Количество результатов на странице (макс 100)
            page: Номер страницы
            fields: Поля для включения в ответ (через запятую)
            actual_since: Unix timestamp начала периода (только предстоящие события)
        
        Returns:
            Словарь с результатами запроса
        """
        try:
            url = f"{self.base_url}/events/"
            params = {
                'lang': 'ru',
                'page_size': min(page_size, 100),  # Максимум 100
                'page': page
            }
            
            if location:
                params['location'] = location
            
            if categories:
                params['categories'] = str(categories)
            
            # Фильтр по дате - только предстоящие события
            if actual_since:
                params['actual_since'] = actual_since
            
            # Пробуем без fields сначала, если ошибка - уберем
            if fields:
                params['fields'] = fields
            
            # Параметр expand для получения детальной информации
            if expand:
                params['expand'] = expand
            
            logger.debug(f"Запрос к API: {url} с параметрами: {params}")
            response = self.session.get(url, params=params)
            
            # Если ошибка 400, пробуем без fields
            if response.status_code == 400 and fields:
                logger.debug("Ошибка 400, пробуем без fields")
                params.pop('fields', None)
                response = self.session.get(url, params=params)
            
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Ошибка при получении событий: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Ответ сервера: {e.response.text}")
            return {'count': 0, 'results': [], 'next': None, 'previous': None}
    
    def get_all_events(
        self,
        location: Optional[str] = None,
        categories: Optional[str] = None,
        fields: Optional[str] = None,
        max_pages: Optional[int] = None,
        actual_since: Optional[int] = None,
        expand: Optional[str] = None
    ) -> List[Dict]:
        """
        Получает все события с пагинацией.
        
        Args:
            location: Slug города
            categories: ID категории
            fields: Поля для включения
            max_pages: Максимальное количество страниц (None = все)
            actual_since: Unix timestamp начала периода (только предстоящие события)
        
        Returns:
            Список всех событий
        """
        all_events = []
        page = 1
        
        while True:
            if max_pages and page > max_pages:
                break
            
            data = self.get_events(
                location=location,
                categories=categories,
                page=page,
                fields=fields,
                actual_since=actual_since,
                expand=expand
            )
            
            events = data.get('results', [])
            if not events:
                break
            
            all_events.extend(events)
            
            # Проверяем, есть ли следующая страница
            if not data.get('next'):
                break
            
            page += 1
        
        return all_events
    
    def get_place_details(self, place_id: int) -> Optional[Dict]:
        """
        Получает детальную информацию о месте по ID.
        
        Args:
            place_id: ID места
        
        Returns:
            Словарь с информацией о месте или None
        """
        try:
            url = f"{self.base_url}/places/{place_id}/"
            # Запрашиваем title и name (на случай если используется name)
            response = self.session.get(url, params={'lang': 'ru', 'fields': 'id,title,name'})
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.debug(f"Не удалось получить детали места {place_id}: {e}")
            return None
    
    def extract_show_info(self, event: Dict) -> Optional[Dict]:
        """
        Извлекает информацию о спектакле из события.
        
        Args:
            event: Словарь с данными события
        
        Returns:
            Словарь с информацией о спектакле или None
        """
        try:
            event_id = event.get('id')
            short_title = event.get('short_title', event.get('title', ''))
            
            if not event_id:
                return None
            
            # Получаем информацию о месте (place)
            # С expand=place получаем полную информацию о месте
            # В API используется поле 'title', а не 'name'
            place = event.get('place')
            place_info = ''
            
            if place:
                if isinstance(place, dict):
                    # Если place развернут (expand), получаем title (или name как fallback)
                    place_title = place.get('title', '')
                    place_name = place.get('name', '')
                    place_id = place.get('id')
                    
                    if place_title:
                        place_info = place_title
                    elif place_name:
                        place_info = place_name
                    elif place_id:
                        # Если только ID, получаем детали через отдельный запрос
                        place_details = self.get_place_details(place_id)
                        if place_details:
                            place_info = place_details.get('title') or place_details.get('name', '')
                elif isinstance(place, int):
                    # Если только ID, получаем детали через отдельный запрос
                    place_details = self.get_place_details(place)
                    if place_details:
                        place_info = place_details.get('title') or place_details.get('name', '')
            
            # Если place_info все еще пустое, но есть place_id, пробуем получить через детали события
            if not place_info:
                place_id = None
                if isinstance(place, dict):
                    place_id = place.get('id')
                elif isinstance(place, int):
                    place_id = place
                
                if place_id:
                    # Получаем детали места через отдельный запрос
                    place_details = self.get_place_details(place_id)
                    if place_details:
                        place_info = place_details.get('title') or place_details.get('name', '')
            
            # Получаем даты проведения (dates)
            # Фильтруем только актуальные будущие даты
            dates_info = ''
            dates = event.get('dates', [])
            daterange = event.get('daterange', {})
            
            # Получаем текущую дату для фильтрации
            current_date = datetime.now(tz.utc).date()
            
            # Сначала проверяем daterange (если есть)
            if daterange and isinstance(daterange, dict):
                start_date_str = daterange.get('start_date', '')
                start_time = daterange.get('start_time', '')
                end_date_str = daterange.get('end_date', '')
                end_time = daterange.get('end_time', '')
                
                if start_date_str:
                    try:
                        # Парсим дату и проверяем, что она в будущем
                        start_date_obj = datetime.strptime(start_date_str, '%Y-%m-%d').date()
                        if start_date_obj >= current_date:
                            date_str = start_date_str
                            if start_time:
                                date_str += f" {start_time}"
                            if end_date_str and end_date_str != start_date_str:
                                date_str += f" - {end_date_str}"
                                if end_time:
                                    date_str += f" {end_time}"
                            dates_info = date_str
                    except ValueError:
                        pass
            
            # Если dates - это список словарей
            elif dates and isinstance(dates, list):
                date_strings = []
                for date_item in dates:
                    if isinstance(date_item, dict):
                        # Приоритет: start_date/end_date (строковый формат)
                        start_date_str = date_item.get('start_date', '')
                        start_time = date_item.get('start_time', '')
                        end_date_str = date_item.get('end_date', '')
                        end_time = date_item.get('end_time', '')
                        
                        if start_date_str:
                            try:
                                # Парсим дату и проверяем, что она в будущем
                                start_date_obj = datetime.strptime(start_date_str, '%Y-%m-%d').date()
                                if start_date_obj >= current_date:
                                    date_str = start_date_str
                                    if start_time:
                                        date_str += f" {start_time}"
                                    if end_date_str and end_date_str != start_date_str:
                                        date_str += f" - {end_date_str}"
                                        if end_time:
                                            date_str += f" {end_time}"
                                    date_strings.append(date_str)
                            except ValueError:
                                # Если не удалось распарсить дату, пробуем timestamp
                                pass
                        
                        # Fallback: Unix timestamp (start/end) - только если нет start_date
                        if not start_date_str:
                            start_ts = date_item.get('start')
                            end_ts = date_item.get('end')
                            
                            if start_ts:
                                try:
                                    # Конвертируем Unix timestamp в дату
                                    if 0 < start_ts < 2147483647:  # Валидный диапазон Unix timestamp
                                        start_dt = datetime.fromtimestamp(start_ts, tz=tz.utc)
                                        # Проверяем, что дата в будущем
                                        if start_dt.date() >= current_date:
                                            date_str = start_dt.strftime('%Y-%m-%d %H:%M:%S')
                                            
                                            if end_ts and end_ts != start_ts and 0 < end_ts < 2147483647:
                                                end_dt = datetime.fromtimestamp(end_ts, tz=tz.utc)
                                                date_str += f" - {end_dt.strftime('%Y-%m-%d %H:%M:%S')}"
                                            
                                            date_strings.append(date_str)
                                except (ValueError, OSError) as e:
                                    logger.debug(f"Ошибка при конвертации timestamp {start_ts}: {e}")
                                    continue
                
                dates_info = '; '.join(date_strings) if date_strings else ''
            
            # Получаем город из location (опционально)
            location_info = ''
            location = event.get('location', {})
            if isinstance(location, dict):
                location_info = location.get('name', '')
                if not location_info:
                    location_info = location.get('slug', '')
            elif isinstance(location, str):
                location_info = location
            
            return {
                'id': event_id,
                'short_title': short_title,
                'place': place_info,
                'dates': dates_info,
                'location': location_info
            }
        except Exception as e:
            logger.error(f"Ошибка при извлечении информации о спектакле: {e}")
            logger.debug(f"Структура события: {event}")
            return None
    
    def search_events(self, query: str, location: Optional[str] = None, categories: Optional[str] = None, limit: int = 10) -> List[Dict]:
        """
        Ищет события по текстовому запросу.
        
        Args:
            query: Текст для поиска
            location: Slug города (опционально)
            categories: ID категории (опционально, например "theater")
            limit: Максимальное количество результатов
        
        Returns:
            Список найденных событий
        """
        try:
            # Используем поиск через API
            url = f"{self.base_url}/events/"
            # Увеличиваем page_size для лучшего поиска (получаем больше результатов для фильтрации)
            params = {
                'lang': 'ru',
                'page_size': min(max(limit * 3, 50), 100),  # Получаем больше для фильтрации
                'text_format': 'text',
                'fields': 'id,title,short_title,place,location,dates',
                'expand': 'place,location'
            }
            
            if location:
                params['location'] = location
            
            if categories:
                params['categories'] = str(categories)
            
            # Поиск по тексту - получаем все события и фильтруем на клиенте
            # KudaGo API не всегда поддерживает текстовый поиск напрямую
            
            # Получаем текущую дату для фильтрации
            from datetime import timezone
            current_timestamp = int(datetime.now(timezone.utc).timestamp())
            params['actual_since'] = current_timestamp
            
            response = self.session.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            
            events = data.get('results', [])
            
            # Фильтруем по тексту запроса (ищем в title и short_title)
            if query:
                query_lower = query.lower()
                filtered_events = []
                for event in events:
                    title = (event.get('title') or '').lower()
                    short_title = (event.get('short_title') or '').lower()
                    if query_lower in title or query_lower in short_title:
                        filtered_events.append(event)
                events = filtered_events
            
            return events[:limit]
        except Exception as e:
            logger.error(f"Ошибка при поиске событий: {e}")
            return []
    
    def get_event_schedule(self, event_id: int) -> List[Dict]:
        """
        Получает расписание (даты и время) для события.
        
        Args:
            event_id: ID события
        
        Returns:
            Список словарей с датами и временем показа
        """
        try:
            # Получаем детальную информацию о событии с расписанием
            event = self.get_event_details(
                event_id,
                fields='id,title,dates',
                expand='dates'
            )
            
            if not event:
                return []
            
            dates = event.get('dates', [])
            if not dates:
                return []
            
            # Фильтруем только будущие даты и форматируем
            current_date = datetime.now(tz.utc).date()
            schedule = []
            
            for date_item in dates:
                if isinstance(date_item, dict):
                    start_date_str = date_item.get('start_date', '')
                    start_time = date_item.get('start_time', '')
                    start_ts = date_item.get('start')
                    
                    # Проверяем, что дата в будущем
                    is_future = False
                    datetime_obj = None
                    
                    if start_date_str:
                        try:
                            date_obj = datetime.strptime(start_date_str, '%Y-%m-%d').date()
                            if date_obj >= current_date:
                                is_future = True
                                # Формируем datetime объект
                                if start_time:
                                    datetime_str = f"{start_date_str} {start_time}"
                                    datetime_obj = datetime.strptime(datetime_str, '%Y-%m-%d %H:%M:%S')
                                else:
                                    datetime_obj = datetime.strptime(start_date_str, '%Y-%m-%d')
                        except ValueError:
                            pass
                    elif start_ts:
                        try:
                            if 0 < start_ts < 2147483647:
                                dt = datetime.fromtimestamp(start_ts, tz=tz.utc)
                                if dt.date() >= current_date:
                                    is_future = True
                                    datetime_obj = dt
                        except (ValueError, OSError):
                            pass
                    
                    if is_future and datetime_obj:
                        # Формируем читаемую метку
                        if start_time:
                            label = datetime_obj.strftime('%d %B %Y %H:%M')
                        else:
                            label = datetime_obj.strftime('%d %B %Y')
                        
                        schedule.append({
                            'datetime': datetime_obj,
                            'label': label,
                            'start_date': start_date_str or datetime_obj.strftime('%Y-%m-%d'),
                            'start_time': start_time or datetime_obj.strftime('%H:%M:%S'),
                            'raw': date_item
                        })
            
            # Сортируем по дате
            schedule.sort(key=lambda x: x['datetime'])
            return schedule
        except Exception as e:
            logger.error(f"Ошибка при получении расписания для события {event_id}: {e}")
            return []

