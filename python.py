# investment_app.py - Phiên bản Hoàn chỉnh và Sửa lỗi

import streamlit as st
import pandas as pd
import numpy as np
# Cần import numpy_financial vì các hàm npv/irr đã bị loại khỏi numpy
import numpy_financial as npf 
from google import genai
from google.genai.errors import APIError
from docx import Document
import io
import re

# --- Cấu hình Trang Streamlit ---
st.set_page_config(
    page_title="App Đánh Giá Phương Án Kinh Doanh",
    layout="wide"
)

st.title("Ứng dụng Đánh giá Phương án Kinh doanh 📈")

# --- Hàm đọc file Word ---
@st.cache_data(show_spinner="Đang đọc nội dung file Word...")
def read_docx_file(uploaded_file):
    """Đọc nội dung văn bản từ file Word."""
    try:
        # Cần reset con trỏ file nếu nó đã được đọc trước đó
        uploaded_file.seek(0)
        doc = Document(io.BytesIO(uploaded_file.read()))
        full_text = []
        for para in doc.paragraphs:
            full_text.append(para.text)
        return "\n".join(full_text)
    except Exception as e:
        return f"Lỗi đọc file Word: {e}"

# --- Hàm gọi API Gemini để trích xuất thông tin (Yêu cầu 1) ---
@st.cache_data(show_spinner="Đang gửi văn bản và trích xuất thông số tài chính bằng Gemini...")
def extract_financial_data(doc_text, api_key):
    """Sử dụng Gemini để trích xuất các thông số tài chính từ văn bản."""
    
    if not api_key:
        raise ValueError("Khóa API không được cung cấp.")
        
    client = genai.Client(api_key=api_key)
    model_name = 'gemini-2.5-flash'
    
    # Prompt yêu cầu JSON nguyên mẫu để dễ dàng parse
    prompt = f"""
    Bạn là một chuyên gia tài chính và phân tích dự án. Nhiệm vụ của bạn là trích xuất các thông số sau từ nội dung văn bản kinh doanh bên dưới. 
    Các thông số này phải là GIÁ TRỊ SỐ (dạng tiền tệ), không có đơn vị (ví dụ: 30000000000 cho 30 tỷ). Vui lòng chuyển đổi mọi đơn vị tiền tệ (như tỷ VNĐ) về đơn vị VNĐ (đồng).
    
    Vốn đầu tư (Initial Investment - C0): Giá trị tuyệt đối của vốn ban đầu cần bỏ ra.
    Dòng đời dự án (Project Life - N): Số năm hoạt động của dự án.
    WACC (Cost of Capital - k): Tỷ lệ chiết khấu (dạng thập phân, ví dụ: 0.13 cho 13%).
    Thuế suất (Tax Rate - t): Tỷ lệ thuế thu nhập doanh nghiệp (dạng thập phân, ví dụ: 0.20 cho 20%).
    
    Doanh thu hàng năm (Annual Revenue - R): Ước tính con số đại diện cho doanh thu hàng năm.
    Chi phí hoạt động hàng năm (Annual Operating Cost - C): Ước tính con số đại diện cho chi phí hoạt động hàng năm (chưa bao gồm Khấu hao).
    
    Nếu không tìm thấy thông tin cụ thể, hãy trả về 0 cho giá trị số.

    Định dạng đầu ra **bắt buộc** là JSON nguyên mẫu (RAW JSON), không có bất kỳ giải thích hay văn bản nào khác.
    
    {{
      "Vốn đầu tư": <Giá trị số VNĐ>,
      "Dòng đời dự án": <Giá trị số năm>,
      "Doanh thu hàng năm": <Giá trị số VNĐ>,
      "Chi phí hoạt động hàng năm": <Giá trị số VNĐ>,
      "WACC": <Giá trị số thập phân>,
      "Thuế suất": <Giá trị số thập phân>
    }}

    Nội dung file Word:
    ---
    {doc_text}
    """
    
    try:
        response = client.models.generate_content(
            model=model_name,
            contents=prompt
        )
        
        # Xử lý chuỗi JSON trả về
        json_str = response.text.strip()
        # Loại bỏ các dấu ```json hoặc ``` có thể có
        if json_str.startswith("```json"):
            json_str = json_str[7:]
        if json_str.endswith("```"):
            json_str = json_str[:-3]
        
        return pd.read_json(io.StringIO(json_str), typ='series')
    except Exception as e:
        # Trong trường hợp AI trả về không phải JSON thuần
        st.error(f"AI không trả về JSON hợp lệ. Nội dung phản hồi: {response.text}")
        raise e

