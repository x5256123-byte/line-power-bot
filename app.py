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

# --- 🎯 射頻設備日常運轉基本功耗資料庫 (完全對齊您最終核定瓦數) ---
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
    進階高容錯檢索：直接讀取原始大表
    因為同一站號會有多行資料，這裡會將所有同站點的設備自動『揉合融合成一筆資料』
    """
    if not os.path.exists(CSV_FILE_PATH):
        return 'NOT_FOUND', None
        
    keyword_up = keyword.upper().strip()
    
    # 用來暫存搜尋到的站點行資料
    matched_rows = []
    
    with open(CSV_FILE_PATH, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # 欄位防呆去空格
            sid = str(row.get("台號", row.get("site_id", ""))).strip().upper()
            sname = str(row.get("台名", row.get("site_name", ""))).strip()
            sname_up = sname.upper()
            
            # 精準比對站號 或是 模糊包含站名關鍵字
            if sid == keyword_up or keyword_up in sname_up:
                matched_rows.append({
                    "site_id": sid,
                    "site_name": sname,
                    "model": str(row.get("模組型號", "")).strip().upper(),
                    "ac_phase": "3P4W" if "3P" in str(row.get("細胞(頻寬) / 細胞名稱", "")).upper() else "1P3W"
                })
                
    if not matched_rows:
        return 'NOT_FOUND', None
        
    # 檢查搜出來的結果，到底有幾種不同的「站號」
    unique_site_ids = list(set([item["site_id"] for item in matched_rows]))
    
    # 情境 A：剛好只找到一個站點（不論它在原表裡佔了幾行）
    if len(unique_site_ids) == 1:
        target_id = unique_site_ids[0]
        # 篩選出屬於該站點的所有行
        site_allels = [item for item in matched_rows if item["site_id"] == target_id]
        
        # 開始自動揉合融合同一座台的所有射頻型號數量
        merged_equipments = {}
        final_name = site_allels[0]["site_name"]
        final_phase = "1P3W" # 預設相別
        
        for item in site_allels:
            model = item["model"]
            # 檢查這個型號是不是在我們的功耗數據庫裡
            if model in EQUIPMENT_DATABASE:
                merged_equipments[model] = merged_equipments.get(model, 0) + 1
                
        # 回傳揉合包裝好的標準格式字典
        final_result = {
            "site_id": target_id,
            "site_name": final_name,
            "ac_phase": final_phase,
            "equipments": merged_equipments
        }
        return 'MATCH', final_result
        
    # 情境 B：範圍太寬，同時找到了多個不一樣的站點，交給同仁重新決定
    if len(unique_site_ids) > 1:
        multi_list = []
