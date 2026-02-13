# app.py - Complete for your translation bot with per-user From mappings and admin controls
import os
import json
import requests
import traceback
from flask import Flask, request
import telebot
from telebot import types

LANGUAGE_FLAGS = {
    "en": "🇬🇧",
    "ru": "🇷🇺",
    "ar": "🇸🇦",
    "vi": "🇻🇳",
    "ja": "🇯🇵",
    "th": "🇹🇭",
    "zh": "🇨🇳"
}

# ---------- Persistent storage files ----------
DATA_STORE_FILE = "message_store.json"   # key: "chat_id:bot_msg_id" -> "sender|original|source_lang"
CHAT_CONFIG_FILE = "chat_config.json"    # key: str(chat_id) -> { "from_map": {...}, "custom_langs": [...], "compact_mode": "on"/"off", "topic_permissions": [...] }

# ---------- Language flags and defaults ----------
btn_en = types.InlineKeyboardButton("🇬🇧", callback_data="lang_en")
btn_ru = types.InlineKeyboardButton("🇷🇺", callback_data="lang_ru")
btn_ar = types.InlineKeyboardButton("🇸🇦", callback_data="lang_ar")
btn_vi = types.InlineKeyboardButton("🇻🇳", callback_data="lang_vi")
btn_ja = types.InlineKeyboardButton("🇯🇵", callback_data="lang_ja")
btn_th = types.InlineKeyboardButton("🇹🇭", callback_data="lang_th")
btn_zh = types.InlineKeyboardButton("🇨🇳", callback_data="lang_zh")
markup = types.InlineKeyboardMarkup()

markup.row(btn_en, btn_ru, btn_ar)
markup.row(btn_ja, btn_th, btn_zh)

DEFAULT_LANGS = ["en", "ru", "ar", "vi", "ja", "th", "zh"]

# ---------- Helpers to load/save JSON ----------
def load_json_file(path, default):
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print(f"Cannot read {path}: {e}")
    return default

