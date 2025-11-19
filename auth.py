import os
import json
import threading
from datetime import datetime  # [!! ★★★ 추가 ★★★ !!]
from flask import Blueprint, request, jsonify, session, redirect, url_for, flash, render_template
from werkzeug.security import generate_password_hash, check_password_hash

# 'auth'라는 이름의 Blueprint(청사진)를 생성합니다.
auth_bp = Blueprint('auth', __name__)

USERS_FILE = "users.json"
# users.json 파일 접근을 위한 전용 잠금(lock)입니다.
auth_lock = threading.Lock()

def load_users():
    """사용자 데이터를 스레드 안전하게 불러옵니다."""
    with auth_lock:
        if not os.path.exists(USERS_FILE):
            with open(USERS_FILE, 'w', encoding='utf-8') as f:
                json.dump({}, f)
            return {}
        try:
            with open(USERS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {}

def save_users(users_data):
    """사용자 데이터를 스레드 안전하게 저장합니다."""
    with auth_lock:
        with open(USERS_FILE, 'w', encoding='utf-8') as f:
            json.dump(users_data, f, ensure_ascii=False, indent=4)

@auth_bp.route("/login_folder", methods=["POST"])
def login_folder():
    """폴더 ID와 비밀번호로 로그인합니다."""
    folder_id = request.form.get('folder_id')
    password = request.form.get('password')

    if not folder_id or not password:
        flash("폴더 ID와 비밀번호를 모두 입력해야 합니다.")
        return redirect(url_for('index'))

    users = load_users()

    # 1. ID가 이미 있는 경우 (로그인 시도)
    if folder_id in users:
        if check_password_hash(users[folder_id]['password_hash'], password):
            # [성공] 비밀번호 일치
            session['folder_id'] = folder_id # 쿠키(세션)에 사용자 ID 저장
            flash(f"'{folder_id}' 폴더로 로그인했습니다.")
            print(f"✅ [Auth] '{folder_id}' 로그인 성공.")
        else:
            # [실패] 비밀번호 불일치
            flash("비밀번호가 틀렸습니다.")
            print(f"⚠️ [Auth] '{folder_id}' 로그인 실패: 비밀번호 불일치")
    else:
        # 2. ID가 없는 경우
        flash(f"'{folder_id}' 폴더가 존재하지 않습니다. [생성] 버튼을 눌러주세요.")
        print(f"⚠️ [Auth] '{folder_id}' 로그인 실패: 존재하지 않는 ID")

    return redirect(url_for('index'))

@auth_bp.route("/create_folder", methods=["POST"])
def create_folder():
    """새 폴더 ID와 비밀번호를 생성합니다."""
    folder_id = request.form.get('folder_id')
    password = request.form.get('password')

    if not folder_id or not password:
        flash("폴더 ID와 비밀번호를 모두 입력해야 합니다.")
        return redirect(url_for('index'))

    users = load_users()

    # 1. ID가 이미 있는 경우
    if folder_id in users:
        flash("이미 존재하는 폴더 ID입니다. 다른 ID를 사용해주세요.")
        print(f"⚠️ [Auth] '{folder_id}' 생성 실패: 이미 존재하는 ID")
    else:
        # 2. ID가 없는 경우 (신규 생성)
        new_user = {
            "password_hash": generate_password_hash(password),
            "created_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        users[folder_id] = new_user
        save_users(users)
        
        # [성공] 생성 후 바로 로그인 처리
        session['folder_id'] = folder_id
        flash(f"'{folder_id}' 폴더를 새로 만들고 로그인했습니다.")
        print(f"✅ [Auth] '{folder_id}' 생성 및 로그인 성공.")

    return redirect(url_for('index'))

@auth_bp.route("/logout")
def logout():
    """세션에서 folder_id를 제거하여 로그아웃합니다."""
    folder_id = session.pop('folder_id', None)
    if folder_id:
        print(f"✅ [Auth] '{folder_id}' 로그아웃.")
        flash("로그아웃되었습니다.")
    return redirect(url_for('index'))