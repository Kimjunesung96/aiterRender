from flask import Blueprint, request, render_template, redirect, url_for, jsonify, Response, stream_with_context, session, flash, current_app
from werkzeug.utils import secure_filename
from collections import deque
from datetime import datetime 
import threading
import os
from urllib.parse import unquote

# [!! ★★★ 핵심 ★★★ !!]
# app.py에서 생성된 app과 data_lock을 import합니다.
from app import app, data_lock, LATEX_FIX_INSTRUCTION
# storage.py와 prompts.py에서 헬퍼 함수와 프롬프트를 import합니다.
# storage.py와 prompts.py에서 헬퍼 함수와 프롬프트를 import합니다.
import storage
import prompts
import google.generativeai as genai # [!! ★★★ 추가 ★★★ !!]

# 'core'라는 이름의 Blueprint(청사진)를 생성합니다.
core_bp = Blueprint('core', __name__)

# ----------------------------
# [!! ★★★ 재설계 ★★★ !!]
# 핵심 라우트 (메인 페이지 로드, 스트리밍, 파일 관리)
# ----------------------------

@core_bp.route("/load_main_page", methods=["GET", "POST"])
def load_main_page():
    """
    (개인화) 로그인한 사용자의 메인 페이지 데이터를 불러옵니다.
    (현재는 스트리밍이 아닌 '현재 퀴즈내기' 등 동기식 버튼 처리를 담당)
    """
    
    # [!! ★★★ 핵심 ★★★ !!]
    # 이제 모든 함수는 세션(쿠키)에서 사용자 ID를 가져옵니다.
    user_id = session.get('folder_id')
    if not user_id:
        flash("세션이 만료되었습니다. 다시 로그인해주세요.")
        return redirect(url_for('index'))

    answer = ""
    question_text = ""
    
    # (참고: GET 요청은 app.py의 index()에서 이미 처리되었습니다)

    # [POST 요청]
    if request.method == "POST":
        question_text = request.form.get("query", "")
        action_type = request.form.get("action", "ask")
        previous_answer_html = request.form.get("previous_answer", "")
        original_question_text = question_text 
        
        qa_cache = storage.load_qa_cache(user_id)
        odapnote_list = storage.load_odapnote(user_id)
        all_file_text = storage.load_all_text_from_data(user_id)
        
        try:
            # ===============================================
            # 시나리오 1: 답변 핵심 추출
            # ===============================================
            if action_type == "extract_answer":
                print(f"\n🧠 [Core] '{user_id}' 답변 핵심 추출 요청...")
                if not previous_answer_html or previous_answer_html == "(답변이 여기에 표시됩니다.)":
                    answer = "추출할 답변이 없습니다."
                else:
                    previous_answer_text = previous_answer_html.replace("<br>", "\n").strip()
                    cache_key = f"[요약] {original_question_text}_{previous_answer_text[:50]}"
                    
                    if cache_key in qa_cache:
                        answer = qa_cache[cache_key]["answer"]
                        question_text = qa_cache[cache_key]["question_text"]
                    else:
                        system_content = prompts.EXTRACT_ANSWER_PROMPT.format(previous_answer_text=previous_answer_text)
                        model = genai.GenerativeModel("gemini-flash-latest", system_instruction=system_content)
                        response = model.generate_content("위 [텍스트]의 모든 정보를 빠짐없이 추출해줘.")
                        answer = response.text.strip().replace("\n", "<br>")
                        
                        question_text = f"[요약] {original_question_text}" 
                        qa_cache[cache_key] = { "answer": answer, "question_text": question_text, "action_type": "extract_answer", "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S') }
                        storage.save_qa_cache(user_id, qa_cache)

            # ===============================================
            # [!! ★★★ 롤백 ★★★ !!] 'quiz_context' -> 'quiz_file'
            # ===============================================
            elif action_type == "quiz_file":
                print(f"\n🧠 [Core] '{user_id}' 파일 퀴즈 요청...")
                target_filename = original_question_text.strip()
                if not target_filename:
                    answer = "퀴즈를 낼 파일 이름을 질문창에 정확히 입력해주세요."
                else:
                    context_text = storage.get_text_from_single_file(user_id, target_filename) # RLock으로 안전
                    
                    if context_text is None:
                         answer = f"'{target_filename}'... 파일명을 찾을 수 없거나 텍스트를 추출할 수 없습니다."
                    else:
                        system_content = prompts.QUIZ_SELECTED_PROMPT.format(context_to_use=context_text) # 선택 퀴즈 프롬프트 재활용
                        model = genai.GenerativeModel("gemini-flash-latest", system_instruction=system_content)
                        response = model.generate_content(original_question_text)
                        answer = response.text.strip().replace("\n", "<br>")
                        
                        cache_key = f"{original_question_text}_{action_type}"
                        qa_cache[cache_key] = { "answer": answer, "question_text": original_question_text, "action_type": action_type, "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S') }
                        storage.save_qa_cache(user_id, qa_cache)
            
            # (기타 비-스트리밍 액션들)

        except Exception as e:
            answer = f"❌ 전체 프로세스 오류: {e}" 

        # --- 최종 렌더링 (POST 요청의 결과) ---
        ask_list, summarize_list, quiz_list, mindmap_list = storage.get_categorized_cache(qa_cache)
        supported_files = storage.get_supported_files(user_id)
        ocr_cache = storage.load_ocr_cache(user_id)
        
        return render_template("index.html", 
                               answer=answer, question_text=original_question_text, 
                               ask_list=ask_list, summarize_list=summarize_list,
                               quiz_list=quiz_list, 
                               mindmap_list=mindmap_list,
                               supported_files=supported_files,
                               odapnote_list=odapnote_list,
                               chat_history=[], # (2단계에서 구현)
                               ocr_cache_keys=list(ocr_cache.keys()),
                               current_user=user_id)

# ----------------------------
# (개인화) 스트리밍 엔드포인트
# ----------------------------
@core_bp.route("/stream_ask", methods=["POST"])
def stream_ask():
    user_id = session.get('folder_id')
    if not user_id:
        return Response("❌ Error: Not Authenticated", mimetype='text/html')

    data = request.get_json()
    question_text = data.get("query", "")
    source = data.get("source", "main_form") 
    cache_key = f"{question_text}_ask"
    
    qa_cache = storage.load_qa_cache(user_id)
    
    # 1. 캐시 확인 (이제 'ask'는 캐시 사용 안 함)
    # (맥락이 매번 바뀌므로 캐시가 의미 없음)
    
    # 2. API 호출
    print(f"\n🧠 [Stream] '{user_id}' 스트리밍 요청 (Source: {source})")
    
    previous_answer_html = data.get("previous_answer", "")
    context_to_use = ""
    system_content = ""
    
    context_is_from_main_window = False
    
    # [!! ★★★ 롤백 ★★★ !!]
    # 'main_form'은 항상 '전체 파일' 맥락을 사용합니다.
    if source == 'main_form':
        print(f"🧠 [Stream] '메인 폼(Ask)' 요청. '전체 파일' 맥락을 사용합니다.")
        context_to_use = storage.load_all_text_from_data(user_id)
        system_content = prompts.STREAM_ASK_PROMPT.format(context_to_use=context_to_use) 
    
    # [!! ★★★ 롤백 ★★★ !!]
    # 'floating_widget'만 '현재 맥락'을 확인합니다.
    elif source == 'floating_widget':
        if previous_answer_html and previous_answer_html != "(답변이 여기에 표시됩니다.)":
            # 1. 플로팅 위젯 + 현재 맥락 O -> '채팅' 프롬프트
            print(f"⚡️ [Stream] '플로팅 위젯(Chat)' 요청. '현재 맥락'을 사용합니다.")
            context_to_use = previous_answer_html.replace("<br>", "\n").strip() 
            system_content = prompts.STREAM_CHAT_PROMPT.format(context_to_use=context_to_use)
        else:
            # 2. 플로팅 위젯 + 현재 맥락 X -> '질문' 프롬프트
            print(f"🧠 [Stream] '플로팅 위젯(Ask)' 요청. '전체 파일' 맥락을 사용합니다.")
            context_to_use = storage.load_all_text_from_data(user_id)
            system_content = prompts.STREAM_ASK_PROMPT.format(context_to_use=context_to_use)
    
    else:
        # 3. 비상 사태
        print(f"⚠️ [Stream] 알 수 없는 Source: {source}. '전체 파일' 맥락을 사용합니다.")
        context_to_use = storage.load_all_text_from_data(user_id)
        system_content = prompts.STREAM_ASK_PROMPT.format(context_to_use=context_to_use) 

    # 'context_to_use'가 비어있는 경우 최종 처리
    if not context_to_use:
        context_to_use = "죄송합니다. 'data' 폴더에 분석할 파일이 없습니다. (OCR 캐시가 비어있습니다)"
        # 프롬프트를 다시 포맷팅 (어떤 프롬프트가 선택되었든 다시 덮어씀)
        if source == 'floating_widget' and previous_answer_html and previous_answer_html != "(답변이 여기에 표시됩니다.)":
             system_content = prompts.STREAM_CHAT_PROMPT.format(context_to_use=context_to_use)
        else:
             system_content = prompts.STREAM_ASK_PROMPT.format(context_to_use=context_to_use)
    

    model = genai.GenerativeModel("gemini-flash-latest", system_instruction=system_content)
    
    # 3. 스트림 생성기 정의
    def stream_generator():
        try:
            gemini_history = [{"role": "user", "parts": [question_text]}]
            
            stream = model.generate_content(gemini_history, stream=True)
            full_answer = []
            
            for chunk in stream:
                text_chunk = chunk.text.replace("\n", "<br>")
                full_answer.append(chunk.text) 
                yield text_chunk
            
            final_answer_raw = "".join(full_answer)
            final_answer_html = final_answer_raw.replace("\n", "<br>")

            # 'main_form'이 보낸 질문은 캐시 저장
            if source == 'main_form':
                current_qa_cache = storage.load_qa_cache(user_id)
                current_qa_cache[cache_key] = {
                    "answer": final_answer_html, 
                    "question_text": question_text, 
                    "action_type": "ask", 
                    "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S') 
                }
                storage.save_qa_cache(user_id, current_qa_cache)
                print(f"✅ [Stream] '{user_id}' API 응답 및 '메인' 캐시 저장 완료.")
            else:
                # 플로팅 위젯은 캐시 저장 안 함
                print(f"✅ [Stream] '{user_id}' API 응답 완료 (보조 질문창 - 캐시 저장 안 함).")

        except Exception as e:
            print(f"💥 [Stream] '{user_id}' 생성기 오류: {e}")
            yield f"❌ Gemini API 스트림 오류: {e}"

    return Response(stream_with_context(stream_generator()), mimetype='text/html')

# ----------------------------
# (개인화) 업로드/삭제/OCR API
# ----------------------------
@core_bp.route("/upload", methods=["POST"])
def upload_file():
    user_id = session.get('folder_id')
    if not user_id:
        return jsonify({"success": False, "error": "로그인이 필요합니다."}), 401

    if 'file' not in request.files:
        return jsonify({"success": False, "error": "No file part"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"success": False, "error": "No selected file"}), 400
        
    if file and storage.allowed_file(file.filename):
        try:
            filename = secure_filename(file.filename)
            user_data_path = storage.get_user_data_path(user_id)
            filepath = os.path.join(user_data_path, filename)
            
            file.save(filepath)
            print(f"✅ [Upload] '{user_id}/{filename}' 저장 완료. 수동 OCR이 필요합니다.")
            return jsonify({"success": True, "filename": filename})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
    else:
        return jsonify({"success": False, "error": "File type not allowed"}), 400

@core_bp.route("/delete_file", methods=["POST"])
def delete_file():
    user_id = session.get('folder_id')
    if not user_id:
        return jsonify({"success": False, "error": "로그인이 필요합니다."}), 401

    try:
        data = request.get_json()
        filename = data.get('filename') 
        if not filename:
            return jsonify({"success": False, "error": "Filename is missing"}), 400
        
        filename = os.path.basename(filename) 
        user_data_path = storage.get_user_data_path(user_id)
        filepath = os.path.join(user_data_path, filename)
        
        print(f"🗑️ [Delete] '{user_id}/{filename}' 삭제 요청...")
        
        with data_lock:
            # 1. 파일 삭제
            if os.path.exists(filepath):
                os.remove(filepath)
                print(f"  - (1/2) '{user_id}/{filename}' 파일 시스템에서 삭제 완료.")
            
            # 2. OCR 캐시 삭제
            ocr_cache = storage.load_ocr_cache(user_id)
            if filename in ocr_cache:
                del ocr_cache[filename]
                storage.save_ocr_cache(user_id, ocr_cache)
                print(f"  - (2/2) OCR 캐시에서 '{user_id}/{filename}' 삭제 완료.")
            
        return jsonify({"success": True, "filename": filename})
    except Exception as e:
        print(f"💥 [Delete] '{user_id}/{filename}' 파일 삭제 오류: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@core_bp.route("/run_ocr", methods=["POST"])
def run_ocr():
    user_id = session.get('folder_id')
    if not user_id:
        return jsonify({"success": False, "error": "로그인이 필요합니다."}), 401

    data = request.get_json()
    filename = data.get('filename')
    if not filename:
        return jsonify({"success": False, "error": "Filename is missing"}), 400
    
    filename = os.path.basename(filename)
    
    def background_ocr_task(u_id, fname):
        print(f"🧵 [OCR] '{u_id}/{fname}' 백그라운드 작업 시작...")
        storage.get_text_from_single_file(u_id, fname, force_ocr=True) 
        print(f"✅ [OCR] '{u_id}/{fname}' 백그라운드 작업 완료.")

    # (스레드 시작)
    ocr_thread = threading.Thread(target=background_ocr_task, args=(user_id, filename))
    ocr_thread.start()
    
    print(f"✅ [OCR] '{user_id}/{filename}' 백그라운드 처리 시작. 즉시 응답.")
    return jsonify({"success": True, "message": "OCR processing started"})


# ----------------------------
# (개인화) 기록 삭제 API
# ----------------------------
@core_bp.route("/delete_history", methods=["POST"])
def delete_history():
    """
    [!! ★★★ 신규 추가 ★★★ !!]
    (개인화) Q&A 캐시(qa_cache)에서 특정 항목을 삭제합니다.
    index.html의 'x' 버튼이 호출합니다.
    """
    user_id = session.get('folder_id')
    if not user_id:
        return jsonify({"success": False, "error": "로그인이 필요합니다."}), 401

    try:
        data = request.get_json()
        key_to_delete = data.get('key') 
        if not key_to_delete:
            return jsonify({"success": False, "error": "Key is missing"}), 400
        
        # (참고) URL-Safe 문자가 포함될 수 있으므로 unquote
        key_to_delete = unquote(key_to_delete)
        
        print(f"🗑️ [Core] '{user_id}' Q&A 캐시 삭제 요청: {key_to_delete}")

        qa_cache = storage.load_qa_cache(user_id)
        
        if key_to_delete in qa_cache:
            del qa_cache[key_to_delete]
            storage.save_qa_cache(user_id, qa_cache)
            print(f"✅ [Core] '{user_id}' Q&A 캐시 삭제 완료.")
            return jsonify({"success": True})
        else:
            print(f"⚠️ [Core] '{user_id}' Q&A 캐시 삭제 실패: 키를 찾을 수 없음")
            return jsonify({"success": False, "error": "Key not found"}), 404

    except Exception as e:
        print(f"💥 [Core] Q&A 캐시 삭제 오류: {e}")
        return jsonify({"success": False, "error": str(e)}), 500