# --- Hàm tính toán Chỉ số Tài chính (Yêu cầu 3) ---
def calculate_project_metrics(df_cashflow, initial_investment, wacc):
    """Tính toán NPV, IRR, PP, DPP."""
    
    # Dòng tiền từ năm 1 đến năm N
    cash_flows = df_cashflow['Dòng tiền thuần (CF)'].values
    
    # Dòng tiền đầy đủ: [Năm 0 (đầu tư), Năm 1, ..., Năm N]
    full_cash_flows = np.insert(cash_flows, 0, -initial_investment) 
    
    # 1. NPV
    # npf.npv tính NPV bằng cách chiết khấu các CF[1:] và cộng với CF[0]
    npv_value = npf.npv(wacc, full_cash_flows)
    
    # 2. IRR
    try:
        # Dùng npf.irr
        irr_value = npf.irr(full_cash_flows)
    except ValueError:
        irr_value = np.nan # Không tính được IRR nếu dòng tiền không đổi dấu

    # 3. PP (Payback Period - Thời gian hoàn vốn)
    cumulative_cf = np.cumsum(full_cash_flows)
    pp_year = np.where(cumulative_cf >= 0)[0]
    pp = 'Không hoàn vốn'
    
    if pp_year.size > 0:
        pp_year = pp_year[0]
        if pp_year == 0: 
             pp = 0.0 
        else:
             capital_remaining = abs(cumulative_cf[pp_year-1])
             # Lấy dòng tiền thuần từ năm hoàn vốn
             cf_of_payback_year = full_cash_flows[pp_year]
             if cf_of_payback_year != 0:
                 pp = pp_year - 1 + (capital_remaining / cf_of_payback_year)
             else:
                 pp = float(pp_year)

    # 4. DPP (Discounted Payback Period - Thời gian hoàn vốn có chiết khấu)
    discount_factors = 1 / ((1 + wacc) ** np.arange(0, len(full_cash_flows)))
    discounted_cf = full_cash_flows * discount_factors
    cumulative_dcf = np.cumsum(discounted_cf)
    
    dpp_year = np.where(cumulative_dcf >= 0)[0]
    dpp = 'Không hoàn vốn'
    
    if dpp_year.size > 0:
        dpp_year = dpp_year[0]
        if dpp_year == 0:
             dpp = 0.0
        else:
             capital_remaining_d = abs(cumulative_dcf[dpp_year-1])
             dcf_of_payback_year = discounted_cf[dpp_year] 
             if dcf_of_payback_year != 0:
                 dpp = dpp_year - 1 + (capital_remaining_d / dcf_of_payback_year)
             else:
                 dpp = float(dpp_year)
        
    return npv_value, irr_value, pp, dpp

# --- Hàm gọi AI phân tích chỉ số (Yêu cầu 4) ---
def get_ai_evaluation(metrics_data, wacc_rate, api_key):
    """Gửi các chỉ số đánh giá dự án đến Gemini API và nhận phân tích."""
    
    if not api_key:
        return "Lỗi: Khóa API không được cung cấp."

    try:
        client = genai.Client(api_key=api_key)
        model_name = 'gemini-2.5-flash'  

        # Xử lý các giá trị 'Không hoàn vốn' hoặc nan
        npv_display = f"{metrics_data['NPV']:,.0f} VNĐ"
        irr_display = f"{metrics_data['IRR']:.2%}" if not np.isnan(metrics_data['IRR']) else "Không tính được"
        pp_display = f"{metrics_data['PP']:.2f} năm" if isinstance(metrics_data['PP'], float) else metrics_data['PP']
        dpp_display = f"{metrics_data['DPP']:.2f} năm" if isinstance(metrics_data['DPP'], float) else metrics_data['DPP']

        prompt = f"""
Bạn là một chuyên gia phân tích dự án đầu tư có kinh nghiệm. Dựa trên các chỉ số hiệu quả dự án sau, hãy đưa ra nhận xét ngắn gọn, khách quan (khoảng 3-4 đoạn) về khả năng chấp nhận và rủi ro của dự án. 
        
        Các chỉ số cần phân tích:
        - NPV: {npv_display}
        - IRR: {irr_display}
        - WACC (Tỷ lệ chiết khấu): {wacc_rate:.2%}
        - PP (Thời gian hoàn vốn): {pp_display}
        - DPP (Thời gian hoàn vốn có chiết khấu): {dpp_display}
        
        Chú ý:
        1. Đánh giá tính khả thi (NPV > 0 và IRR > WACC).
        2. Nhận xét về tốc độ hoàn vốn (PP và DPP).
        3. Kết luận tổng thể về việc chấp nhận hay từ chối dự án.
        """

        response = client.models.generate_content(
            model=model_name,
            contents=prompt
        )
        return response.text

    except APIError as e:
        return f"Lỗi gọi Gemini API: Vui lòng kiểm tra Khóa API. Chi tiết lỗi: {e}"
    except Exception as e:
        return f"Đã xảy ra lỗi không xác định: {e}"

