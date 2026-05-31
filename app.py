import os
import math
import csv
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

# --- LINE API 金鑰設定 ---
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# --- 本地 CSV 檔案路徑 ---
CSV_FILE_PATH = os.path.join(os.path.dirname(__file__), "pingtung_sites.csv")

# --- 🎯 射頻設備日常運轉基本功耗資料庫 (完全對齊您最新修正的精確瓦數) ---
EQUIPMENT_DATABASE = {
    # 宏基站 (Macro Cell) 既存規格
    "FXDB": {"name": "FXDB", "power": 780},
    "ARDA": {"name": "ARDA", "power": 480},  
    "FHDB": {"name": "FHDB", "power": 780},
    "AHDB": {"name": "AHDB", "power": 410},
    "FXEB": {"name": "FXEB", "power": 915},  
    "FXED": {"name": "FXED", "power": 860},  
    "FHEB": {"name": "FHEB", "power": 410},  
    "AHEB": {"name": "AHEB", "power": 410},
    "FHEL": {"name": "FHEL", "power": 350},  
    "FRHG": {"name": "FRHG", "power": 490},  
    "AHHB": {"name": "AHHB", "power": 321},  
    "AZQG": {"name": "AZQG", "power": 720},
    "AZQI": {"name": "AZQI", "power": 520},
    "AEQZ": {"name": "AEQZ", "power": 570},
    "AQQA": {"name": "AQQA", "power": 2095},
    "AQQY": {"name": "AQQY", "power": 740},
    "AVQC": {"name": "AVQC", "power": 900},
    "AVQL": {"name": "AVQL", "power": 380},
    "AHEGB": {"name": "AHEGB", "power": 1367},
    "AHEGB+B3": {"name": "AHEGB+B3", "power": 2128},
    "AHEGG": {"name": "AHEGG", "power": 410},
    "AHEGG+B3": {"name": "AHEGG+B3", "power": 780},
    
    # 最新硬體常態瓦數精確版 (Small Cell 微細胞規格)
    "FW2EHB": {"name": "FW2EHB", "power": 210},  
    "FR2EB": {"name": "FR2EB", "power": 140},    
    "FWEA": {"name": "FWEA", "power": 84},      
    "AHEJ": {"name": "AHEJ", "power": 90},      
    "AWHQE": {"name": "AWHQE", "power": 285}, 
    "FWHN": {"name": "FWHN", "power": 95}        
}

USER_SESSIONS = {}

