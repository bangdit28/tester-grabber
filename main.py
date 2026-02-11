import threading
import time
import os
import re
import random
import requests
from bs4 import BeautifulSoup
from curl_cffi import requests as curl_req

# === CONFIGURATION (SET DI KOYEB) ===
FIREBASE_URL = os.getenv("FIREBASE_URL")
MY_COOKIE = os.getenv("MY_COOKIE")      # CallTime
MNIT_COOKIE = os.getenv("MNIT_COOKIE")  # X-MNIT
MNIT_TOKEN = os.getenv("MNIT_TOKEN")    # Mauthtoken
MY_UA = os.getenv("MY_UA")              # User Agent
TELE_TOKEN = os.getenv("TELE_TOKEN")
TELE_CHAT_ID = os.getenv("TELE_CHAT_ID")

def send_or_edit_tele(text, msg_id=None):
    """Kirim pesan baru atau edit pesan lama agar tidak nyampah di grup"""
    try:
        if msg_id:
            url = f"https://api.telegram.org/bot{TELE_TOKEN}/editMessageText"
            data = {'chat_id': TELE_CHAT_ID, 'message_id': msg_id, 'text': text, 'parse_mode': 'HTML'}
        else:
            url = f"https://api.telegram.org/bot{TELE_TOKEN}/sendMessage"
            data = {'chat_id': TELE_CHAT_ID, 'text': text, 'parse_mode': 'HTML'}
        
        res = requests.post(url, data=data, timeout=10).json()
        return res.get('result', {}).get('message_id')
    except: return None

# ==========================================
# 1. MANAGER: PROSES AMBIL NOMOR (SINKRON NAMA)
# ==========================================
def run_manager():
    print("🚀 Manager Running: Multi-Team System Active...")
    while True:
        try:
            # Ambil antrian perintah dari Web
            raw_cmds = requests.get(f"{FIREBASE_URL}/perintah_bot.json").json()
            if not raw_cmds:
                time.sleep(1); continue
            
            # Ambil gudang inventory
            inv = requests.get(f"{FIREBASE_URL}/inventory.json").json()
            
            for cmd_id, val in raw_cmds.items():
                m_id = val.get('memberId')
                m_name = val.get('memberName', 'Admin')
                inv_id = val.get('inventoryId')
                
                item = inv.get(inv_id) if inv else None
                if not item:
                    requests.delete(f"{FIREBASE_URL}/perintah_bot/{cmd_id}.json")
                    continue

                nomor_hasil = None
                situs = "CallTime" if item['type'] == 'manual' else "x.mnitnetwork"
                
                # --- LOGIKA AMBIL STOK ---
                if item['type'] == 'manual':
                    nums = item.get('stock', [])
                    if nums:
                        if isinstance(nums, list):
                            nomor_hasil = nums.pop(0)
                            requests.put(f"{FIREBASE_URL}/inventory/{inv_id}/stock.json", json=nums)
                        else:
                            k = list(nums.keys())[0]; nomor_hasil = nums[k]
                            requests.delete(f"{FIREBASE_URL}/inventory/{inv_id}/stock/{k}.json")
                
                elif item['type'] == 'xmnit':
                    prefixes = item.get('prefixes', [])
                    if prefixes:
                        target = random.choice(prefixes)
                        h = {'content-type':'application/json','cookie':MNIT_COOKIE,'mauthtoken':MNIT_TOKEN,'user-agent':MY_UA}
                        res = curl_req.post("https://x.mnitnetwork.com/mapi/v1/mdashboard/getnum/number", headers=h, json={"range": target}, impersonate="chrome", timeout=20)
                        if res.status_code == 200:
                            nomor_hasil = res.json().get('data', {}).get('copy')

                if nomor_hasil:
                    # NOTIF TELE TAHAP 1 (DIPOST)
                    text_start = (
                        f"📞 <b>BERHASIL AMBIL NOMOR!</b>\n\n"
                        f"👤 <b>Nama :</b> {m_name}\n"
                        f"📱 <b>Nomor :</b> <code>{nomor_hasil}</code>\n"
                        f"📌 <b>Situs :</b> {situs}\n"
                        f"🌍 <b>Negara :</b> {item.get('name')}\n"
                        f"💬 <b>Pesan :</b> menunggu sms . . ."
                    )
                    tele_msg_id = send_or_edit_tele(text_start)

                    # SIMPAN KE DASHBOARD ANGGOTA & LOOKUP GRABBER
                    data_final = {
                        "number": str(nomor_hasil),
                        "name": m_name,
                        "country": item.get('name'),
                        "situs": situs,
                        "tele_msg_id": tele_msg_id,
                        "timestamp": int(time.time() * 1000)
                    }
                    # Simpan ke folder privat member
                    requests.post(f"{FIREBASE_URL}/members/{m_id}/active_numbers.json", json=data_final)
                    # Simpan ke lookup (pencarian cepat) berdasarkan nomor tanpa '+'
                    requests.patch(f"{FIREBASE_URL}/active_numbers_lookup/{str(nomor_hasil).replace('+','')}.json", json=data_final)
                    print(f"✅ Nomor {nomor_hasil} dialokasikan ke {m_name}")

                requests.delete(f"{FIREBASE_URL}/perintah_bot/{cmd_id}.json")
            time.sleep(1)
        except Exception as e:
            print(f"Manager Error: {e}")
            time.sleep(5)

