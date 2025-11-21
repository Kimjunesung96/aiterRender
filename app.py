from flask import Flask, session, render_template, request, redirect, url_for, flash
import threading
import os
import storage
from urllib.parse import unquote

# 1. 앱과 잠금 생성
app = Flask(__name__)
data_lock = threading.RLock()

# 세션 비밀 키
app.secret_key = 'super-secret-key-please-change-this' 

# LaTeX 수정 지시어
LATEX_FIX_INSTRUCTION = "[중요 지시]: 절대로 \\msubGt, \\msubRt 같은 \\msub... 코드를 사용하지 마세요. 항상 $G_t$, $R_t$ 처럼 정상적인 LaTeX 수식($...$ 또는 $$...$$)을 사용하세요."

# ----------------------------
# [!! 중요 !!] Tesseract 관련 설정 삭제됨
# ----------------------------
# 이제 서버에 Tesseract를 설치할 필요가 없습니다.

# ----------------------------
# Google Gemini API 설정
# ----------------------------
try:
    import google.generativeai as genai
    # [주의] 배포 환경 변수 또는 여기에 직접 키 입력
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "AIzaSyBh26hfl_c73QcUtrVn6ajjW8endz12Rhw") 
    genai.configure(api_key=GEMINI_API_KEY)
    print("✅ Google Gemini API 키 설정 완료.")
except Exception as e:
    print(f"💥 [오류] Gemini API 설정 실패: {e}")

# ----------------------------
# Excel 라이브러리 확인
# ----------------------------
try:
    import openpyxl
    app.config['OPENPYXL_AVAILABLE'] = True
    print("✅ 'openpyxl' (Excel 라이브러리) 로드 성공.")
except ImportError:
    app.config['OPENPYXL_AVAILABLE'] = False
    print("⚠️ 'openpyxl' 라이브러리를 찾을 수 없습니다. .xlsx 파일은 처리할 수 없습니다.")
    
# ----------------------------
# 블루프린트 등록
# ----------------------------
try:
    from auth import auth_bp
    from routes_core import core_bp
    from routes_analysis import analysis_bp
    from routes_quiz import quiz_bp
    
    app.register_blueprint(auth_bp)
    app.register_blueprint(core_bp)
    app.register_blueprint(analysis_bp)
    app.register_blueprint(quiz_bp)
    print("✅ [Init] 모든 API 블루프린트 로드 성공.")
except ImportError as e:
    print(f"💥 [Init] 블루프린트 import 실패: {e}")
    print("   필수 파일들이 모두 존재하는지 확인하세요.")

# ----------------------------
# 로그인 확인 (미들웨어)
# ----------------------------
@app.before_request
def require_login():
    if request.path.startswith('/static'):
        return
    if request.endpoint not in ['auth.login_folder', 'auth.create_folder', 'index']:
        if 'folder_id' not in session:
            flash("먼저 폴더 ID로 로그인하거나 새 폴더를 생성해야 합니다.")
            return redirect(url_for('index'))

# ----------------------------
# 메인 페이지 라우트
# ----------------------------
@app.route("/")
def index():
    current_user = session.get('folder_id')
    
    if current_user:
        qa_cache = storage.load_qa_cache(current_user)
        odapnote_list = storage.load_odapnote(current_user)
        
        cache_key = request.args.get('cache_key')
        odap_key = request.args.get('odap_key')
        
        answer = ""
        question_text = ""

        if cache_key:
            cache_key = unquote(cache_key)
            if cache_key in qa_cache:
                answer = qa_cache[cache_key].get('answer', '')
                question_text = qa_cache[cache_key].get('question_text', '')
        elif odap_key:
            try:
                odap_index = int(odap_key)
                if 0 <= odap_index < len(odapnote_list):
                    answer = odapnote_list[odap_index].get('content', '')
                    question_text = f"[{odapnote_list[odap_index].get('timestamp', '')} 오답노트]"
            except ValueError:
                pass
        
        try:
            ask_list, summarize_list, quiz_list, mindmap_list = storage.get_categorized_cache(qa_cache)
        except AttributeError:
            ask_list, summarize_list, quiz_list, mindmap_list = [], [], [], []

        supported_files = storage.get_supported_files(current_user)
        ocr_cache = storage.load_ocr_cache(current_user)
        
        return render_template("index.html", 
                                current_user=current_user,
                                answer=answer,
                                question_text=question_text,
                                ask_list=ask_list, 
                                summarize_list=summarize_list,
                                quiz_list=quiz_list, 
                                mindmap_list=mindmap_list,
                                supported_files=supported_files,
                                odapnote_list=odapnote_list,
                                chat_history=[],
                                ocr_cache_keys=list(ocr_cache.keys())
                                )
    else:
        return render_template("index.html", current_user=current_user)

# ----------------------------
# 캐시 제어
# ----------------------------
@app.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

# ----------------------------
# 서버 실행
# ----------------------------
if __name__ == "__main__":
    print("🚀 Flask 서버 시작 중... (http://127.0.0.1:5000)")
    if not os.path.exists("data"):
        os.makedirs("data")
    if not os.path.exists("cache"):
        os.makedirs("cache")
        
    app.run(debug=False, host='0.0.0.0', threaded=True)