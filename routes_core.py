from flask import Blueprint, request, render_template, jsonify, session, Response, stream_with_context
from datetime import datetime
import threading
import storage
import prompts
import google.generativeai as genai
from app import data_lock, LATEX_FIX_INSTRUCTION

core_bp = Blueprint('core', __name__)

# ----------------------------
# 메인 페이지 로드
# ----------------------------
@core_bp.route("/load_main_page", methods=["GET","POST"])
def load_main_page():
    user_id = session.get('folder_id')
    if not user_id:
        return "로그인 필요", 401

    qa_cache = storage.load_qa_cache(user_id)
    odapnote_list = storage.load_odapnote(user_id)
    supported_files = storage.get_supported_files(user_id)
    ocr_cache = storage.load_ocr_cache(user_id)

    return render_template("index.html",
                           answer="",
                           question_text="",
                           ask_list=[],
                           summarize_list=[],
                           quiz_list=[],
                           mindmap_list=[],
                           supported_files=supported_files,
                           odapnote_list=odapnote_list,
                           chat_history=[],
                           ocr_cache_keys=list(ocr_cache.keys()),
                           current_user=user_id)

# ----------------------------
# 스트리밍 Ask
# ----------------------------
@core_bp.route("/stream_ask", methods=["POST"])
def stream_ask():
    user_id = session.get('folder_id')
    if not user_id:
        return Response("Not Authenticated", mimetype='text/html')

    data = request.get_json()
    question_text = data.get("query","")
    source = data.get("source","main_form")

    context_to_use = storage.load_all_text_from_data(user_id)
    system_content = prompts.STREAM_ASK_PROMPT.format(context_to_use=context_to_use)

    model = genai.GenerativeModel("gemini-flash-latest", system_instruction=system_content)

    def generator():
        try:
            stream = model.generate_content([{"role":"user","parts":[question_text]}], stream=True)
            full_text = []
            for chunk in stream:
                text = chunk.text.replace("\n","<br>")
                full_text.append(chunk.text)
                yield text
            final_text = "".join(full_text).replace("\n","<br>")
            with data_lock:
                qa_cache = storage.load_qa_cache(user_id)
                cache_key = f"{question_text}_ask"
                qa_cache[cache_key] = {"answer":final_text,"question_text":question_text,"action_type":"ask",
                                       "timestamp":datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
                storage.save_qa_cache(user_id, qa_cache)
        except Exception as e:
            yield f"Error: {e}"

    return Response(stream_with_context(generator()), mimetype='text/html')

# ----------------------------
# 파일 업로드/삭제/OCR
# ----------------------------
@core_bp.route("/upload", methods=["POST"])
def upload_file():
    user_id = session.get('folder_id')
    if not user_id:
        return jsonify({"success":False,"error":"로그인 필요"}),401
    if 'file' not in request.files:
        return jsonify({"success":False,"error":"No file"}),400
    f = request.files['file']
    if f.filename=='':
        return jsonify({"success":False,"error":"No file selected"}),400
    if storage.allowed_file(f.filename):
        import os
        from werkzeug.utils import secure_filename
        filename = secure_filename(f.filename)
        user_path = storage.get_user_data_path(user_id)
        f.save(os.path.join(user_path, filename))
        return jsonify({"success":True,"filename":filename})
    return jsonify({"success":False,"error":"Not allowed"}),400

# 📌 파일이 짧아진 이유: PDF 이미지 OCR 처리 제거 → Gemini OCR 호출로 통합
