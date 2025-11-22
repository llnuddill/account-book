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
    columns = ['날짜', '구분', '세부구분', '카테고리', '내용', '금액', '결제수단', '카드명', '메모']
    
    spreadsheet = get_gsheet_connection()
    if spreadsheet:
        try:
            worksheet = spreadsheet.sheet1  # 첫 번째 시트 사용
            data = worksheet.get_all_records()
            if data:
                df = pd.DataFrame(data)
                
                # 데이터 타입 명시적 변환
                if '날짜' in df.columns:
                    df['날짜'] = pd.to_datetime(df['날짜'])
                
                # 텍스트 컬럼들을 문자열로 변환
                text_columns = ['구분', '세부구분', '카테고리', '내용', '결제수단', '카드명', '메모']
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
            save_df['날짜'] = save_df['날짜'].dt.strftime('%Y-%m-%d')
            
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


def save_data(date, division, sub_division, category, content, amount, method, card_name, memo):
    new_row = {
        '날짜': pd.to_datetime(date),
        '구분': division,
        '세부구분': sub_division,
        '카테고리': category,
        '내용': content,
        '금액': amount,
        '결제수단': method,
        '카드명': card_name,
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
        
        # 날짜 & 구분 (폼 외부에서 선택하여 즉시 반영)
        date_input = st.date_input("날짜", datetime.today())
        division_input = st.selectbox("구분", ["지출", "수입", "저축"], key="division_select")
        
        # 카테고리 로직
        if division_input == "수입": current_cat_key = 'cat_income'
        elif division_input == "지출": current_cat_key = 'cat_expense'
        else: current_cat_key = 'cat_saving'
        
        categories = st.session_state[current_cat_key]
        
        # 카테고리 추가 버튼 (컬럼 레이아웃)
        st.markdown('<p style="font-size: 14px; font-weight: bold; margin-bottom: -10px;">카테고리</p>', unsafe_allow_html=True)
        col_cat, col_btn1 = st.columns([0.8, 0.2], vertical_alignment="bottom")
        with col_cat:
            # 마지막 추가된 항목이 있으면 자동 선택
            default_cat_index = 0
            if st.session_state['last_added_item'] in categories:
                default_cat_index = categories.index(st.session_state['last_added_item'])
            category_input = st.selectbox("카테고리", categories, index=default_cat_index, label_visibility="collapsed")
            
        with col_btn1:
            if st.button("＋", key="add_cat_btn", help="새 카테고리 추가", use_container_width=True):
                add_item_dialog(current_cat_key, "카테고리")

        # 지출 성격
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
        # 입력 폼 (내용, 금액, 메모)
        # -------------------------------------------------------
        with st.form("entry_form", clear_on_submit=True):
            content_input = st.text_input("내용")
            amount_input = st.number_input("금액 (원)", min_value=0, step=1000, format="%d")
            
            memo_input = st.text_area("메모", height=50)
            
            submitted = st.form_submit_button("입력 하기", type="primary", use_container_width=True)
            
            if submitted:
                if amount_input <= 0:
                    st.warning("금액은 0보다 커야 합니다.")
                else:
                    save_data(
                        date_input, 
                        division_input, 
                        sub_division, 
                        category_input, 
                        content_input, 
                        amount_input, 
                        method_input, 
                        selected_card if selected_card != "-" else "-", 
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
@st.dialog("삭제 확인")
def confirm_delete_dialog(delete_indices):
    st.write(f"**{len(delete_indices)}개의 항목**을 삭제하시겠습니까?")
    st.warning("이 작업은 되돌릴 수 없습니다.")
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("예, 삭제합니다", type="primary", use_container_width=True):
            st.session_state['data'] = st.session_state['data'].drop(delete_indices).reset_index(drop=True)
            save_data_to_sheet(st.session_state['data'])
            st.session_state['pending_delete'] = []
            st.success("삭제되었습니다.")
            st.rerun()
    with col2:
        if st.button("취소", use_container_width=True):
            st.session_state['pending_delete'] = []
            st.rerun()

def update_from_editor(edited_df, original_subset):
    # 1. 삭제 체크된 행 확인 (즉시 삭제하지 않고 pending 상태로 저장)
    if '삭제' in edited_df.columns:
        rows_to_delete = edited_df[edited_df['삭제'] == True]
        if not rows_to_delete.empty:
            delete_indices = rows_to_delete['original_index'].tolist()
            st.session_state['pending_delete'] = delete_indices
            return False  # 변경사항 없음 (아직 삭제 안함)

    # 2. 수정된 행 처리
    changes_made = False
    for i, row in edited_df.iterrows():
        org_idx = row['original_index']
        if pd.isna(org_idx): continue 
        
        # 삭제 체크된 행은 스킵
        if '삭제' in row and row['삭제']: continue

        # 값 할당
        st.session_state['data'].at[org_idx, '날짜'] = pd.to_datetime(row['날짜'])
        st.session_state['data'].at[org_idx, '구분'] = row['구분']
        st.session_state['data'].at[org_idx, '세부구분'] = row['세부구분']
        st.session_state['data'].at[org_idx, '카테고리'] = row['카테고리']
        st.session_state['data'].at[org_idx, '내용'] = row['내용']
        st.session_state['data'].at[org_idx, '금액'] = row['금액']
        st.session_state['data'].at[org_idx, '결제수단'] = row['결제수단']
        st.session_state['data'].at[org_idx, '카드명'] = row['카드명']
        st.session_state['data'].at[org_idx, '메모'] = row['메모']
        
        changes_made = True
        
    if changes_made:
        save_data_to_sheet(st.session_state['data'])
        
    return changes_made

# -----------------------------------------------------------------------------
# 달력 렌더링 함수
# -----------------------------------------------------------------------------
def render_calendar(year, month, df):
    # CSS 스타일
    st.markdown("""
    <style>
    .calendar-cell {
        border: 1px solid #4a5568;
        border-radius: 8px;
        padding: 8px;
        min-height: 120px;
        font-size: 0.85rem;
        background-color: #1E1E1E;
        color: #e2e8f0;
    }
    .calendar-date {
        font-weight: bold;
        margin-bottom: 5px;
        color: #e2e8f0;
        font-size: 1rem;
    }
    .cal-income { color: #48bb78; margin-bottom: 2px; }
    .cal-expense { color: #f56565; margin-bottom: 2px; }
    .cal-saving { color: #4299e1; margin-bottom: 2px; }
    .cal-total { font-weight: bold; font-size: 0.85rem; margin-top: 4px; border-top: 1px dashed #718096; padding-top: 2px; color: #e2e8f0; }
    .week-summary {
        background-color: #1E1E1E;
        border-radius: 8px;
        padding: 8px;
        min-height: 120px;
        border: 1px solid #4a5568;
        color: #e2e8f0;
        font-size: 0.85rem;
    }
    </style>
    """, unsafe_allow_html=True)

    # 데이터 필터링
    mask = (df['날짜'].dt.year == year) & (df['날짜'].dt.month == month)
    monthly_data = df[mask]
    
    # 달력 데이터 생성
    cal = calendar.monthcalendar(year, month)
    
    # 요일 헤더
    cols = st.columns(8)
    days = ['일', '월', '화', '수', '목', '금', '토', '주간 합계']
    for i, day in enumerate(days):
        cols[i].markdown(f"<div style='text-align: center; font-weight: bold; padding: 5px; color: #e2e8f0;'>{day}</div>", unsafe_allow_html=True)
        
    # 달력 그리기
    for week in cal:
        cols = st.columns(8)
        weekly_income = 0
        weekly_expense = 0
        weekly_saving = 0
        
        for i, day in enumerate(week):
            with cols[i]:
                if day == 0:
                    st.markdown("<div class='calendar-cell' style='background-color: transparent; border: none;'></div>", unsafe_allow_html=True)
                else:
                    # 해당 날짜 데이터 가져오기
                    day_data = monthly_data[monthly_data['날짜'].dt.day == day]
                    
                    # 주간 합계 계산용
                    income_sum = day_data[day_data['구분']=='수입']['금액'].sum()
                    expense_sum = day_data[day_data['구분']=='지출']['금액'].sum()
                    saving_sum = day_data[day_data['구분']=='저축']['금액'].sum()
                    
                    weekly_income += income_sum
                    weekly_expense += expense_sum
                    weekly_saving += saving_sum
                    
                    html = f"<div class='calendar-cell'>"
                    html += f"<div class='calendar-date'>{day}</div>"
                    
                    for _, row in day_data.iterrows():
                        amt = row['금액']
                        content = row['내용']
                        # 내용이 너무 길면 자르기 (10자)
                        if len(content) > 10:
                            content = content[:9] + ".."
                            
                        if row['구분'] == '수입':
                            html += f"<div class='cal-income'>{content}: +{amt:,.0f}</div>"
                        elif row['구분'] == '지출':
                            html += f"<div class='cal-expense'>{content}: -{amt:,.0f}</div>"
                        elif row['구분'] == '저축':
                            html += f"<div class='cal-saving'>{content}: {amt:,.0f}</div>"
                            
                    html += "</div>"
                    st.markdown(html, unsafe_allow_html=True)
        
        # 주간 합계
        with cols[7]:
            html = f"<div class='week-summary'>"
            html += f"<div class='calendar-date'>주간 합계</div>"
            html += f"<div class='cal-income'>수입 : {weekly_income:,.0f}</div>"
            html += f"<div class='cal-expense'>지출 : {weekly_expense:,.0f}</div>"
            html += f"<div class='cal-saving'>저축 : {weekly_saving:,.0f}</div>"
            html += "</div>"
            
            
            st.markdown(html, unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 로그인 페이지
# -----------------------------------------------------------------------------
def login_page():
    st.markdown("<h1 style='text-align: center;'>💰 슈퍼 가계부 로그인</h1>", unsafe_allow_html=True)
    
    with st.form("login_form"):
        username = st.text_input("아이디")
        password = st.text_input("비밀번호", type="password")
        submit = st.form_submit_button("로그인", use_container_width=True)
        
        if submit:
            users = load_users()
            if username in users:
                user_data = users[username]
                if verify_password(user_data['password_hash'], user_data['salt'], password):
                    st.session_state['logged_in'] = True
                    st.session_state['username'] = username
                    st.success("로그인 성공!")
                    st.rerun()
                else:
                    st.error("비밀번호가 일치하지 않습니다.")
            else:
                st.error("존재하지 않는 아이디입니다.")

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
    tab1, tab_cal, tab2, tab3, tab4 = st.tabs(["📊 월별 리포트", "📅 달력 보기", "📋 전체 내역", "📈 분석", "⚙️ 설정"])
    
    # --- [Tab 1] 월별 리포트 & 카드 실적 ---
    with tab1:
        col1, col2 = st.columns(2)
        available_years = sorted(st.session_state['available_years'])
        search_year = col1.selectbox("연도", available_years, index=len(available_years)-1 if available_years else 0)

        search_month = col2.selectbox("월", range(1, 13), index=datetime.now().month-1)

        if not df.empty:
            monthly_df = df[(df['날짜'].dt.year == search_year) & (df['날짜'].dt.month == search_month)]
        else:
            monthly_df = pd.DataFrame(columns=df.columns)

        # 1. 기본 요약
        st.markdown(f"### 📌 {search_month}월 요약")
        if not monthly_df.empty:
            income = monthly_df[monthly_df['구분']=='수입']['금액'].sum()
            expense = monthly_df[monthly_df['구분']=='지출']['금액'].sum()
            saving = monthly_df[monthly_df['구분']=='저축']['금액'].sum()
            
            m1, m2, m3 = st.columns(3)
            m1.metric("총 수입", f"{income:,.0f}원")
            m2.metric("총 지출", f"{expense:,.0f}원")
            m3.metric("총 저축", f"{saving:,.0f}원")
        else:
            st.info("데이터가 없습니다.")

        st.divider()

        # [NEW] 2. 상세 내역 및 지출 분석 (인라인 수정)
        col_detail, col_analysis = st.columns([0.65, 0.35])
        
        with col_detail:
            # [NEW] 고정 지출 섹션 (상단 배치)
            fh_col1, fh_col2 = st.columns([0.5, 0.5])
            fh_col1.subheader("📌 고정 지출")
            
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
                        "구분": st.column_config.SelectboxColumn("구분", options=["지출", "수입", "저축"], required=True),
                        "세부구분": st.column_config.SelectboxColumn("세부구분", options=["고정지출", "비고정지출", "-"], required=True),
                        "카테고리": st.column_config.SelectboxColumn("카테고리", options=all_categories, required=True),
                        "내용": st.column_config.TextColumn("내용", required=True),
                        "금액": st.column_config.NumberColumn("금액", format="%d원", step=1000, required=True),
                        "결제수단": st.column_config.SelectboxColumn("결제수단", options=payment_methods),
                        "카드명": st.column_config.SelectboxColumn("카드명", options=cards),
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
            dh_col1.subheader("📄 비고정 지출")
            
            if not monthly_df.empty:
                # 고정지출 제외
                detail_df = monthly_df[monthly_df['세부구분'] != '고정지출'].copy()
                
                if not detail_df.empty:
                    variable_sum = detail_df[detail_df['구분'] == '지출']['금액'].sum() 
                    variable_expense_sum = detail_df[detail_df['구분'] == '지출']['금액'].sum()
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
                            "구분": st.column_config.SelectboxColumn("구분", options=["지출", "수입", "저축"], required=True),
                            "세부구분": st.column_config.SelectboxColumn("세부구분", options=["고정지출", "비고정지출", "-"], required=True),
                            "카테고리": st.column_config.SelectboxColumn("카테고리", options=all_categories, required=True),
                            "내용": st.column_config.TextColumn("내용", required=True),
                            "금액": st.column_config.NumberColumn("금액", format="%d원", step=1000, required=True),
                            "결제수단": st.column_config.SelectboxColumn("결제수단", options=payment_methods),
                            "카드명": st.column_config.SelectboxColumn("카드명", options=cards),
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
            st.subheader("🍩 지출 분석")
            if not monthly_df.empty:
                expense_df = monthly_df[monthly_df['구분'] == '지출']
                if not expense_df.empty:
                    chart_data = expense_df.groupby('카테고리')['금액'].sum().reset_index()
                    
                    base = alt.Chart(chart_data).encode(
                        theta=alt.Theta("금액", stack=True)
                    )
                    
                    pie = base.mark_arc(outerRadius=120).encode(
                        color=alt.Color("카테고리"),
                        order=alt.Order("금액", sort="descending"),
                        tooltip=["카테고리", alt.Tooltip("금액", format=",")]
                    )
                    
                    text = base.mark_text(radius=140).encode(
                        text=alt.Text("금액", format=","),
                        order=alt.Order("금액", sort="descending"),
                        color=alt.value("white") 
                    )
                    
                    st.altair_chart(pie + text, use_container_width=True)
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
            valid_cards = [c for c in monthly_df['카드명'].unique() if c in st.session_state['cards_info']]
            card_spend = monthly_df[monthly_df['카드명'].isin(valid_cards)].groupby('카드명')['금액'].sum()
            
            # 등록된 모든 카드에 대해 표시 (사용액 0원이라도)
            for card_name, tiers in st.session_state['cards_info'].items():
                current_amount = card_spend.get(card_name, 0)
                
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

    # --- [Tab 2] 연간 리포트 ---
    # --- [Tab 2] 달력 보기 ---
    with tab_cal:
        st.subheader("📅 월별 달력")
        c1, c2 = st.columns(2)
        available_years = sorted(st.session_state['available_years'])
        cal_year = c1.selectbox("연도", available_years, index=len(available_years)-1 if available_years else 0, key="cal_year")
        cal_month = c2.selectbox("월", range(1, 13), index=datetime.now().month-1, key="cal_month")
        
        st.divider()
        render_calendar(cal_year, cal_month, df)

    # --- [Tab 3] 분석 (연간 리포트) ---
    with tab3:
        if df.empty:
            st.info("데이터가 없습니다.")
        else:
            year_select = st.selectbox("연도 확인", available_years, key='year_select_tab2', index=len(available_years)-1)
            
            year_df = df[df['날짜'].dt.year == year_select].copy()
            if not year_df.empty:
                year_df['월'] = year_df['날짜'].dt.month
                pivot = year_df.groupby(['월', '구분'])['금액'].sum().unstack(fill_value=0)
                st.bar_chart(pivot)
                st.dataframe(pivot.style.format("{:,.0f}원"), use_container_width=True)
            else:
                st.write("해당 연도 데이터가 없습니다.")

    # --- [Tab 3] 데이터 관리 ---
    # --- [Tab 2] 전체 내역 (데이터 관리) ---
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
                    required_columns = ['날짜', '구분', '세부구분', '카테고리', '내용', '금액', '결제수단', '카드명', '메모']
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

    # --- [Tab 4] 설정 (카테고리 & 카드 관리) ---
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

