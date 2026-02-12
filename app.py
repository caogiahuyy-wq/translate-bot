# app.py — Full Telegram bot with Unicode-safe PDF (default ch12.pdf)
import os
import json
import requests
import threading
import tempfile
import traceback
from io import BytesIO
from flask import Flask, request, jsonify
from google.cloud import secretmanager
import psycopg2
from psycopg2 import extras
from fpdf import FPDF
from PIL import Image

app = Flask(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else None

PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
CLOUD_SQL_CONNECTION_NAME = os.environ.get("CLOUD_SQL_CONNECTION_NAME", "")
DB_USER = os.environ.get("DB_USER", "bot-user")
DB_NAME = os.environ.get("DB_NAME", "telegram_users")

ADMIN_USER_ID = os.environ.get("ADMIN_USER_ID", None)

PDF_CONVERSATION_STATE = {}

# TOPIC_MAP (example entries)
TOPIC_MAP = {
    ("-1003048051082", 394): {"target_group": "-1003167105880", "target_topic": 2},
    ("-1002975670789", 227): {"target_group": "-1003167105880", "target_topic": 2},
}

# AUTO_REPLY
AUTO_REPLY = {
    "hey huycon": " 👋  Xin chào! Tôi là Mr.HuyCon.",
    "huy con": "đây đây đây  🐧 ",
    "cảm ơn": "tuyệt  😎 ",
    "làm gì": "tôi đang chờ bạn ...",
    "mệt quá": "thả lỏng người, hít thật sâu... 3... 2... 1...",
    "đm": "không được nói bậy, biết chưa",
    "yes": "tuyệt  🚀 ",
    "ok": " 👌  Chuẩn!",
}

def _api_post(method: str, data=None, files=None, timeout=15):
    if not API_URL:
        print("⚠️ API_URL (BOT_TOKEN) chưa được cấu hình.")
        return None
    try:
        url = f"{API_URL}/{method}"
        r = requests.post(url, data=data, files=files, timeout=timeout)
        if r.status_code != 200:
            print(f"Telegram API {method} trả về {r.status_code}: {r.text}")
        return r
    except Exception as e:
        print(f"Exception khi gọi Telegram API {method}: {e}")
        return None

def send_message(chat_id, text, message_thread_id=None, parse_mode=None):
    payload = {"chat_id": chat_id, "text": text}
    if message_thread_id is not None:
        payload["message_thread_id"] = message_thread_id
    if parse_mode:
        payload["parse_mode"] = parse_mode
    return _api_post("sendMessage", data=payload)

def send_document(chat_id, document_bytes_or_fileid, filename=None, caption=None, message_thread_id=None):
    if isinstance(document_bytes_or_fileid, (bytes, bytearray, BytesIO)):
        files = {"document": (filename or "file.pdf", document_bytes_or_fileid, "application/pdf")}
        data = {"chat_id": chat_id}
        if message_thread_id: data["message_thread_id"] = message_thread_id
        if caption: data["caption"] = caption
        return _api_post("sendDocument", data=data, files=files)
    else:
        payload = {"chat_id": chat_id, "document": document_bytes_or_fileid}
        if message_thread_id: payload["message_thread_id"] = message_thread_id
        if caption: payload["caption"] = caption
        return _api_post("sendDocument", data=payload)

def send_photo(chat_id, photo_bytes_or_fileid, caption=None, message_thread_id=None):
    if isinstance(photo_bytes_or_fileid, (bytes, bytearray, BytesIO)):
        files = {"photo": ("photo.jpg", photo_bytes_or_fileid, "image/jpeg")}
        data = {"chat_id": chat_id}
        if message_thread_id: data["message_thread_id"] = message_thread_id
        if caption: data["caption"] = caption
        return _api_post("sendPhoto", data=data, files=files)
    else:
        payload = {"chat_id": chat_id, "photo": photo_bytes_or_fileid}
        if message_thread_id: payload["message_thread_id"] = message_thread_id
        if caption: payload["caption"] = caption
        return _api_post("sendPhoto", data=payload)

def send_video(chat_id, video_bytes_or_fileid, caption=None, message_thread_id=None):
    if isinstance(video_bytes_or_fileid, (bytes, bytearray, BytesIO)):
        files = {"video": ("video.mp4", video_bytes_or_fileid, "video/mp4")}
        data = {"chat_id": chat_id}
        if message_thread_id: data["message_thread_id"] = message_thread_id
        if caption: data["caption"] = caption
        return _api_post("sendVideo", data=data, files=files)
    else:
        payload = {"chat_id": chat_id, "video": video_bytes_or_fileid}
        if message_thread_id: payload["message_thread_id"] = message_thread_id
        if caption: payload["caption"] = caption
        return _api_post("sendVideo", data=payload)

def send_sticker(chat_id, sticker_fileid, message_thread_id=None):
    payload = {"chat_id": chat_id, "sticker": sticker_fileid}
    if message_thread_id: payload["message_thread_id"] = message_thread_id
    return _api_post("sendSticker", data=payload)

def get_file_info(file_id):
    r = _api_post("getFile", data={"file_id": file_id})
    if r and r.status_code == 200:
        try:
            j = r.json()
            if j.get("ok"):
                return j["result"]
        except Exception:
            pass
    return None

def download_file_from_telegram(file_id):
    info = get_file_info(file_id)
    if not info:
        print(f"Không lấy được file info cho file_id={file_id}")
        return None
    file_path = info.get("file_path")
    if not file_path:
        print(f"File info không có file_path cho file_id={file_id}")
        return None
    file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
    try:
        r = requests.get(file_url, timeout=20)
        if r.status_code == 200:
            return r.content
        else:
            print(f"Không tải được file từ Telegram: {r.status_code} {r.text}")
    except Exception as e:
        print(f"Exception khi tải file từ Telegram: {e}")
    return None

def get_db_password():
    if not PROJECT_ID:
        print("⚠️ PROJECT_ID không đặt. Secret Manager sẽ không được dùng.")
        return None
    try:
        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{PROJECT_ID}/secrets/telegram-db-password/versions/latest"
        response = client.access_secret_version(request={"name": name})
        return response.payload.data.decode("UTF-8")
    except Exception as e:
        print(f"❌ Lỗi get_db_password: {e}")
        return None

def get_db_connection():
    db_password = get_db_password()
    if not db_password:
        print("❌ Password DB không lấy được.")
        return None
    try:
        conn = psycopg2.connect(
            host=f"/cloudsql/{CLOUD_SQL_CONNECTION_NAME}" if CLOUD_SQL_CONNECTION_NAME else "127.0.0.1",
            user=DB_USER,
            password=db_password,
            database=DB_NAME,
            connect_timeout=5
        )
        return conn
    except Exception as e:
        print(f"❌ Lỗi kết nối DB: {e}")
        return None

def ensure_user_exists(telegram_user_id, username):
    conn = get_db_connection()
    if not conn:
        return None
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO users (telegram_user_id, username)
            VALUES (%s, %s)
            ON CONFLICT (telegram_user_id) DO UPDATE SET username = EXCLUDED.username, updated_at = CURRENT_TIMESTAMP
            RETURNING permission_level, allowed_topics;
        """, (telegram_user_id, username))
        res = cur.fetchone()
        conn.commit()
        cur.close()
        return res
    except Exception as e:
        print("❌ ensure_user_exists error:", e)
        try:
            conn.rollback()
        except:
            pass
    finally:
        conn.close()
    return None

def get_user_permissions(telegram_user_id):
    conn = get_db_connection()
    if not conn:
        return None
    try:
        cur = conn.cursor(cursor_factory=extras.RealDictCursor)
        cur.execute("SELECT permission_level, allowed_topics FROM users WHERE telegram_user_id = %s;", (telegram_user_id,))
        user_data = cur.fetchone()
        cur.close()
        return user_data
    except Exception as e:
        print("❌ get_user_permissions error:", e)
    finally:
        conn.close()
    return None

def update_user_permission_level(telegram_user_id, permission_level):
    conn = get_db_connection()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute("UPDATE users SET permission_level = %s, updated_at = CURRENT_TIMESTAMP WHERE telegram_user_id = %s;",
                    (permission_level, telegram_user_id))
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        print("❌ update_user_permission_level error:", e)
        try:
            conn.rollback()
        except:
            pass
    finally:
        conn.close()
    return False

def update_user_allowed_topics(telegram_user_id, topic_ids, action):
    conn = get_db_connection()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        if action == "add":
            cur.execute("""
                UPDATE users
                SET allowed_topics = array_distinct(array_cat(COALESCE(allowed_topics, '{}'::TEXT[]), %s::TEXT[])), updated_at = CURRENT_TIMESTAMP
                WHERE telegram_user_id = %s;
            """, (topic_ids, telegram_user_id))
        elif action == "remove":
            cur.execute("""
                UPDATE users
                SET allowed_topics = array_remove_many(COALESCE(allowed_topics, '{}'::TEXT[]), %s::TEXT[]), updated_at = CURRENT_TIMESTAMP
                WHERE telegram_user_id = %s;
            """, (topic_ids, telegram_user_id))
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        print("❌ update_user_allowed_topics error:", e)
    finally:
        conn.close()
    return False

def _ensure_fonts():
    import os, requests
    reg = "/tmp/DejaVuSans.ttf"
    bold = "/tmp/DejaVuSans-Bold.ttf"
    try:
        if not os.path.exists(reg):
            url_reg = "https://github.com/dejavu-fonts/dejavu-fonts/raw/master/ttf/DejaVuSans.ttf"
            r = requests.get(url_reg, timeout=20)
            with open(reg, "wb") as f:
                f.write(r.content)
        if not os.path.exists(bold):
            url_bold = "https://github.com/dejavu-fonts/dejavu-fonts/raw/master/ttf/DejaVuSans-Bold.ttf"
            r = requests.get(url_bold, timeout=20)
            with open(bold, "wb") as f:
                f.write(r.content)
    except Exception as e:
        print("⚠️ Could not download fonts:", e)
    return reg, bold

def process_and_send_pdf(chat_id, thread_id, collected_data, filename="ch12.pdf"):
    if not collected_data:
        send_message(chat_id, "❌ Không có ảnh/nội dung để tạo PDF.", thread_id)
        return

    try:
        reg_path, bold_path = _ensure_fonts()

        pdf = FPDF()
        pdf.add_page()

        try:
            pdf.add_font("DejaVuSans", "", reg_path, uni=True)
            pdf.add_font("DejaVuSans", "B", bold_path, uni=True)
            font_name = "DejaVuSans"
        except Exception:
            font_name = "Arial"

        pdf.set_font(font_name, size=14)
        pdf.cell(0, 10, txt="BÁO CÁO ẢNH TỔNG HỢP TỪ TELEGRAM", ln=True, align='C')
        pdf.line(10, 20, 200, 20)

        for idx, item in enumerate(collected_data):
            pdf.ln(6)
            if font_name == "DejaVuSans":
                pdf.set_font(font_name, style="B", size=12)
            else:
                pdf.set_font(font_name, size=12)
            pdf.multi_cell(0, 6, txt=f"Mục {idx+1}:", new_x="LMARGIN", new_y="NEXT")

            caption = item.get('caption', '') or ''
            pdf.set_font(font_name, size=10)
            pdf.multi_cell(0, 5, txt=f"Nội dung: {caption}")

            if item.get('type') == 'image':
                img_bytes = item.get('content')
                if not img_bytes:
                    pdf.multi_cell(0,5, txt="(Không thể tải ảnh)", new_x="LMARGIN", new_y="NEXT")
                    continue
                try:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tf:
                        tf.write(img_bytes)
                        temp_name = tf.name
                    pdf.image(temp_name, w=150)
                except Exception as ie:
                    pdf.multi_cell(0,5, txt=f"(Lỗi chèn ảnh: {ie})")
                finally:
                    try:
                        if 'temp_name' in locals() and os.path.exists(temp_name):
                            os.remove(temp_name)
                    except Exception:
                        pass
            elif item.get('type') == 'text':
                text_content = item.get('caption') or (item.get('content').decode('utf-8') if isinstance(item.get('content'), (bytes, bytearray)) else str(item.get('content')))
                pdf.multi_cell(0,5, txt=text_content)

        out = pdf.output(dest='S')
        pdf_bytes = out.encode('latin-1') if isinstance(out, str) else out
        send_document(chat_id, pdf_bytes, filename=filename, caption="Báo cáo ảnh tổng hợp đã sẵn sàng.", message_thread_id=thread_id)

    except Exception as e:
        print("❌ Lỗi process_and_send_pdf:", e)
        traceback.print_exc()
        send_message(chat_id, f"❌ Lỗi khi tạo báo cáo PDF: {e}", thread_id)

def handle_update(update):
    try:
        if "message" not in update:
            print("Received update without 'message' field.")
            return
        message = update["message"]
        chat = message.get("chat", {})
        chat_id = str(chat.get("id"))
        thread_id = message.get("message_thread_id")
        text = message.get("text") or message.get("caption") or ""
        photo_list = message.get("photo")
        caption = message.get("caption")
        chat_type = chat.get("type")
        from_user = message.get("from", {})
        telegram_user_id = str(from_user.get("id")) if from_user.get("id") else None
        username = from_user.get("username") or from_user.get("first_name") or ""

        print(f"Processing message from {telegram_user_id} in chat {chat_id} thread {thread_id}: '{(text or '')[:50]}'")

        if telegram_user_id:
            try:
                ensure_user_exists(telegram_user_id, username)
            except Exception as e:
                print("ensure_user_exists error:", e)

        current_state = PDF_CONVERSATION_STATE.get(chat_id, {'state': 0, 'data': []})

        if current_state['state'] == 1:
            if text and text.strip().lower().startswith("/done"):
                parts = text.split(maxsplit=1)
                filename_to_use = "ch12.pdf"
                if len(parts) > 1:
                    userfn = parts[1].strip()
                    if userfn and not userfn.lower().endswith(".pdf"):
                        userfn += ".pdf"
                    if userfn:
                        filename_to_use = userfn
                send_message(chat_id, f"✅ Đã nhận lệnh /done. Tên file: {filename_to_use}. Đang tạo PDF...", thread_id)
                data_to_process = current_state.get('data', [])
                PDF_CONVERSATION_STATE[chat_id] = {'state': 0, 'data': []}
                threading.Thread(target=process_and_send_pdf, args=(chat_id, thread_id, data_to_process, filename_to_use)).start()
                return

            if photo_list:
                file_id = photo_list[-1].get("file_id")
                image_bytes = download_file_from_telegram(file_id)
                processed_caption = caption or f"Ảnh {len(current_state.get('data', [])) + 1}: Không chú thích"
                if image_bytes:
                    current_state['data'].append({
                        'type': 'image',
                        'content': image_bytes,
                        'caption': processed_caption,
                        'mime_type': 'image/jpeg'
                    })
                    PDF_CONVERSATION_STATE[chat_id] = current_state
                    send_message(chat_id, f"Đã nhận 1 ảnh. Tổng: {len(current_state['data'])} mục. Gửi ảnh/nội dung tiếp theo hoặc /done [ten_file_pdf].", thread_id)
                else:
                    send_message(chat_id, "❌ Lỗi: không tải được ảnh từ Telegram.", thread_id)
                return

            if text and not text.strip().startswith("/"):
                current_state['data'].append({
                    'type': 'text',
                    'content': text,
                    'caption': text,
                    'mime_type': 'text/plain'
                })
                PDF_CONVERSATION_STATE[chat_id] = current_state
                send_message(chat_id, "Mr. HuyCon đang chờ ảnh, nội dung văn bản hoặc lệnh /done [ten_file_pdf].", thread_id)
                return

            send_message(chat_id, "Mr. HuyCon đang chờ ảnh, nội dung văn bản hoặc lệnh /done [ten_file_pdf].", thread_id)
            return

        if text and (text.strip().lower() == "/pdf" or text.strip().lower() == "/start_pdf"):
            if current_state.get('data'):
                send_message(chat_id, "⚠️ Đã phát hiện dữ liệu cũ chưa được xử lý. Dữ liệu này sẽ bị xóa. Bắt đầu phiên mới.", thread_id)
            PDF_CONVERSATION_STATE[chat_id] = {'state': 1, 'data': []}
            send_message(chat_id, "📄 Bắt đầu tạo file PDF. Gửi lần lượt ảnh (kèm chú thích) hoặc tin nhắn văn bản. Nhắn /done [Tên File Bạn Muốn] khi hoàn tất.", thread_id)
            return

        source_key = (chat_id, thread_id)
        if thread_id and source_key in TOPIC_MAP:
            mapping = TOPIC_MAP[source_key]
            target_chat = mapping.get("target_group")
            target_thread = mapping.get("target_topic")
            forward_caption = f"- User: @{username or 'ẩn danh'}"
            if text:
                send_message(target_chat, forward_caption + ("\n\n" + text if text else ""), target_thread)
                return
            if photo_list:
                file_id = photo_list[-1].get("file_id")
                send_photo(target_chat, file_id, caption=forward_caption + ("\n\n" + (caption or "")), message_thread_id=target_thread)
                return
            return

        if text:
            clean = text.lower()
            for kw, resp in AUTO_REPLY.items():
                if kw.lower() in clean:
                    send_message(chat_id, resp, thread_id)
                    return

        if text and text.strip().lower() == "/start":
            send_message(chat_id, "Xin chào! Tôi là bot quản lý. Hãy dùng lệnh /mypermission để kiểm tra quyền của bạn.", thread_id)
            return

    except Exception as e:
        print("❌ Fatal error in handle_update:", e)
        traceback.print_exc()
        try:
            if ADMIN_USER_ID:
                send_message(ADMIN_USER_ID, f"Bot gặp lỗi: {e}")
        except:
            pass

@app.route("/", methods=["GET"])
def index():
    return "Bot service is running.", 200

@app.route("/db-check", methods=["GET"])
def db_check():
    try:
        conn = get_db_connection()
        if conn:
            conn.close()
            return "Database connection OK.", 200
        return "Database connection failed.", 500
    except Exception as e:
        return f"Exception: {e}", 500

@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
    if not BOT_TOKEN:
        return "Token missing", 400
    try:
        update = request.get_json()
        if update:
            threading.Thread(target=handle_update, args=(update,)).start()
            return "OK", 200
        return "No update", 200
    except Exception as e:
        print("Webhook error:", e)
        return "Internal error", 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=True)