def save_json_file(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Cannot write {path}: {e}")

# ---------- Persistent stores (loaded on start) ----------
MESSAGE_DATA = load_json_file(DATA_STORE_FILE, {})   # persistent mapping for callbacks
CHAT_CONFIG = load_json_file(CHAT_CONFIG_FILE, {})    # persistent chat configs

def save_message_data():
    save_json_file(DATA_STORE_FILE, MESSAGE_DATA)

def save_chat_config():
    save_json_file(CHAT_CONFIG_FILE, CHAT_CONFIG)

def get_chat_cfg(chat_id):
    return CHAT_CONFIG.get(str(chat_id), {"from_map": {}, "custom_langs": list(DEFAULT_LANGS), "compact_mode": "on", "topic_permissions": []})

def set_chat_cfg(chat_id, cfg):
    CHAT_CONFIG[str(chat_id)] = cfg
    save_chat_config()

# ---------- Bot init ----------
TOKEN = os.environ.get("TELEGRAM_TOKEN")
if not TOKEN:
    raise RuntimeError("Please set TELEGRAM_TOKEN environment variable")
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# ---------- Translate helper ----------
def translate_text_with_source(text, target_lang):
    """Return (translated_text, detected_source_lang). Uses google translate public endpoint (demo)."""
    try:
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl={target_lang}&dt=t&q={requests.utils.quote(text)}"
        r = requests.get(url, timeout=8)
        r.raise_for_status()
        data = r.json()
        translated = data[0][0][0] if data and data[0] and data[0][0] else ""
        source_lang = data[2] if len(data) > 2 else "und"
        return translated, source_lang
    except Exception as e:
        print("Translate error:", e)
        return f"[Lỗi dịch: {e}]", "und"

# ---------- Create inline keyboard ----------
def create_markup(chat_id):
    cfg = get_chat_cfg(chat_id)
    langs = cfg.get("custom_langs", list(DEFAULT_LANGS))
    markup = types.InlineKeyboardMarkup()
    buttons = []
    for l in langs:
        flag = LANGUAGE_FLAGS.get(l.lower(), "❓")
        buttons.append(types.InlineKeyboardButton(f"{flag}", callback_data=l.lower()))
    markup.add(*buttons)
    return markup

# ---------- Admin commands: per-username From mapping ----------
@bot.message_handler(commands=['ch12from_on', 'ch12from_off', 'ch12from_list'])
def ch12from_commands(message):
    """
    /ch12from_on <username> <label>  -> set mapping for username (no @)
    /ch12from_off <username>         -> remove mapping
    /ch12from_list                   -> list mappings
    Only group admins can set/unset. Listing allowed for all.
    """
    chat_id = message.chat.id
    user_id = message.from_user.id
    text = message.text or ""
    parts = text.strip().split(maxsplit=2)
    cmd = parts[0].lstrip('/').lower()

    # list mapping
    if cmd == "ch12from_list":
        cfg = get_chat_cfg(chat_id)
        fm = cfg.get("from_map", {})
        if not fm:
            bot.reply_to(message, "❗ Chưa có mapping nào trong chat này.")
            return
        lines = [f"{u} -> {lbl}" for u, lbl in fm.items()]
        bot.reply_to(message, "Mappings (username -> label):\n" + "\n".join(lines))
        return

    # check admin
    try:
        admins = bot.get_chat_administrators(chat_id)
        is_admin = any(a.user.id == user_id for a in admins)
    except Exception as e:
        print("Error getting admins:", e)
        is_admin = False

    if not is_admin:
        bot.reply_to(message, "❌ Lệnh này chỉ dành cho quản trị viên nhóm.")
        return

    if cmd == "ch12from_on":
        if len(parts) < 3:
            bot.reply_to(message, "⚠️ Cú pháp: /ch12from_on <username> <label>\nVí dụ: /ch12from_on Ch12_09 \"Cao Huy\"")
            return
        username = parts[1].lstrip('@')
        label = parts[2].strip()
        cfg = get_chat_cfg(chat_id)
        fm = cfg.get("from_map", {})
        fm[username] = label
        cfg['from_map'] = fm
        set_chat_cfg(chat_id, cfg)
        bot.reply_to(message, f"✅ Đã đặt From cho @{username} là: {label}")
        return

    if cmd == "ch12from_off":
        if len(parts) < 2:
            bot.reply_to(message, "⚠️ Cú pháp: /ch12from_off <username>\nVí dụ: /ch12from_off Ch12_09")
            return
        username = parts[1].lstrip('@')
        cfg = get_chat_cfg(chat_id)
        fm = cfg.get("from_map", {})
        if username in fm:
            fm.pop(username)
            cfg['from_map'] = fm
            set_chat_cfg(chat_id, cfg)
            bot.reply_to(message, f"✅ Đã xóa mapping cho @{username}")
        else:
            bot.reply_to(message, f"ℹ️ Không tìm thấy mapping cho @{username}")
        return

# ---------- Admin commands: topics, compact, custom languages ----------
@bot.message_handler(commands=['ch12topic_on', 'ch12topic_off', 'ch12compact_on', 'ch12compact_off', 'ch12language_on', 'ch12language_off'])
def ch12_admin_misc(message):
    """
    /ch12topic_on  (reply to a message in the topic) -> enable bot responses in that topic
    /ch12topic_off (reply to a message in the topic) -> disable bot responses in that topic
    /ch12compact_on  -> turn compact mode ON for chat
    /ch12compact_off -> turn compact mode OFF
    /ch12language_on <lang>  -> add language button (e.g. en, ru, ar)
    /ch12language_off <lang> -> remove language button
    """
    chat_id = message.chat.id
    user_id = message.from_user.id
    cmd = (message.text or "").split(maxsplit=1)[0].lstrip('/').lower()

    # check admin
    try:
        admins = bot.get_chat_administrators(chat_id)
        is_admin = any(a.user.id == user_id for a in admins)
    except Exception as e:
        print("Error get admins:", e)
        is_admin = False

    if not is_admin:
        bot.reply_to(message, "❌ Lệnh này chỉ dành cho quản trị viên nhóm.")
        return

    cfg = get_chat_cfg(chat_id)
    if 'topic_permissions' not in cfg:
        cfg['topic_permissions'] = []
    if 'custom_langs' not in cfg:
        cfg['custom_langs'] = list(DEFAULT_LANGS)
    if 'compact_mode' not in cfg:
        cfg['compact_mode'] = 'on'

    if cmd in ('ch12topic_on', 'ch12topic_off'):
        if not message.reply_to_message:
            bot.reply_to(message, "⚠️ Vui lòng reply vào 1 tin trong topic bạn muốn bật/tắt quyền.")
            return
        thread_id = message.reply_to_message.message_thread_id
        if thread_id is None:
            bot.reply_to(message, "⚠️ Không tìm thấy message_thread_id. Hãy chắc bạn đang reply vào 1 tin trong topic.")
            return
        if cmd == 'ch12topic_on':
            if thread_id not in cfg['topic_permissions']:
                cfg['topic_permissions'].append(thread_id)
                set_chat_cfg(chat_id, cfg)
                bot.reply_to(message, f"✅ Đã BẬT quyền xử lý trong topic `{thread_id}`.")
            else:
                bot.reply_to(message, f"ℹ️ Topic `{thread_id}` đã được bật rồi.")
        else:
            if thread_id in cfg['topic_permissions']:
                cfg['topic_permissions'].remove(thread_id)
                set_chat_cfg(chat_id, cfg)
                bot.reply_to(message, f"✅ Đã TẮT quyền xử lý trong topic `{thread_id}`.")
            else:
                bot.reply_to(message, f"ℹ️ Topic `{thread_id}` hiện không được bật.")
        return

    if cmd in ('ch12compact_on', 'ch12compact_off'):
        cfg['compact_mode'] = 'on' if cmd == 'ch12compact_on' else 'off'
        set_chat_cfg(chat_id, cfg)
        state = "BẬT" if cfg['compact_mode'] == 'on' else "TẮT"
        bot.reply_to(message, f"✅ Đã {state} chế độ gọn gàng (compact mode).")
        return

    if cmd in ('ch12language_on', 'ch12language_off'):
        parts = (message.text or "").split()
        if len(parts) < 2:
            bot.reply_to(message, "⚠️ Cú pháp: /ch12language_on <lang> hoặc /ch12language_off <lang>")
            return
        lang = parts[1].lower()
        if lang == 'vi':
            bot.reply_to(message, "ℹ️ Tiếng Việt luôn tự động có sẵn (không cần thêm nút).")
            return
        langs = cfg.get('custom_langs', list(DEFAULT_LANGS))
        if cmd == 'ch12language_on':
            if lang not in langs:
                langs.append(lang)
                cfg['custom_langs'] = langs
                set_chat_cfg(chat_id, cfg)
                bot.reply_to(message, f"✅ Đã thêm nút dịch `{lang.upper()}`.")
            else:
                bot.reply_to(message, f"ℹ️ `{lang.upper()}` đã tồn tại.")
        else:
            if lang in langs:
                langs.remove(lang)
                cfg['custom_langs'] = langs
                set_chat_cfg(chat_id, cfg)
                bot.reply_to(message, f"✅ Đã gỡ nút dịch `{lang.upper()}`.")
            else:
                bot.reply_to(message, f"ℹ️ `{lang.upper()}` không tồn tại.")
        return

# ---------- Main message handler ----------
@bot.message_handler(content_types=["text", "photo"])
def handle_message(message):
    try:
        # ignore messages from bots
        if getattr(message.from_user, "is_bot", False):
            return

        chat_id = message.chat.id
        cfg = get_chat_cfg(chat_id)

        # Topic permission: if message is in topic and topic not allowed -> ignore
        if getattr(message, "is_topic_message", False):
            thread_id = getattr(message, "message_thread_id", None)
            allowed = cfg.get('topic_permissions', [])
            if thread_id is not None and thread_id not in allowed:
                return

        compact = cfg.get("compact_mode", "on")

        # sender display
        user = message.from_user
        sender_display = f"👤@{user.username}" if getattr(user, "username", None) else (user.full_name if getattr(user, "full_name", None) else (user.first_name or "User"))

        # extract text
        if message.content_type == "photo":
            text = (message.caption or "").strip()
            if not text:
                # optional OCR (best-effort)
                try:
                    file_id = message.photo[-1].file_id
                    file_info = bot.get_file(file_id)
                    file_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_info.file_path}"
                    ocr_url = f"https://api.ocr.space/parse/imageurl?apikey=helloworld&url={file_url}"
                    r = requests.get(ocr_url, timeout=8).json()
                    parsed = r.get("ParsedResults")
                    if parsed and parsed[0].get("ParsedText"):
                        text = parsed[0]["ParsedText"].strip()
                except Exception as e:
                    print("OCR error:", e)
        else:
            text = (message.text or "").strip()

        if not text:
            return

        # auto translate to Vietnamese
        translated_vi, source_lang = translate_text_with_source(text, "vi")

        # determine From label ONLY from per-username mapping (explicit)
        from_map = cfg.get('from_map', {})
        sender_username = getattr(message.from_user, "username", "") or ""
        short_sender_username = sender_username.lstrip('@')
        from_label = ""
        if short_sender_username and short_sender_username in from_map:
            from_label = from_map[short_sender_username]

        # Build header + original + blank + vi_line
        header_line = f"<b>{sender_display} - From {from_label}</b>" if from_label else f"<b>{sender_display}</b>"
        original_line = text
        vi_line = f"{LANGUAGE_FLAGS.get('vi', ' 🇻🇳')} {translated_vi}"
        final_text = f"{header_line}\n{original_line}\n\n{vi_line}"

        markup = create_markup(chat_id)

        sent_msg = None
        if compact == "on":
            sent_msg = bot.send_message(chat_id, final_text, parse_mode="HTML", reply_markup=markup,
                                        message_thread_id=message.message_thread_id if getattr(message, "is_topic_message", False) else None)
            # try delete original
            try:
                bot.delete_message(chat_id, message.message_id)
            except Exception as e:
                if "message can't be deleted" in str(e):
                    bot.send_message(chat_id, "⚠️ Bot không thể xóa tin nhắn. Vui lòng cấp quyền 'Xóa tin nhắn' cho bot.")
                else:
                    print("Delete error:", e)
        else:
            sent_msg = bot.reply_to(message, final_text, parse_mode="HTML", reply_markup=markup,
                                    message_thread_id=message.message_thread_id if getattr(message, "is_topic_message", False) else None)

        # persist mapping for callback
        if sent_msg:
            key = f"{chat_id}:{sent_msg.message_id}"
            MESSAGE_DATA[key] = f"{sender_display}|{text}|{source_lang}"
            save_message_data()

    except Exception as e:
        print("Error in handle_message:", e)
        traceback.print_exc()

