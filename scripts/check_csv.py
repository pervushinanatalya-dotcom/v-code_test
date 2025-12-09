"""Проверка содержимого CSV файла."""
import csv
from pathlib import Path

csv_path = Path(__file__).parent.parent / "data" / "shows_catalog.csv"

with open(csv_path, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    rows = list(reader)
    
    print(f"Всего записей: {len(rows)}")
    print(f"Колонки: {reader.fieldnames}\n")
    
    # Находим записи с заполненными полями
    filled = [r for r in rows if r.get('place') or r.get('dates') or r.get('location')]
    print(f"Записей с заполненными полями: {len(filled)}\n")
    
    # Показываем первые 5 записей
    print("Первые 5 записей:")
    for i, row in enumerate(rows[:5], 1):
        print(f"\n{i}. ID: {row['id']}")
        print(f"   Short title: {row['short_title'][:60]}")
        print(f"   Place: {row['place'][:60] if row['place'] else '(пусто)'}")
        print(f"   Dates: {row['dates'][:60] if row['dates'] else '(пусто)'}")
        print(f"   Location: {row['location'] if row['location'] else '(пусто)'}")
    
    # Показываем записи с заполненными полями
    if filled:
        print(f"\n\nПримеры записей с заполненными полями (первые 3):")
        for i, row in enumerate(filled[:3], 1):
            print(f"\n{i}. ID: {row['id']}")
            print(f"   Short title: {row['short_title'][:60]}")
            print(f"   Place: {row['place'][:60]}")
            print(f"   Dates: {row['dates'][:60]}")
            print(f"   Location: {row['location']}")

