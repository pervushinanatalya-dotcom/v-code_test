# Скрипты для работы с API KudaGo

## fetch_shows.py

Скрипт для выгрузки данных о спектаклях из API KudaGo и сохранения в CSV файл.

### Использование

```bash
# Из корневой директории проекта
python scripts/fetch_shows.py
```

Или:

```bash
# Из директории scripts
cd scripts
python fetch_shows.py
```

### Что делает скрипт

1. Подключается к API KudaGo
2. Находит город Москва и категорию "театр"
3. Загружает все спектакли из Москвы
4. Извлекает информацию: id, title, theatre, city
5. Сохраняет данные в `data/shows_catalog.csv`

### Формат выходного файла

CSV файл `data/shows_catalog.csv` содержит следующие колонки:

- `id` - ID события из API KudaGo
- `title` - Название спектакля
- `theatre` - Название театра
- `city` - Город (Москва)

### Пример использования в коде

```python
from scripts.fetch_shows import fetch_moscow_shows

# Выгрузить спектакли
fetch_moscow_shows()

# Или указать свой путь
fetch_moscow_shows("custom/path/shows.csv")
```

### Интеграция в Telegram-бот

Данные из CSV можно использовать для:
- Поиска спектаклей по названию
- Предложения спектаклей пользователям
- Автозаполнения при добавлении спектакля

Пример интеграции:

```python
import csv
from pathlib import Path

def load_shows_catalog():
    """Загружает каталог спектаклей из CSV."""
    catalog = []
    csv_path = Path("data/shows_catalog.csv")
    
    if csv_path.exists():
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            catalog = list(reader)
    
    return catalog

def search_shows(query: str, catalog: list):
    """Ищет спектакли по запросу."""
    query_lower = query.lower()
    return [
        show for show in catalog
        if query_lower in show['title'].lower() or 
           query_lower in show['theatre'].lower()
    ]
```

