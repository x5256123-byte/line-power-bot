import os
import math
import gspread
from flask import Flask, request, abort
from oauth2client.service_account import ServiceAccountCredentials
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

# --- 設定 ---
line_bot_api = LineBotApi(os.environ.get("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.environ.get("LINE_CHANNEL_SECRET"))
USER_SESSIONS = {}

# --- 設備資料庫 ---
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

# --- Google Sheets 連接 (防禦性寫法) ---
def get_site_data():
    try:
        scope = ["https://spreadsheets.google.com/feeds", 'https://www.googleapis.com/auth/spreadsheets']
        if not os.path.exists('credentials.json'):
            return []
        creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
        client = gspread.authorize(creds)
        sheet = client.open("你的 Google Sheet 名稱").sheet1
        return sheet.get_all_records()
    except Exception as e:
        print(f"Error connecting to Google Sheets: {e}")
        return []

def get_report(site_name, equipments, ac_phase):
    bbu_p = 400
    total_rf = sum(EQUIPMENT_DATABASE[m]["power"] * q for m, q in equipments.items() if m in EQUIPMENT_DATABASE)
    net_dc = bbu_p + total_rf
    ac_w = net_dc / 0.92
    ac_curr = ac_w / (220 * 0.9)
    nfb = max(30, min(100, (math.ceil((ac_curr * 1.25)/10)*10)))
    wire = "8.0 mm²" if nfb <= 30 else ("14 mm²" if nfb <= 50 else "22 mm²")
    details = "\n".join([f"• {EQUIPMENT_DATABASE[m]['name']} x {q}台" for m, q in equipments.items()])
    return f"🔍 【站台：{site_name}】\n供電：{ac_phase}\n\n設備清單：\n{details}\n-------------------\n總負載: {net_dc:.0f} W\n建議 NFB: {nfb} A\n建議線徑: {wire}\n\n輸入「0」返回，或「型號 數量」追加。"

@app.route("/callback", methods=['POST'])
def callback():
    try:
        handler.handle(request.get_data(as_text=True), request.headers.get('X-Line-Signature'))
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    uid = event.source.user_id
    msg = event.message.text.strip().upper()
    if msg in ["開始評估", "HELP", "0"]:
        USER_SESSIONS[uid] = {"step": "input_id", "equipments": {}}
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="請輸入站號："))
        return
    
    session = USER_SESSIONS.get(uid, {"step": "input_id", "equipments": {}})
    
    if session["step"] == "input_id":
        data = get_site_data()
        results = [r for r in data if msg in str(r.get("台號", ""))]
        if not results:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="查無此站，請確認 Google Sheet 資料已同步。"))
        else:
            process_selection(uid, event.reply_token, results[0])
            
    elif session["step"] == "input_equip":
        if msg == "計算":
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=get_report(session["site_name"], session["equipments"], "1P3W")))
        else:
            parts = msg.split()
            if len(parts) == 2 and parts[0] in EQUIPMENT_DATABASE:
                m, q = parts[0], int(parts[1])
                session["equipments"][m] = session["equipments"].get(m, 0) + q
                USER_SESSIONS[uid] = session
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"已更新 {m}，共 {session['equipments'][m]} 台。"))

def process_selection(uid, token, r):
    site_name = f"{r.get('台名', '未知')}-{r.get('模組位置', '未知')}"
    equipments = {}
    raw_model = str(r.get("模組型號", "")).upper()
    for db_model in EQUIPMENT_DATABASE:
        if db_model in raw_model:
            equipments[db_model] = equipments.get(db_model, 0) + 1
    
    USER_SESSIONS[uid] = {"step": "input_equip", "site_name": site_name, "equipments": equipments}
    line_bot_api.reply_message(token, TextSendMessage(text=f"已載入 {site_name}。\n輸入「計算」顯示報告，或「型號 數量」追加。"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