# ==========================================
# 2. GRABBER: PROSES SMS & EDIT NOTIF TELE
# ==========================================
def process_sms_logic(num, msg):
    try:
        clean_num = str(num).replace('+','')
        # Cari siapa pemilik nomor ini di lookup table
        owner = requests.get(f"{FIREBASE_URL}/active_numbers_lookup/{clean_num}.json").json()
        
        if owner:
            # Format OTP monospaced (pake tag <code>)
            otp_match = re.search(r'\d{4,8}', msg)
            clean_msg = msg
            if otp_match:
                otp = otp_match.group(0)
                clean_msg = msg.replace(otp, f"<code>{otp}</code>")

            # NOTIF TELE TAHAP 2 (EDIT PESAN LAMA)
            text_finish = (
                f"📩 <b>SMS MASUK!</b>\n\n"
                f"👤 <b>Nama :</b> {owner['name']}\n"
                f"📱 <b>Nomor :</b> <code>{num}</code>\n"
                f"📌 <b>Situs :</b> {owner['situs']}\n"
                f"🌍 <b>Negara :</b> {owner['country']}\n"
                f"💬 <b>Pesan :</b> {clean_msg}"
            )
            send_or_edit_tele(text_finish, owner.get('tele_msg_id'))
            
            # Kirim data ke Firebase Global Messages untuk Dashboard Web
            requests.post(f"{FIREBASE_URL}/messages.json", json={
                "liveSms": num,
                "messageContent": msg,
                "timestamp": int(time.time() * 1000)
            })
            
            # Hapus lookup agar tidak diproses berulang
            requests.delete(f"{FIREBASE_URL}/active_numbers_lookup/{clean_num}.json")
    except: pass

def run_grabber():
    print("📡 SMS Grabber Aktif (Dual Panel)...")
    done_ids = []
    while True:
        try:
            # --- GRAB CALLTIME (Scraping) ---
            res_ct = requests.get(f"https://www.calltimepanel.com/yeni/SMS/?_={int(time.time()*1000)}", headers={'Cookie': MY_COOKIE}, timeout=15)
            soup = BeautifulSoup(res_ct.text, 'html.parser')
            for r in soup.select('table tr'):
                tds = r.find_all('td')
                if len(tds) < 4: continue
                n = tds[1].text.strip().split('-')[-1].strip()
                m = tds[2].text.strip()
                if f"{n}_{m[:5]}" not in done_ids:
                    process_sms_logic(n, m)
                    done_ids.append(f"{n}_{m[:5]}")

            # --- GRAB X-MNIT (API) ---
            for tgl in [time.strftime("%Y-%m-%d"), time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))]:
                api_info = f"https://x.mnitnetwork.com/mapi/v1/mdashboard/getnum/info?date={tgl}&page=1&search=&status="
                headers = {'cookie': MNIT_COOKIE, 'mauthtoken': MNIT_TOKEN, 'user-agent': MY_UA}
                res_mn = curl_req.get(api_info, headers=headers, impersonate="chrome", timeout=15)
                if res_mn.status_code == 200:
                    items = res_mn.json().get('data', {}).get('data', [])
                    for it in items:
                        num, code = it.get('copy'), it.get('code')
                        if num and code:
                            c_code = re.sub('<[^<]+?>', '', str(code)).strip()
                            if f"{num}_{c_code}" not in done_ids:
                                process_sms_logic(num, f"Your code is {c_code}")
                                done_ids.append(f"{num}_{c_code}")
            
            if len(done_ids) > 200: done_ids = done_ids[-100:]
            time.sleep(3)
        except: time.sleep(5)

if __name__ == "__main__":
    threading.Thread(target=run_manager, daemon=True).start()
    threading.Thread(target=run_grabber, daemon=True).start()
    print("🔥 TASK SMS ENGINE RUNNING...")
    while True: time.sleep(10)
