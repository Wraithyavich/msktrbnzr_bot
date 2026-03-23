import csv
import os
import re
from collections import defaultdict
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ---------- Получение токена из переменной окружения ----------
API_TOKEN = os.environ.get('API_TOKEN')
if API_TOKEN is None:
    raise ValueError("❌ Переменная окружения API_TOKEN не задана!")

# ---------- Список разрешенных пользователей ----------
ALLOWED_IDS_STR = os.environ.get('ALLOWED_IDS', '')
ALLOWED_IDS = set()
if ALLOWED_IDS_STR:
    try:
        ALLOWED_IDS = set(int(id.strip()) for id in ALLOWED_IDS_STR.split(',') if id.strip())
        print(f"✅ Загружено {len(ALLOWED_IDS)} разрешенных пользователей")
    except ValueError:
        print("⚠️ Ошибка парсинга ALLOWED_IDS")

# ---------- Проверка доступа ----------
def is_allowed(user_id):
    if not ALLOWED_IDS_STR:
        return True
    return user_id in ALLOWED_IDS

# ---------- Константы ----------
MIN_SEARCH_LENGTH = 4
DATA_FILE = 'data.csv'
JRONE_FILE = 'jronecross.csv'
OEM_FILE = 'oemcross.csv'
FLP_FILE = 'flp.csv'
INVENTORY_FILE = 'inventory.csv'

MARGIN_OPTIONS = [20, 25, 30, 35, 40, 45, 50]
DEFAULT_MARGIN = 50

# ---------- Очистка текста ----------
def clean_text(s):
    s = s.strip()
    s = s.replace('\r', '').replace('\n', '').replace('\ufeff', '')
    return ' '.join(s.split())

# ---------- Замена кириллических букв, похожих на латиницу ----------
CYRILLIC_TO_LATIN = {
    'А': 'A', 'а': 'a',
    'В': 'B', 'в': 'b',
    'Е': 'E', 'е': 'e',
    'К': 'K', 'к': 'k',
    'М': 'M', 'м': 'm',
    'Н': 'H', 'н': 'h',
    'О': 'O', 'о': 'o',
    'Р': 'P', 'р': 'p',
    'С': 'C', 'с': 'c',
    'Т': 'T', 'т': 't',
    'У': 'Y', 'у': 'y',
    'Х': 'X', 'х': 'x',
}

def replace_cyrillic_like_latin(s):
    return ''.join(CYRILLIC_TO_LATIN.get(ch, ch) for ch in s)

def normalize(s):
    s = replace_cyrillic_like_latin(s)
    return s.replace('-', '').lower()

def is_11_digit_number(s):
    return re.fullmatch(r'\d{11}', s) is not None

# ---------- Работа с ценами ----------
def parse_price(price_str):
    if not price_str:
        return 0.0
    cleaned = price_str.replace(' ', '').replace(',', '.')
    try:
        return float(cleaned)
    except ValueError:
        return 0.0

def format_price(price):
    rounded = round(price, 2)
    s = f"{rounded:.2f}".replace('.', ',')
    parts = s.split(',')
    int_part = parts[0]
    frac_part = parts[1] if len(parts) > 1 else '00'
    int_part_with_spaces = ''
    for i, digit in enumerate(reversed(int_part)):
        if i > 0 and i % 3 == 0:
            int_part_with_spaces = ' ' + int_part_with_spaces
        int_part_with_spaces = digit + int_part_with_spaces
    return f"{int_part_with_spaces},{frac_part}"

# ---------- Загрузка основной базы (data.csv) ----------
dict_by_col1 = defaultdict(list)
dict_by_col2 = defaultdict(list)
col1_norm_to_original = defaultdict(list)
col2_norm_to_original = defaultdict(list)

try:
    with open(DATA_FILE, mode='r', encoding='utf-8-sig') as file:
        reader = csv.reader(file, delimiter=';')
        for row in reader:
            if len(row) >= 2:
                col1 = clean_text(row[0])
                col2 = clean_text(row[1])
                if col1 and col2:
                    dict_by_col1[col1].append(col2)
                    dict_by_col2[col2].append(col1)
                    col1_norm_to_original[normalize(col1)].append(col1)
                    col2_norm_to_original[normalize(col2)].append(col2)
except FileNotFoundError:
    print("❌ Файл data.csv не найден! Поместите его в папку со скриптом.")
    exit(1)

print(f"✅ Основная база: {len(dict_by_col1)} Turbo P/N, {len(dict_by_col2)} E&E P/N.")

