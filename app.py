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

# --- Nokia AirScale 日常運轉基本功耗資料庫 (Typical) ---
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
    raw_msg = event.message.text.strip()
    user_msg = raw_msg.upper()

    if user_id not in USER_SESSIONS:
        USER_SESSIONS[user_id] = {"step": "input_site_name", "site_name": "未命名站台", "equipments": {}}

    session = USER_SESSIONS[user_id]

    if user_msg in ["開始評估", "HELP", "⚡ 新設基地台電力評估"]:
        USER_SESSIONS[user_id] = {"step": "input_site_name", "site_name": "未命名站台", "equipments": {}}
        reply_text = (
            "📱 【Nokia AirScale 電力與度數估算助手】\n\n"
            "【步驟 1：請輸入站台名稱】\n"
            "請直接回覆文字告知此站台名稱或編號（如：林園園區_01）。"
        )
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return

    # 階段零：設定站台名稱
    if session["step"] == "input_site_name":
        session["site_name"] = raw_msg
        session["step"] = "input_equip"
        
        reply_text = (
            f"✅ 站台名稱已設定為：【 {raw_msg} 】\n\n"
            f"【步驟 2：輸入新設射頻】\n"
            f"請輸入型號與數量，格式為：【型號 數量】\n"
            f"確認好設備後，請輸入【計算】。"
        )
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return

    # 階段一：處理設備輸入與直流瓦數/度數計算
    elif session["step"] == "input_equip":
        if user_msg == "計算":
            if not session["equipments"]:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ 您的清單目前是空的，請先輸入設備。"))
                return

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

            # 換算直流端日常基本電度量
            dc_kwh_per_hour = total_dc_demand / 1000.0
            dc_kwh_per_month = dc_kwh_per_hour * 24 * 30

            session["net_dc_load"] = net_dc_load
            session["total_dc_demand"] = total_dc_demand
            session["detail_str"] = "\n".join(detail_list)
            session["step"] = "select_smr"

            smart_rec = "超出單組 7.5kW 容量！"
            for k, smr in SMR_DATABASE.items():
                if smr["capacity"] >= total_dc_demand:
                    smart_rec = smr["name"]
                    break

            reply_text = (
                f"🏢 站台：{session['site_name']}\n"
                f"🔋 【日常基本直流電量與度數統計】\n\n"
                f"設備常態直流明細：\n{session['detail_str']}\n"
                f" -----------------------------------\n"
                f" • 主設備直流負載總和: {net_dc_load:.0f} W\n"
                f" ⚡ 直流端總電量需求: {total_dc_demand:.0f} W ({total_dc_demand/1000:.2f} kW)\n"
                f" 📊 直流端每小時耗電: {dc_kwh_per_hour:.3f} 度電\n"
                f" 📊 直流端每月預估耗電: {dc_kwh_per_month:.1f} 度電\n"
                f" 💡 (平時基本運轉推薦：{smart_rec})\n"
                f" -----------------------------------\n\n"
                f"【步驟 3：請選填現場要配置的直流設備】\n"
                f"請直接回覆【代號數字 1 ~ 4】:\n"
                f"【1】 TYPE 1 (2.0 kW)\n"
                f"【2】 SMR (5.0 kW)\n"
                f"【3】 TYPE 3 (6.0 kW)\n"
                f"【4】 SMR (7.5 kW)"
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
                        session["equipments"][model] = qty
                        reply = f"✅ 已記錄：{EQUIPMENT_DATABASE[model]['name']} 共 {qty} 台。\n"
                        for k, v in session["equipments"].items():
                            reply += f"• {EQUIPMENT_DATABASE[k]['name']}: {v}台\n"
                        reply += "\n輸入【計算】觀看常態瓦數、度數並選擇SMR。"
                    
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
                    return
        except ValueError:
            pass

        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ 請輸入「型號 數量」(如：AVQL 3)，或輸入「計算」。"))

    # 階段二：手選直流設備並輸出最終報告 (精準連動台電管內安全安培容量)
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

            # 最終交流電統計與度數換算
            ac_total_w = total_dc_demand / smr_efficiency
            ac_current = ac_total_w / (220 * pf)
            
            # 留 1.25 倍安全裕度進行開關與電氣級數精算
            calculated_nfb = math.ceil(ac_current * 1.25)
            
            # 🎯 🎯 依據使用者實務指導與最安全官方電工法規（管內安培容量）判定：
            if calculated_nfb <= 30:
                suggested_nfb = 30
                suggested_wire = "8.0 mm²"  # 30A以下(含30A)一律鎖死 8.0 mm² 打底
            elif calculated_nfb <= 50:
                suggested_nfb = 50          # 自動跳升級數
                suggested_wire = "14 mm²"   # 30A以上以此類推：14平方穿管安全容量可衝到 50A
            elif calculated_nfb <= 60:
                suggested_nfb = 60
                suggested_wire = "22 mm²"   # 22平方穿管法定安全容量為 60A
            elif calculated_nfb <= 85:
                suggested_nfb = 75 if calculated_nfb <= 75 else 100
                suggested_wire = "38 mm²"   # 38平方穿管法定安全容量為 85A
            else:
                suggested_nfb = calculated_nfb
                suggested_wire = "50 mm² 或以上"

            # 換算台電交流端日常基本電度量
            ac_kwh_per_hour = ac_total_w / 1000.0
            ac_kwh_per_month = ac_kwh_per_hour * 24 * 30

            report = (
                f"📋 【⚡ 基地台日常常態電力與度數報告】\n"
                f"🏢 站台名稱：{session['site_name']}\n"
                f"{safety_warning}\n"
                f" 🔹 1. 新設射頻清單：\n{session['detail_str']}\n"
                f" -----------------------------------\n"
                f" 🔋 2. 直流供電設備確認\n"
                f"   • 主設備基本直流負載: {net_dc_load:.0f} W\n"
                f"   👉 現場配置設備: 【{chosen_smr['name']}】\n"
                f" -----------------------------------\n"
                f" ⚡ 3. 交流供電系統統計 (單相三線 220V)\n"
                f"   • SMR 常態交流側總功耗: {ac_total_w:.0f} W\n"
                f"   • 現場基本運轉線電流: {ac_current:.2f} A\n"
                f"   👉 建議 NFB 開關規格: {suggested_nfb} A 2P\n"
                f"   👉 現場拉線進線線徑: {suggested_wire} (30A內保底8.0mm²，30A以上依法規以此類推)\n"
                f" -----------------------------------\n"
                f" 📊 4. 預估現場日常耗電度數 (台電計費基準)\n"
                f"   • 每小時基本用電: {ac_total_w:.0f} W ➡️ 【 {ac_kwh_per_hour:.3f} 度電 / 小時 】\n"
                f"   • 每月份預估總用電: 【 {ac_kwh_per_month:.1f} 度電 / 月 】\n\n"
                f"💡 輸入「開始評估」可開啟下一座台的電力計算。"
            )
            
            USER_SESSIONS[user_id] = {"step": "input_site_name", "site_name": "未命名站台", "equipments": {}}
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=report))
            return
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ 請輸入正確的直流設備代號數字 (1、2、3 或 4)。"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
