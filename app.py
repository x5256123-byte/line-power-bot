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

def get_site_data():
    try:
        creds_json = os.environ.get("GOOGLE_CREDS_JSON")
        if not creds_json: return []
        creds_dict = json.loads(creds_json)
        scope = [
            "https://spreadsheets.google.com/feeds",
            'https://www.googleapis.com/auth/spreadsheets',
            "https://www.googleapis.com/auth/drive.file",
            "https://www.googleapis.com/auth/drive"
        ]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        # 使用正確的新 ID
        spreadsheet = client.open_by_key("1GOPuTeocq6G0gj4AUMdPUiE84TicJhj0Qcwvn2Sjoe4")
        sheet = spreadsheet.worksheet("工作表1")
        data = sheet.get_all_records(head=2)
        print(f"DEBUG: 成功讀取 {len(data)} 筆資料")
        return data
    except Exception as e:
        print(f"DEBUG: Sheets 連線異常: {e}")
        return []

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
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
        results = [r for r in data if msg.strip() == str(r.get("台號", "")).strip()]
        if not results:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"查無此站 '{msg}'，請確認 Google Sheet 是否已共用給服務帳號。"))
        else:
            process_selection(uid, event.reply_token, results[0])
    elif session["step"] == "input_equip":
        if msg == "計算":
            line_bot_api.reply_message(event.reply_token, TextSendMessage(get_report(session["site_name"], session["equipments"], "1P3W")))
        elif len(msg.split()) == 2 and msg.split()[0] in EQUIPMENT_DATABASE:
            m, q = msg.split()[0], int(msg.split()[1])
            session["equipments"][m] = session["equipments"].get(m, 0) + q
            USER_SESSIONS[uid] = session
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"已追加 {m}，共 {session['equipments'][m]} 台。"))

def get_report(site_name, equipments, ac_phase):
    bbu_p = 400
    total_rf = sum(EQUIPMENT_DATABASE[m]["power"] * q for m, q in equipments.items() if m in EQUIPMENT_DATABASE)
    net_dc = bbu_p + total_rf
    nfb = max(30, min(100, (math.ceil(((net_dc / 0.92) / (220 * 0.9) *