# ---------- Загрузка JRN-кроссов (jronecross.csv) ----------
jrone_norm_to_art = defaultdict(set)

try:
    with open(JRONE_FILE, mode='r', encoding='utf-8-sig') as file:
        reader = csv.reader(file, delimiter=';')
        for row in reader:
            if len(row) >= 3:
                jrone = clean_text(row[0])
                our_art = clean_text(row[2])
                if jrone and our_art:
                    norm = normalize(jrone)
                    jrone_norm_to_art[norm].add(our_art)
except FileNotFoundError:
    print("⚠️ Файл jronecross.csv не найден, поиск по JRN-номерам недоступен.")
except Exception as e:
    print(f"❌ Ошибка загрузки {JRONE_FILE}: {e}")

print(f"✅ JRN-база: {len(jrone_norm_to_art)} уникальных нормализованных JRN-номеров.")

# ---------- Загрузка OEM-кроссов (oemcross.csv) ----------
oem_norm_to_art = defaultdict(set)

try:
    with open(OEM_FILE, mode='r', encoding='utf-8-sig') as file:
        reader = csv.reader(file, delimiter=';')
        for row in reader:
            if len(row) >= 2:
                art = clean_text(row[0])
                oem = clean_text(row[1])
                if art and oem:
                    norm = normalize(oem)
                    oem_norm_to_art[norm].add(art)
except FileNotFoundError:
    print("⚠️ Файл oemcross.csv не найден, поиск по OEM-номерам недоступен.")
except Exception as e:
    print(f"❌ Ошибка загрузки {OEM_FILE}: {e}")

print(f"✅ OEM-база: {len(oem_norm_to_art)} уникальных нормализованных OEM-номеров.")

# ---------- Загрузка FLP-кроссов (flp.csv) ----------
flp_norm_to_art = defaultdict(set)
art_norm_to_flp = defaultdict(set)

try:
    with open(FLP_FILE, mode='r', encoding='utf-8-sig') as file:
        reader = csv.reader(file, delimiter=';')
        for row in reader:
            if len(row) >= 2:
                art = clean_text(row[0])
                flp = clean_text(row[1])
                if art and flp:
                    norm_flp = normalize(flp)
                    norm_art = normalize(art)
                    flp_norm_to_art[norm_flp].add(art)
                    art_norm_to_flp[norm_art].add(flp)
except FileNotFoundError:
    print("⚠️ Файл flp.csv не найден, поиск по FLP-номерам недоступен.")
except Exception as e:
    print(f"❌ Ошибка загрузки {FLP_FILE}: {e}")

print(f"✅ FLP-база: {len(flp_norm_to_art)} уникальных FLP-номеров, {len(art_norm_to_flp)} уникальных артикулов.")

# ---------- Загрузка складской базы (inventory.csv) ----------
inventory = {}
stock_norm_to_art = {}

try:
    with open(INVENTORY_FILE, mode='r', encoding='utf-8-sig') as file:
        reader = csv.reader(file, delimiter=';')
        for row in reader:
            # Пропускаем строки, где меньше 4 полей (без количества или цены)
            if len(row) < 4:
                continue
            art = clean_text(row[0])
            # Доп. артикул может быть пустым
            dop = clean_text(row[1]) if len(row) > 1 else ''
            # Количество – целое число
            try:
                qty = int(clean_text(row[2]))
            except ValueError:
                qty = 0
            # Цена – строка, может содержать пробелы и запятую
            price_str = clean_text(row[3])
            # Флаг скидки: если 5-я колонка есть и равна "1", то скидки нет
            discount = True
            if len(row) >= 5 and clean_text(row[4]) == "1":
                discount = False
            if art:
                inventory[art] = [dop, qty, price_str, discount]
                stock_norm_to_art[normalize(art)] = art
    print(f"✅ Складская база: {len(inventory)} записей.")
    # Для отладки выведем первые 5 артикулов
    print("Примеры артикулов из inventory:", list(inventory.keys())[:5])
except FileNotFoundError:
    print("⚠️ Файл inventory.csv не найден, информация о наличии будет недоступна.")
except Exception as e:
    print(f"❌ Ошибка загрузки {INVENTORY_FILE}: {e}")

