import streamlit as st
import os
import sys
import re
import time
import json
import subprocess
import urllib.parse
import requests
from datetime import datetime, timedelta
from pydub import AudioSegment

# --- CẤU HÌNH TRANG WEB ---
st.set_page_config(
    page_title="VietVoice AI - Premium TTS",
    page_icon="✨",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- ĐƯỜNG DẪN HỆ THỐNG ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PIPER_EXE = os.path.join(BASE_DIR, "piper", "piper")
if os.name == 'nt':  
    PIPER_EXE += ".exe"

# File dữ liệu lưu thông tin tài khoản ngay trên Web
DB_FILE = os.path.join(BASE_DIR, "users_db.json")

# Tự động khởi tạo file cơ sở dữ liệu nếu chưa có
if not os.path.exists(DB_FILE):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        # Tạo sẵn tài khoản quản trị admin/admin123
        json.dump({
            "admin": {
                "password": "admin123",
                "expire_date": "2036-12-31 23:59:59",
                "is_vip": True,
                "is_admin": True
            }
        }, f, ensure_ascii=False, indent=4)

# --- CÁC HÀM XỬ LÝ DATABASE CỤC BỘ (LƯU TRÊN WEB) ---
def load_users():
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_users(users_data):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(users_data, f, ensure_ascii=False, indent=4)

def get_session_output_path():
    if "session_id" not in st.session_state:
        st.session_state.session_id = f"{int(time.time())}_{os.getpid()}"
    return os.path.join(BASE_DIR, f"output_temp_{st.session_state.session_id}.wav")

# ================= CẤU HÌNH THÔNG TIN NẠP TIỀN & API BANK =================
WEB_MUA_KEY = "http://localhost:8000"
BANK_ID = "MB" 
BANK_ACCOUNT = "05165917641234" 
ACCOUNT_NAME = "HO MINH PHUONG" 

# Nhập token API từ cổng dịch vụ quét biến động số dư của bạn (Ví dụ: Sepay, Casso,...)
API_KEY_BANK = "JGURMKIPD29F8H83OBBFJQXWS0T7IAXMKWY1BECT2NUCTS9NQUVTVQG6LDHLPH40"  
API_URL_CHECK = "https://api.sepay.vn/user/balance/history" # Endpoint kiểm tra lịch sử giao dịch

VIP_PACKAGES = {
    "Gói 1 Tháng": {"days": 30, "price": 50000, "desc": "Sử dụng đầy đủ giọng đọc chất lượng cao, không giới hạn ký tự trong 30 ngày."},
    "Gói 3 Tháng": {"days": 90, "price": 100000, "desc": "Tiết kiệm 15%. Sử dụng đầy đủ tính năng Premium trong 90 ngày."},
    "Gói 1 Năm": {"days": 365, "price": 799000, "desc": "Tiết kiệm 30%. Gói VIP dài hạn tối ưu nhất trong 365 ngày."}
}

# --- KHỞI TẠO STATE SESSION ---
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "username" not in st.session_state:
    st.session_state.username = None
if "expire_date" not in st.session_state:
    st.session_state.expire_date = None
if "is_vip" not in st.session_state:
    st.session_state.is_vip = False
if "is_admin" not in st.session_state:
    st.session_state.is_admin = False 
if "srt_data" not in st.session_state:
    st.session_state.srt_data = []

# --- HÀM TRỢ GIÚP PHỤ ĐỀ SRT ---
def srt_time_to_ms(time_str):
    time_str = time_str.replace(',', '.')
    hours, minutes, seconds = time_str.split(':')
    secs, ms = seconds.split('.')
    return (int(hours) * 3600 + int(minutes) * 60 + int(secs)) * 1000 + int(ms)

def parse_srt(content):
    pattern = re.compile(
        r'(\d+)\s*\n'
        r'(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*\n'
        r'(.*?)(?=\n\s*\n|\n*\s*$)', re.DOTALL
    )
    matches = pattern.findall(content)
    srt_list = []
    for match in matches:
        idx, start_str, end_str, text = match
        srt_list.append({
            "start": srt_time_to_ms(start_str),
            "end": srt_time_to_ms(end_str),
            "text": " ".join(text.strip().split('\n'))
        })
    return srt_list

def get_available_voices():
    return [f for f in os.listdir(BASE_DIR) if f.endswith('.onnx')]

def check_payment_via_api(expected_content, expected_amount):
    """
    Gọi tới cổng API để duyệt tìm giao dịch.
    Đã được tối ưu hóa để ẩn lỗi hệ thống và hiển thị cảnh báo thân thiện.
    """
    try:
        headers = {
            "Authorization": f"Bearer {API_KEY_BANK}",
            "Content-Type": "application/json"
        }
        # Thực hiện gọi API với timeout ngắn (5 giây) để tránh treo app
        response = requests.get(API_URL_CHECK, headers=headers, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            transactions = data.get("transactions", []) or data.get("data", [])
            
            for tx in transactions:
                tx_content = str(tx.get("transaction_content", "") or tx.get("description", "")).lower()
                tx_amount = float(tx.get("amount", 0) or tx.get("creditAmount", 0))
                
                if expected_content.lower() in tx_content and tx_amount >= expected_amount:
                    return True
        return False
    except requests.exceptions.ConnectionError:
        # Bắt riêng lỗi mất mạng/lỗi DNS và đưa ra cảnh báo đẹp đẽ
        st.warning("⚠️ Không thể kết nối tới máy chủ ngân hàng. Vui lòng kiểm tra lại kết nối Internet của máy chủ hoặc thử lại sau ít phút!")
        return False
    except Exception as e:
        # Các lỗi vụn vặt khác
        return Fals
# ================= GIAO DIỆN CHƯA ĐĂNG NHẬP =================
if not st.session_state.logged_in:
    tab_login, tab_register = st.tabs(["🔐 Đăng Nhập", "📝 Đăng Ký Tài Khoản"])
    
    # --- Tab Đăng Nhập ---
    with tab_login:
        st.subheader("ĐĂNG NHẬP HỆ THỐNG")
        login_user = st.text_input("Tên đăng nhập", key="login_user_input").strip()
        login_pass = st.text_input("Mật khẩu", type="password", key="login_pass_input")
        
        if st.button("Đăng Nhập 🚀", use_container_width=True):
            if not login_user or not login_pass:
                st.warning("Vui lòng điền đầy đủ tài khoản và mật khẩu!")
            else:
                users = load_users()
                if login_user in users and users[login_user]["password"] == login_pass:
                    user_info = users[login_user]
                    expire_date = datetime.strptime(user_info["expire_date"], "%Y-%m-%d %H:%M:%S")
                    
                    if datetime.now() > expire_date and not user_info.get("is_admin", False):
                        st.error("Tài khoản đã hết hạn! Vui lòng nạp tiền nâng cấp VIP.")
                        st.session_state.username = login_user
                    else:
                        st.session_state.logged_in = True
                        st.session_state.username = login_user
                        st.session_state.expire_date = user_info["expire_date"]
                        st.session_state.is_vip = user_info["is_vip"]
                        st.session_state.is_admin = user_info.get("is_admin", False)
                        st.success(f"Chào mừng {login_user} quay trở lại!")
                        st.rerun()
                else:
                    st.error("Tên đăng nhập hoặc mật khẩu không đúng!")

    # --- Tab Đăng Ký ---
    with tab_register:
        st.subheader("TẠO TÀI KHOẢN MỚI")
        reg_user = st.text_input("Tên đăng nhập mới").strip()
        reg_pass = st.text_input("Mật khẩu", type="password", key="reg_pass_input")
        reg_confirm = st.text_input("Xác nhận mật khẩu", type="password")
        
        if st.button("Tạo Tài Khoản 🟢", use_container_width=True):
            if not reg_user or not reg_pass or not reg_confirm:
                st.warning("Vui lòng điền đầy đủ thông tin!")
            elif reg_pass != reg_confirm:
                st.error("Mật khẩu xác nhận không khớp!")
            else:
                users = load_users()
                if reg_user in users:
                    st.error("Tên đăng nhập đã tồn tại trên hệ thống!")
                else:
                    # Tạo hạn dùng thử 1 ngày
                    trial_expire = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
                    
                    users[reg_user] = {
                        "password": reg_pass,
                        "expire_date": trial_expire,
                        "is_vip": False,
                        "is_admin": False
                    }
                    save_users(users)
                    
                    st.success("🎉 Đăng ký thành công! Đang tự động đăng nhập...")
                    
                    st.session_state.logged_in = True
                    st.session_state.username = reg_user
                    st.session_state.expire_date = trial_expire
                    st.session_state.is_vip = False
                    st.session_state.is_admin = False
                    
                    time.sleep(1.5)
                    st.rerun()

# ================= GIAO DIỆN CHÍNH KHI ĐÃ ĐĂNG NHẬP THÀNH CÔNG =================
else:
    with st.sidebar:
        st.title("✨ VietVoice AI Studio")
        st.write(f"👤 **User:** `{st.session_state.username}`")
        st.write(f"📅 **Hạn dùng:** `{st.session_state.expire_date}`")
        
        if st.session_state.is_admin:
            st.markdown("🛠️ **Cấp bậc:** `Administrator` 👑")
        elif st.session_state.is_vip:
            st.markdown("🏆 **Cấp bậc:** `Premium VIP` ✨")
        else:
            st.markdown("⭐ **Cấp bậc:** `Học viên / Trial` ⏱️")
            
        st.markdown("---")
        
        if st.button("Đăng Xuất 🚪", use_container_width=True):
            st.session_state.logged_in = False
            st.session_state.username = None
            st.session_state.expire_date = None
            st.session_state.is_admin = False
            st.session_state.is_vip = False
            st.rerun()

    menu_tabs = ["🎙️ Studio TTS", "💳 Mua Gói VIP & Nạp Tiền"]
    if st.session_state.is_admin:
        menu_tabs.append("⚙️ Trang Quản Trị (Admin)")
        
    main_tabs = st.tabs(menu_tabs)

    # ================= TAB 1: STUDIO CHUYỂN GIỌNG NÓI =================
    with main_tabs[0]:
        st.markdown("### 👥 Cài Đặt Giọng Đọc AI")
        col_voice, col_speed = st.columns([1.5, 1])
        
        with col_voice:
            voices = get_available_voices()
            selected_model = st.selectbox(
                "Chọn Mô hình Giọng Đọc (.onnx):", 
                options=voices if voices else ["Không tìm thấy mô hình .onnx nào trong thư mục ứng dụng"]
            )
            
        with col_speed:
            speed = st.slider("⚡ Tốc độ đọc (Speed Scale):", min_value=0.5, max_value=2.0, value=1.0, step=0.1)
            length_scale = str(1.0 / speed)

        st.markdown("---")
        tab_text, tab_srt = st.tabs(["📝 Chuyển Văn Bản Thường", "🎬 Đồng Bộ Phụ Đề SRT"])

        with tab_text:
            st.subheader("Chuyển văn bản tự do thành giọng nói")
            input_text = st.text_area("Nhập văn bản cần đọc:", value="Chào mừng bạn đến với VietVoice AI Studio.", height=200)
            
            if st.button("🔊 Phát Sinh Giọng Đọc", type="primary"):
                if not input_text.strip():
                    st.warning("Vui lòng nhập văn bản!")
                elif not selected_model or "Không tìm thấy" in selected_model:
                    st.error("Vui lòng tải file giọng đọc .onnx vào thư mục ứng dụng!")
                else:
                    progress_text = "Đang sinh giọng đọc..."
                    my_bar = st.progress(0, text=progress_text)
                    
                    try:
                        start_time = time.time()
                        model_path = os.path.join(BASE_DIR, selected_model)
                        my_bar.progress(30, text="Đang xử lý mô hình Piper AI...")
                        
                        output_path = get_session_output_path()
                        subprocess.run(
                            [PIPER_EXE, "--model", model_path, "--length_scale", length_scale, "--output_file", output_path],
                            input=input_text, text=True, encoding="utf-8", check=True,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                        )
                        
                        my_bar.progress(100, text="Hoàn tất!")
                        elapsed = time.time() - start_time
                        st.success(f"Thành công! Thời gian xử lý: {elapsed:.2f} giây.")
                        
                        if os.path.exists(output_path):
                            with open(output_path, "rb") as f:
                                audio_bytes = f.read()
                            st.audio(audio_bytes, format="audio/wav")
                            st.download_button("💾 Tải File Audio Ra Máy", data=audio_bytes, file_name="VietVoice_Output.wav", mime="audio/wav")
                    except Exception as e:
                        st.error(f"Đã xảy ra lỗi khi chạy Piper: {str(e)}")

        with tab_srt:
            st.subheader("Tự động đồng bộ và co dãn giọng đọc theo dòng thời gian SRT")
            uploaded_file = st.file_uploader("Nạp File Phụ đề SRT (*.srt)", type=["srt"])
            
            if uploaded_file is not None:
                stringio = uploaded_file.getvalue().decode("utf-8")
                st.session_state.srt_data = parse_srt(stringio)
                st.info(f"Đã nạp thành công `{len(st.session_state.srt_data)}` phân đoạn phụ đề từ file.")
            
            if st.button("⚡ Tạo Khớp Thời Gian & Phát Sinh File", type="primary", key="btn_gen_srt_web"):
                if not st.session_state.srt_data:
                    st.warning("Vui lòng tải lên file phụ đề .SRT trước!")
                elif not selected_model or "Không tìm thấy" in selected_model:
                    st.error("Chưa chọn được mô hình giọng đọc .onnx!")
                else:
                    progress_bar = st.progress(0, text="Bắt đầu phân tích...")
                    try:
                        start_time = time.time()
                        model_path = os.path.join(BASE_DIR, selected_model)
                        
                        total_duration_ms = st.session_state.srt_data[-1]["end"]
                        combined_audio = AudioSegment.silent(duration=total_duration_ms)
                        
                        temp_dir = os.path.join(BASE_DIR, "temp_tts")
                        os.makedirs(temp_dir, exist_ok=True)
                        total_segments = len(st.session_state.srt_data)
                        
                        for index, segment in enumerate(st.session_state.srt_data):
                            seg_id = index + 1
                            start_ms = segment["start"]
                            end_ms = segment["end"]
                            text = segment["text"]
                            duration_limit = end_ms - start_ms
                            
                            percent = int((index / total_segments) * 100)
                            progress_bar.progress(percent, text=f"Đang xử lý phân đoạn {seg_id}/{total_segments}...")
                            temp_segment_wav = os.path.join(temp_dir, f"seg_{seg_id}.wav")
                            
                            subprocess.run(
                                [PIPER_EXE, "--model", model_path, "--length_scale", length_scale, "--output_file", temp_segment_wav],
                                input=text, text=True, encoding="utf-8", check=True,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                            )
                            
                            if os.path.exists(temp_segment_wav):
                                seg_audio = AudioSegment.from_wav(temp_segment_wav)
                                seg_len = len(seg_audio)
                                
                                if seg_len > duration_limit and duration_limit > 0:
                                    speed_ratio = seg_len / duration_limit
                                    seg_audio = seg_audio.speedup(playback_speed=speed_ratio)
                                
                                combined_audio = combined_audio.overlay(seg_audio, position=start_ms)
                                try: os.remove(temp_segment_wav)
                                except: pass
                                    
                        output_path = get_session_output_path()
                        combined_audio.export(output_path, format="wav")
                        try: os.rmdir(temp_dir)
                        except: pass
                        
                        progress_bar.progress(100, text="Hoàn tất ghép nối!")
                        st.success(f"Khớp nối thành công trong {time.time() - start_time:.2f} giây!")
                        
                        if os.path.exists(output_path):
                            with open(output_path, "rb") as f:
                                audio_bytes = f.read()
                            st.audio(audio_bytes, format="audio/wav")
                            
                            col_dl1, col_dl2 = st.columns(2)
                            with col_dl1:
                                st.download_button("💾 Tải File WAV", data=audio_bytes, file_name="VietVoice_Synced.wav", mime="audio/wav", use_container_width=True)
                            with col_dl2:
                                mp3_buffer = os.path.join(BASE_DIR, "output_temp.mp3")
                                combined_audio.export(mp3_buffer, format="mp3", bitrate="192k")
                                with open(mp3_buffer, "rb") as f_mp3:
                                    mp3_bytes = f_mp3.read()
                                st.download_button("💾 Tải File MP3", data=mp3_bytes, file_name="VietVoice_Synced.mp3", mime="audio/mp3", use_container_width=True)
                    except Exception as e:
                        st.error(f"Lỗi ghép nối phụ đề: {str(e)}")

    # ================= TAB 2: MUA GÓI VIP & TỰ ĐỘNG CỘNG HẠN QUA API =================
    with main_tabs[1]:
        st.subheader("💳 Nâng Cấp Tài Khoản VIP Trực Tuyến")
        
        cols_pack = st.columns(3)
        for idx, (pkg_name, info) in enumerate(VIP_PACKAGES.items()):
            with cols_pack[idx]:
                st.markdown(f"### 🏆 {pkg_name}")
                st.markdown(f"## {info['price']:,} VNĐ")
                st.write(info['desc'])
                if st.button(f"Chọn {pkg_name}", key=f"btn_pkg_{idx}", use_container_width=True):
                    st.session_state.selected_package = pkg_name

        st.markdown("---")
        
        if "selected_package" in st.session_state:
            pkg_name = st.session_state.selected_package
            pkg_info = VIP_PACKAGES[pkg_name]
            
            transfer_content = f"VV {st.session_state.username} {pkg_name.replace(' ', '')}"
            qr_url = f"https://img.vietqr.io/image/{BANK_ID}-{BANK_ACCOUNT}-compact2.png?amount={pkg_info['price']}&addInfo={urllib.parse.quote(transfer_content)}&accountName={urllib.parse.quote(ACCOUNT_NAME)}"
            
            col_pay1, col_pay2 = st.columns([1, 1.2])
            with col_pay1:
                st.image(qr_url, caption="Quét mã QR để tự động làm lệnh thanh toán", width=300)
            with col_pay2:
                st.info(f"""
                *   **Ngân hàng:** {BANK_ID.upper()}
                *   **Số tài khoản:** `{BANK_ACCOUNT}`
                *   **Số tiền:** `{pkg_info['price']:,} VNĐ`
                *   **Nội dung chuyển khoản:** `{transfer_content}`
                """)
                
                # --- NÚT BẤM TỰ ĐỘNG KIỂM TRA LỊCH SỬ GIAO DỊCH QUA API ---
                if st.button("Xác nhận đã chuyển tiền 🔔 (Tự động kích hoạt)", use_container_width=True, type="primary"):
                    with st.spinner("Đang truy vấn lịch sử ngân hàng để xác nhận giao dịch..."):
                        is_paid = check_payment_via_api(expected_content=transfer_content, expected_amount=pkg_info['price'])
                        
                        if is_paid:
                            users = load_users()
                            current_user = st.session_state.username
                            
                            if current_user in users:
                                # Lấy mốc thời gian hạn dùng hiện tại
                                try:
                                    current_expire = datetime.strptime(users[current_user]["expire_date"], "%Y-%m-%d %H:%M:%S")
                                except:
                                    current_expire = datetime.now()
                                    
                                if current_expire < datetime.now():
                                    current_expire = datetime.now()
                                    
                                # Cộng dồn số ngày sử dụng
                                days_to_add = pkg_info["days"]
                                new_expire = (current_expire + timedelta(days=days_to_add)).strftime("%Y-%m-%d %H:%M:%S")
                                
                                # Cập nhật DB cục bộ JSON
                                users[current_user]["expire_date"] = new_expire
                                users[current_user]["is_vip"] = True
                                save_users(users)
                                
                                # Cập nhật trực tiếp lên Client UI State
                                st.session_state.expire_date = new_expire
                                st.session_state.is_vip = True
                                
                                st.balloons()
                                st.success(f"🎉 Xác nhận thành công! Tài khoản `{current_user}` đã được kích hoạt thành công {pkg_name} ({days_to_add} ngày) đến ngày {new_expire}!")
                                time.sleep(2)
                                st.rerun()
                        else:
                            st.error("❌ Hệ thống chưa ghi nhận được khoản chuyển của bạn. Nếu vừa thao tác, xin vui lòng chờ 1-2 phút rồi nhấn xác nhận lại.")

    # ================= TAB 3: TRANG QUẢN TRỊ ADMIN CỤC BỘ =================
    if st.session_state.is_admin:
        with main_tabs[2]:
            st.subheader("⚙️ Bảng Quản Trị Hệ Thống Web - Quản Lý File JSON")
            
            col_ad1, col_ad2 = st.columns(2)
            
            with col_ad1:
                st.markdown("#### 👤 Kích hoạt / Duyệt VIP Trực Tiếp Cho Khách")
                target_user = st.text_input("Nhập chính xác tên tài khoản khách:")
                add_days = st.number_input("Số ngày VIP cấp mới:", min_value=1, max_value=365, value=30)
                
                if st.button("Cập Nhật Quyền VIP 🚀", use_container_width=True):
                    users = load_users()
                    if target_user in users:
                        new_expire = (datetime.now() + timedelta(days=int(add_days))).strftime("%Y-%m-%d %H:%M:%S")
                        users[target_user]["expire_date"] = new_expire
                        users[target_user]["is_vip"] = True
                        save_users(users)
                        st.success(f"Thành công! Tài khoản `{target_user}` đã được lên VIP tới ngày {new_expire}")
                    else:
                        st.error("Tên tài khoản này không tồn tại trên hệ thống web cục bộ!")
            
            with col_ad2:
                st.markdown("#### 📊 Danh Sách Người Dùng Hiện Tại")
                users_list = load_users()
                display_data = []
                for username, info in users_list.items():
                    display_data.append({
                        "Tài khoản": username,
                        "Hạn dùng": info["expire_date"],
                        "Trạng thái VIP": "Premium ✨" if info["is_vip"] else "Thường ⏱️",
                        "Admin": "Đúng" if info.get("is_admin", False) else "Không"
                    })
                st.table(display_data)