import os
import math
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

# --- 中華電信現役 Nokia AirScale 設備直流功耗資料庫 (已優化 +B3 識別邏輯) ---
EQUIPMENT_DATABASE = {
    "FXDB": {"name": "FXDB (B8)", "power": 520},
    "FHDB": {"name": "FHDB (B8)", "power": 580},
    "AHDB": {"name": "AHDB (B8)", "power": 580},
    "FXEB": {"name": "FXEB (B3)", "power": 560},
    "FHEB": {"name": "FHEB (B3)", "power": 620},
    "AHEB": {"name": "AHEB (B3)", "power": 620},
    "FRHG": {"name": "FRHG (B7)", "power": 540},
    "AHHB": {"name": "AHHB (B7 8TR)", "power": 780},
    "AZQG": {"name": "AZQG (N35 8TR)", "power": 750},
    "AZQI": {"name": "AZQI (N35 8TR)", "power": 750},
    "AEQZ": {"name": "AEQZ (N35 32TR)", "power": 1050},
    "AQQA": {"name": "AQQA (N35 32TR)", "power": 1050},
    "AQQY": {"name": "AQQY (N35 32TR)", "power": 950},
    "AVQC": {"name": "AVQC (N35 32TR)", "power": 950},
    "AVQL": {"name": "AVQL (N35 64TR)", "power": 1450},
    # 更改：使用符合日常習慣的 +B3 直覺打法
    "AHEGB": {"name": "AHEGB (N1 純5G)", "power": 350},
    "AHEGB+B3": {"name": "AHEGB (N1+B3 混模)", "power": 560},
    "AHEGG": {"name": "AHEGG (N1 純5G)", "power": 350},
    "AHEGG+B3": {"name": "AHEGG (N1+B3 混模)", "power": 560}
}

SMR_DATABASE = [
    {"name": "TYPE 1 (2.0 kW)", "capacity": 2000},
    {"name": "SMR (5.0 kW)", "capacity": 5000},
    {"name": "TYPE 3 (6.0 kW)", "capacity": 6000},
    {"name": "SMR (7.5 kW)", "capacity": 7500}
]

USER_SESSIONS = {}

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    user_msg = event.message.text.strip().upper()  # 自動轉大寫，打小寫 ahegb+b3 也能通

    if user_id not in USER_SESSIONS:
        USER_SESSIONS[user_id] = {}

    # 指令：開始評估
    if user_msg in ["開始評估", "HELP", "⚡ 新設基地台電力評估"]:
        USER_SESSIONS[user_id] = {} 
        reply_text = (
            "📱 【Nokia AirScale 電力估算助手】\n\n"
            "請輸入型號與數量，格式為：【型號 數量】\n"
            "範例：\n"
            "輸入「AVQL 3」代表新增3片 64TR 天線\n"
            "輸入「AHEGB 3」代表 3台 純N1 設備 (350W)\n"
            "輸入「AHEGB+B3 3」代表 3台 N1+B3 設備 (560W)\n\n"
            "確認好所有設備後，輸入【計算】產出評估報告！"
        )
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return

    # 指令：計算
    if user_msg == "計算":
        session = USER_SESSIONS[user_id]
        if not session:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ 您的清單目前是空的，請先輸入設備與數量（如：AVQL 3）。"))
            return

        bbu_p = 500  
        smr_efficiency = 0.92  
        total_rf_power = 0
        detail_list = []

        for model, qty in session.items():
            spec = EQUIPMENT_DATABASE[model]
            row_total = spec["power"] * qty
            total_rf_power += row_total
            detail_list.append(f"   • {spec['name']} x {qty}台 = {row_total} W")

        net_dc_load = bbu_p + total_rf_power
        battery_charge_margin = net_dc_load * 0.15
        total_dc_demand = net_dc_load + battery_charge_margin

        # 匹配 SMR 直流設備
        selected_smr = "⚠️ 超出單組 7.5kW SMR 容量！"
        for smr in SMR_DATABASE:
            if smr["capacity"] >= total_dc_demand:
                selected_smr = smr["name"]
                break

        # 交流單相三線 220V 計算 (PF=0.9)
        ac_total_w = total_dc_demand / smr_efficiency
        pf = 0.90
        ac_current = ac_total_w / (220 * pf)
        suggested_nfb = math.ceil(ac_current * 1.25)

        if suggested_nfb <= 20: suggested_wire = "2.0 mm 或 3.5 mm²"
        elif suggested_nfb <= 30: suggested_wire = "5.5 mm²"
        elif suggested_nfb <= 50: suggested_wire = "8.0 mm² 或 14 mm²"
        else: suggested_wire = "22 mm² 或以上"

        details_str = "\n".join(detail_list)
        report = (
            f"📋 【現場電力勘查評估報告】\n\n"
            f"新設設備明細：\n{details_str}\n"
            f" -----------------------------------\n"
            f" 🔋 【直流電源系統 (DC -48V)】\n"
            f"   • 主設備純直流負載: {net_dc_load:.0f} W\n"
            f"   • 預留電池充電容量: {battery_charge_margin:.0f} W\n"
            f"   ⚡ 直流端總電量需求: {total_dc_demand:.0f} W\n"
            f"   👉 建議直流設備: 【{selected_smr}】\n"
            f" -----------------------------------\n"
            f" ⚡ 【交流系統 (AC 單相三線 220V)】\n"
            f"   • SMR 交流側總功耗: {ac_total_w:.0f} W\n"
            f"   • 運轉線電流負載: {ac_current:.2f} A\n"
            f"   👉 建議 NFB 規格: {suggested_nfb} A 2P\n"
            f"   👉 參考建議進線線徑: {suggested_wire}\n\n"
            f"💡 輸入「開始評估」可重新計算。"
        )
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=report))
        return

    # 處理設備輸入 (例如: AHEGB+B3 3)
    try:
        parts = user_msg.split()
        if len(parts) == 2:
            model = parts[0]
            qty_str = parts[1]
            if model in EQUIPMENT_DATABASE:
                qty = int(qty_str)
                if qty < 0: raise ValueError
                
                if qty == 0:
                    if model in USER_SESSIONS[user_id]:
                        del USER_SESSIONS[user_id][model]
                    reply = f"已從清單中移除 {model}。"
                else:
                    USER_SESSIONS[user_id][model] = qty
                    reply = f"✅ 已記錄：{EQUIPMENT_DATABASE[model]['name']} 共 {qty} 台。\n現有清單：\n"
                    for k, v in USER_SESSIONS[user_id].items():
                        reply += f"• {EQUIPMENT_DATABASE[k]['name']}: {v}台\n"
                    reply += "\n繼續輸入其他設備，或輸入【計算】觀看報告。"
                
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
                return
    except ValueError:
        pass

    line_bot_api.reply_message(
        event.reply_token, 
        TextSendMessage(text="⚠️ 無法辨識指令。請輸入「型號 數量」(如：AHEGB+B3 3)，或輸入「計算」看報告。")
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
