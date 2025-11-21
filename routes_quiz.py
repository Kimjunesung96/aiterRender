from flask import Blueprint, request, jsonify, session
from datetime import datetime 
import google.generativeai as genai

# [!! ★★★ 핵심 ★★★ !!]
from app import data_lock, LATEX_FIX_INSTRUCTION
import storage
import prompts

quiz_bp = Blueprint('quiz', __name__)

# ----------------------------
# [!! ★★★ 재설계 ★★★ !!]
# 퀴즈/오답노트 관련 라우트
# ----------------------------

@quiz_bp.route("/run_quiz", methods=["POST"])
def run_quiz():
    """ (개인화) '전체 퀴즈', '선택 퀴즈', '약점 퀴즈' 생성 """
    user_id = session.get('folder_id')
    if not user_id:
        return jsonify({"success": False, "error": "로그인이 필요합니다."}), 401

    data = request.get_json()
    action_type = data.get("action")
    
    qa_cache = storage.load_qa_cache(user_id)
    all_file_text = storage.load_all_text_from_data(user_id)
    
    context_to_use = ""
    question_text = ""
    
    try:
        # ===============================================
        # 시나리오 1: 전체 파일 퀴즈
        # ===============================================
        if action_type == "quiz_all":
            print(f"\n🧠 [Quiz] '{user_id}' 전체 파일 퀴즈 요청...")
            context_to_use = all_file_text
            question_text = "전체 파일 퀴즈"
            if not context_to_use:
                return jsonify({"success": False, "error": "퀴즈를 낼 파일이 없습니다."})
            
            system_content = prompts.QUIZ_ALL_PROMPT.format(context_to_use=context_to_use)

        # ===============================================
        # 시나리오 2: 선택 파일 퀴즈
        # ===============================================
        elif action_type == "quiz_selected":
            print(f"\n🧠 [Quiz] '{user_id}' 선택 파일 퀴즈 요청...")
            selected_files = data.get("selected_files", [])
            if not selected_files:
                return jsonify({"success": False, "error": "파일을 1개 이상 선택해주세요."})
            
            question_text = f"선택 파일 퀴즈 ({', '.join(selected_files)})"
            for filename in selected_files:
                file_text = storage.get_text_from_single_file(user_id, filename)
                if file_text:
                    context_to_use += f"--- {filename} 시작 ---\n{file_text}\n--- {filename} 끝 ---\n\n"
            
            if not context_to_use:
                return jsonify({"success": False, "error": "선택한 파일에서 텍스트를 찾을 수 없습니다."})
            
            system_content = prompts.QUIZ_SELECTED_PROMPT.format(context_to_use=context_to_use)

        # ===============================================
        # 시나리오 3: 약점 퀴즈
        # ===============================================
        elif action_type == "quiz_weakness":
            print(f"\n🧠 [Quiz] '{user_id}' 약점 퀴즈 요청...")
            odapnote_list = storage.load_odapnote(user_id)
            if not odapnote_list:
                return jsonify({"success": False, "error": "퀴즈를 낼 오답노트가 비어있습니다."})
            
            context_to_use = "\n\n".join([item['content'].replace("<br>", "\n") for item in odapnote_list])
            question_text = "오답노트 기반 약점 퀴즈"
            system_content = prompts.QUIZ_WEAKNESS_PROMPT.format(odap_content=context_to_use)
            
        # ===============================================
        # 시나리오 4: 취약점 분석 (신규 추가)
        # ===============================================
        elif action_type == "analyze_weakness":
            print(f"\n🧠 [Quiz] '{user_id}' 취약점 분석 요청...")
            odapnote_list = storage.load_odapnote(user_id)
            if not odapnote_list:
                return jsonify({"success": False, "error": "분석할 오답노트가 비어있습니다."})
            
            # ANALYZE_WEAKNESS_PROMPT는 '오답'과 '원본' 둘 다 필요
            odap_content = "\n\n".join([item['content'].replace("<br>", "\n") for item in odapnote_list])
            context_to_use = all_file_text # 원본 문서
            
            question_text = "오답노트 기반 취약점 분석"
            system_content = prompts.ANALYZE_WEAKNESS_PROMPT.format(odap_content=odap_content, context_to_use=context_to_use)

        else:
            return jsonify({"success": False, "error": "알 수 없는 퀴즈 작업입니다."})

        # --- Gemini API 호출 공통 로직 ---
        print(f"💬 [Quiz] '{user_id}' Gemini API 요청 ({action_type})...")
        model = genai.GenerativeModel("gemini-flash-latest", system_instruction=system_content)
        response = model.generate_content(f"{question_text} 생성해줘.")
        answer = response.text.strip().replace("\n", "<br>")

        # --- 캐시 저장 공통 로직 ---
        cache_key = f"{action_type}_{datetime.now().strftime('%Y%m%d%H%M%S')}" 
        qa_cache[cache_key] = {
            "answer": answer, "question_text": question_text,
            "action_type": action_type, "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S') 
        }
        storage.save_qa_cache(user_id, qa_cache)
        
        return jsonify({"success": True, "status": "complete", "answer": answer, "question_text": question_text})

    except Exception as e:
        print(f"💥 [Quiz] '{user_id}' 퀴즈 생성 실패: {e}")
        return jsonify({"success": False, "error": str(e)})


