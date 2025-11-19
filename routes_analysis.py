from flask import Blueprint, request, jsonify, session
from datetime import datetime 
import threading
import google.generativeai as genai

# [!! ★★★ 핵심 ★★★ !!]
from app import data_lock, LATEX_FIX_INSTRUCTION
import storage
import prompts

analysis_bp = Blueprint('analysis', __name__)

# ----------------------------
# [!! ★★★ 재설계 ★★★ !!]
# 분석/요약 관련 라우트
# ----------------------------

@analysis_bp.route("/run_analysis", methods=["POST"])
def run_analysis():
    """
    (개인화) '전체 핵심 추출' 또는 '연관 분석' 같은 오래 걸리는 작업을 처리.
    (기존 index()의 POST 로직을 분리)
    """
    user_id = session.get('folder_id')
    if not user_id:
        return jsonify({"success": False, "error": "로그인이 필요합니다."}), 401
    
    data = request.get_json()
    action_type = data.get("action")
    
    qa_cache = storage.load_qa_cache(user_id)
    all_file_text = storage.load_all_text_from_data(user_id)

    # ===============================================
    # 시나리오 1: 전체 파일 핵심 추출
    # ===============================================
    if action_type == "extract_all":
        print(f"\n🧠 [Analysis] '{user_id}' 전체 핵심 추출 요청...")
        cache_key = "global_extract_all"
        
        if cache_key in qa_cache:
            print(f"⚡️ [Analysis] '{user_id}' 캐시 HIT")
            return jsonify({"success": True, "status": "complete", "answer": qa_cache[cache_key]["answer"], "question_text": "전체 파일 핵심 추출"})
        
        if not all_file_text:
            return jsonify({"success": False, "error": "추출할 파일이 없습니다."})

        # (캐시 없음 -> 실시간 생성)
        try:
            print(f"💬 [Analysis] '{user_id}' Gemini API 요청 중...")
            system_content = prompts.EXTRACT_ALL_PROMPT.format(context_to_use=all_file_text)
            model = genai.GenerativeModel("gemini-flash-latest", system_instruction=system_content)
            response = model.generate_content("위 [전체 문서]의 모든 정보를 빠짐없이 추출해줘.")
            answer = response.text.strip().replace("\n", "<br>")
            
            qa_cache[cache_key] = {"answer": answer, "question_text": "전체 파일 핵심 추출", "action_type": action_type, "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S') }
            storage.save_qa_cache(user_id, qa_cache)
            
            return jsonify({"success": True, "status": "complete", "answer": answer, "question_text": "전체 파일 핵심 추출"})
        
        except Exception as e:
            return jsonify({"success": False, "error": str(e)})

    return jsonify({"success": False, "error": "알 수 없는 분석 작업입니다."})


# ----------------------------
# (개인화) 백그라운드 연관 분석 API
# ----------------------------
@analysis_bp.route("/generate_correlation_async", methods=["POST"])
def generate_correlation_async():
    user_id = session.get('folder_id')
    if not user_id:
        return jsonify({"success": False, "error": "로그인이 필요합니다."}), 401
        
    data = request.get_json()
    selected_files = data.get('selected_files', [])

    if not selected_files:
        return jsonify({"success": False, "error": "파일을 1개 이상 선택해주세요."})

    cache_key = "mindmap_v3_" + "_".join(sorted(selected_files))
    question_text = f"[연관 분석] ({', '.join(selected_files)})"

    qa_cache = storage.load_qa_cache(user_id)
    
    # 1. 캐시 확인 (HIT)
    if cache_key in qa_cache:
        print(f"⚡️ [Analysis] '{user_id}' 비동기 캐시 HIT")
        answer = qa_cache[cache_key]["answer"]
        return jsonify({"success": True, "status": "complete", "answer": answer, "question_text": question_text})
    
    # 2. 캐시 없음 (MISS) -> 백그라운드 작업 시작
    print(f"🧠 [Analysis] '{user_id}' 비동기 캐시 MISS, 백그라운드 작업 시작: {selected_files}")
    
    def background_correlation_task(u_id, files, key, q_text):
        print(f"🧵 [BG-Analysis] '{u_id}/{key}' 생성 작업 시작...")
        context_to_use = ""
        try:
            # (RLock 상태에서 storage 함수들 호출)
            for filename in files:
                file_text = storage.get_text_from_single_file(u_id, filename) 
                if file_text:
                    context_to_use += f"--- {filename} 시작 ---\n{file_text}\n--- {filename} 끝 ---\n\n"
            
            if not context_to_use:
                print(f"🧵 [BG-Analysis 오류] '{u_id}/{key}' 텍스트 추출 실패.")
                return

            print(f"💬 [BG-Analysis] '{u_id}/{key}' Gemini API 요청 중...")
            system_content = prompts.CORRELATION_PROMPT.format(context_to_use=context_to_use)
            model = genai.GenerativeModel("gemini-flash-latest", system_instruction=system_content)
            response = model.generate_content("위 내용을 바탕으로 주제별 연관 관계를 상세히 분석해줘.")
            answer = response.text.strip()
            
            # 캐시 저장
            current_qa_cache = storage.load_qa_cache(u_id) # 최신 캐시 다시 읽기
            current_qa_cache[key] = {
                "answer": answer, 
                "question_text": q_text,
                "action_type": "generate_mindmap", 
                "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S') 
            }
            storage.save_qa_cache(u_id, current_qa_cache)
            print(f"✅ [BG-Analysis] '{u_id}/{key}' 생성 및 캐시 저장 완료.")

        except Exception as e:
            print(f"💥 [BG-Analysis 오류] '{u_id}/{key}' 생성 실패: {e}")

    # 4. 백그라운드 스레드 시작
    ocr_thread = threading.Thread(
        target=background_correlation_task, 
        args=(user_id, selected_files, cache_key, question_text)
    )
    ocr_thread.start()
    
    # 5. "작업 시작됨" 알림을 0.1초 만에 즉시 반환
    return jsonify({"success": True, "status": "processing", "message": "연관 분석 작업을 백그라운드에서 시작했습니다. 1~2분 후 버튼을 다시 눌러주세요."})