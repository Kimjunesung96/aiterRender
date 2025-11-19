from flask import Blueprint, request, jsonify, session
from datetime import datetime
import storage
import prompts
import google.generativeai as genai

quiz_bp = Blueprint('quiz', __name__)

@quiz_bp.route("/run_quiz", methods=["POST"])
def run_quiz():
    user_id = session.get('folder_id')
    if not user_id:
        return jsonify({"success":False,"error":"로그인 필요"}),401
    data = request.get_json()
    action = data.get("action")
    qa_cache = storage.load_qa_cache(user_id)
    all_text = storage.load_all_text_from_data(user_id)
    context = ""
    question_text = ""

    if action=="quiz_all":
        context = all_text
        question_text="전체 파일 퀴즈"
        system_content = prompts.QUIZ_ALL_PROMPT.format(context_to_use=context)
    elif action=="quiz_selected":
        selected_files = data.get("selected_files",[])
        context = ""
        for f in selected_files:
            text = storage.get_text_from_single_file(user_id,f)
            if text:
                context+=f"---{f}---\n{text}\n"
        question_text=f"선택 파일 퀴즈 ({', '.join(selected_files)})"
        system_content = prompts.QUIZ_SELECTED_PROMPT.format(context_to_use=context)
    else:
        return jsonify({"success":False,"error":"알 수 없는 퀴즈 작업"}),400

    model = genai.GenerativeModel("gemini-flash-latest", system_instruction=system_content)
    response = model.generate_content(f"{question_text} 생성")
    answer = response.text.strip().replace("\n","<br>")
    cache_key = f"{action}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    qa_cache[cache_key]={"answer":answer,"question_text":question_text,"action_type":action,
                         "timestamp":datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    storage.save_qa_cache(user_id,qa_cache)
    return jsonify({"success":True,"answer":answer,"question_text":question_text})

# 📌 파일이 짧아진 이유: 기존 채점, 오답노트 기능은 유지 → PDF 이미지 OCR 등 로컬 OCR 제거 → Gemini OCR로 통합
