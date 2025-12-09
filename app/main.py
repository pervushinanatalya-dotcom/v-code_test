"""Главный модуль Telegram-бота для управления спектаклями."""
import logging
import os
import subprocess
import csv
import zoneinfo
from pathlib import Path
from typing import Optional
from datetime import datetime, timedelta, timezone

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

import dateparser
from apscheduler.schedulers.background import BackgroundScheduler

from app.config import BOT_TOKEN, EXPORT_DIR, PROXY_URL
from app.db import (
    init_db,
    add_user,
    add_show,
    get_user_shows,
    get_show_by_id,
    delete_show,
    update_show,
    get_pending_notifications,
    mark_notification_sent,
    get_theatres_stats,
)
from app.export_utils import generate_txt

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Отключаем детальное логирование httpx и telegram (скрывает токен из логов)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)

# Часовой пояс пользователя (Москва UTC+3)
MOSCOW_TZ = zoneinfo.ZoneInfo("Europe/Moscow")

# Константы для напоминаний
REMINDER_1_DAY = "1 день"
REMINDER_6_HOURS = "6 часов"
REMINDER_3_HOURS = "3 часа"
REMINDER_1_HOUR = "1 час"

# Состояния для ConversationHandler
SEARCH_MODE, SEARCH_QUERY, MANUAL_SHOW_NAME, MANUAL_THEATRE, MANUAL_SHOW_DATE, SELECT_REMINDER = range(6)
EDIT_SHOW_NAME, EDIT_SHOW_THEATRE, EDIT_SHOW_DATE, EDIT_REMINDER = range(6, 10)

# Путь к CSV с каталогом спектаклей
CSV_PATH = Path("data/shows_catalog.csv")


def parse_user_datetime(date_text: str) -> Optional[datetime]:
    """
    Парсит строку даты/времени, введенную пользователем, как московское время
    и возвращает datetime объект в UTC.
    """
    parsed_date = dateparser.parse(
        date_text,
        languages=['ru', 'en'],
        settings={
            'TIMEZONE': 'Europe/Moscow',
            'RETURN_AS_TIMEZONE_AWARE': True,  # Важно: возвращаем с таймзоной
            'DATE_ORDER': 'DMY',
            'PREFER_DAY_OF_MONTH': 'first',
        }
    )
    if parsed_date:
        # Конвертируем в UTC
        return parsed_date.astimezone(timezone.utc)
    return None