# ---------- Частичный поиск в основной базе ----------
def partial_search_main(search_norm):
    results = set()
    for norm_key, original_keys in col1_norm_to_original.items():
        if search_norm in norm_key:
            for orig_key in original_keys:
                for val in dict_by_col1[orig_key]:
                    results.add(val)
    for norm_key, original_keys in col2_norm_to_original.items():
        if search_norm in norm_key:
            for orig_key in original_keys:
                for val in dict_by_col2[orig_key]:
                    results.add(val)
    return results

# ---------- Форматирование артикула с учётом наценки ----------
def format_art_with_stock(art, links=None, margin=DEFAULT_MARGIN):
    stock = inventory.get(art)
    if stock:
        _, qty, price_str, discount = stock
        original_price = parse_price(price_str)
        if original_price != 0:
            base_price = original_price / 1.5
            final_price = base_price * (1 + margin / 100.0)
            price_display = format_price(final_price)
        else:
            price_display = price_str
        discount_str = " (скидка)" if discount else ""
        stock_part = f" – наличие: {qty} ед., цена: {price_display}{discount_str}"
    else:
        stock_part = " – нет на складе (цена неизвестна)"
    if links:
        return f"• {art}{stock_part} → {', '.join(links)}"
    else:
        return f"• {art}{stock_part}"

# ---------- Клавиатура выбора наценки ----------
def get_margin_keyboard():
    buttons = []
    row = []
    for i, margin in enumerate(MARGIN_OPTIONS, 1):
        row.append(KeyboardButton(f"{margin}%"))
        if i % 4 == 0:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([KeyboardButton("Текущая наценка")])
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

# ---------- Функция безопасной отправки длинных сообщений ----------
async def safe_send(update: Update, text: str, reply_markup=None, parse_mode=None, max_len=4000):
    if len(text) <= max_len:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        return

    lines = text.split('\n')
    parts = []
    current = ''

    for line in lines:
        if len(line) > max_len:
            if current:
                parts.append(current)
                current = ''
            for i in range(0, len(line), max_len):
                parts.append(line[i:i+max_len])
            continue

        if current:
            candidate = current + '\n' + line
        else:
            candidate = line

        if len(candidate) <= max_len:
            current = candidate
        else:
            parts.append(current)
            current = line

    if current:
        parts.append(current)

    for i, part in enumerate(parts):
        if i == len(parts) - 1:
            await update.message.reply_text(part, reply_markup=reply_markup, parse_mode=parse_mode)
        else:
            await update.message.reply_text(part, parse_mode=parse_mode)

