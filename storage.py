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

# ... [기본 경로/캐시 로드/저장 함수들은 기존과 동일하게 유지 (생략)] ...
# (get_user_data_path, load_qa_cache, save_qa_cache 등등...)
# ... [스크롤 압박을 줄이기 위해 위쪽 헬퍼 함수들은 생략했습니다. 기존 코드 그대로 두세요.] ...

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
            with open(qa_cache_file, 'r', encoding='utf-8') as f: return json.load(f)
        except: return {}
    return {}

def save_qa_cache(user_id, qa_cache):
    qa_cache_file = get_user_cache_path(user_id, "qa")
    with data_lock:
        try:
            with open(qa_cache_file, 'w', encoding='utf-8') as f: json.dump(qa_cache, f, ensure_ascii=False, indent=4)
        except Exception as e: print(f"💥 Error: {e}")

def load_ocr_cache(user_id):
    ocr_cache_file = get_user_cache_path(user_id, "ocr")
    if os.path.exists(ocr_cache_file):
        try:
            with open(ocr_cache_file, 'r', encoding='utf-8') as f: return json.load(f)
        except: return {}
    return {}

def save_ocr_cache(user_id, ocr_cache):
    ocr_cache_file = get_user_cache_path(user_id, "ocr")
    with data_lock:
        try:
            with open(ocr_cache_file, 'w', encoding='utf-8') as f: json.dump(ocr_cache, f, ensure_ascii=False, indent=4)
        except Exception as e: print(f"💥 Error: {e}")

def load_odapnote(user_id):
    odapnote_file = get_user_cache_path(user_id, "odap")
    if os.path.exists(odapnote_file):
        try:
            with open(odapnote_file, 'r', encoding='utf-8') as f: return json.load(f)
        except: return []
    return []

def save_odapnote(user_id, odapnote_list):
    odapnote_file = get_user_cache_path(user_id, "odap")
    with data_lock:
        try:
            with open(odapnote_file, 'w', encoding='utf-8') as f: json.dump(odapnote_list, f, ensure_ascii=False, indent=4)
        except Exception as e: print(f"💥 Error: {e}")

def get_supported_files(user_id):
    user_data_path = get_user_data_path(user_id)
    if not os.path.exists(user_data_path): return []
    return sorted([f for f in os.listdir(user_data_path) if any(f.lower().endswith(ext) for ext in ALLOWED_EXTENSIONS)])

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# --- [!! 핵심 수정 !!] 수동 OCR 전략 ---
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
            
    print(f"🧠 [Analysis] '{filename}' 분석 시작... (Force_OCR={force_ocr})")

    if not os.path.exists(file_path):
        return None
        
    full_text = ""
    
    try:
        # ==================================================
        # [상황 1] 사용자가 [OCR] 버튼을 누름 (force_ocr=True)
        # ==================================================
        if force_ocr:
            # (무조건 Gemini에게 보냄)
            if filename.lower().endswith(('.pdf', '.png', '.jpg', '.jpeg')):
                print(f"🚀 [Manual-OCR] '{filename}' Gemini 전송 중...")
                sample_file = genai.upload_file(path=file_path, display_name=filename)
                while sample_file.state.name == "PROCESSING":
                    time.sleep(0.5)
                    sample_file = genai.get_file(sample_file.name)
                
                if sample_file.state.name == "FAILED": raise ValueError("Gemini failed")
                
                model = genai.GenerativeModel("gemini-1.5-flash") 
                response = model.generate_content(["Extract everything.", sample_file])
                full_text = response.text
                try: genai.delete_file(sample_file.name) 
                except: pass
            else:
                # PPT, TXT 등은 로컬 방식으로 처리 (기존 유지)
                pass 

        # ==================================================
        # [상황 2] 자동 파싱 (버튼 안 누름)
        # ==================================================
        else:
            # (A) PDF -> 텍스트 추출 시도
            if filename.lower().endswith('.pdf'):
                try:
                    doc = fitz.open(file_path)
                    for page in doc: full_text += page.get_text() + "\n"
                    doc.close()
                except: pass

                # [!! 핵심 !!] 텍스트가 너무 적으면? -> "OCR 추천 메시지"를 텍스트로 저장
                if len(full_text.strip()) < 50:
                    print(f"⚠️ [Image-PDF] '{filename}' 텍스트 부족. OCR 추천 플래그 반환.")
                    # 이 메시지가 나중에 프롬프트에 들어가서 AI가 대답하게 됨
                    return "[SYSTEM_FLAG: NEED_OCR]" 

            # (B) 이미지 파일 -> 무조건 OCR 추천
            elif filename.lower().endswith(('.png', '.jpg', '.jpeg')):
                return "[SYSTEM_FLAG: NEED_OCR]"

            # (C) PPTX, TXT 등 -> 로컬 파싱
            elif filename.lower().endswith('.pptx'):
                prs = pptx.Presentation(file_path)
                for slide in prs.slides:
                    for shape in slide.shapes:
                        if hasattr(shape, "text"): full_text += shape.text + "\n"
            
            elif filename.lower().endswith('.txt'):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f: full_text = f.read()
                except:
                    with open(file_path, 'r', encoding='cp949') as f: full_text = f.read()
            
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

        # 결과 저장 (성공한 텍스트만 캐시에 저장)
        if full_text and len(full_text.strip()) > 0:
            with data_lock:
                ocr_cache[filename] = full_text
                save_ocr_cache(user_id, ocr_cache)
            return full_text
            
    except Exception as e:
        print(f"❌ Error: {e}")
        return None
    return None

# --- [자동 감지] ---
def load_all_text_from_data(user_id):
    temp_text_list = []
    current_files = get_supported_files(user_id)
    ocr_cache = load_ocr_cache(user_id)
    
    for filename in current_files:
        text = ocr_cache.get(filename)
        if not text:
            # 캐시 없으면 1차 파싱 시도 (파싱 실패시 'NEED_OCR' 플래그가 옴)
            text = get_text_from_single_file(user_id, filename)

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