# --- Giao diện và Luồng chính ---

# Lấy API Key
api_key = st.secrets.get("GEMINI_API_KEY")

if not api_key:
     st.error("⚠️ Vui lòng cấu hình Khóa 'GEMINI_API_KEY' trong Streamlit Secrets để sử dụng chức năng AI.")

uploaded_file = st.file_uploader(
    "1. Tải file Word (.docx) chứa Phương án Kinh doanh:",
    type=['docx']
)

# Khởi tạo state để lưu trữ dữ liệu đã trích xuất
if 'extracted_data' not in st.session_state:
    st.session_state['extracted_data'] = None

# --- Chức năng 1: Lọc dữ liệu bằng AI ---
if uploaded_file is not None:
    # Đọc file ngay khi tải lên để lấy doc_text
    doc_text = read_docx_file(uploaded_file)
    
    if st.button("Trích xuất Dữ liệu Tài chính bằng AI 🤖"):
        if api_key:
            try:
                # Đảm bảo doc_text không phải là chuỗi lỗi
                if doc_text.startswith("Lỗi đọc file Word"):
                     st.error(doc_text)
                else:
                    st.session_state['extracted_data'] = extract_financial_data(doc_text, api_key)
                    st.success("Trích xuất dữ liệu thành công! Vui lòng cuộn xuống để xem kết quả.")
            except APIError:
                st.error("Lỗi API: Không thể kết nối hoặc xác thực API Key.")
            except Exception as e:
                st.error(f"Lỗi trích xuất: {e}")
        else:
            st.error("Vui lòng cung cấp Khóa API.")