def search_csv_database_advanced(keyword):
    """
    🎯 進階多行揉合核心：直接完美對齊您的全中文原始表格欄位
    支援「台號」精準搜尋與「台名」關鍵字模糊搜尋
    """
    if not os.path.exists(CSV_FILE_PATH):
        return 'NOT_FOUND', None
        
    keyword_up = keyword.upper().strip()
    matched_rows = []
    
    with open(CSV_FILE_PATH, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # 💡 精準修正：直接讀取您中文表格的「台號」與「台名」欄位，並去除頭尾空格
            sid = str(row.get("台號", "")).strip().upper()
            sname = str(row.get("台名", "")).strip()
            sname_up = sname.upper()
            
            # 如果「台號」完全符合，或者「台名」裡包含關鍵字
            if sid == keyword_up or keyword_up in sname_up:
                # 💡 精準修正：撈取您表格中的「模組型號」
                raw_model = str(row.get("模組型號", "")).strip().upper()
                
                # 東港安泰等站常出現 FWEA_FREA 複合字體，切開只取主體型號以防對不上硬體庫
                clean_model = raw_model.split('_')[0] if '_' in raw_model else raw_model
                
                # 自動抓取細胞名稱裡有沒有 3P 欄位（通常預設為 1P3W）
                cell_info = str(row.get("細胞(頻寬) / 細胞名稱", "")).upper()
                phase_type = "3P4W" if "3P" in cell_info else "1P3W"
                
                matched_rows.append({
                    "site_id": sid,
                    "site_name": sname,
                    "model": clean_model,
                    "ac_phase": phase_type
                })
                
    if not matched_rows:
        return 'NOT_FOUND', None
        
    # 算出一共抓到了幾種獨立的「台號」
    unique_site_ids = list(set([item["site_id"] for item in matched_rows]))
    
    # 情境 A：剛好鎖定唯一一座基站（自動把該基站散落在多行的射頻加總）
    if len(unique_site_ids) == 1:
        target_id = unique_site_ids[0]
        site_allels = [item for item in matched_rows if item["site_id"] == target_id]
        
        merged_equipments = {}
        final_name = site_allels[0]["site_name"]
        final_phase = "1P3W"  # 保底 1P3W 220V
        
        for item in site_allels:
            model = item["model"]
            if item["ac_phase"] == "3P4W":
                final_phase = "3P4W"
                
            # 揉合數量計演：如果該行型號存在於我們的功耗資料庫，數量就 +1
            if model in EQUIPMENT_DATABASE:
                merged_equipments[model] = merged_equipments.get(model, 0) + 1
                
        final_result = {
            "site_id": target_id,
            "site_name": final_name,
            "ac_phase": final_phase,
            "equipments": merged_equipments
        }
        return 'MATCH', final_result
        
    # 情境 B：關鍵字太模糊（如輸入「屏東」），同時找到多座不同台名的站，交給同仁重新補打
    if len(unique_site_ids) > 1:
        multi_list = []
        seen = set()
        for item in matched_rows:
            if item["site_id"] not in seen:
                seen.add(item["site_id"])
                multi_list.append(item)
        return 'MULTI', multi_list

def calculate_current_report(site_id, site_name, ac_phase, equipments):
    """即時計算該站點目前的現況電氣報告"""
    bbu_p = 400
    total_rf_power = 0
    detail_list = []

    for model, qty in equipments.items():
        spec = EQUIPMENT_DATABASE[model]
        row_total = spec["power"] * qty
        total_rf_power += row_total
        detail_list.append(f"   • {spec['name']} x {qty}台 = {row_total} W")

    net_dc_load = bbu_p + total_rf_power
    smr_efficiency = 0.92
    pf = 0.90
    ac_total_w = net_dc_load / smr_efficiency
    
    phase_title = "單相三線 (1P3W 220V)" if ac_phase == "1P3W" else "三相四線 (3P4W -> 實務抓單相 RST+N)"
    ac_current = ac_total_w / (220 * pf)
    calculated_nfb = math.ceil(ac_current * 1.25)
    
    if calculated_nfb <= 30:
        suggested_nfb, suggested_wire = 30, "8.0 mm²"
    elif calculated_nfb <= 50:
        suggested_nfb, suggested_wire = 50, "14 mm²"
    elif calculated_nfb <= 60:
        suggested_nfb, suggested_wire = 60, "22 mm²"
    elif calculated_nfb <= 85:
        suggested_nfb = 75 if calculated_nfb <= 75 else 100
        suggested_wire = "38 mm²"
    else:
        suggested_nfb, suggested_wire = calculated_nfb, "50 mm² 或以上"

    ac_kwh_per_hour = ac_total_w / 1000.0
    ac_kwh_per_month = ac_kwh_per_hour * 24 * 30
    detail_str = "\n".join(detail_list) if detail_list else "   • 無既存或相符之射頻設備"

    report = (
        f"🔍 【資料庫檢索——站台歷史現況報告】\n"
        f"🏢 台號：{site_id}\n"
        f"🏢 台名：{site_name}\n"
        f"⚡ 預設供電：{phase_title}\n\n"
        f"📋 既存射頻耗電明細：\n{detail_str}\n"
        f" -----------------------------------\n"
        f" 🔋 1. 直流端耗電需求\n"
        f"   • 主設備直流負載總和 (含BBU): {net_dc_load:.0f} W\n"
        f" ⚡ 2. 交流供電運轉統計\n"
        f"   • SMR 常態交流側總功耗: {ac_total_w:.0f} W\n"
        f"   • 現場運轉線電流: {ac_current:.2f} A\n"
        f"   👉 建議開關：{suggested_nfb} A 2P\n"
        f"   👉 建議拉線線徑: {suggested_wire}\n"
        f" 📊 3. 既有每月耗電度數預估\n"
        f"   👉 每月份總用電: 【 {ac_kwh_per_month:.1f} 度電 / 月 】\n"
        f" -----------------------------------\n\n"
        f"🛠️ 【擴頻加掛防呆引導】\n"
        f"若此站要「追加新射頻」，請直接輸入【型號 數量】（如：fwhn 3）進行累加。\n"
        f"💡 輸入 【0】 可直接返回重新輸入站號。"
    )
    return report

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Signature') or request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    raw_msg = event.message.text.strip()
    user_msg = raw_msg.upper() 

    if user_id not in USER_SESSIONS:
        USER_SESSIONS[user_id] = {
            "step": "input_site_id", "site_id": "未知站號", "site_name": "未命名站台", 
            "equipments": {}, "ac_phase": "1P3W", "chosen_smrs": [], "failed_keyword": ""
        }

    session = USER_SESSIONS[user_id]

    if user_msg in ["開始評估", "HELP", "⚡ 新設基地台電力評估"]:
        USER_SESSIONS[user_id] = {
            "step": "input_site_id", "site_id": "未知站號", "site_name": "未命名站台", 
            "equipments": {}, "ac_phase": "1P3W", "chosen_smrs": [], "failed_keyword": ""
        }
        reply_text = (
            "📱 【Nokia 電力助手 - 智慧雙向搜尋版】\n\n"
            "【步驟 1：請輸入站號 或 站台名稱】\n"
            "• 可以直接打站號（如：701873）\n"
            "• 也可以打站台名稱關鍵字（如：安泰醫院）\n\n"
            "系統將會自動檢索屏東歷史資料清單。"
        )
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return

    # 🔍 階段零：雙向檢索邏輯
    if session["step"] == "input_site_id":
        status, result = search_csv_database_advanced(raw_msg)
        
        if status == 'MATCH':
            session["site_id"] = result["site_id"]
            session["site_name"] = result["site_name"]
            session["ac_phase"] = result["ac_phase"]
            session["equipments"] = result["equipments"]
            session["step"] = "input_equip" 
            
            reply_text = calculate_current_report(
                session["site_id"], session["site_name"], session["ac_phase"], session["equipments"]
            )
            
        elif status == 'MULTI':
            reply_text = "⚠️ 【搜尋到多個類似站台名稱】\n請輸入更完整的字眼重新搜尋：\n\n"
            for row in result[:10]:
                reply_text += f"• 台號: {row['site_id']} | 台名: {row['site_name']}\n"
            
        else:
            session["step"] = "ask_not_found_options"
            session["failed_keyword"] = raw_msg  
            reply_text = (
                f"🔎 關鍵字【 {raw_msg} 】於資料庫中查無紀錄！\n"
                f"-----------------------------------\n"
                f"請回覆代號數字【1 或 2】決定後續操作：\n\n"
                f"【1】 🔄 重新搜尋（我可能打錯字了）\n"
                f"【2】 🟢 新增站台（這是一座全新的新站）\n\n"
                f"💡 輸入 【0】 亦可直接退回重新輸入。"
            )
            
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return

    # 智慧選單關卡：查無紀錄時的二選一抉擇 (支援輸入 0 或 1 返回)
    elif session["step"] == "ask_not_found_options":
        if user_msg == "0" or user_msg == "1":
            session["step"] = "input_site_id"
            reply_text = "🔄 已返回。請重新輸入正確的【站號 或 站台名稱關鍵字】："
        elif user_msg == "2":
            session["step"] = "input_equip"
            session["site_id"] = "NEW_SITE"
            session["site_name"] = session["failed_keyword"]
            reply_text = (
                f"⚙️ 系統已成功切換至 ➡️ 【 🟢 新站建設模式 】\n"
                f"✅ 全新站台名稱已設定：【 {session['site_name']} 】\n\n"
                f"【步驟 2：請輸入新設射頻設備】\n"
                f"請直接輸入型號與數量（大小寫皆可，如：fwhn 3），確認好設備後輸入【計算】。\n"
                f"💡 輸入 【0】 可直接退回重新輸入站號。"
            )
        else:
            reply_text = "⚠️ 輸入無效！請回覆 【1】 重新搜尋，【2】 新增全新站台，或回覆 【0】 退回起點。"
            
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text