# ---------- Callback handler ----------
@bot.callback_query_handler(func=lambda call: True)
def handle_translate_callback(call):
    try:
        lang = call.data.lower()
        chat_id = call.message.chat.id
        msg_id = call.message.message_id
        key = f"{chat_id}:{msg_id}"

        data_storage = MESSAGE_DATA.get(key)
        if not data_storage:
            bot.answer_callback_query(call.id, "❌ Không tìm thấy dữ liệu gốc (tin đã bị sửa hoặc bot khởi động lại).")
            return

        parts = data_storage.split("|", 2)
        if len(parts) < 2:
            bot.answer_callback_query(call.id, "❌ Dữ liệu gốc bị lỗi.")
            return
        original_text = parts[1]

        # translate
        translated, _ = translate_text_with_source(original_text, lang)
        flag = LANGUAGE_FLAGS.get(lang, " ❓")
        new_translation_line = f"{flag} {lang.upper()} {translated}"

        # parse visible message: header, original, blank, vi_line, extras...
        current_text = call.message.text or ""
        lines = current_text.splitlines()
        header_line = lines[0] if len(lines) > 0 else ""
        original_line = lines[1] if len(lines) > 1 else original_text

        # find vi_line
        vi_line = None
        vi_index = None
        for i in range(2, len(lines)):
            if lines[i].strip() == "":
                continue
            if lines[i].startswith(LANGUAGE_FLAGS.get('vi', ' 🇻🇳')) or lines[i].startswith("🇻🇳"):
                vi_line = lines[i]
                vi_index = i
                break
        if vi_line is None:
            vi_line = f"{LANGUAGE_FLAGS.get('vi', ' 🇻🇳')} {translate_text_with_source(original_text, 'vi')[0]}"
            vi_index = 3 if len(lines) >= 3 else len(lines)

        extra_lines = []
        if vi_index is not None and vi_index + 1 < len(lines):
            extra_lines = [l for l in lines[vi_index + 1:] if l.strip() != ""]

        # replace or append new translation
        target_prefix = f"{LANGUAGE_FLAGS.get(lang, ' ❓')}"
        replaced = False
        new_extra = []
        for l in extra_lines:
            if l.startswith(target_prefix):
                new_extra.append(new_translation_line)
                replaced = True
            else:
                new_extra.append(l)
        if not replaced:
            new_extra.append(new_translation_line)

        final_visible = "\n".join([header_line, original_line, "", vi_line] + new_extra)
        bot.edit_message_text(final_visible, chat_id=chat_id, message_id=msg_id,
                              reply_markup=call.message.reply_markup, parse_mode="HTML")
        bot.answer_callback_query(call.id, f"Đã dịch sang {lang.upper()}!")

        # persist mapping unchanged
        MESSAGE_DATA[key] = data_storage
        save_message_data()

    except Exception as e:
        print("Error in callback:", e)
        traceback.print_exc()
        try:
            bot.answer_callback_query(call.id, f"Lỗi: {e}")
        except:
            pass

# ---------- Webhook endpoint ----------
@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    if request.headers.get("content-type") == "application/json":
        update = types.Update.de_json(request.data.decode("utf-8"))
        bot.process_new_updates([update])
    return "OK", 200

# ---------- Run ----------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)


