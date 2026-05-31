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

# SMR 直流設備對照
SMR_DATABASE = {
    "1": {"name": "TYPE 1 (2.0 kW)", "capacity": 2000},
    "2": {"name": "SMR (5.0 kW)", "capacity": 5000},
    "3": {"name": "TYPE 3 (6.0 kW)", "capacity": 6000},
    "4": {"name": "SMR (7.5 kW)", "capacity": 7500}
}

USER_SESSIONS = {}

def search_csv_database(keyword):
    """搜尋本地 CSV 資料庫，支援站號精準比對與站名模糊比對"""
    if not os.path.exists(CSV_FILE_PATH):
        return 'NOT_FOUND', None
        
    keyword_up = keyword.upper().strip()
    exact_match = None
    fuzzy_matches = []
    
    with open(CSV_FILE_PATH, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            sid = str(row.get("site_id", "")).strip().upper()
            sname = str(row.get("site_name", "")).strip()
            sname_up = sname.upper()
            
            if sid == keyword_up:
                exact_match = row
                break
            if keyword_up in sname_up:
                fuzzy_matches.append(row)
                
    if exact_match:
        return 'MATCH', exact_match
    if len(fuzzy_matches) == 1:
        return 'MATCH', fuzzy_matches[0]
    if len(fuzzy_matches) > 1:
        return 'MULTI', fuzzy_matches
        
    return 'NOT_FOUND', None

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
        suggested_nfb, Archetype_wire = 50, "14 mm²"
    elif calculated_nfb <= 60:
        suggested_nfb, suggested_wire = 60, "22 mm²"
    elif calculated_nfb <= 85:
        suggested_nfb = 75 if calculated_nfb <= 75 else 100
        suggested_wire = "38 mm²"
    else:
        suggested_nfb, suggested_wire = calculated_nfb, "50 mm² 或以上"

    ac_kwh_per_hour = ac_total_w / 1000.0
    ac_kwh_per_month = ac_kwh_per_hour * 24 * 30
    detail_str = "\n".join(detail_list) if detail_list else "   • 無既存射頻設備"

    report = (
        f"🔍 【本地資料庫——站台歷史現況報告】\n"
        f"🏢 站號：{site_id}\n"
        f"🏢 站名：{site_name}\n"
        f"⚡ 現場供電：{phase_title}\n\n"
        f"📋 既存射頻耗電明細：\n{detail_str}\n"
        f" -----------------------------------\n"
        f" 🔋 1. 直流端基本耗電需求的總和\n"
        f"   • 主設備直流負載總和 (含BBU): {net_dc_load:.0f} W\n"
        f" ⚡ 2. 交流供電運轉統計\n"
        f"   • SMR 常態交流側總功耗: {ac_total_w:.0f} W\n"
        f"   • 現場運轉線電流: {ac_current:.2f} A\n"
        f"   👉 建議開關：{suggested_nfb} A 2P\n"
        f"   👉 建議拉線線徑: {suggested_wire}\n"
        f" 📊 3. 既有常態耗電度數預估\n"
        f"   👉 每月份總用電: 【 {ac_kwh_per_month:.1f} 度電 / 月 】\n"
        f" -----------------------------------\n\n"
        f"🛠| 【擴頻加掛防呆引導】\n"
        f"若此站需要「追加新射頻」，請直接輸入【型號 數量】（如：fwhn 3）進行累加。\n"
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

    # 萬用重頭開始指令
    if user_msg in ["開始評估", "HELP", "⚡ 新設基地台電力評估"]:
        USER_SESSIONS[user_id] = {
            "step": "input_site_id", "site_id": "未知站號", "site_name": "未命名站台", 
            "equipments": {}, "ac_phase": "1P3W", "chosen_smrs": [], "failed_keyword": ""
        }
        reply_text = (
            "📱 【Nokia 電力助手 - 智慧雙向搜尋版】\n\n"
            "【步驟 1：請輸入站號 或 站台名稱】\n"
            "• 可以直接打站號（如：PTG1234）\n"
            "• 也可以打站台名稱關鍵字（如：萬丹）\n\n"
            "系統將會自動檢索屏東歷史資料清單。"
        )
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return

    # 🔍 階段零：雙向檢索邏輯
    if session["step"] == "input_site_id":
        status, result = search_csv_database(raw_msg)
        
        if status == 'MATCH':
            session["site_id"] = str(result.get("site_id", "既存站號"))
            session["site_name"] = str(result.get("site_name", "既存站台"))
            session["ac_phase"] = "3P4W" if "3P4W" in str(result.get("ac_phase", "")).upper() else "1P3W"
            
            exist_equip_str = str(result.get("exist_equip", "")).strip()
            parsed_equip = {}
            if exist_equip_str and ":" in exist_equip_str:
                items = exist_equip_str.split(",")
                for item in items:
                    if ":" in item:
                        m, q = item.split(":")
                        m_up = m.strip().upper()
                        if m_up in EQUIPMENT_DATABASE:
                            parsed_equip[m_up] = int(q)
            
            session["equipments"] = parsed_equip
            session["step"] = "input_equip"
            
            reply_text = calculate_current_report(
                session["site_id"], session["site_name"], session["ac_phase"], session["equipments"]
            )
            
        elif status == 'MULTI':
            reply_text = "⚠️ 【搜尋到多個類似站台名稱】\n請輸入更完整的字眼重新搜尋：\n\n"
            for row in result[:10]:
                reply_text += f"• 站號: {row.get('site_id')} | 站名: {row.get('site_name')}\n"
            
        else:
            session["step"] = "ask_not_found_options"
            session["failed_keyword"] = raw_msg 
            reply_text = (
                f"🔎 關鍵字【 {raw_msg} 】於資料庫中查無紀錄！\n"
                f"-----------------------------------\n"
                f"請回覆代號數字【1 或 2】決定後續操作：\n\n"
                f"【1】 🔄 重新搜尋（我可能打錯字了）\n"
                f"【2】 🟢 新增站台（這是一座全新的站）\n"
                f"💡 輸入 【0】 亦可直接退回重新搜尋。"
            )
            
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return

    # 🛑 關卡：處理查無站台時的二選一抉擇 (支援 0 返回)
    elif session["step"] == "ask_not_found_options":
        if user_msg == "0" or user_msg == "1":
            session["step"] = "input_site_id"
            reply_text = "🔄 已返回。請重新輸入正確的【站號 或 站台名稱關鍵字】："
        elif user_msg == "2":
            session["step"] = "input_equip"
            session["site_id"] = "NEW_SITE"
            session["site_name"] = session["failed_keyword"]
            reply_text = (
                f"⚙️ 系統已成功建立 ➡️ 【 🟢 新站建設模式 】\n"
                f"✅ 新設站台名稱定為：【 {session['site_name']} 】\n\n"
                f"【步驟 2：請輸入新設射頻設備】\n"
                f"請直接輸入型號與數量（大小寫皆可，如：fwhn 3），確認好設備後輸入【計算】。\n"
                f"💡 輸入 【0】 可退回重新輸入站號。"
            )
        else:
            reply_text = "⚠️ 輸入無效！請回覆 【1】 重新搜尋，【2】 新增全新站台，或回覆 【0】 退回起點。"
            
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return

    # 階段一：處理新設/累加設備輸入 (支援 0 返回)
    elif session["step"] == "input_equip":
        if user_msg == "0":
            # 🟢 返回：退回最一開始輸入站號的狀態
            session["step"] = "input_site_id"
            session["equipments"] = {}
            reply_text = "🔄 已返回初始狀態。請重新輸入【站號 或 站台名稱關鍵字】："
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
            return

        if user_msg == "計算":
            if not session["equipments"]:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ 目前清單是空的，請先輸入設備。"))
                return
            
            session["step"] = "select_ac_phase"
            reply_text = (
                f"🏢 站號：{session['site_id']} | 站名：{session['site_name']}\n\n"
                f"【步驟 3：請選擇現場交流供電相別】\n"
                f"請直接回覆代號數字【1 或 2】:\n"
                f"【1】 🔴 單相三線 (1P3W 220V)\n"
                f"【2】 🔵 三相四線 (3P4W 380V) - 實務抓 RST 任一相配 N 相接法\n\n"
                f"💡 輸入 【0】 可退回上一步調整設備。"
            )
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
            return

        try:
            parts = user_msg.split()
            if len(parts) == 2:
                model, qty_str = parts[0], parts[1]
                if model in EQUIPMENT_DATABASE:
                    qty = int(qty_str)
                    if qty < 0: raise ValueError
                    
                    if qty == 0:
                        if model in session["equipments"]:
                            del session["equipments"][model]
                        reply = f"已從清單中移除 {model}。"
                    else:
                        session["equipments"][model] = session["equipments"].get(model, 0) + qty
                        reply = f"✅ 已成功累加變更：{EQUIPMENT_DATABASE[model]['name']} 追加 {qty} 台。\n調整後完整清單：\n"
                        for k, v in session["equipments"].items():
                            reply += f"• {EQUIPMENT_DATABASE[k]['name']}: {v}台\n"
                        reply += "\n輸入【計算】選擇供電相別，或輸入【0】重新來過。"
                    
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
                    return
        except ValueError:
            pass
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ 請輸入「型號 數量」(如：arda 3)，或輸入「計算」。\n輸入「0」可退回起點。"))

    # 階段二：選擇 AC 供電相別 (支援 0 返回)
    elif session["step"] == "select_ac_phase":
        if user_msg == "0":
            # 🟢 返回：退回設備輸入階段
            session["step"] = "input_equip"
            reply_text = "🔄 已退回設備編輯階段。請繼續追加射頻設備，或輸入【計算】推進："
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
            return

        if user_msg in ["1", "2"]:
            session["ac_phase"] = "1P3W" if user_msg == "1" else "3P4W"
            
            bbu_p = 400  
            total_rf_power = 0
            detail_list = []

            for model, qty in session["equipments"].items():
                spec = EQUIPMENT_DATABASE[model]
                row_total = spec["power"] * qty
                total_rf_power += row_total
                detail_list.append(f"   • {spec['name']} x {qty}台 = {row_total} W")

            net_dc_load = bbu_p + total_rf_power
            total_dc_demand = net_dc_load 

            dc_kwh_per_hour = total_dc_demand / 1000.0
            dc_kwh_per_month = dc_kwh_per_hour * 24 * 30

            session["net_dc_load"] = net_dc_load
            session["total_dc_demand"] = total_dc_demand
            session["detail_str"] = "\n".join(detail_list)
            
            session["step"] = "select_smr"
            session["chosen_smrs"] = []

            phase_name = "單相三線 220V" if session["ac_phase"] == "1P3W" else "三相四線 (實務抓單相 RST+N 220V)"

            reply_text = (
                f"🏢 站台：[{session['site_id']}] {session['site_name']}\n"
                f"⚡ 供電相別：{phase_name}\n"
                f"🔋 【變更調整後——日常基本直流電量與度數統計】\n\n"
                f"設備常態直流明細：\n{session['detail_str']}\n"
                f" -----------------------------------\n"
                f" • 主設備直流負載總和: {net_dc_load:.0f} W\n"
                f" ⚡ 直流端總電量需求: {total_dc_demand:.0f} W ({total_dc_demand/1000:.2f} kW)\n"
                f" 📊 直流端每小時耗電: {dc_kwh_per_hour:.3f} 度電\n"
                f" 📊 直流端每月預估耗電: {dc_kwh_per_month:.1f} 度電\n"
                f" -----------------------------------\n\n"
                f"【步驟 4：請選填直流供電設備（支援多機累加）】\n"
                f"請直接回覆代號數字【1 ~ 4】:\n"
                f"【1】 TYPE 1 (2.0 kW)\n"
                f"【2】 SMR (5.0 kW)\n"
                f"【3】 TYPE 3 (6.0 kW)\n"
                f"【4】 SMR (7.5 kW)\n\n"
                f"💡 輸入 【0】 可退回上一步重選交流相別。"
            )
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
            return
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ 請回覆 1 選擇單相三線，或回覆 2 選擇三相四線。\n輸入「0」可退回上一步。"))

    # 階段三：手選直流設備 (支援 0 返回)
    elif session["step"] == "select_smr":
        if user_msg == "0":
            # 🟢 返回：退回供電相別選擇階段
            session["step"] = "select_ac_phase"
            reply_text = (
                f"🔄 已退回供電相別階段。\n"
                f"請重新回覆供電相別代號數字【1 或 2】:\n"
                f"【1】 🔴 單相三線 (1P3W 220V)\n"
                f"【2】 🔵 三相四線 (3P4W 380V)"
            )
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
            return

        if user_msg in SMR_DATABASE:
            chosen_smr_spec = SMR_DATABASE[user_msg]
            session["chosen_smrs"].append(chosen_smr_spec)

            current_total_capacity = sum([smr["capacity"] for smr in session["chosen_smrs"]])
            total_dc_demand = session["total_dc_demand"]

            if current_total_capacity < total_dc_demand:
                remaining_w = total_dc_demand - current_total_capacity
                chosen_names = " + ".join([smr["name"] for smr in session["chosen_smrs"]])
                loop_reply = (
                    f"⚡ 【直流供電容量仍有不足！】\n\n"
                    f" • 目前已選配置: {chosen_names}\n"
                    f" 🔋 目前累計總供電容量: {current_total_capacity:.0f} W\n"
                    f" ⚠️ 缺額尚差: 🔴 【 {remaining_w:.0f} W 】\n"
                    f" -----------------------------------\n\n"
                    f"【請選擇再補一台直流設備（回覆 1 ~ 4）】\n"
                    f"💡 輸入 【0】 可退回重選供電相別。"
                )
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=loop_reply))
                return

            net_dc_load = session["net_dc_load"]
            smr_efficiency = 0.92
            pf = 0.90
            ac_total_w = total_dc_demand / smr_efficiency

            if session["ac_phase"] == "1P3W":
                phase_title = "單相三線 (1P3W 220V)"
                nfb_poles = "2P"
            else:
                phase_title = "開關使用 2P (RST單相配N)"
            
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
            final_smr_config = " + ".join([smr["name"] for smr in session["chosen_smrs"]])

            report = (
                f"📋 【⚡ 擴頻調整後——日常基地台電力度數報告】\n"
                f"🏢 站台代號：{session['site_id']}\n"
                f"🏢 站台名稱：{session['site_name']}\n\n"
                f" 🔹 1. 調整後完整射頻清單：\n{session['detail_str']}\n"
                f" -----------------------------------\n"
                f" 🔋 2. 直流供電設備確認\n"
                f"   • 主設備基本直流負載: {net_dc_load:.0f} W\n"
                f"   👉 最終多機配置: 【 {final_smr_config} 】\n"
                f"   👉 供電總瓦數能力: {current_total_capacity} W\n"
                f" -----------------------------------\n"
                f" ⚡ 3. 交流供電系統統計 ({phase_title})\n"
                f"   • SMR 變更後交流側總功耗: {ac_total_w:.0f} W\n"
                f"   • 現場基本運轉線電流: {ac_current:.2f} A\n"
                f"   👉 建議 NFB 開關規格: {suggested_nfb} A 2P\n"
                f"   👉 現場拉線進線線徑: {suggested_wire}\n"
                f" -----------------------------------\n"
                f" 📊 4. 預估現場日常耗電度數 (台電計費基準)\n"
                f"   • 每月份預估總用電: 【 {ac_kwh_per_month:.1f} 度電 / 月 】\n\n"
                f"💡 輸入「開始評估」可開啟下一座台的電力計算。"
            )
            
            USER_SESSIONS[user_id] = {"step": "input_site_id", "site_id": "未知站號", "site_name": "未命名站台", "equipments": {}, "ac_phase": "1P3W", "chosen_smrs": [], "failed_keyword": ""}
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=report))
            return
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ 請輸入正確的直流設備代號數字 (1、2、3 或 4)。\n輸入「0」可退回上一步。"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