# ---------- Обработчики ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_allowed(user_id):
        await update.message.reply_text("⛔ Доступ к боту запрещён.")
        return

    context.user_data['margin'] = DEFAULT_MARGIN

    emoji_id = "5247029251940586192"
    welcome_text = (
        f"<tg-emoji emoji-id=\"{emoji_id}\">😊</tg-emoji> Бот поиска с проверкой наличия!\n"
        "Введите E&E P/N, Turbo P/N, JRN-номер, OEM-номер или FLP-номер\n\n"
        "Пример: CT-VNT11B или 17201-52010\n\n"
        f"🔍 Можно искать по части номера (минимум {MIN_SEARCH_LENGTH} символа).\n"
        "Дефисы можно не ставить – бот поймёт.\n"
        "Также бот понимает русские буквы, похожие на латинские.\n"
        "Для найденных артикулов показывается наличие на складе.\n"
        "Используйте кнопки ниже для выбора наценки."
    )
    await safe_send(update, welcome_text, reply_markup=get_margin_keyboard(), parse_mode='HTML')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_allowed(user_id):
        await safe_send(update, "⛔ Доступ к боту запрещён.")
        return

    user_input = clean_text(update.message.text)
    if not user_input:
        return

    # Обработка кнопок наценки
    if user_input.endswith('%') and user_input[:-1].isdigit():
        margin = int(user_input[:-1])
        if margin in MARGIN_OPTIONS:
            context.user_data['margin'] = margin
            await safe_send(update, f"✅ Установлена наценка {margin}%", reply_markup=get_margin_keyboard())
            return
        else:
            await safe_send(update, "❌ Неверное значение. Используйте кнопки.", reply_markup=get_margin_keyboard())
            return
    elif user_input == "Текущая наценка":
        current = context.user_data.get('margin', DEFAULT_MARGIN)
        await safe_send(update, f"📊 Текущая наценка: {current}%", reply_markup=get_margin_keyboard())
        return

    margin = context.user_data.get('margin', DEFAULT_MARGIN)
    user_input_norm = normalize(user_input)
    input_len = len(user_input_norm)

    # Сбор результатов
    main_arts = set()
    jrone_arts = set()
    oem_arts = set()
    flp_arts = set()
    flp_nums = set()
    inventory_arts = set()

    # Основная база
    if input_len < MIN_SEARCH_LENGTH:
        if user_input_norm in col2_norm_to_original:
            for key in col2_norm_to_original[user_input_norm]:
                for val in dict_by_col2[key]:
                    main_arts.add(val)
        elif user_input_norm in col1_norm_to_original:
            for key in col1_norm_to_original[user_input_norm]:
                for val in dict_by_col1[key]:
                    main_arts.add(val)
    else:
        main_arts = partial_search_main(user_input_norm)
        if not main_arts and is_11_digit_number(user_input_norm):
            first4 = user_input_norm[:4]
            middle3 = user_input_norm[4:7]
            last4 = user_input_norm[7:]
            if middle3 != '970':
                new_norm = first4 + '970' + last4
                main_arts = partial_search_main(new_norm)

    # JRN
    if input_len < MIN_SEARCH_LENGTH:
        if user_input_norm in jrone_norm_to_art:
            jrone_arts = jrone_norm_to_art[user_input_norm]
    else:
        for norm_key, arts in jrone_norm_to_art.items():
            if user_input_norm in norm_key:
                jrone_arts.update(arts)

    # OEM
    if input_len < MIN_SEARCH_LENGTH:
        if user_input_norm in oem_norm_to_art:
            oem_arts = oem_norm_to_art[user_input_norm]
    else:
        for norm_key, arts in oem_norm_to_art.items():
            if user_input_norm in norm_key:
                oem_arts.update(arts)

    # FLP
    if input_len < MIN_SEARCH_LENGTH:
        if user_input_norm in flp_norm_to_art:
            flp_arts = flp_norm_to_art[user_input_norm]
    else:
        for norm_key, arts in flp_norm_to_art.items():
            if user_input_norm in norm_key:
                flp_arts.update(arts)

    if input_len < MIN_SEARCH_LENGTH:
        if user_input_norm in art_norm_to_flp:
            flp_nums = art_norm_to_flp[user_input_norm]
    else:
        for norm_key, nums in art_norm_to_flp.items():
            if user_input_norm in norm_key:
                flp_nums.update(nums)

    # Inventory
    if input_len < MIN_SEARCH_LENGTH:
        if user_input_norm in stock_norm_to_art:
            inventory_arts.add(stock_norm_to_art[user_input_norm])
        elif user_input in inventory:
            inventory_arts.add(user_input)
    else:
        for norm_art, orig_art in stock_norm_to_art.items():
            if user_input_norm in norm_art:
                inventory_arts.add(orig_art)

    # Формирование строк ответа
    answer_lines = []

    for art in sorted(main_arts):
        answer_lines.append(format_art_with_stock(art, margin=margin))

    for art in sorted(jrone_arts):
        links = set()
        if art in dict_by_col1:
            links.update(dict_by_col1[art])
        if art in dict_by_col2:
            links.update(dict_by_col2[art])
        answer_lines.append(format_art_with_stock(art, links=sorted(links), margin=margin))

    for art in sorted(oem_arts):
        answer_lines.append(format_art_with_stock(art, margin=margin))

    for art in sorted(flp_arts):
        answer_lines.append(f"• FLP артикул: " + format_art_with_stock(art, margin=margin)[2:])

    for num in sorted(flp_nums):
        answer_lines.append(f"• FLP номер: {num}")

    shown_arts = set(main_arts) | set(jrone_arts) | set(oem_arts) | set(flp_arts)
    for art in sorted(inventory_arts):
        if art not in shown_arts:
            answer_lines.append(format_art_with_stock(art, margin=margin))

    if not answer_lines:
        await safe_send(update, f"❌ Ничего не найдено по запросу `{user_input}`.", reply_markup=get_margin_keyboard())
        return

    full_text = "\n".join(answer_lines)
    await safe_send(update, full_text, reply_markup=get_margin_keyboard())

def main():
    app = Application.builder().token(API_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🚀 Четвёртый бот (поиск + наличие на складе) с регулировкой наценки и безопасной отправкой запущен...")
    if ALLOWED_IDS_STR:
        print(f"🔒 Доступ разрешён для {len(ALLOWED_IDS)} пользователей.")
    else:
        print("🔓 Доступ разрешён для всех (ALLOWED_IDS не задана).")
    app.run_polling()

if __name__ == '__main__':
    main()
