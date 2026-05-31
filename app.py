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

# --- 🎯 射頻設備功耗庫 ---
EQUIPMENT_DATABASE = {
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
    "FW2EHB": {"name": "FW2EHB", "power": 210},
    "FR2EB": {"name": "FR2EB", "power": 140},
    "FWEA": {"name": "FWEA", "power": 84},
    "AHEJ": {"name": "AHEJ", "power": 90},
    "AWHQE": {"name": "AWHQE", "power": 285},
    "FWHN": {"name": "FWHN", "power": 95}
}

SMR_DATABASE = {
    "1": {"name": "TYPE 1 (2.0 kW)", "capacity": 2000},
    "2": {"name": "SMR (5.0 kW)", "capacity": 5000},
    "3": {"name": "TYPE 3 (6.0 kW)", "capacity": 6000},
    "4": {"name": "SMR (7.5 kW)", "capacity": 7500}
}

USER_SESSIONS = {}

def search_csv_database_advanced(keyword):
    if not os.path.exists(CSV_FILE_PATH):
        return 'NOT_FOUND', None
    keyword_up = keyword.upper().strip()
    matched_rows = []
    with open(CSV_FILE_PATH, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            sid = str(row.get("台號", "")).strip().upper()
            sname = str(row.get("台名", "")).strip()
            sname_up = sname.upper()
            if sid == keyword_up or keyword_up in sname_up:
                raw_model = str(row.get("模組型號", "")).strip().upper()
                clean_model = raw_model.split('_')[0] if '_' in raw_model else raw_model
                cell_info = str(row.get("細胞(頻寬) / 細胞名稱", "")).upper()
                phase_type = "3P4W" if "3P" in cell_info else "1P3W"
                matched_rows.append({"site_id": sid, "site_name": sname, "model": clean_model, "ac_phase": phase_type})
    if not matched_rows:
        return 'NOT_FOUND', None
    unique_site_ids = list(set([item["site_id"] for item in matched_rows]))
    if len(unique_site_ids) == 1:
        target_id = unique_site_ids[0]
        site_allels = [item for item in matched_rows if item["site_id"] == target_id]
        merged_equipments = {}
        final_name = site_allels[0]["site_name"]
        final_phase = "1P3W"
        for item in site_allels:
            model = item["model"]
            if item["ac_phase"] == "3P4W": final_phase = "3P4W"
            if model in EQUIPMENT_DATABASE:
                merged_equipments[model] = merged_equipments.get(model, 0) + 1
        return 'MATCH', {"site_id": target_id, "site_name": final_name, "ac_phase": final_phase, "equipments": merged_equipments}
    return 'MULTI', list({item["site_id"]: item for item in matched_rows}.values())

def calculate_current_report(site_id, site_name, ac_phase, equipments):
    bbu_p = 400
    total_rf_power = sum(EQUIPMENT_DATABASE[m]["power"] * q for m, q in equipments.items())
    net_dc_load = bbu_p + total_rf_power
    ac_total_w_calc = net_dc_load / 0.92
    ac_current = ac_total_w_calc / (220 * 0.9)
    calculated_nfb = math.ceil(ac_current * 1.25)
    
    suggested_nfb = max(30, min(100, (math.ceil(calculated_nfb/10)*10)))
    suggested_wire = "8.0 mm²" if suggested_nfb <= 30 else ("14 mm²" if suggested_nfb <= 50 else "22 mm²")

    phase_title = "單相三線 (1P3W 220V)" if ac_phase == "1P3W" else "三相四線 (3P4W)"
    ac_kwh_per_month = (ac_total_w_calc / 1000) * 24 * 30
    detail_str = "\n".join([f"   • {EQUIPMENT_DATABASE[m]['name']} x {q}台" for m, q in equipments.items()])
    
    return (f"🔍 【站台現況報告】\n台號：{site_id}\n台名：{site_name}\n供電：{phase_title}\n\n明細：\n{detail_str}\n"
            f"-------------------\n總負載: {net_dc_load:.0f} W\n建議開關: {suggested_nfb} A\n建議線徑: {suggested_wire}\n預估月用電: {ac_kwh_per_month:.1f} 度\n\n"
            f"🛠️ 追加設備請輸入「型號 數量」，輸入 0 返回。")

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    try: handler.handle(body, signature)
    except InvalidSignatureError: abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    raw_msg = event.message.text.strip()
    user_msg = raw_msg.upper()
    
    if user_msg in ["開始評估", "HELP"]:
        USER_SESSIONS[user_id] = {"step": "input_site_id", "site_id": "未知", "site_name": "未知", "equipments": {}, "ac_phase": "1P3W"}
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="請輸入站號或台名進行搜尋："))
        return

    session = USER_SESSIONS.get(user_id, {"step": "input_site_id"})
    
    if user_msg == "0":
        USER_SESSIONS[user_id] = {"step": "input_site_id", "site_id": "未知", "site_name": "未知", "equipments": {}, "ac_phase": "1P3W"}
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="已重置，請輸入站號："))
        return

    if session["step"] == "input_site_id":
        status, result = search_csv_database_advanced(raw_msg)
        if status == 'MATCH':
            session.update(result)
            session["step"] = "input_equip"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=calculate_current_report(session["site_id"], session["site_name"], session["ac_phase"], session["equipments"])))
        elif status == 'MULTI':
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="找到多個站，請更精確輸入：\n" + "\n".join([f"{r['site_id']} {r['site_name']}" for r in result])))
        else:
            session["step"] = "ask_new"
            session["failed_keyword"] = raw_msg
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"查無此站。回覆 1 重新搜尋，回覆 2 新增站台："))
            
    elif session["step"] == "ask_new":
        if user_msg == "2":
            session["step"] = "input_equip"
            session["site_id"] = "NEW"
            session["site_name"] = session["failed_keyword"]
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="進入新站模式，請輸入「型號 數量」："))
        else:
            session["step"] = "input_site_id"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="請重新輸入站號："))

    elif session["step"] == "input_equip":
        if user_msg == "計算":
            session["step"] = "select_ac"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="請選擇相別 (1:1P3W, 2:3P4W)："))
        else:
            parts = user_msg.split()
            if len(parts) == 2 and parts[0] in EQUIPMENT_DATABASE:
                session["equipments"][parts[0]] = session["equipments"].get(parts[0], 0) + int(parts[1])
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"已更新清單，輸入「計算」完成。"))

    elif session["step"] == "select_ac":
        session["ac_phase"] = "3P4W" if user_msg == "2" else "1P3W"
        session["step"] = "select_smr"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="請選擇直流設備 (1~4)："))

    elif session["step"] == "select_smr":
        # 此處省略 SMR 累加邏輯，可直接呼叫 calculate_current_report
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="評估完成！(開發測試中)"))

    USER_SESSIONS[user_id] = session

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
