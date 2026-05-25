import os
import math
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

# ---------- 請填寫您的 LINE 憑證 ----------
CHANNEL_ACCESS_TOKEN = '你的 Channel Access Token'
CHANNEL_SECRET = '你的 Channel Secret'

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# ---------- 設備資料庫 (與原程式相同) ----------
EQUIPMENT_DATABASE = {
    "FXDB (B8)": {"type": "normal", "power": 520},
    "FHDB (B8)": {"type": "normal", "power": 580},
    "AHDB (B8)": {"type": "normal", "power": 580},
    "FXEB (B3)": {"type": "normal", "power": 560},
    "FHEB (B3)": {"type": "normal", "power": 620},
    "AHEB (B3)": {"type": "normal", "power": 620},
    "FRHG (B7)": {"type": "normal", "power": 540},
    "AHHB (B7 8TR)": {"type": "normal", "power": 780},
    "AZQG (N35 8TR)": {"type": "normal", "power": 750},
    "AZQI (N35 8TR)": {"type": "normal", "power": 750},
    "AEQZ (N35 32TR)": {"type": "normal", "power": 1050},
    "AQQA (N35 32TR)": {"type": "normal", "power": 1050},
    "AQQY (N35 32TR)": {"type": "normal", "power": 950},
    "AVQC (N35 32TR)": {"type": "normal", "power": 950},
    "AVQL (N35 64TR)": {"type": "normal", "power": 1450},
    "AHEGB (N1)": {"type": "dual", "N1_Only": 650, "N1_With_B3": 1020},
    "AHEGG (N1)": {"type": "dual", "N1_Only": 650, "N1_With_B3": 1020}
}
SMR_DATABASE = [
    {"name": "TYPE 1 (2.0 kW)", "capacity": 2000},
    {"name": "SMR (5.0 kW)", "capacity": 5000},
    {"name": "TYPE 3 (6.0 kW)", "capacity": 6000},
    {"name": "SMR (7.5 kW)", "capacity": 7500}
]
BATTERY_MARGIN = 0.15
PF = 0.90
AC_VOLTAGE = 220
CB_SAFETY = 1.25

def calculate_power(bbu_watt, efficiency_percent, devices):
    if not devices:
        return None
    eff = efficiency_percent / 100.0
    total_rf = 0
    details = []
    for model, qty, b3 in devices:
        spec = EQUIPMENT_DATABASE.get(model)
        if not spec:
            continue
        if spec["type"] == "dual":
            unit_power = spec["N1_With_B3"] if b3 else spec["N1_Only"]
            tag = " (含B3)" if b3 else " (純N1)"
        else:
            unit_power = spec["power"]
            tag = ""
        row_power = unit_power * qty
        total_rf += row_power
        details.append(f"{model}{tag} x{qty}台 = {row_power}W")
    net_dc = bbu_watt + total_rf
    battery_margin = net_dc * BATTERY_MARGIN
    total_dc = net_dc + battery_margin
    selected_smr = "⚠️ 超出 7.5kW"
    for smr in SMR_DATABASE:
        if smr["capacity"] >= total_dc:
            selected_smr = smr["name"]
            break
    ac_power = total_dc / eff
    ac_current = ac_power / (AC_VOLTAGE * PF)
    nfb = math.ceil(ac_current * CB_SAFETY)
    if nfb <= 20:
        wire = "2.0mm 或 3.5mm²"
    elif nfb <= 30:
        wire = "5.5mm²"
    elif nfb <= 50:
        wire = "8.0mm² 或 14mm²"
    else:
        wire = "22mm² 以上"
    return {
        "details": details,
        "net_dc": net_dc,
        "total_dc": total_dc,
        "selected_smr": selected_smr,
        "ac_power": ac_power,
        "ac_current": ac_current,
        "nfb": nfb,
        "wire": wire,
        "efficiency": efficiency_percent
    }

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
    user_text = event.message.text.strip()
    if user_text == "幫助" or user_text == "help":
        reply = "請輸入設備格式：\n型號 數量 [含B3]\n多行輸入多個設備，最後一行輸入 BBU功耗 效率%\n範例：\nFRHG (B7) 2\nAHEGB (N1) 1 含B3\n500 92"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
        return
    # 解析輸入
    lines = user_text.split('\n')
    devices = []
    bbu = 500
    eff = 92
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # 判斷是否為 BBU 效率行
        parts = line.split()
        if len(parts) == 2 and parts[0].replace('.','',1).isdigit() and parts[1].replace('.','',1).isdigit():
            bbu = float(parts[0])
            eff = float(parts[1])
            continue
        # 解析設備行
        import re
        match = re.match(r'^(.+?)\s+(\d+)\s*(含B3|B3)?', line)
        if match:
            model = match.group(1).strip()
            qty = int(match.group(2))
            b3 = match.group(3) is not None
            if model in EQUIPMENT_DATABASE:
                devices.append((model, qty, b3))
            else:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"未知型號: {model}"))
                return
        else:
            # 嘗試直接當成型號，數量預設1
            if line in EQUIPMENT_DATABASE:
                devices.append((line, 1, False))
            else:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"無法辨識: {line}"))
                return
    if not devices:
        reply = "未偵測到設備，請輸入如：\nFRHG (B7) 2\nAHEGB (N1) 1 含B3\n最後一行加上 500 92"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
        return
    result = calculate_power(bbu, eff, devices)
    if not result:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="計算失敗"))
        return
    msg = f"📊 基地台電力報告\n"
    msg += "\n".join(result["details"]) + "\n"
    msg += f"直流總負載: {result['net_dc']:.0f} W\n"
    msg += f"含15%充電: {result['total_dc']:.0f} W\n"
    msg += f"建議SMR: {result['selected_smr']}\n"
    msg += f"交流總功耗: {result['ac_power']:.0f} W (效率{result['efficiency']}%)\n"
    msg += f"220V電流: {result['ac_current']:.2f} A\n"
    msg += f"建議NFB: {result['nfb']} A 2P\n"
    msg += f"建議線徑: {result['wire']}"
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=msg))

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)