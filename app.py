import streamlit as st
import pandas as pd
from datetime import datetime
import altair as alt
import gspread
import calendar
import textwrap
import hashlib
import secrets

# -----------------------------------------------------------------------------
# 커스텀 CSS 스타일링
# -----------------------------------------------------------------------------
def apply_custom_css():
    # CSS 스타일링 제거 - 기본 Streamlit 스타일 사용
    pass

# -----------------------------------------------------------------------------
# 인증 관련 헬퍼 함수
# -----------------------------------------------------------------------------
def hash_password(password, salt=None):
    """비밀번호 해싱 (SHA-256 + Salt)"""
    if salt is None:
        salt = secrets.token_hex(16)
    return hashlib.sha256((password + salt).encode()).hexdigest(), salt

def verify_password(stored_password, stored_salt, provided_password):
    """비밀번호 검증"""
    return stored_password == hashlib.sha256((provided_password + stored_salt).encode()).hexdigest()

def get_users_worksheet(spreadsheet):
    """Users 시트 가져오기 (없으면 생성)"""
    try:
        return spreadsheet.worksheet("Users")
    except:
        ws = spreadsheet.add_worksheet(title="Users", rows=100, cols=5)
        ws.append_row(["username", "password_hash", "salt", "created_at"])
        return ws

def load_users():
    """사용자 목록 불러오기"""
    spreadsheet = get_gsheet_connection()
    if not spreadsheet:
        return {}
    
    try:
        ws = get_users_worksheet(spreadsheet)
        records = ws.get_all_records()
        # username을 키로 하는 dict 반환
        return {r['username']: r for r in records}
    except Exception as e:
        st.error(f"사용자 데이터 로드 실패: {e}")
        return {}

def register_user(username, password):
    """사용자 등록"""
    spreadsheet = get_gsheet_connection()
    if not spreadsheet:
        return False, "Google Sheets 연결 실패"
    
    try:
        ws = get_users_worksheet(spreadsheet)
        # 중복 확인
        existing_users = ws.col_values(1) # 첫 번째 컬럼 (username)
        if username in existing_users:
            return False, "이미 존재하는 아이디입니다."
        
        password_hash, salt = hash_password(password)
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        ws.append_row([username, password_hash, salt, created_at])
        return True, "회원가입 성공!"
    except Exception as e:
        return False, f"회원가입 실패: {e}"

# -----------------------------------------------------------------------------
# Google Sheets 연동 헬퍼 함수
# -----------------------------------------------------------------------------
def get_gsheet_connection():
    """Google Sheets 연결 객체 반환 (실패 시 None)"""
    if "gcp_service_account" not in st.secrets or "sheet" not in st.secrets:
        return None
    
    try:
        # st.secrets를 dict로 변환하여 gspread에 전달
        credentials = dict(st.secrets["gcp_service_account"])
        gc = gspread.service_account_from_dict(credentials)
        sh = gc.open_by_url(st.secrets["sheet"]["url"])
        return sh  # 전체 스프레드시트 객체 반환
    except Exception as e:
        st.error(f"Google Sheets 연결 오류: {e}")
        return None

def load_data():
    """데이터 불러오기 (Sheets -> DataFrame)"""
    # 뱅크샐러드 스타일 스키마 + 앱 전용 '세부구분'
    columns = ['날짜', '시간', '타입', '대분류', '소분류', '내용', '금액', '화폐', '결제수단', '메모', '세부구분']
    
    spreadsheet = get_gsheet_connection()
    if spreadsheet:
        try:
            worksheet = spreadsheet.sheet1  # 첫 번째 시트 사용
            data = worksheet.get_all_records()
            if data:
                df = pd.DataFrame(data)
                
                # --- 마이그레이션 로직 ---
                # 1. '구분' -> '타입'
                if '구분' in df.columns and '타입' not in df.columns:
                    df.rename(columns={'구분': '타입'}, inplace=True)
                
                # 2. '카테고리' -> '대분류'
                if '카테고리' in df.columns and '대분류' not in df.columns:
                    df.rename(columns={'카테고리': '대분류'}, inplace=True)
                
                # 3. '카드명' 병합 (기존 '결제수단'이 단순 '신용카드' 등이고 '카드명'에 실제 카드 이름이 있는 경우)
                if '카드명' in df.columns:
                    if '결제수단' in df.columns:
                        # 카드명이 있으면 결제수단으로 사용, 없으면 기존 결제수단 유지
                        df['결제수단'] = df.apply(lambda x: x['카드명'] if x['카드명'] and x['카드명'] != '-' else x['결제수단'], axis=1)
                    else:
                        df['결제수단'] = df['카드명']
                
                # 4. 신규 컬럼 기본값 설정
                if '시간' not in df.columns:
                    df['시간'] = '00:00'
                if '소분류' not in df.columns:
                    df['소분류'] = ''
                if '화폐' not in df.columns:
                    df['화폐'] = 'KRW'
                if '세부구분' not in df.columns:
                    df['세부구분'] = '-' # 기본값

                # -----------------------

                # 데이터 타입 명시적 변환
                if '날짜' in df.columns:
                    df['날짜'] = pd.to_datetime(df['날짜'])
                
                # 텍스트 컬럼들을 문자열로 변환
                text_columns = ['타입', '대분류', '소분류', '내용', '화폐', '결제수단', '메모', '세부구분']
                for col in text_columns:
                    if col in df.columns:
                        df[col] = df[col].astype(str)
                
                # 금액은 숫자형으로 변환
                if '금액' in df.columns:
                    df['금액'] = pd.to_numeric(df['금액'], errors='coerce').fillna(0).astype(int)
                
                # 필수 컬럼 확인 및 보정
                for col in columns:
                    if col not in df.columns:
                        if col == '금액':
                            df[col] = 0
                        else:
                            df[col] = ""
                
                # '시간' 컬럼을 datetime.time 객체로 변환 (데이터 에디터 호환성)
                if '시간' in df.columns:
                    # 1. 문자열로 변환 (이미 문자열일 수 있지만 안전하게)
                    df['시간'] = df['시간'].astype(str)
                    # 2. datetime 객체로 변환 후 time 부분만 추출
                    # 형식이 안맞는 경우 00:00:00으로 처리
                    def parse_time(t_str):
                        try:
                            return pd.to_datetime(t_str, format='%H:%M:%S').time()
                        except:
                            try:
                                return pd.to_datetime(t_str, format='%H:%M').time()
                            except:
                                return datetime.strptime('00:00', '%H:%M').time()
                                
                    df['시간'] = df['시간'].apply(parse_time)

                # 5. 지출 금액 음수 처리 (마이그레이션)
                if '타입' in df.columns and '금액' in df.columns:
                    # 지출이면서 금액이 양수인 경우 음수로 변환
                    mask = (df['타입'] == '지출') & (df['금액'] > 0)
                    df.loc[mask, '금액'] = df.loc[mask, '금액'] * -1

                return df[columns] # 컬럼 순서 정렬
        except Exception as e:
            st.warning(f"데이터 불러오기 실패 (로컬 모드로 시작): {e}")
            
    return pd.DataFrame(columns=columns)

