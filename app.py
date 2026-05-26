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

# --- 🎯 重新校正：全面改用「日常運轉基本功耗（Typical）」資料庫 ---
EQUIPMENT_DATABASE = {
    "FXDB": {"name": "FXDB (B8)", "power": 380},
    "FHDB": {"name": "FHDB (B8)", "power": 380},
    "AHDB": {"name": "AHDB (B8)", "power": 380},
    "FXEB": {"name": "FXEB (B3)", "power": 400},
    "FHEB": {"name": "FHEB (B3)", "power": 400},
    "AHEB": {"name": "AHEB (B3)", "power": 400},
    "FHEL": {"name": "FHEL (B3)", "power": 400},
    "FRHG": {"name": "FRHG (B7)", "power": 350},
    "AHHB": {"name": "AHHB (B7 8TR)", "power": 510},
    "AZQG": {"name": "AZQG (N35 8TR)", "power": 480},
    "AZQI": {"name": "AZQI (N35 8TR)", "power": 480},
    "AEQZ": {"name": "AEQZ (N35 32TR)", "power": 680},
    "AQQA": {"name": "AQQA (N35 32TR)", "power": 680},
    "AQQY": {"name": "AQQY (N35 32TR)", "power": 620},
    "AVQC": {"name": "AVQC (N35 32TR)", "power": 620},
    "AVQL": {"name": "AVQL (N35 64TR)", "power": 950},
    # 雙頻設備基本運轉功耗
    "AHEGB": {"name": "AHEGB (N1 純5G)", "power": 350},
    "AHEGB+B3": {"name": "AHEGB (N1+B3 混模)", "power": 560},
    "AHEGG": {"name": "AHEGG (N1 純5G)", "power": 350},
    "AHEGG+B3": {"name": "AHEGG (N1+B3 混模)", "power": 560}
}

