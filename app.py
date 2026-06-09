import os
import math
import json
import gspread
from flask import Flask, request, abort
from oauth2client.service_account import ServiceAccountCredentials
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

# --- 初始化 ---
def init_line():
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    secret = os.environ.get("LINE_CHANNEL_SECRET")
    return LineBotApi(token) if token else None, WebhookHandler(secret) if secret else None

line_bot_api, handler = init_line()

EQUIPMENT_DATABASE = {
    "FXDB": {"name": "FXDB", "power": 780}, "ARDA": {"name": "ARDA", "power": 480},
    "FHDB": {"name": "FHDB", "power": 780}, "AHDB": {"name": "AHDB", "power": 410},
    "FXEB": {"name": "FXEB", "power": 915}, "FXED": {"name": "FXED", "power": 860},
    "FHEB": {"name": "FHEB", "power": 410}, "AHEB": {"name": "AHEB", "power": 410},
    "FHEL": {"name": "FHEL", "power": 350}, "FRHG": {"name": "FRHG", "power": 490},
    "AHHB": {"name": "AHHB", "power": 321}, "AZQG": {"name": "AZQG", "power": 720},
    "AZQI": {"name": "AZQI", "power": 520}, "AEQZ": {"name": "AEQZ", "power": 570},
    "AQQA": {"name": "AQQA", "power": 2095}, "AQQY": {"name": "AQQY", "power": 740},
    "AVQC": {"name": "AVQC", "power": 900}, "AVQL": {"name": "AVQL", "power": 380},
    "AHEGB": {"name": "AHEGB", "power": 1367}, "AHEGG": {"name": "AHEGG", "power": 410},
    "FW2EHB": {"name": "FW2EHB", "power": 210}, "FWHN": {"name": "FWHN", "power": 95},
    "AWHQE": {"name": "AWHQE", "power": 285}
}

USER_SESSIONS = {}

@app.route("/", methods=['GET'])
def home():
    return "Bot is running", 200

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    handler.handle(request.get_data(as_text=True), signature)
    return 'OK'

def get_site_data():
    try:
        creds_json = os.environ.get("GOOGLE_CREDS_JSON")
        creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(creds_json), ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"])
        client = gspread.authorize(creds)
        sheet = client.open_by_key("172To-4ENLnZutCsPP7qXCpXNANo4A5YNcyuRadHUGzg").worksheet("工作表1")
        all_values = sheet.get_all_values()
        
        data = []
        for r in all_values[1:]: # 從第2列開始
            if len(r) >= 4:
                full_id = str(r[0]).strip().upper()
                parts = full_id.split()
                data.append({
                    "完整台號": full_id,
                    "主站號": parts[0] if parts else "",
                    "選項": parts[1] if len(parts) > 1 else "",
                    "台名": str(r[1]).strip(),
                    "模組型號": str(r[2]).strip(),
                    "(模組位置 / 光接點)": str(r[3]).strip()
                })
        return data
    except Exception as e:
        print(f"DEBUG: 連線異常: {e}")
        return []

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    uid, msg = event.source.user_id, event.message.text.strip().upper()
    if msg in ["開始評估", "HELP", "0"]:
        USER_SESSIONS[uid] = {"step": "input_id", "equipments": {}}
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="請輸入站號 (例如: 716210 B)："))
        return
    
    session = USER_SESSIONS.get(uid, {"step": "input_id", "equipments": {}})
    if session["step"] == "input_id":
        data = get_site_data()
        parts = msg.split()
        user_main_id = parts[0]
        user_option = parts[1] if len(parts) > 1 else None
        
        results = [r for r in data if r["主站號"] == user_main_id]
        if user_option:
            results = [r for r in results if r["選項"] == user_option]
            
        if not results:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"查無 '{msg}' 相關站台，請確認輸入格式。"))
        else:
            process_all_records(uid, event.reply_token, results)
    elif session["step"] == "input_equip":
        if msg == "計算":
            line_bot_api.reply_message(event.reply_token, TextSendMessage(get_report(session["site_name"], session["equipments"])))
        elif len(msg.split()) == 2 and msg.split()[0] in EQUIPMENT_DATABASE:
            m, q = msg.split()[0], int(msg.split()[1])
            session["equipments"][m] = session["equipments"].get(m, 0) + q
            USER_SESSIONS[uid] = session
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"已追加 {m}，共 {session['equipments'][m]} 台。"))

def process_all_records(uid, token, r_list):
    site_name = f"{r_list[0].get('台名', '未知')}-{r_list[0].get('(模組位置 / 光接點)', '未知')}"
    equipments = {}
    for r in r_list:
        model = str(r.get("模組型號", "")).strip().upper()
        if model in EQUIPMENT_DATABASE:
            equipments[model] = equipments.get(model, 0) + 1
            
    USER_SESSIONS[uid] = {"step": "input_equip", "site_name": site_name, "equipments": equipments}
    summary = "\n".join([f"• {m} x {q}台" for m, q in equipments.items()])
    line_bot_api.reply_message(token, TextSendMessage(text=f"已載入 {site_name}，發現設備：\n{summary if summary else '未匹配到資料庫中的型號'}\n\n輸入「計算」顯示報告，或「型號 數量」追加。"))

def get_report(site_name, equipments):
    bbu_p = 400
    total_rf = sum(EQUIPMENT_DATABASE[m]["power"] * q for m, q in equipments.items())
    net_dc = bbu_p + total_rf
    nfb = max(30, min(100, (math.ceil(((net_dc / 0.92) / (220 * 0.9) * 1.25)/10)*10)))
    wire = "8.0 mm²" if nfb <= 30 else ("14 mm²" if nfb <= 50 else "22 mm²")
    return f"🔍 【站台：{site_name}】\n總負載: {net_dc:.0f} W\n建議 NFB: {nfb} A\n建議線徑: {wire}\n\n輸入「0」返回，或「型號 數量」追加。"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