def save_data_to_sheet(df):
    """데이터 저장하기 (DataFrame -> Sheets)"""
    spreadsheet = get_gsheet_connection()
    if spreadsheet:
        try:
            worksheet = spreadsheet.sheet1
            # 날짜를 문자열로 변환하여 저장 (JSON 직렬화 문제 방지)
            save_df = df.copy()
            if '날짜' in save_df.columns:
                save_df['날짜'] = save_df['날짜'].dt.strftime('%Y-%m-%d')
            
            # 시간도 문자열로 변환
            if '시간' in save_df.columns:
                save_df['시간'] = save_df['시간'].astype(str)
            
            # 시트 클리어 후 헤더 포함하여 전체 업데이트
            worksheet.clear()
            worksheet.update([save_df.columns.values.tolist()] + save_df.values.tolist())
        except Exception as e:
            st.error(f"데이터 저장 실패: {e}")

def load_settings():
    """설정 데이터 불러오기 (카테고리, 결제수단, 카드정보)"""
    spreadsheet = get_gsheet_connection()
    if not spreadsheet:
        return None
    
    try:
        # 설정 시트 가져오기 (없으면 생성)
        try:
            settings_sheet = spreadsheet.worksheet("설정")
        except:
            settings_sheet = spreadsheet.add_worksheet(title="설정", rows=100, cols=10)
            # 초기 헤더 설정
            settings_sheet.update('A1:C1', [['타입', '키', '값']])
        
        data = settings_sheet.get_all_records()
        if not data:
            return None
        
        settings = {
            'cat_income': [],
            'cat_expense': [],
            'cat_saving': [],
            'payment_methods': [],
            'cards_info': {},
            'available_years': []
        }
        
        for row in data:
            type_val = row.get('타입', '')
            key = row.get('키', '')
            value = row.get('값', '')
            
            if type_val == 'cat_income':
                settings['cat_income'].append(value)
            elif type_val == 'cat_expense':
                settings['cat_expense'].append(value)
            elif type_val == 'cat_saving':
                settings['cat_saving'].append(value)
            elif type_val == 'payment_methods':
                settings['payment_methods'].append(value)
            elif type_val == 'available_years':
                settings['available_years'].append(int(value))
            elif type_val == 'card_tier':
                # 카드 정보는 JSON 형태로 저장
                import json
                card_name = key
                if card_name not in settings['cards_info']:
                    settings['cards_info'][card_name] = []
                settings['cards_info'][card_name] = json.loads(value)
        
        return settings
    except Exception as e:
        st.warning(f"설정 불러오기 실패: {e}")
        return None

def save_settings_to_sheet():
    """설정 데이터 저장하기"""
    spreadsheet = get_gsheet_connection()
    if not spreadsheet:
        return
    
    try:
        # 설정 시트 가져오기 (없으면 생성)
        try:
            settings_sheet = spreadsheet.worksheet("설정")
        except:
            settings_sheet = spreadsheet.add_worksheet(title="설정", rows=100, cols=10)
        
        # 데이터 준비
        rows = [['타입', '키', '값']]
        
        # 카테고리 저장
        for cat in st.session_state['cat_income']:
            rows.append(['cat_income', '', cat])
        for cat in st.session_state['cat_expense']:
            rows.append(['cat_expense', '', cat])
        for cat in st.session_state['cat_saving']:
            rows.append(['cat_saving', '', cat])
        
        # 결제수단 저장
        for method in st.session_state['payment_methods']:
            rows.append(['payment_methods', '', method])
        
        # 연도 목록 저장
        for year in st.session_state['available_years']:
            rows.append(['available_years', '', str(year)])
        
        # 카드 정보 저장
        import json
        for card_name, tiers in st.session_state['cards_info'].items():
            rows.append(['card_tier', card_name, json.dumps(tiers, ensure_ascii=False)])
        
        # 시트 클리어 후 업데이트
        settings_sheet.clear()
        settings_sheet.update(rows)
    except Exception as e:
        st.error(f"설정 저장 실패: {e}")

# -----------------------------------------------------------------------------
# 1. 초기 설정 및 데이터 관리 (Session State)
# -----------------------------------------------------------------------------
def init_session_state():
    # 로그인 상태 초기화
    if 'logged_in' not in st.session_state:
        st.session_state['logged_in'] = False
    if 'username' not in st.session_state:
        st.session_state['username'] = None

    # 기본 데이터 초기화
    if 'data' not in st.session_state:
        st.session_state['data'] = load_data()

    # 설정 데이터 불러오기 (구글 시트에서)
    loaded_settings = load_settings()
    
    # 카테고리 초기값
    if 'cat_income' not in st.session_state:
        if loaded_settings and loaded_settings['cat_income']:
            st.session_state['cat_income'] = loaded_settings['cat_income']
        else:
            st.session_state['cat_income'] = ["월급", "부수입", "보너스", "이월금", "기타"]
    
    if 'cat_expense' not in st.session_state:
        if loaded_settings and loaded_settings['cat_expense']:
            st.session_state['cat_expense'] = loaded_settings['cat_expense']
        else:
            st.session_state['cat_expense'] = ["식비", "주거/통신", "생활용품", "의복/미용", "건강/문화", "교통/차량", "육아/교육", "경조사/회비", "기타"]
    
    if 'cat_saving' not in st.session_state:
        if loaded_settings and loaded_settings['cat_saving']:
            st.session_state['cat_saving'] = loaded_settings['cat_saving']
        else:
            st.session_state['cat_saving'] = ["적금", "예금", "투자", "비상금", "기타"]

    # 결제수단 초기값
    if 'payment_methods' not in st.session_state:
        if loaded_settings and loaded_settings['payment_methods']:
            st.session_state['payment_methods'] = loaded_settings['payment_methods']
        else:
            st.session_state['payment_methods'] = ["신용카드", "체크카드", "현금", "계좌이체"]

    # 카드 정보 저장소
    if 'cards_info' not in st.session_state:
        if loaded_settings and loaded_settings['cards_info']:
            st.session_state['cards_info'] = loaded_settings['cards_info']
        else:
            st.session_state['cards_info'] = {} 

    # 방금 추가한 항목을 기억하기 위한 변수
    if 'last_added_item' not in st.session_state:
        st.session_state['last_added_item'] = None

    # 연도 목록 초기화
    if 'available_years' not in st.session_state:
        if loaded_settings and 'available_years' in loaded_settings and loaded_settings['available_years']:
            st.session_state['available_years'] = loaded_settings['available_years']
        else:
            st.session_state['available_years'] = [datetime.now().year]

    # 입력 폼 초기화 값
    if 'form_content' not in st.session_state: st.session_state['form_content'] = ''
    if 'form_amount' not in st.session_state: st.session_state['form_amount'] = 0
    if 'form_memo' not in st.session_state: st.session_state['form_memo'] = ''
    
    # 삭제 대기 목록
    if 'pending_delete' not in st.session_state: st.session_state['pending_delete'] = []