@quiz_bp.route("/grade_quiz", methods=["POST"])
def grade_quiz():
    """ (개인화) 퀴즈 채점 및 오답노트 저장 """
    user_id = session.get('folder_id')
    if not user_id:
        return jsonify({"success": False, "error": "로그인이 필요합니다."}), 401
        
    print(f"\n🧠 [Quiz] '{user_id}' 퀴즈 채점 요청...")
    data = request.get_json()
    quiz_questions_html = data.get("previous_answer", "")
    user_answers_text = data.get("query", "")
    
    all_file_text = storage.load_all_text_from_data(user_id)

    if not quiz_questions_html or quiz_questions_html == "(답변이 여기에 표시됩니다.)":
        return jsonify({"success": False, "error": "채점할 퀴즈가 없습니다."})
    if not user_answers_text.strip():
        return jsonify({"success": False, "error": "제출할 답안을 입력해주세요."})
    if not all_file_text:
        return jsonify({"success": False, "error": "채점 기준이 될 원본 파일이 없습니다."})

    try:
        print(f"💬 [Quiz] '{user_id}' 1/2: 퀴즈 채점 API 요청 중...")
        quiz_questions_text = quiz_questions_html.replace("<br>", "\n").strip()
        
        system_content_grader = prompts.GRADE_QUIZ_PROMPT.format(context_to_use=all_file_text, quiz_questions_text=quiz_questions_text)
        model_grader = genai.GenerativeModel("gemini-flash-latest", system_instruction=system_content_grader)
        response_grader = model_grader.generate_content(f"[사용자 답안]\n{user_answers_text}")
        
        answer_text = response_grader.text.strip()
        answer = answer_text.replace("\n", "<br>") 
        print(f"✅ [Quiz] '{user_id}' 1/2: 채점 완료.")
        
        if "(X)" in answer_text:
            print(f"💬 [Quiz] '{user_id}' 2/2: 오답 추출 API 요청 중...")
            system_content_extractor = prompts.EXTRACT_ERRORS_PROMPT.format(answer_text=answer_text)
            model_extractor = genai.GenerativeModel("gemini-flash-latest", system_instruction=system_content_extractor)
            response_extractor = model_extractor.generate_content("위 [채점 결과]에서 틀린 문제만 모두 추출해줘.")
            extracted_errors = response_extractor.text.strip()
            
            if "추출할 오답이 없습니다." not in extracted_errors and extracted_errors:
                new_odap_entry = {
                    "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M'),
                    "content": extracted_errors.replace("\n", "<br>")
                }
                odapnote_list = storage.load_odapnote(user_id)
                odapnote_list.append(new_odap_entry)
                storage.save_odapnote(user_id, odapnote_list)
                print(f"✅ [Quiz] '{user_id}' 2/2: 오답노트 저장 완료.")
        
        return jsonify({"success": True, "status": "complete", "answer": answer, "question_text": "퀴즈 채점 결과"})

    except Exception as e:
        print(f"💥 [Quiz] '{user_id}' 채점 실패: {e}")
        return jsonify({"success": False, "error": str(e)})


@quiz_bp.route("/delete_odapnote", methods=["POST"])
def delete_odapnote():
    """ (개인화) 오답노트 삭제 """
    user_id = session.get('folder_id')
    if not user_id:
        return jsonify({"success": False, "error": "로그인이 필요합니다."}), 401

    try:
        data = request.get_json()
        key_index = data.get('key') 
        if key_index is None:
            return jsonify({"success": False, "error": "Key index is missing"}), 400
            
        key_index = int(key_index)
        print(f"🗑️ [Quiz] '{user_id}' 오답노트 {key_index}번째 항목 삭제 요청...")

        odapnote_list = storage.load_odapnote(user_id)
        if 0 <= key_index < len(odapnote_list):
            del odapnote_list[key_index] 
            storage.save_odapnote(user_id, odapnote_list)
            print("✅ [Quiz] 오답노트 삭제 완료.")
        else:
            print("💡 [Quiz] 잘못된 인덱스입니다.")
            return jsonify({"success": False, "error": "Invalid index"}), 400

        return jsonify({"success": True})
    except Exception as e:
        print(f"💥 [Quiz] 오답노트 삭제 오류: {e}")
        return jsonify({"success": False, "error": str(e)}), 500