# --- Hiển thị và Tính toán (Yêu cầu 2 & 3) ---
if st.session_state['extracted_data'] is not None:
    data = st.session_state['extracted_data']
    
    # ****************** Lọc các giá trị số và xử lý ngoại lệ ******************
    try:
        # Cố gắng chuyển đổi các giá trị đã trích xuất từ AI
        initial_investment = float(data.get('Vốn đầu tư', 0))
        project_life = int(data.get('Dòng đời dự án', 0))
        annual_revenue = float(data.get('Doanh thu hàng năm', 0))
        annual_cost = float(data.get('Chi phí hoạt động hàng năm', 0))
        wacc = float(data.get('WACC', 0.13)) 
        tax_rate = float(data.get('Thuế suất', 0.20)) 
        
        # Đảm bảo WACC và Thuế suất ở dạng thập phân (0 < value < 1)
        if wacc > 1 and wacc <= 100: wacc /= 100
        if tax_rate > 1 and tax_rate <= 100: tax_rate /= 100
        
        # Kiểm tra tính hợp lệ cơ bản
        if project_life <= 0:
            st.error("Dòng đời dự án phải là số nguyên dương (> 0).")
            project_life = 1

    except Exception as e:
        st.error(f"Lỗi chuyển đổi dữ liệu trích xuất thành số. Vui lòng kiểm tra lại phản hồi JSON: {e}")
        initial_investment, project_life, wacc, tax_rate = 0, 1, 0.13, 0.2

    # ****************** Hiển thị Thông số ******************
    st.subheader("2. Các Thông số Dự án đã Trích xuất")
    
    # Định dạng tiền tệ
    def format_vnd(value):
        # Định dạng tiền tệ lớn
        if abs(value) >= 10**9:
            return f"{value / 10**9:,.2f} tỷ VNĐ"
        elif abs(value) >= 10**6:
            return f"{value / 10**6:,.0f} triệu VNĐ"
        return f"{value:,.0f} VNĐ"

    col1, col2, col3 = st.columns(3)
    col1.metric("Vốn Đầu tư (C₀)", format_vnd(initial_investment))
    col2.metric("Dòng đời dự án (N)", f"{project_life} năm")
    col3.metric("WACC (k)", f"{wacc:.2%}")
    col1.metric("Doanh thu Hàng năm (R)", format_vnd(annual_revenue))
    col2.metric("Chi phí HĐ Hàng năm (C)", format_vnd(annual_cost))
    col3.metric("Thuế suất (t)", f"{tax_rate:.2%}")

    st.markdown("---")
    
    # ****************** Bảng Dòng tiền (Yêu cầu 2) ******************
    st.subheader("3. Bảng Dòng tiền (Cash Flow)")
    
    if project_life > 0 and initial_investment >= 0:
        try:
            # Tính Khấu hao (theo phương pháp đường thẳng)
            depreciation = initial_investment / project_life 
            years = np.arange(1, project_life + 1)
            
            # Tính toán dòng tiền hàng năm (Giả định đơn giản: dòng tiền đều)
            EBT = annual_revenue - annual_cost - depreciation
            Tax = EBT * tax_rate if EBT > 0 else 0
            EAT = EBT - Tax
            # Dòng tiền thuần = Lợi nhuận sau thuế + Khấu hao
            CF = EAT + depreciation
            
            # Tạo DataFrame cho Dòng tiền
            cashflow_data = {
                'Năm': years,
                'Doanh thu (R)': [annual_revenue] * project_life,
                'Chi phí HĐ (C)': [annual_cost] * project_life,
                'Khấu hao (D)': [depreciation] * project_life,
                'Lợi nhuận trước thuế (EBT)': [EBT] * project_life,
                'Thuế (Tax)': [Tax] * project_life,
                'Lợi nhuận sau thuế (EAT)': [EAT] * project_life,
                'Dòng tiền thuần (CF)': [CF] * project_life
            }
            
            df_cashflow = pd.DataFrame(cashflow_data)
            
            st.dataframe(
                df_cashflow.style.format({
                    col: '{:,.0f}' for col in df_cashflow.columns if col not in ['Năm']
                }), 
                use_container_width=True
            )

            st.markdown("---")
            
            # ****************** Tính toán Chỉ số (Yêu cầu 3) ******************
            st.subheader("4. Các Chỉ số Đánh giá Hiệu quả Dự án")
            
            if wacc > 0:
                npv, irr, pp, dpp = calculate_project_metrics(df_cashflow, initial_investment, wacc)
                
                metrics_data = {
                    'NPV': npv,
                    'IRR': irr if not np.isnan(irr) else 0.0, 
                    'PP': pp,
                    'DPP': dpp
                }
                
                col1, col2, col3, col4 = st.columns(4)
                
                # Hàm định dạng cho PP/DPP
                def format_payback(value):
                    return f"{value:.2f} năm" if isinstance(value, float) else value
                
                # Hàm tính delta cho NPV
                delta_label = "Dự án có lời" if npv > 0 else "Dự án lỗ"
                delta_color = "inverse" if npv < 0 else "normal"
                
                col1.metric("NPV (Giá trị hiện tại thuần)", format_vnd(npv), delta=delta_label, delta_color=delta_color)
                col2.metric("IRR (Tỷ suất sinh lời nội tại)", f"{irr:.2%}" if not np.isnan(irr) else "Không tính được")
                col3.metric("PP (Thời gian hoàn vốn)", format_payback(pp))
                col4.metric("DPP (Hoàn vốn có chiết khấu)", format_payback(dpp))

                # ****************** Phân tích AI (Yêu cầu 4) ******************
                st.markdown("---")
                st.subheader("5. Phân tích Hiệu quả Dự án (AI)")
                
                if st.button("Yêu cầu AI Phân tích Chỉ số 🧠"):
                    if api_key:
                        with st.spinner('Đang gửi dữ liệu và chờ Gemini phân tích...'):
                            ai_result = get_ai_evaluation(metrics_data, wacc, api_key)
                            st.markdown("**Kết quả Phân tích từ Gemini AI:**")
                            st.info(ai_result)
                    else:
                         st.error("Lỗi: Không tìm thấy Khóa API. Vui lòng kiểm tra cấu hình Secrets.")

            except Exception as e:
                st.error(f"Có lỗi xảy ra khi tính toán chỉ số: {e}. Vui lòng kiểm tra các thông số đầu vào và WACC.")
        else:
            st.warning("WACC (Tỷ lệ chiết khấu) phải lớn hơn 0 để tính toán NPV và DPP.")

        # Xử lý trường hợp có thể không tính được IRR (dòng tiền không đổi dấu)
        if wacc > 0 and 'metrics_data' in locals() and np.isnan(metrics_data['IRR']):
            st.warning("IRR không thể tính được. Điều này thường xảy ra khi dòng tiền thuần không đổi dấu trong suốt vòng đời dự án (ví dụ: chỉ có dòng tiền dương).")


    else:
        st.warning("Vui lòng đảm bảo Dòng đời Dự án và Vốn Đầu tư đã được trích xuất thành công và có giá trị lớn hơn 0.")

else:
    st.info("Vui lòng tải lên file Word và nhấn nút 'Trích xuất Dữ liệu Tài chính bằng AI' để bắt đầu.")