def save_data(date, time, type_val, sub_division, big_category, small_category, content, amount, currency, method, memo):
    # 지출인 경우 금액을 음수로 저장
    final_amount = amount
    if type_val == '지출' and final_amount > 0:
        final_amount = final_amount * -1
        
    new_row = {
        '날짜': pd.to_datetime(date),
        '시간': str(time), # 시간은 문자열로 저장
        '타입': type_val,
        '세부구분': sub_division,
        '대분류': big_category,
        '소분류': small_category,
        '내용': content,
        '금액': final_amount,
        '화폐': currency,
        '결제수단': method,
        '메모': memo
    }
    st.session_state['data'] = pd.concat([st.session_state['data'], pd.DataFrame([new_row])], ignore_index=True)
    save_data_to_sheet(st.session_state['data'])

# -----------------------------------------------------------------------------
# 팝업창(Dialog) 기능 함수
# -----------------------------------------------------------------------------
@st.dialog("새 항목 추가")
def add_item_dialog(target_list_key, item_type_name):
    st.write(f"새로운 {item_type_name}을(를) 입력하세요.")
    new_item = st.text_input("항목 이름")
    
    if st.button("추가하기"):
        if new_item:
            if new_item not in st.session_state[target_list_key]:
                st.session_state[target_list_key].append(new_item)
                st.session_state['last_added_item'] = new_item
                save_settings_to_sheet()  # 설정 저장
                st.success(f"'{new_item}' 추가 완료!")
                st.rerun()
            else:
                st.error("이미 존재하는 항목입니다.")
        else:
            st.warning("이름을 입력해주세요.")

# -----------------------------------------------------------------------------
# 로그인 페이지
# -----------------------------------------------------------------------------
def login_page():
    st.markdown("""
        <div style='text-align: center; margin-top: 50px;'>
            <h1>💰 슈퍼 가계부</h1>
            <p>로그인이 필요합니다.</p>
        </div>
    """, unsafe_allow_html=True)
    
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        with st.form("login_form"):
            username = st.text_input("아이디")
            password = st.text_input("비밀번호", type="password")
            
            submitted = st.form_submit_button("로그인", use_container_width=True, type="primary")
            
            if submitted:
                users = load_users()
                if username in users:
                    stored_hash = users[username]['password_hash']
                    stored_salt = users[username]['salt']
                    
                    if verify_password(stored_hash, stored_salt, password):
                        st.session_state['logged_in'] = True
                        st.session_state['username'] = username
                        st.success("로그인 성공!")
                        st.rerun()
                    else:
                        st.error("비밀번호가 일치하지 않습니다.")
                else:
                    st.error("존재하지 않는 아이디입니다.")
        
        with st.expander("회원가입"):
            with st.form("signup_form"):
                new_user = st.text_input("새 아이디")
                new_pw = st.text_input("새 비밀번호", type="password")
                new_pw_confirm = st.text_input("비밀번호 확인", type="password")
                
                signup_submitted = st.form_submit_button("가입하기")
                
                if signup_submitted:
                    if new_pw != new_pw_confirm:
                        st.error("비밀번호가 일치하지 않습니다.")
                    elif not new_user or not new_pw:
                        st.warning("아이디와 비밀번호를 입력해주세요.")
                    else:
                        success, msg = register_user(new_user, new_pw)
                        if success:
                            st.success(msg)
                        else:
                            st.error(msg)

