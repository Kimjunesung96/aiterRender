from flask import Flask, session
from flask_session import Session
from threading import RLock

# ----------------------------
# Flask 앱 생성
# ----------------------------
app = Flask(__name__)
app.secret_key = "AIzaSyBh26hfl_c73QcUtrVn6ajjW8endz12Rhw"  # Render 배포 시 환경변수로 관리 가능
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_FILE_DIR'] = './.flask_session'
Session(app)

# Render에서 OPENPYXL 사용 여부 (xlsx 지원)
app.config['OPENPYXL_AVAILABLE'] = True

# ----------------------------
# 글로벌 Lock
# ----------------------------
data_lock = RLock()

# ----------------------------
# 고정 지침 (LaTeX 관련 등)
# ----------------------------
LATEX_FIX_INSTRUCTION = "LaTeX 문법을 유지하고 수식은 변형하지 마세요."

# ----------------------------
# Blueprint 등록
# ----------------------------
from routes_core import core_bp
from routes_quiz import quiz_bp

app.register_blueprint(core_bp)
app.register_blueprint(quiz_bp)

# ----------------------------
# 기본 라우트
# ----------------------------
@app.route("/")
def index():
    # 임시 로그인 세션 (Render에서 테스트용)
    if "folder_id" not in session:
        session["folder_id"] = "test_user"
    return "Render용 Flask 서버 실행 중. 세션 folder_id: {}".format(session['folder_id'])

# ----------------------------
# 앱 실행 (Render에서는 gunicorn 등 사용)
# ----------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

# 📌 파일이 짧아진 이유: 원래 여러 환경 체크, 로컬 OCR 설정, Windows 경로 처리 등 Render 불필요 코드 제거