def format_datetime_for_user(dt_utc: datetime) -> str:
    """
    Форматирует datetime объект из UTC в московское время для отображения пользователю.
    """
    if dt_utc.tzinfo is None:
        # Если datetime наивный, предполагаем, что это UTC (как хранится в БД)
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    
    dt_moscow = dt_utc.astimezone(MOSCOW_TZ)
    
    # Проверяем, есть ли время (не равно 00:00:00)
    if dt_moscow.hour == 0 and dt_moscow.minute == 0 and dt_moscow.second == 0:
        return dt_moscow.strftime('%d.%m.%Y')
    return dt_moscow.strftime('%d.%m.%Y %H:%M')


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start."""
    user = update.effective_user
    add_user(user.id, user.username, user.first_name)
    
    # Проверяем наличие CSV файла
    csv_date_text = "данные отсутствуют"
    if CSV_PATH.exists():
        csv_mtime = CSV_PATH.stat().st_mtime
        csv_date = datetime.fromtimestamp(csv_mtime, tz=MOSCOW_TZ)
        csv_date_text = csv_date.strftime('%d.%m.%Y %H:%M')
    
    keyboard = [
        [InlineKeyboardButton("✅ Использовать текущие данные", callback_data="use_current_csv")],
        [InlineKeyboardButton("🔄 Обновить данные (до 5 минут)", callback_data="update_csv")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"👋 Привет, {user.first_name}!\n\n"
        f"Я помогу вам сохранять и управлять информацией о спектаклях.\n\n"
        f"📅 Последнее обновление каталога: {csv_date_text}\n\n"
        f"Выберите действие:",
        reply_markup=reply_markup
    )


async def handle_csv_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик выбора: использовать текущий CSV или обновить."""
    query = update.callback_query
    await query.answer()
    
    if query.data == "use_current_csv":
        await query.edit_message_text(
            "✅ Используется текущий каталог спектаклей.\n\n"
            "Используйте /add_show для добавления спектакля."
        )
    
    elif query.data == "update_csv":
        await query.edit_message_text(
            "⏳ Начинаю обновление данных из KudaGo API...\n"
            "Это может занять до 5 минут. Пожалуйста, подождите."
        )
        
        try:
            # Запускаем скрипт обновления в фоне
            script_path = Path("scripts/fetch_shows.py")
            if not script_path.exists():
                await query.edit_message_text(
                    "❌ Скрипт обновления не найден. Используйте текущие данные."
                )
                return
            
            # Запускаем скрипт синхронно (в реальном приложении лучше использовать async)
            result = subprocess.run(
                ["python", "-m", "scripts.fetch_shows"],
                capture_output=True,
                text=True,
                timeout=600  # 10 минут максимум
            )
            
            if result.returncode == 0:
                # Получаем новую дату обновления
                csv_mtime = CSV_PATH.stat().st_mtime
                csv_date = datetime.fromtimestamp(csv_mtime, tz=MOSCOW_TZ)
                csv_date_text = csv_date.strftime('%d.%m.%Y %H:%M')
                
                await query.edit_message_text(
                    f"✅ Данные успешно обновлены!\n"
                    f"📅 Дата обновления: {csv_date_text}\n\n"
                    f"Используйте /add_show для добавления спектакля."
                )
            else:
                logger.error(f"Ошибка при обновлении CSV: {result.stderr}")
                await query.edit_message_text(
                    "❌ Не удалось обновить данные. Используйте текущие данные.\n\n"
                    f"Ошибка: {result.stderr[:200]}"
                )
        
        except subprocess.TimeoutExpired:
            await query.edit_message_text(
                "❌ Превышено время ожидания обновления. Используйте текущие данные."
            )
        except Exception as e:
            logger.error(f"Ошибка при обновлении CSV: {e}")
            await query.edit_message_text(
                f"❌ Ошибка при обновлении данных: {e}\n\n"
                "Используйте текущие данные."
            )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /help."""
    help_text = (
        "📋 *Доступные команды:*\n\n"
        "/start - Начать работу с ботом\n"
        "/add_show - Добавить спектакль\n"
        "/my_shows - Показать мои спектакли\n"
        "/export - Экспортировать спектакли\n"
        "/theatres - Список театров в базе\n"
        "/cancel - Отменить текущее действие\n"
        "/help - Показать эту справку\n\n"
        "При добавлении спектакля вы можете:\n"
        "• Искать по названию спектакля\n"
        "• Искать по названию театра\n"
        "• Ввести данные вручную\n\n"
        "Для каждого спектакля можно установить напоминание!"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')


async def cmd_add_show(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало процесса добавления спектакля: выбор режима поиска."""
    keyboard = [
        [InlineKeyboardButton("🔍 Поиск по названию спектакля", callback_data="search_mode:title")],
        [InlineKeyboardButton("🏛️ Поиск по названию театра", callback_data="search_mode:theatre")],
        [InlineKeyboardButton("✍️ Ручной ввод", callback_data="search_mode:manual")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "Выберите способ добавления спектакля:",
        reply_markup=reply_markup
    )
    return SEARCH_MODE


async def handle_search_mode_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик выбора режима поиска."""
    query = update.callback_query
    await query.answer()
    
    mode = query.data.split(':')[1]
    context.user_data['search_mode'] = mode
    
    if mode == 'manual':
        await query.edit_message_text("Введите название спектакля:")
        return MANUAL_SHOW_NAME
    elif mode == 'title':
        await query.edit_message_text("Введите название спектакля для поиска:")
        return SEARCH_QUERY
    elif mode == 'theatre':
        await query.edit_message_text("Введите название театра для поиска:")
        return SEARCH_QUERY


def search_in_csv(query: str, mode: str = "title", limit: int = 10) -> list:
    """
    Ищет спектакли в CSV файле по названию спектакля или театра.
    
    Args:
        query: Поисковый запрос
        mode: Режим поиска ("title" или "theatre")
        limit: Максимальное количество результатов (None = без ограничения)
    
    Returns:
        Список найденных записей в формате dict
    """
    if not CSV_PATH.exists():
        return []
    
    results = []
    query_lower = query.lower()
    
    try:
        with open(CSV_PATH, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if mode == "title":
                    field_value = row.get('short_title', '').lower()
                elif mode == "theatre":
                    field_value = row.get('place', '').lower()
                else:
                    continue
                
                if query_lower in field_value:
                    results.append(row)
                    if limit and len(results) >= limit:
                        break
    except Exception as e:
        logger.error(f"Ошибка при чтении CSV: {e}")
    
    return results


async def send_csv_results_page(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    results: list,
    page: int = 0,
    is_edit: bool = False
):
    """
    Отправляет или редактирует сообщение со страницей результатов поиска (пагинация по 10).
    
    Args:
        update: Update объект
        context: Context объект
        results: Список результатов
        page: Номер страницы (0-based)
        is_edit: True если нужно отредактировать существующее сообщение
    """
    page_size = 10
    start_idx = page * page_size
    end_idx = start_idx + page_size
    current_results = results[start_idx:end_idx]
    total_results = len(results)
    
    # Формируем кнопки с результатами
    keyboard = []
    for idx, show in enumerate(current_results, start=start_idx + 1):
        show_name = show.get('short_title', 'Без названия')
        place = show.get('place', 'Не указано')
        button_text = f"{idx}. {show_name} ({place})"
        callback_data = f"csv_show:{show.get('id')}:{idx-1}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
    
    # Добавляем кнопку "Другой спектакль (ручной ввод)"
    keyboard.append([InlineKeyboardButton("✍️ Другой спектакль (ручной ввод)", callback_data="csv_manual")])
    
    # Кнопки навигации
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"csv_prev:{page}"))
    if end_idx < total_results:
        nav_buttons.append(InlineKeyboardButton("Показать еще ➡️", callback_data=f"csv_more:{page}"))
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = f"Найдено {total_results} спектаклей. Показаны {start_idx + 1}-{min(end_idx, total_results)}:\n\n" \
           f"Выберите спектакль:"
    
    if is_edit:
        query = update.callback_query
        try:
            await query.edit_message_text(text, reply_markup=reply_markup)
        except Exception as e:
            # Если не удалось отредактировать (например, сообщение устарело), отправляем новое
            logger.warning(f"Не удалось отредактировать сообщение: {e}")
            await query.message.reply_text(text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup)


async def process_search_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик поискового запроса пользователя."""
    search_query = update.message.text
    search_mode = context.user_data.get('search_mode', 'title')
    
    # Сохраняем запрос для возможного ручного ввода
    context.user_data['last_search_query'] = search_query
    
    # Ищем в CSV (получаем все результаты для пагинации)
    results = search_in_csv(search_query, mode=search_mode, limit=None)
    
    if not results:
        # Нет результатов - переходим к ручному вводу
        context.user_data['manual_show_name'] = search_query
        await update.message.reply_text(
            f"😔 Ничего не найдено по запросу \"{search_query}\".\n\n"
            f"Продолжаем ручной ввод. Название спектакля: {search_query}\n\n"
            f"Теперь введите название театра:"
        )
        return MANUAL_THEATRE
    
    # Сохраняем результаты для пагинации
    context.user_data['search_results'] = results
    context.user_data['search_page'] = 0
    
    # Отправляем первую страницу результатов
    await send_csv_results_page(update, context, results, page=0, is_edit=False)
    return SEARCH_QUERY


async def handle_csv_more(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопки 'Показать еще'."""
    query = update.callback_query
    await query.answer()
    
    current_page = int(query.data.split(':')[1])
    next_page = current_page + 1
    
    results = context.user_data.get('search_results', [])
    context.user_data['search_page'] = next_page
    
    await send_csv_results_page(update, context, results, page=next_page, is_edit=True)


async def handle_csv_prev(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопки 'Назад'."""
    query = update.callback_query
    await query.answer()
    
    current_page = int(query.data.split(':')[1])
    prev_page = current_page - 1
    
    if prev_page < 0:
        prev_page = 0
    
    results = context.user_data.get('search_results', [])
    context.user_data['search_page'] = prev_page
    
    await send_csv_results_page(update, context, results, page=prev_page, is_edit=True)


async def handle_csv_manual_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопки 'Другой спектакль (ручной ввод)'."""
    query = update.callback_query
    await query.answer()
    
    # Берем последний поисковый запрос как название спектакля
    last_query = context.user_data.get('last_search_query', '')
    context.user_data['manual_show_name'] = last_query
    
    if last_query:
        await query.edit_message_text(
            f"Название спектакля: {last_query}\n\n"
            f"Теперь введите название театра:"
        )
    else:
        await query.edit_message_text("Введите название спектакля:")
        return MANUAL_SHOW_NAME
    
    return MANUAL_THEATRE


async def handle_csv_show_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик выбора спектакля из CSV результатов."""
    query = update.callback_query
    await query.answer()
    
    # Парсим callback data
    data_parts = query.data.split(':')
    show_id = data_parts[1]
    
    # Ищем спектакль в результатах
    results = context.user_data.get('search_results', [])
    selected_show = None
    for show in results:
        if show.get('id') == show_id:
            selected_show = show
            break
    
    if not selected_show:
        await query.edit_message_text("❌ Ошибка: спектакль не найден.")
        return ConversationHandler.END
    
    # Сохраняем данные спектакля
    context.user_data['csv_show_id'] = show_id
    context.user_data['csv_show_name'] = selected_show.get('short_title', 'Без названия')
    context.user_data['csv_place'] = selected_show.get('place', 'Не указано')
    
    # Парсим даты (разделены точкой с запятой)
    dates_str = selected_show.get('dates', '')
    schedule = []
    
    if dates_str:
        date_parts = [d.strip() for d in dates_str.split(';') if d.strip()]
        for date_str in date_parts:
            # Парсим дату в формате YYYY-MM-DD или YYYY-MM-DD HH:MM:SS
            try:
                if ' ' in date_str:
                    # Дата + время: парсим как московское время, конвертируем в UTC
                    datetime_obj = datetime.strptime(date_str.split(' - ')[0].strip(), '%Y-%m-%d %H:%M:%S')
                    datetime_obj_moscow = MOSCOW_TZ.localize(datetime_obj)
                    datetime_obj_utc = datetime_obj_moscow.astimezone(timezone.utc)
                else:
                    # Только дата: парсим как московское время (00:00), конвертируем в UTC
                    datetime_obj = datetime.strptime(date_str.split(' - ')[0].strip(), '%Y-%m-%d')
                    datetime_obj_moscow = MOSCOW_TZ.localize(datetime_obj)
                    datetime_obj_utc = datetime_obj_moscow.astimezone(timezone.utc)
                
                schedule.append({
                    'datetime': datetime_obj_utc,
                    'label': date_str
                })
            except Exception as e:
                logger.error(f"Ошибка при парсинге даты '{date_str}': {e}")
    
    if not schedule:
        # Нет дат - предлагаем ввести вручную
        await query.edit_message_text(
            f"Спектакль: {context.user_data['csv_show_name']}\n"
            f"Театр: {context.user_data['csv_place']}\n\n"
            f"📅 Даты не найдены. Введите дату спектакля вручную (например, 25.12.2025 или 25.12.2025 19:00):"
        )
        context.user_data['waiting_csv_manual_date'] = True
        return MANUAL_SHOW_DATE
    
    if len(schedule) == 1:
        # Только одна дата - предлагаем подтвердить или ввести другую
        context.user_data['csv_schedule'] = schedule
        formatted_datetime = format_datetime_for_user(schedule[0]['datetime'])
        
        keyboard = [
            [InlineKeyboardButton("✅ Использовать эту дату", callback_data="csv_date_confirm")],
            [InlineKeyboardButton("✍️ Ввести другую дату", callback_data="csv_date_manual")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"Спектакль: {context.user_data['csv_show_name']}\n"
            f"Театр: {context.user_data['csv_place']}\n\n"
            f"📅 Найдена одна дата: {formatted_datetime}\n\n"
            f"Использовать эту дату или ввести другую?",
            reply_markup=reply_markup
        )
        return MANUAL_SHOW_DATE
    
    # Несколько дат - предлагаем выбрать
    context.user_data['csv_schedule'] = schedule
    
    keyboard = []
    for idx, date_item in enumerate(schedule):
        formatted_datetime = format_datetime_for_user(date_item['datetime'])
        keyboard.append([InlineKeyboardButton(
            formatted_datetime,
            callback_data=f"csv_date:{idx}"
        )])
    
    # Добавляем опцию ручного ввода
    keyboard.append([InlineKeyboardButton("✍️ Ввести другую дату", callback_data="csv_date_manual")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"Спектакль: {context.user_data['csv_show_name']}\n"
        f"Театр: {context.user_data['csv_place']}\n\n"
        f"Выберите дату:",
        reply_markup=reply_markup
    )
    return MANUAL_SHOW_DATE


async def handle_csv_date_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик подтверждения единственной даты из CSV."""
    query = update.callback_query
    await query.answer()
    
    schedule = context.user_data.get('csv_schedule', [])
    if not schedule:
        await query.edit_message_text("❌ Ошибка: даты не найдены.")
        return ConversationHandler.END
    
    selected_date = schedule[0]
    datetime_obj = selected_date['datetime']
    
    # Сохраняем спектакль в БД
    user_id = query.from_user.id
    show_name = context.user_data.get('csv_show_name', '')
    theatre = context.user_data.get('csv_place', '')
    external_id = int(context.user_data.get('csv_show_id', 0))
    
    datetime_str = datetime_obj.strftime('%Y-%m-%d %H:%M:%S')
    show_date_only = datetime_obj.strftime('%Y-%m-%d')
    
    show_id = add_show(
        user_id=user_id,
        theatre=theatre,
        show_name=show_name,
        show_date=show_date_only,
        source='csv',
        external_id=external_id,
        datetime_str=datetime_str
    )
    
    context.user_data['current_show_id'] = show_id
    context.user_data['show_datetime'] = datetime_obj
    
    formatted_datetime = format_datetime_for_user(datetime_obj)
    
    keyboard = [
        [InlineKeyboardButton(f"⏰ {REMINDER_1_DAY} до события", callback_data=f"reminder:{REMINDER_1_DAY}")],
        [InlineKeyboardButton(f"⏰ {REMINDER_6_HOURS} до события", callback_data=f"reminder:{REMINDER_6_HOURS}")],
        [InlineKeyboardButton(f"⏰ {REMINDER_3_HOURS} до события", callback_data=f"reminder:{REMINDER_3_HOURS}")],
        [InlineKeyboardButton(f"⏰ {REMINDER_1_HOUR} до события", callback_data=f"reminder:{REMINDER_1_HOUR}")],
        [InlineKeyboardButton("🚫 Без напоминания", callback_data="reminder:none")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"✅ Спектакль добавлен!\n\n"
        f"📌 {show_name}\n"
        f"🏛️ {theatre}\n"
        f"📅 {formatted_datetime}\n\n"
        f"Когда напомнить о событии?",
        reply_markup=reply_markup
    )
    
    return SELECT_REMINDER


async def handle_csv_date_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопки 'Ввести другую дату'."""
    query = update.callback_query
    await query.answer()
    
    context.user_data['waiting_csv_single_manual_date'] = True
    
    await query.edit_message_text(
        f"Спектакль: {context.user_data.get('csv_show_name', '')}\n"
        f"Театр: {context.user_data.get('csv_place', '')}\n\n"
        f"Введите дату спектакля (например, 25.12.2025 или 25.12.2025 19:00):"
    )
    return MANUAL_SHOW_DATE


async def handle_csv_date_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик выбора даты из расписания CSV."""
    query = update.callback_query
    await query.answer()
    
    # Парсим callback data
    date_idx = int(query.data.split(':')[1])
    
    schedule = context.user_data.get('csv_schedule', [])
    if date_idx >= len(schedule):
        await query.edit_message_text("❌ Ошибка: дата не найдена.")
        return ConversationHandler.END
    
    selected_date = schedule[date_idx]
    datetime_obj = selected_date['datetime']
    
    # Сохраняем спектакль в БД
    user_id = query.from_user.id
    show_name = context.user_data.get('csv_show_name', '')
    theatre = context.user_data.get('csv_place', '')
    external_id = int(context.user_data.get('csv_show_id', 0))
    
    datetime_str = datetime_obj.strftime('%Y-%m-%d %H:%M:%S')
    show_date_only = datetime_obj.strftime('%Y-%m-%d')
    
    show_id = add_show(
        user_id=user_id,
        theatre=theatre,
        show_name=show_name,
        show_date=show_date_only,
        source='csv',
        external_id=external_id,
        datetime_str=datetime_str
    )
    
    context.user_data['current_show_id'] = show_id
    context.user_data['show_datetime'] = datetime_obj
    
    formatted_datetime = format_datetime_for_user(datetime_obj)
    
    keyboard = [
        [InlineKeyboardButton(f"⏰ {REMINDER_1_DAY} до события", callback_data=f"reminder:{REMINDER_1_DAY}")],
        [InlineKeyboardButton(f"⏰ {REMINDER_6_HOURS} до события", callback_data=f"reminder:{REMINDER_6_HOURS}")],
        [InlineKeyboardButton(f"⏰ {REMINDER_3_HOURS} до события", callback_data=f"reminder:{REMINDER_3_HOURS}")],
        [InlineKeyboardButton(f"⏰ {REMINDER_1_HOUR} до события", callback_data=f"reminder:{REMINDER_1_HOUR}")],
        [InlineKeyboardButton("🚫 Без напоминания", callback_data="reminder:none")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"✅ Спектакль добавлен!\n\n"
        f"📌 {show_name}\n"
        f"🏛️ {theatre}\n"
        f"📅 {formatted_datetime}\n\n"
        f"Когда напомнить о событии?",
        reply_markup=reply_markup
    )
    
    return SELECT_REMINDER


async def process_manual_show_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ввода названия спектакля (ручной ввод)."""
    show_name = update.message.text
    context.user_data['manual_show_name'] = show_name
    
    await update.message.reply_text(f"Название спектакля: {show_name}\n\nТеперь введите название театра:")
    return MANUAL_THEATRE


async def process_manual_theatre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ввода названия театра (ручной ввод)."""
    theatre = update.message.text
    context.user_data['manual_theatre'] = theatre
    
    show_name = context.user_data.get('manual_show_name', '')
    await update.message.reply_text(
        f"Спектакль: {show_name}\n"
        f"Театр: {theatre}\n\n"
        f"Теперь введите дату спектакля (например, 25.12.2025 или 25.12.2025 19:00):"
    )
    return MANUAL_SHOW_DATE


async def process_manual_show_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ввода даты спектакля (ручной ввод)."""
    date_text = update.message.text
    
    # Парсим дату как московское время
    datetime_obj_utc = parse_user_datetime(date_text)
    
    if not datetime_obj_utc:
        await update.message.reply_text(
            "❌ Не удалось распознать дату. Пожалуйста, введите дату в формате ДД.ММ.ГГГГ или ДД.ММ.ГГГГ ЧЧ:ММ\n"
            "Например: 25.12.2025 или 25.12.2025 19:00"
        )
        return MANUAL_SHOW_DATE
    
    # Проверяем, что дата в будущем
    now_utc = datetime.now(timezone.utc)
    if datetime_obj_utc <= now_utc:
        await update.message.reply_text(
            "❌ Дата должна быть в будущем. Пожалуйста, введите дату снова:"
        )
        return MANUAL_SHOW_DATE
    
    # Сохраняем спектакль в БД
    user_id = update.effective_user.id
    show_name = context.user_data.get('manual_show_name', '')
    theatre = context.user_data.get('manual_theatre', '')
    
    # Если это ручной ввод после выбора CSV спектакля
    if context.user_data.get('waiting_csv_manual_date') or context.user_data.get('waiting_csv_single_manual_date'):
        show_name = context.user_data.get('csv_show_name', show_name)
        theatre = context.user_data.get('csv_place', theatre)
        external_id = int(context.user_data.get('csv_show_id', 0))
        source = 'csv'
    else:
        external_id = None
        source = 'manual'
    
    datetime_str = datetime_obj_utc.strftime('%Y-%m-%d %H:%M:%S')
    show_date_only = datetime_obj_utc.strftime('%Y-%m-%d')
    
    show_id = add_show(
        user_id=user_id,
        theatre=theatre,
        show_name=show_name,
        show_date=show_date_only,
        source=source,
        external_id=external_id,
        datetime_str=datetime_str
    )
    
    context.user_data['current_show_id'] = show_id
    context.user_data['show_datetime'] = datetime_obj_utc
    
    formatted_datetime = format_datetime_for_user(datetime_obj_utc)
    
    keyboard = [
        [InlineKeyboardButton(f"⏰ {REMINDER_1_DAY} до события", callback_data=f"reminder:{REMINDER_1_DAY}")],
        [InlineKeyboardButton(f"⏰ {REMINDER_6_HOURS} до события", callback_data=f"reminder:{REMINDER_6_HOURS}")],
        [InlineKeyboardButton(f"⏰ {REMINDER_3_HOURS} до события", callback_data=f"reminder:{REMINDER_3_HOURS}")],
        [InlineKeyboardButton(f"⏰ {REMINDER_1_HOUR} до события", callback_data=f"reminder:{REMINDER_1_HOUR}")],
        [InlineKeyboardButton("🚫 Без напоминания", callback_data="reminder:none")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"✅ Спектакль добавлен!\n\n"
        f"📌 {show_name}\n"
        f"🏛️ {theatre}\n"
        f"📅 {formatted_datetime}\n\n"
        f"Когда напомнить о событии?",
        reply_markup=reply_markup
    )
    
    return SELECT_REMINDER


async def handle_reminder_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик выбора времени напоминания."""
    query = update.callback_query
    await query.answer()
    
    reminder_type = query.data.split(':')[1]
    
    show_id = context.user_data.get('current_show_id')
    show_datetime = context.user_data.get('show_datetime')
    
    if reminder_type == "none":
        await query.edit_message_text(
            f"{query.message.text}\n\n"
            f"✅ Спектакль сохранен без напоминания."
        )
        # Очищаем user_data
        context.user_data.clear()
        return ConversationHandler.END
    
    # Вычисляем время напоминания
    if reminder_type == REMINDER_1_DAY:
        reminder_delta = timedelta(days=1)
    elif reminder_type == REMINDER_6_HOURS:
        reminder_delta = timedelta(hours=6)
    elif reminder_type == REMINDER_3_HOURS:
        reminder_delta = timedelta(hours=3)
    elif reminder_type == REMINDER_1_HOUR:
        reminder_delta = timedelta(hours=1)
    else:
        await query.edit_message_text("❌ Неизвестный тип напоминания.")
        context.user_data.clear()
        return ConversationHandler.END
    
    reminder_time = show_datetime - reminder_delta
    reminder_time_str = reminder_time.strftime('%Y-%m-%d %H:%M:%S')
    
    # Сохраняем напоминание
    user_id = query.from_user.id
    update_show(
        show_id=show_id,
        user_id=user_id,
        notify_at=reminder_time_str
    )
    
    # Форматируем для отображения пользователю
    reminder_time_display = format_datetime_for_user(reminder_time)
    
    await query.edit_message_text(
        f"{query.message.text}\n\n"
        f"✅ Напоминание установлено!\n"
        f"Я напомню вам о спектакле \"{context.user_data.get('manual_show_name', '')}\" "
        f"за {reminder_type.lower()} ({reminder_time_display})."
    )
    
    # Очищаем user_data
    context.user_data.clear()
    return ConversationHandler.END


async def cmd_my_shows(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /my_shows."""
    user_id = update.effective_user.id
    shows = get_user_shows(user_id)
    
    if not shows:
        await update.message.reply_text("У вас пока нет сохраненных спектаклей.")
        return
    
    # Формируем список спектаклей с кнопками
    for show in shows:
        show_datetime_str = show.get('datetime') or show.get('show_date', '')
        try:
            if ' ' in show_datetime_str:
                dt_utc = datetime.strptime(show_datetime_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
                formatted_date = format_datetime_for_user(dt_utc)
            else:
                dt_utc = datetime.strptime(show_datetime_str, '%Y-%m-%d').replace(tzinfo=timezone.utc)
                formatted_date = format_datetime_for_user(dt_utc)
        except:
            formatted_date = show_datetime_str
        
        # Проверяем наличие напоминания
        notify_at = show.get('notify_at')
        reminder_text = ""
        if notify_at:
            try:
                notify_dt = datetime.strptime(notify_at, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
                reminder_formatted = format_datetime_for_user(notify_dt)
                reminder_text = f"\n⏰ Напоминание: {reminder_formatted}"
            except:
                pass
        
        text = (
            f"📌 {show['show_name']}\n"
            f"🏛️ {show['theatre']}\n"
            f"📅 {formatted_date}"
            f"{reminder_text}"
        )
        
        keyboard = [
            [
                InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit_show:{show['id']}"),
                InlineKeyboardButton("🗑️ Удалить", callback_data=f"delete_show:{show['id']}")
            ],
            [InlineKeyboardButton("📄 Экспортировать", callback_data=f"export_single:{show['id']}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(text, reply_markup=reply_markup)


async def cmd_export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /export - экспортирует все спектакли."""
    user_id = update.effective_user.id
    shows = get_user_shows(user_id)
    
    if not shows:
        await update.message.reply_text("У вас нет спектаклей для экспорта.")
        return
    
    try:
        file_path = generate_txt(shows, user_id)
        
        with open(file_path, 'rb') as f:
            await update.message.reply_document(
                document=f,
                filename=file_path.name,
                caption=f"📄 Экспорт всех спектаклей ({len(shows)} шт.)"
            )
    except Exception as e:
        logger.error(f"Ошибка при экспорте: {e}")
        await update.message.reply_text(f"❌ Ошибка при создании файла экспорта: {e}")


async def handle_export_single(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик экспорта отдельного спектакля."""
    query = update.callback_query
    await query.answer()
    
    show_id = int(query.data.split(':')[1])
    user_id = query.from_user.id
    
    show = get_show_by_id(show_id, user_id)
    if not show:
        await query.edit_message_text("❌ Спектакль не найден.")
        return
    
    try:
        file_path = generate_txt([], user_id, single_show=show)
        
        with open(file_path, 'rb') as f:
            await query.message.reply_document(
                document=f,
                filename=file_path.name,
                caption=f"📄 Экспорт спектакля: {show['show_name']}"
            )
    except Exception as e:
        logger.error(f"Ошибка при экспорте одного спектакля: {e}")
        await query.message.reply_text(f"❌ Ошибка при создании файла экспорта: {e}")


async def handle_delete_show(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик удаления спектакля."""
    query = update.callback_query
    await query.answer()
    
    show_id = int(query.data.split(':')[1])
    user_id = query.from_user.id
    
    # Получаем информацию о спектакле для отображения
    show = get_show_by_id(show_id, user_id)
    if not show:
        await query.edit_message_text("❌ Спектакль не найден.")
        return
    
    # Создаем подтверждающие кнопки
    keyboard = [
        [
            InlineKeyboardButton("✅ Да, удалить", callback_data=f"confirm_delete:{show_id}"),
            InlineKeyboardButton("❌ Отмена", callback_data="cancel_delete")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"Вы уверены, что хотите удалить спектакль?\n\n"
        f"📌 {show['show_name']}\n"
        f"🏛️ {show['theatre']}\n"
        f"📅 {show.get('datetime') or show.get('show_date')}",
        reply_markup=reply_markup
    )


async def handle_confirm_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик подтверждения удаления спектакля."""
    query = update.callback_query
    await query.answer()
    
    show_id = int(query.data.split(':')[1])
    user_id = query.from_user.id
    
    if delete_show(show_id, user_id):
        await query.edit_message_text("✅ Спектакль удален.")
    else:
        await query.edit_message_text("❌ Не удалось удалить спектакль.")


async def handle_cancel_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик отмены удаления."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Удаление отменено.")


async def handle_edit_show(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик редактирования спектакля."""
    query = update.callback_query
    await query.answer()
    
    show_id = int(query.data.split(':')[1])
    user_id = query.from_user.id
    
    show = get_show_by_id(show_id, user_id)
    if not show:
        await query.edit_message_text("❌ Спектакль не найден.")
        return ConversationHandler.END
    
    # Сохраняем ID спектакля для последующего редактирования
    context.user_data['editing_show_id'] = show_id
    
    # Форматируем дату и напоминание для отображения
    show_datetime_str = show.get('datetime') or show.get('show_date', 'Не указано')
    try:
        if ' ' in show_datetime_str:
            dt_utc = datetime.strptime(show_datetime_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
            formatted_date = format_datetime_for_user(dt_utc)
        else:
            dt_utc = datetime.strptime(show_datetime_str, '%Y-%m-%d').replace(tzinfo=timezone.utc)
            formatted_date = format_datetime_for_user(dt_utc)
    except:
        formatted_date = show_datetime_str
    
    notify_at = show.get('notify_at')
    reminder_formatted = "Не установлено"
    if notify_at:
        try:
            notify_dt = datetime.strptime(notify_at, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
            reminder_formatted = format_datetime_for_user(notify_dt)
        except:
            pass
    
    # Отображаем текущие данные и кнопки для редактирования
    keyboard = [
        [InlineKeyboardButton("📝 Изменить название", callback_data="edit_field:show_name")],
        [InlineKeyboardButton("🏛️ Изменить театр", callback_data="edit_field:theatre")],
        [InlineKeyboardButton("📅 Изменить дату", callback_data="edit_field:show_date")],
        [InlineKeyboardButton("⏰ Изменить напоминание", callback_data="edit_field:reminder")],
        [InlineKeyboardButton("❌ Отмена", callback_data="edit_cancel:")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"Редактирование спектакля:\n\n"
        f"📌 Название: {show['show_name']}\n"
        f"🏛️ Театр: {show['theatre']}\n"
        f"📅 Дата: {formatted_date}\n"
        f"⏰ Напоминание: {reminder_formatted}\n\n"
        f"Выберите, что хотите изменить:",
        reply_markup=reply_markup
    )


async def handle_edit_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик выбора поля для редактирования."""
    query = update.callback_query
    await query.answer()
    
    field = query.data.split(':')[1]
    context.user_data['editing_field'] = field
    
    if field == 'show_name':
        await query.edit_message_text("Введите новое название спектакля:")
        return EDIT_SHOW_NAME
    elif field == 'theatre':
        await query.edit_message_text("Введите новое название театра:")
        return EDIT_SHOW_THEATRE
    elif field == 'show_date':
        await query.edit_message_text("Введите новую дату (например, 25.12.2025 или 25.12.2025 19:00):")
        return EDIT_SHOW_DATE
    elif field == 'reminder':
        # Показываем опции напоминания
        keyboard = [
            [InlineKeyboardButton(f"⏰ {REMINDER_1_DAY} до события", callback_data=f"edit_reminder:{REMINDER_1_DAY}")],
            [InlineKeyboardButton(f"⏰ {REMINDER_6_HOURS} до события", callback_data=f"edit_reminder:{REMINDER_6_HOURS}")],
            [InlineKeyboardButton(f"⏰ {REMINDER_3_HOURS} до события", callback_data=f"edit_reminder:{REMINDER_3_HOURS}")],
            [InlineKeyboardButton(f"⏰ {REMINDER_1_HOUR} до события", callback_data=f"edit_reminder:{REMINDER_1_HOUR}")],
            [InlineKeyboardButton("🗑️ Удалить напоминание", callback_data="edit_reminder:delete")],
            [InlineKeyboardButton("❌ Отмена", callback_data="edit_cancel:")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Выберите время напоминания:", reply_markup=reply_markup)
        return EDIT_REMINDER


async def process_edit_show_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ввода нового названия спектакля."""
    new_name = update.message.text
    show_id = context.user_data.get('editing_show_id')
    user_id = update.effective_user.id
    
    if update_show(show_id, user_id, show_name=new_name):
        await update.message.reply_text(f"✅ Название обновлено: {new_name}")
    else:
        await update.message.reply_text("❌ Не удалось обновить название.")
    
    context.user_data.clear()
    return ConversationHandler.END


async def process_edit_show_theatre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ввода нового названия театра."""
    new_theatre = update.message.text
    show_id = context.user_data.get('editing_show_id')
    user_id = update.effective_user.id
    
    if update_show(show_id, user_id, theatre=new_theatre):
        await update.message.reply_text(f"✅ Театр обновлен: {new_theatre}")
    else:
        await update.message.reply_text("❌ Не удалось обновить театр.")
    
    context.user_data.clear()
    return ConversationHandler.END


async def process_edit_show_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ввода новой даты спектакля."""
    date_text = update.message.text
    
    # Парсим дату как московское время
    datetime_obj_utc = parse_user_datetime(date_text)
    
    if not datetime_obj_utc:
        await update.message.reply_text(
            "❌ Не удалось распознать дату. Пожалуйста, введите дату в формате ДД.ММ.ГГГГ или ДД.ММ.ГГГГ ЧЧ:ММ"
        )
        return EDIT_SHOW_DATE
    
    # Проверяем, что дата в будущем
    now_utc = datetime.now(timezone.utc)
    if datetime_obj_utc <= now_utc:
        await update.message.reply_text(
            "❌ Дата должна быть в будущем. Пожалуйста, введите дату снова:"
        )
        return EDIT_SHOW_DATE
    
    show_id = context.user_data.get('editing_show_id')
    user_id = update.effective_user.id
    
    datetime_str = datetime_obj_utc.strftime('%Y-%m-%d %H:%M:%S')
    show_date_only = datetime_obj_utc.strftime('%Y-%m-%d')
    
    if update_show(show_id, user_id, show_date=show_date_only, datetime_str=datetime_str):
        formatted_datetime = format_datetime_for_user(datetime_obj_utc)
        await update.message.reply_text(f"✅ Дата обновлена: {formatted_datetime}")
    else:
        await update.message.reply_text("❌ Не удалось обновить дату.")
    
    context.user_data.clear()
    return ConversationHandler.END


async def handle_edit_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик изменения напоминания."""
    query = update.callback_query
    await query.answer()
    
    reminder_type = query.data.split(':')[1]
    show_id = context.user_data.get('editing_show_id')
    user_id = query.from_user.id
    
    # Получаем информацию о спектакле для вычисления времени напоминания
    show = get_show_by_id(show_id, user_id)
    if not show:
        await query.edit_message_text("❌ Спектакль не найден.")
        context.user_data.clear()
        return ConversationHandler.END
    
    if reminder_type == "delete":
        # Удаляем напоминание
        if update_show(show_id, user_id, notify_at=""):
            await query.edit_message_text("✅ Напоминание удалено.")
        else:
            await query.edit_message_text("❌ Не удалось удалить напоминание.")
        context.user_data.clear()
        return ConversationHandler.END
    
    # Получаем дату спектакля
    show_datetime_str = show.get('datetime') or show.get('show_date')
    try:
        if ' ' in show_datetime_str:
            show_datetime = datetime.strptime(show_datetime_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
        else:
            show_datetime = datetime.strptime(show_datetime_str, '%Y-%m-%d').replace(tzinfo=timezone.utc)
    except:
        await query.edit_message_text("❌ Ошибка при парсинге даты спектакля.")
        context.user_data.clear()
        return ConversationHandler.END
    
    # Вычисляем время напоминания
    if reminder_type == REMINDER_1_DAY:
        reminder_delta = timedelta(days=1)
    elif reminder_type == REMINDER_6_HOURS:
        reminder_delta = timedelta(hours=6)
    elif reminder_type == REMINDER_3_HOURS:
        reminder_delta = timedelta(hours=3)
    elif reminder_type == REMINDER_1_HOUR:
        reminder_delta = timedelta(hours=1)
    else:
        await query.edit_message_text("❌ Неизвестный тип напоминания.")
        context.user_data.clear()
        return ConversationHandler.END
    
    reminder_time = show_datetime - reminder_delta
    reminder_time_str = reminder_time.strftime('%Y-%m-%d %H:%M:%S')
    
    if update_show(show_id, user_id, notify_at=reminder_time_str):
        reminder_time_display = format_datetime_for_user(reminder_time)
        await query.edit_message_text(
            f"✅ Напоминание обновлено!\n"
            f"Новое время напоминания: {reminder_time_display}"
        )
    else:
        await query.edit_message_text("❌ Не удалось обновить напоминание.")
    
    context.user_data.clear()
    return ConversationHandler.END


async def handle_edit_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик отмены редактирования."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Редактирование отменено.")
    context.user_data.clear()
    return ConversationHandler.END


async def cmd_theatres(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /theatres - показывает список театров."""
    theatres = get_theatres_stats()
    
    if not theatres:
        await update.message.reply_text("В базе пока нет театров.")
        return
    
    text_lines = ["🏛️ *Театры в базе:*\n"]
    for theatre in theatres:
        text_lines.append(f"• {theatre['theatre']} — {theatre['cnt']} спектаклей")
    
    text = "\n".join(text_lines)
    await update.message.reply_text(text, parse_mode='Markdown')


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /cancel."""
    context.user_data.clear()
    await update.message.reply_text("❌ Действие отменено.")
    return ConversationHandler.END


def check_reminders(application: Application):
    """Фоновая задача для проверки и отправки напоминаний."""
    try:
        current_time = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        pending = get_pending_notifications(current_time)
        
        logger.info(f"[REMINDERS] Проверка напоминаний в {current_time} UTC. Найдено: {len(pending)}")
        
        for show in pending:
            try:
                show_datetime_str = show.get('datetime') or show.get('show_date', 'Не указано')
                try:
                    if ' ' in show_datetime_str:
                        dt_utc = datetime.strptime(show_datetime_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
                        formatted_date = format_datetime_for_user(dt_utc)
                    else:
                        dt_utc = datetime.strptime(show_datetime_str, '%Y-%m-%d').replace(tzinfo=timezone.utc)
                        formatted_date = format_datetime_for_user(dt_utc)
                except:
                    formatted_date = show_datetime_str
                
                message = (
                    f"⏰ *Напоминание о спектакле!*\n\n"
                    f"📌 {show['show_name']}\n"
                    f"🏛️ {show['theatre']}\n"
                    f"📅 {formatted_date}\n\n"
                    f"Не пропустите!"
                )
                
                import asyncio
                asyncio.create_task(
                    application.bot.send_message(
                        chat_id=show['user_id'],
                        text=message,
                        parse_mode='Markdown'
                    )
                )
                
                mark_notification_sent(show['id'])
                logger.info(f"[REMINDERS] Отправлено напоминание для спектакля {show['id']} пользователю {show['user_id']}")
            
            except Exception as e:
                logger.error(f"[REMINDERS] Ошибка при отправке напоминания для спектакля {show['id']}: {e}")
        
        # Логируем время следующей проверки
        next_check = datetime.now(timezone.utc) + timedelta(minutes=10)
        logger.info(f"[REMINDERS] Следующая проверка в {next_check.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    
    except Exception as e:
        logger.error(f"[REMINDERS] Ошибка в check_reminders: {e}")


async def set_bot_commands(application: Application):
    """Устанавливает команды бота в меню."""
    commands = [
        BotCommand("start", "Начать работу с ботом"),
        BotCommand("add_show", "Добавить спектакль"),
        BotCommand("my_shows", "Мои спектакли"),
        BotCommand("export", "Экспортировать все спектакли"),
        BotCommand("theatres", "Список театров"),
        BotCommand("cancel", "Отменить текущее действие"),
        BotCommand("help", "Справка"),
    ]
    await application.bot.set_my_commands(commands)


def main():
    """Главная функция запуска бота."""
    # Проверяем токен
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN не установлен! Проверьте файл .env")
        raise ValueError("BOT_TOKEN не найден в переменных окружения")
    
    logger.info("Токен бота загружен успешно")
    
    # Инициализация БД
    init_db()
    
    # Создаем приложение с прокси (если указан)
    if PROXY_URL:
        from telegram.request import HTTPXRequest
        request = HTTPXRequest(proxy=PROXY_URL)
        application = Application.builder().token(BOT_TOKEN).request(request).build()
        logger.info(f"Используется прокси: {PROXY_URL}")
    else:
        application = Application.builder().token(BOT_TOKEN).build()
    
    # Регистрируем команды бота
    application.job_queue.run_once(set_bot_commands, when=0)
    
    # Настройка планировщика для напоминаний (проверка каждые 10 минут)
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        lambda: check_reminders(application),
        'interval',
        seconds=10*60,  # 10 минут
        id='check_reminders'
    )
    scheduler.start()
    logger.info("Планировщик напоминаний запущен (интервал: 10 минут)")
    
    # Обработчики команд
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CommandHandler("my_shows", cmd_my_shows))
    application.add_handler(CommandHandler("export", cmd_export))
    application.add_handler(CommandHandler("theatres", cmd_theatres))
    
    # Обработчики callback-запросов (вне ConversationHandler)
    application.add_handler(CallbackQueryHandler(handle_csv_choice, pattern="^(use_current_csv|update_csv)$"))
    application.add_handler(CallbackQueryHandler(handle_export_single, pattern="^export_single:"))
    application.add_handler(CallbackQueryHandler(handle_delete_show, pattern="^delete_show:"))
    application.add_handler(CallbackQueryHandler(handle_confirm_delete, pattern="^confirm_delete:"))
    application.add_handler(CallbackQueryHandler(handle_cancel_delete, pattern="^cancel_delete$"))
    
    # Глобальная кнопка отмены для редактирования
    application.add_handler(CallbackQueryHandler(handle_edit_cancel, pattern="^edit_cancel:"))
    
    # ConversationHandler для добавления спектакля
    add_show_handler = ConversationHandler(
        entry_points=[CommandHandler("add_show", cmd_add_show)],
        states={
            SEARCH_MODE: [CallbackQueryHandler(handle_search_mode_selection, pattern="^search_mode:")],
            SEARCH_QUERY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_search_query),
                CallbackQueryHandler(handle_csv_manual_selection, pattern="^csv_manual$"),
                CallbackQueryHandler(handle_csv_more, pattern="^csv_more:"),
                CallbackQueryHandler(handle_csv_prev, pattern="^csv_prev:"),
                CallbackQueryHandler(handle_csv_show_selection, pattern="^csv_show:"),
            ],
            MANUAL_SHOW_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_manual_show_name)],
            MANUAL_THEATRE: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_manual_theatre)],
            MANUAL_SHOW_DATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_manual_show_date),
                CallbackQueryHandler(handle_csv_date_selection, pattern="^csv_date:"),
                CallbackQueryHandler(handle_csv_date_confirm, pattern="^csv_date_confirm$"),
                CallbackQueryHandler(handle_csv_date_manual, pattern="^csv_date_manual$"),
            ],
            SELECT_REMINDER: [CallbackQueryHandler(handle_reminder_selection, pattern="^reminder:")],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CommandHandler("add_show", cmd_add_show),
            CallbackQueryHandler(handle_csv_show_selection, pattern="^csv_show:"),
        ],
    )
    application.add_handler(add_show_handler)
    
    # ConversationHandler для редактирования спектакля
    edit_show_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(handle_edit_show, pattern="^edit_show:")],
        states={
            EDIT_SHOW_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_edit_show_name)],
            EDIT_SHOW_THEATRE: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_edit_show_theatre)],
            EDIT_SHOW_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_edit_show_date)],
            EDIT_REMINDER: [CallbackQueryHandler(handle_edit_reminder, pattern="^edit_reminder:")],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CallbackQueryHandler(handle_edit_cancel, pattern="^edit_cancel:"),
        ],
    )
    application.add_handler(edit_show_handler)
    
    # Обработчик для выбора поля редактирования (должен быть после ConversationHandler)
    application.add_handler(CallbackQueryHandler(handle_edit_field, pattern="^edit_field:"))
    
    # Запуск бота
    logger.info("Бот запущен...")
    application.run_polling()


if __name__ == "__main__":
    main()
