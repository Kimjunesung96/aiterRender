import os
import json
import time
import fitz  # PyMuPDF
import pptx
from flask import session, current_app
import google.generativeai as genai 

try:
    from app import data_lock
except ImportError:
    import threading
    data_lock = threading.RLock()

# 설정값
BASE_DATA_DIR = "data"
BASE_CACHE_DIR = "cache"
ALLOWED_EXTENSIONS = {'pdf', 'pptx', 'png', 'jpg', 'jpeg', 'txt', 'xlsx'}

# --- [기존 경로/캐시 로드 함수들 그대로 유지] ---
def get_user_data_path(user_id):
    path = os.path.join(BASE_DATA_DIR, user_id)
    os.makedirs(path, exist_ok=True)
    return path

def get_user_cache_path(user_id, cache_type="qa"):
    os.makedirs(BASE_CACHE_DIR, exist_ok=True)
    return os.path.join(BASE_CACHE_DIR, f"{cache_type}_{user_id}.json")

def load_qa_cache(user_id):
    qa_cache_file = get_user_cache_path(user_id, "qa")
    if os.path.exists(qa_cache_file):
        try:
            with open(qa_cache_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_qa_cache(user_id, qa_cache):
    qa_cache_file = get_user_cache_path(user_id, "qa")
    with data_lock:
        try:
            with open(qa_cache_file, 'w', encoding='utf-8') as f:
                json.dump(qa_cache, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"💥 [Cache] QA Save Error: {e}")

def load_ocr_cache(user_id):
    ocr_cache_file = get_user_cache_path(user_id, "ocr")
    if os.path.exists(ocr_cache_file):
        try:
            with open(ocr_cache_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_ocr_cache(user_id, ocr_cache):
    ocr_cache_file = get_user_cache_path(user_id, "ocr")
    with data_lock:
        try:
            with open(ocr_cache_file, 'w', encoding='utf-8') as f:
                json.dump(ocr_cache, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"💥 [Cache] OCR Save Error: {e}")

def load_odapnote(user_id):
    odapnote_file = get_user_cache_path(user_id, "odap")
    if os.path.exists(odapnote_file):
        try:
            with open(odapnote_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_odapnote(user_id, odapnote_list):
    odapnote_file = get_user_cache_path(user_id, "odap")
    with data_lock:
        try:
            with open(odapnote_file, 'w', encoding='utf-8') as f:
                json.dump(odapnote_list, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"💥 [Cache] Odap Save Error: {e}")

def get_supported_files(user_id):
    user_data_path = get_user_data_path(user_id)
    if not os.path.exists(user_data_path):
        return []
    return sorted([f for f in os.listdir(user_data_path) 
                   if any(f.lower().endswith(ext) for ext in ALLOWED_EXTENSIONS)])

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- [텍스트 추출 함수 (Gemini OCR)] ---
def get_text_from_single_file(user_id, filename, force_ocr=False):
    user_data_path = get_user_data_path(user_id)
    ocr_cache = load_ocr_cache(user_id)
    file_path = os.path.join(user_data_path, filename)
    
    # 1. 캐시 확인 (강제 OCR 아닐 때만)
    if not force_ocr:
        with data_lock:
            cached_text = ocr_cache.get(filename)
        if cached_text:
            return cached_text
            
    print(f"🧠 [Auto-OCR] '{filename}' 분석 시작 (Gemini API)...")

    if not os.path.exists(file_path):
        return None
        
    full_text = ""
    try:
        # (A) PDF/이미지 -> Gemini
        if filename.lower().endswith(('.pdf', '.png', '.jpg', '.jpeg')):
            sample_file = genai.upload_file(path=file_path, display_name=filename)
            
            # 대기
            while sample_file.state.name == "PROCESSING":
                time.sleep(0.5)
                sample_file = genai.get_file(sample_file.name)

            if sample_file.state.name == "FAILED":
                raise ValueError("Gemini processing failed")

            model = genai.GenerativeModel("gemini-1.5-flash") 
            response = model.generate_content([
                "Extract all text from this file verbatim. Do not summarize.", 
                sample_file
            ])
            full_text = response.text
            
            try:
                genai.delete_file(sample_file.name)
            except:
                pass

        # (B) 로컬 처리 (PPTX, TXT, Excel)
        elif filename.lower().endswith('.pptx'):
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
                        row_text = [str(cell.value) for cell in row if cell.value is not None]
                        full_text += " ".join(row_text) + "\n"
                wb.close()

        if full_text:
            with data_lock:
                ocr_cache[filename] = full_text
                save_ocr_cache(user_id, ocr_cache)
            print(f"✅ [Auto-OCR] '{filename}' 분석 완료.")
            return full_text
            
    except Exception as e:
        print(f"❌ [Auto-OCR Error] {filename}: {e}")
        return None
    return None

# --- [!! 핵심 수정 !!] 통합 텍스트 로드 함수 ---
def load_all_text_from_data(user_id):
    """
    파일이 있는데 캐시가 없으면 -> 자동으로 OCR을 돌려서라도 텍스트를 가져옵니다.
    이제 '답변 안 하려고 드는' 현상이 사라집니다.
    """
    print(f"🔄 [Storage] '{user_id}' 통합 텍스트 준비 중...")
    temp_text_list = []
    
    current_files = get_supported_files(user_id)
    ocr_cache = load_ocr_cache(user_id) # 현재 캐시 상태 로드
    
    for filename in current_files:
        # 1. 캐시 확인
        text = ocr_cache.get(filename)
        
        # 2. 캐시에 없으면? -> 즉시 자동 분석 시작! (이게 빠져있었습니다)
        if not text:
            print(f"⚡️ [Smart-Load] '{filename}' 캐시 없음 -> 자동 OCR 수행")
            text = get_text_from_single_file(user_id, filename)
            # 수행 후 캐시가 갱신되었으므로 다시 로드할 필요는 없지만, 메모리상의 text 변수는 채워짐.

        # 3. 텍스트가 확보되었으면 리스트에 추가
        if text: 
            temp_text_list.append(f"--- {filename} 시작 ---\n{text}\n--- {filename} 끝 ---")
                
    all_file_text = "\n\n".join(temp_text_list)
    return all_file_text

def get_categorized_cache(qa_cache):
    # (기존과 동일)
    ask_list, summarize_list, quiz_list, mindmap_list = [], [], [], []
    sorted_items = sorted(qa_cache.items(), key=lambda item: item[1].get('timestamp', '0'), reverse=True)
    for key, value in sorted_items:
        action_type = value.get('action_type', 'ask')
        if action_type in ['ask', 'quiz_file']:
            ask_list.append({'key': key, 'value': value})
        elif action_type in ['extract_answer', 'extract_all']:
            summarize_list.append({'key': key, 'value': value})
        elif action_type in ['quiz_all', 'quiz_selected', 'quiz_weakness', 'grade_quiz', 'analyze_weakness']:
            quiz_list.append({'key': key, 'value': value})
        elif action_type == 'generate_mindmap':
            mindmap_list.append({'key': key, 'value': value})
    return ask_list, summarize_list, quiz_list, mindmap_list