# SMR 直流設備對照
SMR_DATABASE = {
    "1": {"name": "TYPE 1 (2.0 kW)", "capacity": 2000},
    "2": {"name": "SMR (5.0 kW)", "capacity": 5000},
    "3": {"name": "TYPE 3 (6.0 kW)", "capacity": 6000},
    "4": {"name": "SMR (7.5 kW)", "capacity": 7500}
}

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
    user_msg = event.message.text.strip().upper()

    if user_id not in USER_SESSIONS:
        USER_SESSIONS[user_id] = {"step": "input_equip", "equipments": {}}

    session = USER_SESSIONS[user_id]

    # --- 重置評估指令 ---
    if user_msg in ["開始評估", "HELP", "⚡ 新設基地台電力評估"]:
        USER_SESSIONS[user_id] = {"step": "input_equip", "equipments": {}}
        reply_text = (
            "📱 【Nokia AirScale 常態基本電力估算助手】\n\n"
            "【步驟 1：輸入新設射頻】\n"
            "請輸入型號與數量，格式為：【型號 數量】\n"
            "範例：\n"
            "輸入「AVQL 3」\n"
            "輸入「AHEGB+B3 3」\n\n"
            "確認好設備後，請輸入【計算】觀看日常基本運轉直流總瓦數。"
        )
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return

    # 階段一：處理設備輸入並結算直流瓦數 (日常基本功耗版)
    if session["step"] == "input_equip":
        if user_msg == "計算":
            if not session["equipments"]:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ 您的清單目前是空的，請先輸入設備（如：AVQL 3）。"))
                return

            bbu_p = 400  # 日常基本運轉下，BBU+傳輸設備基本功耗也微調至較合理的常態 400W
            total_rf_power = 0
            detail_list = []

            for model, qty in session["equipments"].items():
                spec = EQUIPMENT_DATABASE[model]
                row_total = spec["power"] * qty
                total_rf_power += row_total
                detail_list.append(f"   • {spec['name']} x {qty}台 = {row_total} W")

            net_dc_load = bbu_p + total_rf_power
            # 既然算日常基本用電，蓄電池通常處於浮充飽電狀態，故「不加」大電流充電餘裕，完全看常態基本用電
            total_dc_demand = net_dc_load 

            # 暫存直流計算結果
            session["net_dc_load"] = net_dc_load
            session["total_dc_demand"] = total_dc_demand
            session["detail_str"] = "\n".join(detail_list)
            
            # 推進到階段二
            session["step"] = "select_smr"

            # 智慧推薦 SMR 做為參考
            smart_rec = "超出單組 7.5kW 容量！"
            for k, smr in SMR_DATABASE.items():
                if smr["capacity"] >= total_dc_demand:
                    smart_rec = smr["name"]
                    break

            reply_text = (
                f"🔋 【日常基本直流瓦數加總】\n\n"
                f"設備常態直流明細：\n{session['detail_str']}\n"
                f" -----------------------------------\n"
                f" • 主設備常態直流負載總和: {net_dc_load:.0f} W ({net_dc_load/1000:.2f} kW)\n"
                f" 💡 (平時基本運轉推薦：{smart_rec})\n"
                f" -----------------------------------\n\n"
                f"【步驟 2：請選填現場要配置的直流設備】\n"
                f"請直接回覆【代號數字 1 ~ 4】:\n"
                f"【1】 TYPE 1 (2.0 kW)\n"
                f"【2】 SMR (5.0 kW)\n"
                f"【3】 TYPE 3 (6.0 kW)\n"
                f"【4】 SMR (7.5 kW)"
            )
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
            return

        # 處理日常的型號數量輸入
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
                        session["equipments"][model] = qty
                        reply = f"✅ 已記錄：{EQUIPMENT_DATABASE[model]['name']} 共 {qty} 台。\n現有清單：\n"
                        for k, v in session["equipments"].items():
                            reply += f"• {EQUIPMENT_DATABASE[k]['name']}: {v}台\n"
                        reply += "\n繼續輸入其他設備，或輸入【計算】觀看常態瓦數並選擇SMR。"
                    
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
                    return
        except ValueError:
            pass

        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ 無法辨識。請輸入「型號 數量」(如：AVQL 3)，或輸入「計算」。"))

    # 階段二：手選直流設備並輸出常態交流統計
    elif session["step"] == "select_smr":
        if user_msg in SMR_DATABASE:
            chosen_smr = SMR_DATABASE[user_msg]
            total_dc_demand = session["total_dc_demand"]
            net_dc_load = session["net_dc_load"]
            smr_efficiency = 0.92
            pf = 0.90

            safety_warning = ""
            if chosen_smr["capacity"] < total_dc_demand:
                safety_warning = f"\n⚠️ 【工程警告】：您選的 {chosen_smr['name']} 容量小於常態直流需求 ({total_dc_demand:.0f}W)！\n"

            # 依據常態用電換算交流
            ac_total_w = total_dc_demand / smr_efficiency
            ac_current = ac_total_w / (220 * pf)
            
            # 因為是基本在用的日常電流，NFB開關規格我們依然維持留 1.25 倍安全裕度以策安全
            suggested_nfb = math.ceil(ac_current * 1.25)

            if suggested_nfb <= 20: suggested_wire = "2.0 mm 或 3.5 mm²"
            elif suggested_nfb <= 30: suggested_wire = "5.5 mm²"
            elif suggested_nfb <= 50: suggested_wire = "8.0 mm² 或 14 mm²"
            else: suggested_wire = "22 mm² 或以上"

            report = (
                f"📋 【⚡ 基地台日常常態電力統計報告】\n"
                f"{safety_warning}\n"
                f" 🔹 1. 新設射頻清單 (日常基本用電)：\n{session['detail_str']}\n"
                f" -----------------------------------\n"
                f" 🔋 2. 直流供電設備確認\n"
                f"   • 主設備基本直流負載: {net_dc_load:.0f} W\n"
                f"   👉 現場配置設備: 【{chosen_smr['name']}】\n"
                f" -----------------------------------\n"
                f" ⚡ 3. 交流日常基本用電統計 (單相三線 220V)\n"
                f"   • SMR 常態交流側總功耗: {ac_total_w:.0f} W\n"
                f"   • 現場基本運轉線電流: {ac_current:.2f} A\n"
                f"   👉 建議 NFB 開關規格: {suggested_nfb} A 2P (已含安全係數)\n"
                f"   👉 參考建議進線線徑: {suggested_wire}\n\n"
                f"💡 輸入「開始評估」可開啟下一座台的電力計算。"
            )
            
            USER_SESSIONS[user_id] = {"step": "input_equip", "equipments": {}}
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=report))
            return
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ 請輸入正確的直流設備代號數字 (1、2、3 或 4)。"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
