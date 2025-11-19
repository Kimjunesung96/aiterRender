import os
import json
from flask import current_app
from PIL import Image
from threading import RLock
import google.generativeai as genai  # Gemini OCR 포함

# 글로벌 Lock (app.py와 공유)
try:
    from app import data_lock
except ImportError:
    data_lock = RLock()

# ----------------------------
# 설정값
# ----------------------------
BASE_DATA_DIR = "data"
BASE_CACHE_DIR = "cache"
ALLOWED_EXTENSIONS = {'pdf', 'pptx', 'png', 'jpg', 'jpeg', 'txt', 'xlsx'}
MIN_IMAGE_WIDTH = 100
MIN_IMAGE_HEIGHT = 100

# ----------------------------
# 경로/캐시 관리
# ----------------------------
def get_user_data_path(user_id):
    path = os.path.join(BASE_DATA_DIR, user_id)
    os.makedirs(path, exist_ok=True)
    return path

def get_user_cache_path(user_id, cache_type="qa"):
    os.makedirs(BASE_CACHE_DIR, exist_ok=True)
    return os.path.join(BASE_CACHE_DIR, f"{cache_type}_{user_id}.json")

def load_qa_cache(user_id):
    path = get_user_cache_path(user_id, "qa")
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_qa_cache(user_id, qa_cache):
    path = get_user_cache_path(user_id, "qa")
    with data_lock:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(qa_cache, f, ensure_ascii=False, indent=4)

def load_ocr_cache(user_id):
    path = get_user_cache_path(user_id, "ocr")
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_ocr_cache(user_id, ocr_cache):
    path = get_user_cache_path(user_id, "ocr")
    with data_lock:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(ocr_cache, f, ensure_ascii=False, indent=4)

def load_odapnote(user_id):
    path = get_user_cache_path(user_id, "odap")
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return []
    return []

def save_odapnote(user_id, odapnote_list):
    path = get_user_cache_path(user_id, "odap")
    with data_lock:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(odapnote_list, f, ensure_ascii=False, indent=4)

# ----------------------------
# 파일 관리
# ----------------------------
def get_supported_files(user_id):
    path = get_user_data_path(user_id)
    if not os.path.exists(path):
        return []
    return sorted([f for f in os.listdir(path) if any(f.lower().endswith(ext) for ext in ALLOWED_EXTENSIONS)])

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ----------------------------
# 텍스트 추출 (PDF/이미지 PPTX/TXT/XLSX)
# Gemini OCR 사용
# ----------------------------
def get_text_from_single_file(user_id, filename, force_ocr=False):
    user_path = get_user_data_path(user_id)
    ocr_cache = load_ocr_cache(user_id)
    file_path = os.path.join(user_path, filename)

    if not force_ocr and filename in ocr_cache:
        return ocr_cache[filename]

    if not os.path.exists(file_path) or not allowed_file(filename):
        return None

    full_text = ""
    try:
        if filename.lower().endswith(('.png', '.jpg', '.jpeg', '.pdf')):
            # Gemini OCR 호출
            with open(file_path, "rb") as f:
                content = f.read()
            response = genai.ocr(content)
            full_text = response.text.strip()

        elif filename.lower().endswith('.pptx'):
            import pptx
            prs = pptx.Presentation(file_path)
            for slide in prs.slides:
                for shape in slide.shapes:
                    if hasattr(shape, "text"):
                        full_text += shape.text + "\n"

        elif filename.lower().endswith('.txt'):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    full_text = f.read()
            except UnicodeDecodeError:
                with open(file_path, 'r', encoding='cp949') as f:
                    full_text = f.read()

        elif filename.lower().endswith('.xlsx'):
            if current_app.config.get('OPENPYXL_AVAILABLE', False):
                import openpyxl
                wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
                for sheet_name in wb.sheetnames:
                    sheet = wb[sheet_name]
                    for row in sheet.iter_rows():
                        full_text += " ".join([str(c.value) for c in row if c.value is not None]) + "\n"
                wb.close()

        with data_lock:
            ocr_cache[filename] = full_text
            save_ocr_cache(user_id, ocr_cache)

        return full_text
    except Exception as e:
        with data_lock:
            ocr_cache[filename] = ""
            save_ocr_cache(user_id, ocr_cache)
        return None

def load_all_text_from_data(user_id):
    files = get_supported_files(user_id)
    ocr_cache = load_ocr_cache(user_id)
    texts = []
    with data_lock:
        for f in files:
            if f in ocr_cache and ocr_cache[f]:
                texts.append(f"--- {f} 시작 ---\n{ocr_cache[f]}\n--- {f} 끝 ---")
    return "\n\n".join(texts)

def get_categorized_cache(qa_cache):
    ask_list = []
    summarize_list = []
    quiz_list = []
    mindmap_list = []
    sorted_items = sorted(qa_cache.items(), key=lambda x: x[1].get('timestamp','0'), reverse=True)
    for k,v in sorted_items:
        t = v.get('action_type','ask')
        if t in ['ask','quiz_file']:
            ask_list.append({'key':k,'value':v})
        elif t in ['extract_answer','extract_all']:
            summarize_list.append({'key':k,'value':v})
        elif t in ['quiz_all','quiz_selected','quiz_weakness','grade_quiz','analyze_weakness']:
            quiz_list.append({'key':k,'value':v})
        elif t == 'generate_mindmap':
            mindmap_list.append({'key':k,'value':v})
    return ask_list,summarize_list,quiz_list,mindmap_list

# 📌 파일이 짧아진 이유: PyTesseract, 이미지 세부 처리 제거 → Gemini OCR로 통합, Render 환경 단순화