# -----------------------------------------------------------------------------
# 달력 렌더링 함수
# -----------------------------------------------------------------------------
def render_calendar(year, month, df):
    # 해당 월의 데이터 필터링
    monthly_df = df[(df['날짜'].dt.year == year) & (df['날짜'].dt.month == month)]
    
    # 달력 생성
    cal = calendar.monthcalendar(year, month)
    
    # 요일 헤더
    cols = st.columns(7)
    days = ['월', '화', '수', '목', '금', '토', '일']
    for idx, day in enumerate(days):
        cols[idx].markdown(f"<div style='text-align: center; font-weight: bold; color: #4A5568;'>{day}</div>", unsafe_allow_html=True)
    
    # 달력 날짜 채우기
    for week in cal:
        cols = st.columns(7)
        for idx, day in enumerate(week):
            if day == 0:
                cols[idx].write("")
            else:
                # 해당 날짜의 데이터 요약
                day_str = f"{year}-{month:02d}-{day:02d}"
                day_data = monthly_df[monthly_df['날짜'].dt.strftime('%Y-%m-%d') == day_str]
                
                income = day_data[day_data['타입']=='수입']['금액'].sum()
                expense = day_data[day_data['타입']=='지출']['금액'].sum()
                
                content_html = f"<div style='text-align: center; height: 80px; border: 1px solid #E2E8F0; border-radius: 5px; padding: 5px; margin-bottom: 5px;'>"
                content_html += f"<div style='font-weight: bold;'>{day}</div>"
                
                if income > 0:
                    content_html += f"<div style='color: blue; font-size: 0.8rem;'>+{income:,.0f}</div>"
                if expense != 0: # 지출은 음수이므로 0이 아니면 표시
                    content_html += f"<div style='color: red; font-size: 0.8rem;'>{expense:,.0f}</div>"
                    
                content_html += "</div>"
                
                cols[idx].markdown(content_html, unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 월 선택 버튼 렌더링 함수
# -----------------------------------------------------------------------------
def render_month_selector(key_prefix, default_month=None):
    if default_month is None:
        default_month = datetime.now().month
        
    if key_prefix not in st.session_state:
        st.session_state[key_prefix] = default_month
        
    current_selection = st.session_state[key_prefix]
    
    st.markdown("##### 월 선택")
    
    # 1~12월 (한 줄로 표시)
    cols = st.columns(12)
    for i in range(1, 13):
        btn_type = "primary" if current_selection == i else "secondary"
        if cols[i-1].button(f"{i}월", key=f"{key_prefix}_btn_{i}", type=btn_type, use_container_width=True):
            st.session_state[key_prefix] = i
            st.rerun()
            
    return st.session_state[key_prefix]

# -----------------------------------------------------------------------------
# 2. 사이드바 (입력 폼)
# -----------------------------------------------------------------------------
def sidebar_input_section():
    with st.sidebar:
        # 상단 여백 추가
        st.markdown("<br><br><br>", unsafe_allow_html=True)
        
        st.markdown("""
            <h2 style='text-align: center; color: white; margin-bottom: 1.5rem;'>
                ✏️ 거래 내역 입력
            </h2>
        """, unsafe_allow_html=True)
        
        # 날짜 & 시간 & 타입 (구분)
        c1, c2 = st.columns([0.6, 0.4])
        date_input = c1.date_input("날짜", datetime.today())
        time_input = c2.time_input("시간", datetime.now().time())
        
        division_input = st.selectbox("타입", ["지출", "수입", "저축"], key="division_select")
        
        # 카테고리 로직
        if division_input == "수입": current_cat_key = 'cat_income'
        elif division_input == "지출": current_cat_key = 'cat_expense'
        else: current_cat_key = 'cat_saving'
        
        categories = st.session_state[current_cat_key]
        
        # 대분류 (구 카테고리) 추가 버튼 (컬럼 레이아웃)
        st.markdown('<p style="font-size: 14px; font-weight: bold; margin-bottom: -10px;">대분류</p>', unsafe_allow_html=True)
        col_cat, col_btn1 = st.columns([0.8, 0.2], vertical_alignment="bottom")
        with col_cat:
            # 마지막 추가된 항목이 있으면 자동 선택
            default_cat_index = 0
            if st.session_state['last_added_item'] in categories:
                default_cat_index = categories.index(st.session_state['last_added_item'])
            category_input = st.selectbox("대분류", categories, index=default_cat_index, label_visibility="collapsed")
            
        with col_btn1:
            if st.button("＋", key="add_cat_btn", help="새 대분류 추가", use_container_width=True):
                add_item_dialog(current_cat_key, "대분류")

        # 소분류 (NEW)
        small_category_input = st.text_input("소분류")

        # 지출 성격 (세부구분 - 앱 로직 유지)
        sub_division = "-"
        if division_input == "지출":
            fixed_cats = ["주거/통신", "보험", "교통/차량"]
            default_idx = 0 if category_input in fixed_cats else 1
            sub_division = st.radio("지출 성격", ["고정지출", "비고정지출"], index=default_idx, horizontal=True)

        # 결제수단 & 카드 선택 (수입이 아닐 때만 표시) - 폼 밖으로 이동
        method_input = "-"
        selected_card = "-"
        
        if division_input != "수입":
            # 결제수단 추가 버튼 (컬럼 레이아웃)
            st.markdown('<p style="font-size: 14px; font-weight: bold; margin-bottom: -10px;">결제수단</p>', unsafe_allow_html=True)
            col_pay, col_btn2 = st.columns([0.8, 0.2], vertical_alignment="bottom")
            with col_pay:
                # 마지막 추가된 항목이 있으면 자동 선택
                default_pay_index = 0
                if st.session_state['last_added_item'] in st.session_state['payment_methods']:
                    default_pay_index = st.session_state['payment_methods'].index(st.session_state['last_added_item'])
                    
                method_input = st.selectbox("결제수단", st.session_state['payment_methods'], index=default_pay_index, label_visibility="collapsed")
            
            with col_btn2:
                if st.button("＋", key="add_pay_btn", help="새 결제수단 추가", use_container_width=True):
                    add_item_dialog('payment_methods', "결제수단")

            # 카드 선택 (항상 보여주되, 카드 결제가 아니면 '-' 선택 유도)
            registered_cards = ["-"] + list(st.session_state['cards_info'].keys())
            selected_card = st.selectbox("카드 선택 (카드 결제 시)", registered_cards)

        # -------------------------------------------------------
        # 입력 폼 (내용, 금액, 화폐, 메모)
        # -------------------------------------------------------
        with st.form("entry_form", clear_on_submit=True):
            content_input = st.text_input("내용")
            
            c1, c2 = st.columns([0.7, 0.3])
            with c1:
                amount_input = st.number_input("금액", min_value=0, step=1000, format="%d")
            with c2:
                currency_input = st.selectbox("화폐", ["KRW", "USD", "JPY", "EUR", "CNY"])
            
            memo_input = st.text_area("메모", height=50)
            
            submitted = st.form_submit_button("입력 하기", type="primary", use_container_width=True)
            
            if submitted:
                if amount_input <= 0:
                    st.warning("금액은 0보다 커야 합니다.")
                else:
                    # 결제수단 로직: 카드가 선택되었으면 카드명, 아니면 결제수단
                    final_method = selected_card if selected_card != "-" else method_input
                    
                    save_data(
                        date_input, 
                        time_input,
                        division_input, 
                        sub_division, 
                        category_input, 
                        small_category_input,
                        content_input, 
                        amount_input, 
                        currency_input,
                        final_method, 
                        memo_input
                    )
                    st.success("저장 완료!")
                    # clear_on_submit=True 덕분에 내용, 금액, 메모는 자동 초기화됨.
                    # 날짜, 카테고리 등 폼 밖의 요소는 유지됨 (연속 입력에 유리).


# -----------------------------------------------------------------------------
# 3. 메인 화면 (Tab 1, 2, 3, 4)
# -----------------------------------------------------------------------------
# -----------------------------------------------------------------------------
# 헬퍼 함수들 (삭제 확인, 데이터 업데이트)
# -----------------------------------------------------------------------------
def update_from_editor(edited_df, original_df):
    """데이터 에디터의 변경사항을 원본 데이터에 반영"""
    # 1. 삭제 대기 목록 업데이트
    if '삭제' in edited_df.columns:
        to_delete = edited_df[edited_df['삭제']]
        st.session_state['pending_delete'] = to_delete['original_index'].tolist()
    
    # 2. 값 수정 반영
    # edited_df의 각 행을 순회하며 변경사항 적용
    for index, row in edited_df.iterrows():
        org_idx = row['original_index']
        if pd.isna(org_idx): continue 
        
        # 원본 데이터프레임의 해당 인덱스 행 업데이트
        for col in row.index:
            if col in ['삭제', 'original_index']: continue
            if col in st.session_state['data'].columns:
                val = row[col]
                # 날짜 컬럼인 경우 datetime으로 변환
                if col == '날짜':
                    val = pd.to_datetime(val)
                st.session_state['data'].at[org_idx, col] = val
    
    # 변경사항 저장
    save_data_to_sheet(st.session_state['data'])

@st.dialog("삭제 확인")
def confirm_delete_dialog(delete_indices):
    st.write(f"{len(delete_indices)}개의 항목을 삭제하시겠습니까?")
    if st.button("확인", type="primary"):
        # 인덱스로 삭제
        st.session_state['data'] = st.session_state['data'].drop(delete_indices)
        # 인덱스 재설정 (선택사항, 하지만 보통 유지하는게 안전)
        st.session_state['data'] = st.session_state['data'].reset_index(drop=True)
        
        save_data_to_sheet(st.session_state['data'])
        st.session_state['pending_delete'] = []
        st.success("삭제되었습니다.")
        st.rerun()

# -----------------------------------------------------------------------------
# 3. 메인 콘텐츠 (탭 구성)
# -----------------------------------------------------------------------------
def main_content():
    df = st.session_state['data']
    
    # 공통 설정값 준비
    all_categories = st.session_state['cat_income'] + st.session_state['cat_expense'] + st.session_state['cat_saving']
    all_categories = sorted(list(set(all_categories)))
    
    payment_methods = st.session_state['payment_methods']
    cards = ["-"] + list(st.session_state['cards_info'].keys())
    
    # 탭 구성
    tab1, tab_cal, tab_cat, tab2, tab3, tab4 = st.tabs(["📊 월별 리포트", "📅 달력 보기", "📂 카테고리별 보기", "📋 전체 내역", "📈 분석", "⚙️ 설정"])
    
    # --- [Tab 1] 월별 리포트 & 카드 실적 ---
    with tab1:
        available_years = sorted(st.session_state['available_years'])
        search_year = st.selectbox("연도", available_years, index=len(available_years)-1 if available_years else 0, key="tab1_year")
        
        search_month = render_month_selector("tab1_month")

        if not df.empty:
            monthly_df = df[(df['날짜'].dt.year == search_year) & (df['날짜'].dt.month == search_month)]
        else:
            monthly_df = pd.DataFrame(columns=df.columns)

        # 1. 기본 요약
        st.markdown(f"### 📋 {search_month}월 요약")
        if not monthly_df.empty:
            income = monthly_df[monthly_df['타입']=='수입']['금액'].sum()
            expense = monthly_df[monthly_df['타입']=='지출']['금액'].sum()
            saving = monthly_df[monthly_df['타입']=='저축']['금액'].sum()
            
            m1, m2, m3 = st.columns(3)
            m1.metric("총 수입", f"{income:,.0f}원")
            m2.metric("총 지출", f"{expense:,.0f}원") # 음수로 표시됨
            m3.metric("총 저축", f"{saving:,.0f}원")
        else:
            st.info("데이터가 없습니다.")

        st.divider()

        # [NEW] 2. 상세 내역 및 지출 분석 (인라인 수정)
        col_detail, col_analysis = st.columns([0.75, 0.25])
        
        with col_detail:
            # [NEW] 고정 지출 섹션 (상단 배치)
            fh_col1, fh_col2 = st.columns([0.5, 0.5])
            fh_col1.subheader("🔒 고정 지출")
            
            fixed_expenses = pd.DataFrame()
            if not monthly_df.empty:
                fixed_expenses = monthly_df[monthly_df['세부구분'] == '고정지출'].copy()
            
            if not fixed_expenses.empty:
                fixed_sum = fixed_expenses['금액'].sum()
                fh_col2.markdown(f"<h3 style='text-align: right; color: #FF4B4B;'>{fixed_sum:,.0f}원</h3>", unsafe_allow_html=True)
                
                fixed_expenses['original_index'] = fixed_expenses.index
                fixed_expenses['삭제'] = False # 삭제 체크박스용 컬럼 추가
                
                # 동적 높이 계산 (헤더 + 데이터)
                # num_rows="fixed"이므로 +1 (헤더)
                fixed_height = (len(fixed_expenses) + 1) * 35 + 3
                
                edited_fixed = st.data_editor(
                    fixed_expenses.sort_values(by="날짜"),
                    column_config={
                        "삭제": st.column_config.CheckboxColumn("삭제", width="small"),
                        "날짜": st.column_config.DateColumn("날짜", format="YYYY-MM-DD"),
                        "시간": st.column_config.TimeColumn("시간", format="HH:mm"),
                        "타입": st.column_config.SelectboxColumn("타입", options=["지출", "수입", "저축"], required=True),
                        "세부구분": st.column_config.SelectboxColumn("세부구분", options=["고정지출", "비고정지출", "-"], required=True),
                        "대분류": st.column_config.SelectboxColumn("대분류", options=all_categories, required=True),
                        "소분류": st.column_config.TextColumn("소분류"),
                        "내용": st.column_config.TextColumn("내용", required=True),
                        "금액": st.column_config.NumberColumn("금액", format="%d원", step=1000, required=True),
                        "화폐": st.column_config.SelectboxColumn("화폐", options=["KRW", "USD", "JPY", "EUR", "CNY"]),
                        "결제수단": st.column_config.SelectboxColumn("결제수단", options=payment_methods + cards), # 카드 포함
                        "메모": st.column_config.TextColumn("메모"),
                        "original_index": None,
                    },
                    use_container_width=True,
                    hide_index=True,
                    num_rows="fixed", # 행 추가/삭제 불가 (삭제는 체크박스로 대체)
                    height=fixed_height,
                    key="editor_fixed"
                )
                
                # 변경 감지 및 적용
                if not edited_fixed.equals(fixed_expenses.sort_values(by="날짜")):
                    update_from_editor(edited_fixed, fixed_expenses)
                
                # 삭제 버튼 표시 (체크박스 선택 시)
                if st.session_state['pending_delete']:
                    if st.button("🗑️ 선택 항목 삭제", key="delete_fixed_btn", type="primary"):
                        confirm_delete_dialog(st.session_state['pending_delete'])
            else:
                fh_col2.markdown(f"<h3 style='text-align: right; color: gray;'>0원</h3>", unsafe_allow_html=True)
                st.info("고정 지출 내역이 없습니다.")
                    
            st.divider()

            # 비고정 지출 섹션
            dh_col1, dh_col2 = st.columns([0.5, 0.5])
            dh_col1.subheader("🛒 비고정 지출")
            
            if not monthly_df.empty:
                # 고정지출 제외
                detail_df = monthly_df[monthly_df['세부구분'] != '고정지출'].copy()
                
                if not detail_df.empty:
                    variable_sum = detail_df[detail_df['타입'] == '지출']['금액'].sum() 
                    variable_expense_sum = detail_df[detail_df['타입'] == '지출']['금액'].sum()
                    dh_col2.markdown(f"<h3 style='text-align: right; color: #FF4B4B;'>{variable_expense_sum:,.0f}원</h3>", unsafe_allow_html=True)
                    
                    # 날짜 기준 내림차순 정렬
                    display_df = detail_df.sort_values(by="날짜", ascending=False)
                    display_df['original_index'] = display_df.index # 원본 인덱스 저장
                    display_df['삭제'] = False # 삭제 체크박스용 컬럼 추가
                    
                    # 동적 높이 계산 (헤더 + 데이터)
                    variable_height = (len(display_df) + 1) * 35 + 3
                    
                    edited_detail = st.data_editor(
                        display_df, 
                        column_config={
                            "삭제": st.column_config.CheckboxColumn("삭제", width="small"),
                            "날짜": st.column_config.DateColumn("날짜", format="YYYY-MM-DD"),
                            "시간": st.column_config.TimeColumn("시간", format="HH:mm"),
                            "타입": st.column_config.SelectboxColumn("타입", options=["지출", "수입", "저축"], required=True),
                            "세부구분": st.column_config.SelectboxColumn("세부구분", options=["고정지출", "비고정지출", "-"], required=True),
                            "대분류": st.column_config.SelectboxColumn("대분류", options=all_categories, required=True),
                            "소분류": st.column_config.TextColumn("소분류"),
                            "내용": st.column_config.TextColumn("내용", required=True),
                            "금액": st.column_config.NumberColumn("금액", format="%d원", step=1000, required=True),
                            "화폐": st.column_config.SelectboxColumn("화폐", options=["KRW", "USD", "JPY", "EUR", "CNY"]),
                            "결제수단": st.column_config.SelectboxColumn("결제수단", options=payment_methods + cards),
                            "메모": st.column_config.TextColumn("메모"),
                            "original_index": None, # 화면에서 숨김
                        },
                        use_container_width=True,
                        hide_index=True,
                        num_rows="fixed",
                        height=variable_height,
                        key="editor_detail"
                    )
                    
                    # 변경 감지 및 적용
                    if not edited_detail.equals(display_df):
                        update_from_editor(edited_detail, display_df)
                    
                    # 삭제 버튼 표시 (체크박스 선택 시)
                    if st.session_state['pending_delete']:
                        if st.button("🗑️ 선택 항목 삭제", key="delete_detail_btn", type="primary"):
                            confirm_delete_dialog(st.session_state['pending_delete'])

                else:
                    dh_col2.markdown(f"<h3 style='text-align: right; color: gray;'>0원</h3>", unsafe_allow_html=True)
                    st.info("비고정 지출 내역이 없습니다.")
            else:
                dh_col2.markdown(f"<h3 style='text-align: right; color: gray;'>0원</h3>", unsafe_allow_html=True)
                st.info("이번 달 거래 내역이 없습니다.")


        with col_analysis:
            st.subheader("📉 지출 분석")
            if not monthly_df.empty:
                expense_df = monthly_df[monthly_df['타입'] == '지출']
                if not expense_df.empty:
                    # 카테고리별 지출 합계 표 (내용별 지출 합계와 동일한 스타일)
                    category_group = expense_df.groupby('대분류')['금액'].sum().reset_index()
                    category_group = category_group.sort_values(by='금액', ascending=True) # 음수니까 오름차순이 큰 지출
                    
                    # 동적 높이 계산
                    height_cat = (len(category_group) + 1) * 35 + 3
                    
                    st.dataframe(
                        category_group.style.format({"금액": "{:,.0f}원"}),
                        column_config={
                            "대분류": st.column_config.TextColumn("카테고리"),
                            # "금액": st.column_config.NumberColumn("금액", format="%d원"),
                        },
                        use_container_width=True,
                        hide_index=True,
                        height=height_cat
                    )
                else:
                    st.info("지출 내역이 없습니다.")
            else:
                st.info("데이터가 없습니다.")

        st.divider()

        # 3. 카드 실적 관리 대시보드
        st.subheader(f"💳 카드별 실적 현황 ({search_month}월)")
        
        if not st.session_state['cards_info']:
            st.warning("등록된 카드가 없습니다. '설정' 탭에서 카드를 등록해주세요.")
        else:
            # 카드명이 '-'가 아니고, 실제 등록된 카드인 경우만 필터링
            valid_cards = [c for c in monthly_df['결제수단'].unique() if c in st.session_state['cards_info']]
            card_spend = monthly_df[monthly_df['결제수단'].isin(valid_cards)].groupby('결제수단')['금액'].sum()
            
            # 등록된 모든 카드에 대해 표시 (사용액 0원이라도)
            for card_name, tiers in st.session_state['cards_info'].items():
                # 지출은 음수이므로 절대값으로 계산
                current_amount = abs(card_spend.get(card_name, 0))
                
                with st.expander(f"💳 **{card_name}** (사용액: {current_amount:,.0f}원)", expanded=True):
                    sorted_tiers = sorted(tiers, key=lambda x: x['limit'])
                    max_limit = sorted_tiers[-1]['limit'] if sorted_tiers else 1000000
                    progress = min(current_amount / max_limit, 1.0) if max_limit > 0 else 0
                    st.progress(progress)
                    
                    cols = st.columns(len(sorted_tiers))
                    for idx, tier in enumerate(sorted_tiers):
                        limit = tier['limit']
                        benefit = tier['benefit']
                        is_reached = current_amount >= limit
                        status_icon = "✅ 달성!" if is_reached else "🏃 진행중"
                        diff = limit - current_amount
                        
                        with cols[idx]:
                            st.markdown(f"**{idx+1}구간 ({limit/10000:.0f}만)**")
                            if is_reached:
                                st.success(f"{status_icon}\n\n혜택: {benefit}")
                            else:
                                st.info(f"{status_icon}\n\n남은 금액: {diff:,.0f}원\n\n혜택: {benefit}")

    # --- [Tab 2] 달력 보기 ---
    with tab_cal:
        st.subheader("📅 월별 달력")
        available_years = sorted(st.session_state['available_years'])
        cal_year = st.selectbox("연도", available_years, index=len(available_years)-1 if available_years else 0, key="cal_year_box")
        
        cal_month = render_month_selector("cal_month")
        
        st.divider()
        render_calendar(cal_year, cal_month, df)

    # --- [Tab 3] 카테고리별 보기 ---
    with tab_cat:
        st.subheader("📂 카테고리별 내역")
        
        # 1. 연도/월 선택
        available_years = sorted(st.session_state['available_years'])
        cat_year = st.selectbox("연도", available_years, index=len(available_years)-1 if available_years else 0, key="cat_year_box")
        
        cat_month = render_month_selector("cat_month_selector")
        
        # 2. 해당 월 데이터 필터링
        if not df.empty:
            monthly_cat_df = df[(df['날짜'].dt.year == cat_year) & (df['날짜'].dt.month == cat_month)]
        else:
            monthly_cat_df = pd.DataFrame(columns=df.columns)

        # 3. 카테고리별 합계 계산
        cat_sums = {}
        if not monthly_cat_df.empty:
            cat_sums = monthly_cat_df.groupby('대분류')['금액'].sum().to_dict()
        
        # 세션 상태 초기화
        if 'selected_cat_view' not in st.session_state:
            st.session_state['selected_cat_view'] = all_categories[0] if all_categories else None

        # 카테고리 버튼 그리드 생성
        st.markdown("##### 카테고리 선택")
        cols = st.columns(5)  # 5열 그리드
        for idx, category in enumerate(all_categories):
            col = cols[idx % 5]
            # 현재 선택된 카테고리는 primary 스타일로 표시
            btn_type = "primary" if st.session_state['selected_cat_view'] == category else "secondary"
            
            # 금액 표시
            amount = cat_sums.get(category, 0)
            label = f"{category}\n({amount:,.0f}원)"
            
            if col.button(label, key=f"cat_btn_{idx}", type=btn_type, use_container_width=True):
                st.session_state['selected_cat_view'] = category
                st.rerun()
        
        st.divider()

        selected_category = st.session_state['selected_cat_view']
        
        if selected_category:
            # 해당 카테고리 데이터 필터링 (월별 필터링된 데이터 사용)
            cat_df = monthly_cat_df[monthly_cat_df['대분류'] == selected_category].copy()
            
            if not cat_df.empty:
                # 요약 정보
                total_amount = cat_df['금액'].sum()
                count = len(cat_df)
                
                c1, c2 = st.columns(2)
                c1.metric("총 금액", f"{total_amount:,.0f}원")
                c2.metric("건수", f"{count}건")
                
                st.divider()
                
                # 데이터 표시 (2단 컬럼 구성)
                col_list, col_breakdown = st.columns([0.6, 0.4])
                
                with col_list:
                    st.markdown("###### 📝 상세 내역")
                    # 동적 높이 계산
                    height_list = (len(cat_df) + 1) * 35 + 3
                    st.dataframe(
                        cat_df.sort_values(by="날짜", ascending=False).style.format({"금액": "{:,.0f}원"}),
                        column_config={
                            "날짜": st.column_config.DateColumn("날짜", format="YYYY-MM-DD"),
                            # "금액": st.column_config.NumberColumn("금액", format="%d원"), # style로 대체
                        },
                        use_container_width=True,
                        hide_index=True,
                        height=height_list
                    )
                
                with col_breakdown:
                    st.markdown("###### 📊 내용별 지출 합계")
                    # 내용별 그룹화 및 정렬 (지출은 음수이므로 절대값 기준 정렬? 아니면 그냥 정렬?)
                    # 지출이 주를 이루므로 오름차순(더 작은 음수 = 더 큰 지출)이 맞을 수도 있지만,
                    # 보통 큰 금액부터 보고 싶어하므로 절대값 기준 정렬이 나을 수 있음.
                    # 여기서는 단순 금액 기준 오름차순(큰 지출 순)으로 정렬
                    content_group = cat_df.groupby('내용')['금액'].sum().reset_index()
                    content_group = content_group.sort_values(by='금액', ascending=True) # 음수니까 오름차순이 큰 지출
                    
                    # 동적 높이 계산
                    height_group = (len(content_group) + 1) * 35 + 3
                    st.dataframe(
                        content_group.style.format({"금액": "{:,.0f}원"}),
                        column_config={
                            "내용": st.column_config.TextColumn("내용"),
                            # "금액": st.column_config.NumberColumn("금액", format="%d원"), # style로 대체
                        },
                        use_container_width=True,
                        hide_index=True,
                        height=height_group
                    )
            else:
                st.info(f"'{selected_category}' 카테고리의 내역이 없습니다.")
        else:
            st.info("카테고리를 선택해주세요.")

    # --- [Tab 4] 전체 내역 (데이터 관리) ---
    with tab2:
        st.subheader("📂 데이터 관리")
        
        col_manage1, col_manage2 = st.columns(2)
        
        with col_manage1:
            st.markdown("### 📤 데이터 내보내기")
            st.caption("현재 저장된 모든 내역을 CSV 파일로 다운로드합니다.")
            st.dataframe(df.style.format({"금액": "{:,.0f}원"}), use_container_width=True, height=300)
            st.download_button("엑셀(CSV) 다운로드", df.to_csv(index=False).encode('utf-8-sig'), "gagyebu.csv", "text/csv", use_container_width=True)

        with col_manage2:
            st.markdown("### 📥 데이터 가져오기")
            st.caption("CSV 파일을 업로드하여 데이터를 복원하거나 합칠 수 있습니다.")
            
            uploaded_file = st.file_uploader("CSV 파일 업로드", type=['csv'])
            
            if uploaded_file is not None:
                try:
                    uploaded_df = pd.read_csv(uploaded_file)
                    
                    # 컬럼 유효성 검사
                    required_columns = ['날짜', '시간', '타입', '대분류', '소분류', '내용', '금액', '화폐', '결제수단', '메모', '세부구분']
                    if all(col in uploaded_df.columns for col in required_columns):
                        st.success("파일 형식이 올바릅니다!")
                        st.dataframe(uploaded_df.head(), use_container_width=True, height=150)
                        
                        c1, c2 = st.columns(2)
                        with c1:
                            if st.button("데이터 추가 (Append)", use_container_width=True, help="기존 데이터 뒤에 붙입니다."):
                                # 날짜 형식 변환 후 병합
                                uploaded_df['날짜'] = pd.to_datetime(uploaded_df['날짜'])
                                st.session_state['data'] = pd.concat([st.session_state['data'], uploaded_df], ignore_index=True)
                                st.success(f"{len(uploaded_df)}개의 항목이 추가되었습니다!")
                                st.rerun()
                                
                        with c2:
                            if st.button("덮어쓰기 (Replace)", type="primary", use_container_width=True, help="기존 데이터를 모두 지우고 교체합니다."):
                                uploaded_df['날짜'] = pd.to_datetime(uploaded_df['날짜'])
                                st.session_state['data'] = uploaded_df
                                st.success("데이터가 교체되었습니다!")
                                st.rerun()
                    else:
                        st.error(f"올바른 가계부 파일이 아닙니다.\n필요한 컬럼: {', '.join(required_columns)}")
                except Exception as e:
                    st.error(f"파일을 읽는 중 오류가 발생했습니다: {e}")

    # --- [Tab 5] 분석 (연간 리포트) ---
    with tab3:
        if df.empty:
            st.info("데이터가 없습니다.")
        else:
            year_select = st.selectbox("연도 확인", available_years, key='year_select_tab2', index=len(available_years)-1)
            
            year_df = df[df['날짜'].dt.year == year_select].copy()
            if not year_df.empty:
                year_df['월'] = year_df['날짜'].dt.month
                # 피벗 테이블 생성 (지출은 음수로 합산됨)
                pivot = year_df.groupby(['월', '타입'])['금액'].sum().unstack(fill_value=0)
                st.bar_chart(pivot)
                st.dataframe(pivot.style.format("{:,.0f}원"), use_container_width=True)
            else:
                st.write("해당 연도 데이터가 없습니다.")

    # --- [Tab 6] 설정 (카테고리 & 카드 관리) ---
    with tab4:
        col_set1, col_set2 = st.columns([1, 2])
        
        # 1. 항목(카테고리/결제수단) 관리
        with col_set1:
            st.subheader("⚙️ 항목 편집")
            
            # 결제수단 관리
            st.markdown("**💳 결제수단 관리**")
            new_method = st.text_input("새 결제수단 추가", key="new_method_input")
            if st.button("➕ 추가", key='add_pay_settings'):
                if new_method and new_method not in st.session_state['payment_methods']:
                    st.session_state['payment_methods'].append(new_method)
                    save_settings_to_sheet()
                    st.success(f"'{new_method}' 추가 완료!")
                    st.rerun()
            
            # 결제수단 삭제
            if st.session_state['payment_methods']:
                del_method = st.selectbox("삭제할 결제수단", st.session_state['payment_methods'], key='del_method_select')
                if st.button("🗑️ 결제수단 삭제", key='del_pay_btn'):
                    st.session_state['payment_methods'].remove(del_method)
                    save_settings_to_sheet()
                    st.success(f"'{del_method}' 삭제 완료!")
                    st.rerun()
            
            st.write("현재 결제수단:", ", ".join(st.session_state['payment_methods']))
            st.divider()
            
            # 카테고리 관리
            st.markdown("**📂 지출 카테고리 관리**")
            new_cat = st.text_input("새 지출 카테고리 추가", key="new_cat_input")
            if st.button("➕ 추가", key='add_cat_settings'):
                if new_cat and new_cat not in st.session_state['cat_expense']:
                    st.session_state['cat_expense'].append(new_cat)
                    save_settings_to_sheet()
                    st.success(f"'{new_cat}' 추가 완료!")
                    st.rerun()
            
            # 카테고리 삭제
            if st.session_state['cat_expense']:
                del_cat = st.selectbox("삭제할 카테고리", st.session_state['cat_expense'], key='del_cat_select')
                if st.button("🗑️ 카테고리 삭제", key='del_cat_btn'):
                    st.session_state['cat_expense'].remove(del_cat)
                    save_settings_to_sheet()
                    st.success(f"'{del_cat}' 삭제 완료!")
                    st.rerun()
                    
            st.write(f"**현재 지출 카테고리:** {', '.join(st.session_state['cat_expense'])}")
            st.divider()
            
            # 연도 관리
            st.markdown("**📅 연도 관리**")
            new_year = st.number_input("새 연도 추가", min_value=2000, max_value=2100, value=datetime.now().year, step=1, key="new_year_input")
            if st.button("➕ 추가", key='add_year_settings'):
                if new_year not in st.session_state['available_years']:
                    st.session_state['available_years'].append(new_year)
                    save_settings_to_sheet()
                    st.success(f"'{new_year}년' 추가 완료!")
                    st.rerun()
                else:
                    st.warning("이미 존재하는 연도입니다.")
            
            # 연도 삭제
            if st.session_state['available_years']:
                del_year = st.selectbox("삭제할 연도", sorted(st.session_state['available_years']), key='del_year_select')
                if st.button("🗑️ 연도 삭제", key='del_year_btn'):
                    st.session_state['available_years'].remove(del_year)
                    save_settings_to_sheet()
                    st.success(f"'{del_year}년' 삭제 완료!")
                    st.rerun()
                    
            st.write(f"**현재 연도 목록:** {', '.join(map(str, sorted(st.session_state['available_years'])))}")

        # 2. 카드 실적 관리 설정
        with col_set2:
            st.subheader("💳 내 카드 & 실적 구간 설정")
            
            with st.form("add_card_form"):
                input_card_name = st.text_input("카드 이름 (예: 현대 M카드)")
                
                c1, c2 = st.columns(2)
                with c1:
                    tier1_limit = st.number_input("1구간 실적금액 (원)", value=300000, step=10000)
                    tier1_benefit = st.text_input("1구간 혜택", placeholder="예: 1만원 할인")
                with c2:
                    tier2_limit = st.number_input("2구간 실적금액 (원, 0=미설정)", value=0, step=10000)
                    tier2_benefit = st.text_input("2구간 혜택", placeholder="예: 2만원 할인")
                
                add_card_btn = st.form_submit_button("카드 등록/수정")
                
                if add_card_btn and input_card_name:
                    tiers = []
                    if tier1_limit > 0: tiers.append({'limit': tier1_limit, 'benefit': tier1_benefit})
                    if tier2_limit > 0: tiers.append({'limit': tier2_limit, 'benefit': tier2_benefit})
                    
                    st.session_state['cards_info'][input_card_name] = tiers
                    save_settings_to_sheet()  # 설정 저장
                    st.success(f"'{input_card_name}' 저장 완료!")
                    st.rerun()
            
            st.divider()
            st.write("🗑️ 등록된 카드 삭제")
            cards_list = list(st.session_state['cards_info'].keys())
            if cards_list:
                del_card = st.selectbox("삭제할 카드", cards_list, key='delete_card_select')
                if st.button("카드 삭제"):
                    del st.session_state['cards_info'][del_card]
                    save_settings_to_sheet()  # 설정 저장
                    st.success("삭제되었습니다.")
                    st.rerun()

# -----------------------------------------------------------------------------
# App Entry Point
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    st.set_page_config(
        page_title="💰 슈퍼 가계부",
        page_icon="💰",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    # 커스텀 CSS 적용
    apply_custom_css()
    
    
    init_session_state()
    
    if not st.session_state['logged_in']:
        login_page()
    else:
        sidebar_input_section()
        
        # 사이드바 하단에 로그아웃 버튼 추가
        with st.sidebar:
            st.divider()
            st.write(f"👤 **{st.session_state['username']}**")
            if st.button("🚪 로그아웃", use_container_width=True):
                st.session_state['logged_in'] = False
                st.session_state['username'] = None
                st.rerun()
            
        main_content()
    
    # 리비전 표기 (우측 하단)
    st.markdown("""
    <div style='position: fixed; bottom: 10px; right: 10px; color: #718096; font-size: 0.8rem; z-index: 9999;'>
        Rev. 2025.11.23
    </div>
    """, unsafe_allow_html=True)

