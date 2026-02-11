import threading, time, os, re, random, requests
from bs4 import BeautifulSoup
from curl_cffi import requests as curl_req

# === CONFIG ===
FIREBASE_URL = os.getenv("FIREBASE_URL", "").strip().rstrip('/')
TELE_TOKEN = os.getenv("TELE_TOKEN", "").strip()
TELE_CHAT_ID = os.getenv("TELE_CHAT_ID", "").strip()
MNIT_COOKIE = os.getenv("MNIT_COOKIE", "").strip()
MNIT_TOKEN = os.getenv("MNIT_TOKEN", "").strip()
MY_UA = os.getenv("MY_UA", "").strip()
MY_COOKIE = os.getenv("MY_COOKIE", "").strip()

def send_or_edit_tele(text, msg_id=None):
    """Kirim pesan baru atau edit pesan lama (biar rapi)"""
    if not TELE_TOKEN or not TELE_CHAT_ID: return None
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
# 1. MANAGER: PROSES AMBIL NOMOR
# ==========================================
def run_manager():
    print("🚀 Manager Running: Multi-Panel Active...")
    while True:
        try:
            r = requests.get(f"{FIREBASE_URL}/perintah_bot.json")
            cmds = r.json()
            if not cmds or not isinstance(cmds, dict):
                time.sleep(1); continue
            
            inv = requests.get(f"{FIREBASE_URL}/inventory.json").json()
            for cmd_id, val in cmds.items():
                m_id = val.get('memberId', 'Unknown')
                m_name = val.get('memberName', 'Admin')
                inv_id = val.get('inventoryId')
                
                item = inv.get(inv_id) if inv else None
                if not item:
                    requests.delete(f"{FIREBASE_URL}/perintah_bot/{cmd_id}.json")
                    continue

                nomor_hasil = None
                situs = "CallTime" if item.get('type') != 'PREFIX' else "x.mnitnetwork"
                
                # --- LOGIKA AMBIL NOMOR ---
                if item.get('type') == 'manual' or item.get('type') == 'STOCK':
                    nums = item.get('stock') or []
                    if nums:
                        if isinstance(nums, list):
                            nomor_hasil = nums.pop(0)
                            requests.put(f"{FIREBASE_URL}/inventory/{inv_id}/stock.json", json=nums)
                        else:
                            key = list(nums.keys())[0]; nomor_hasil = nums[key]
                            requests.delete(f"{FIREBASE_URL}/inventory/{inv_id}/stock/{key}.json")
                
                elif item.get('type') == 'PREFIX':
                    # FIX: Jangan hapus XXXX, kirim mentah-mentah sesuai permintaan MNIT
                    target_range = item.get('prefixes') or "2367261XXXX"
                    h = {'content-type':'application/json','cookie':MNIT_COOKIE,'mauthtoken':MNIT_TOKEN,'user-agent':MY_UA}
                    res = curl_req.post("https://x.mnitnetwork.com/mapi/v1/mdashboard/getnum/number", headers=h, json={"range":target_range}, impersonate="chrome", timeout=20)
                    if res.status_code == 200:
                        nomor_hasil = res.json().get('data', {}).get('copy')

                if nomor_hasil:
                    # Notif Telegram Tahap 1
                    txt_start = (f"📞 <b>BERHASIL AMBIL NOMOR!</b>\n\n👤 <b>Nama :</b> {m_name}\n"
                                 f"📱 <b>Nomor :</b> <code>{nomor_hasil}</code>\n📌 <b>Situs :</b> {situs}\n"
                                 f"🌍 <b>Negara :</b> {item.get('serviceName') or item.get('name')}\n💬 <b>Pesan :</b> menunggu sms . . .")
                    tele_id = send_or_edit_tele(txt_start)

                    data_final = {
                        "number": str(nomor_hasil), "name": m_name, "country": item.get('serviceName') or item.get('name'),
                        "situs": situs, "tele_msg_id": tele_id, "timestamp": int(time.time() * 1000)
                    }
                    # Simpan ke web anggota
                    clean_num = str(nomor_hasil).replace('+', '').strip()
                    requests.patch(f"{FIREBASE_URL}/members/{m_id}/active_numbers/{clean_num}.json", json=data_final)
                    # Simpan lookup buat Grabber SMS
                    requests.patch(f"{FIREBASE_URL}/active_numbers_lookup/{clean_num}.json", json=data_final)

                requests.delete(f"{FIREBASE_URL}/perintah_bot/{cmd_id}.json")
            time.sleep(1)
        except Exception as e:
            print(f"Manager Error: {e}")
            time.sleep(5)

# ==========================================
# 2. GRABBER: PROSES SMS & EDIT NOTIF TELE
# ==========================================
def process_incoming_sms(num, msg):
    try:
        clean_num = str(num).replace('+','').strip()
        owner = requests.get(f"{FIREBASE_URL}/active_numbers_lookup/{clean_num}.json").json()
        if owner:
            # Format OTP (Cari angka 4-8 digit)
            otp_match = re.search(r'\d{4,8}', msg)
            clean_msg = msg
            if otp_match:
                otp = otp_match.group(0)
                clean_msg = msg.replace(otp, f"<code>{otp}</code>")

            # Update Notif Telegram Lama (Diedit otomatis)
            txt_sms = (f"📩 <b>SMS MASUK!</b>\n\n👤 <b>Nama :</b> {owner['name']}\n"
                       f"📱 <b>Nomor :</b> <code>{num}</code>\n📌 <b>Situs :</b> {owner['situs']}\n"
                       f"🌍 <b>Negara :</b> {owner['country']}\n💬 <b>Pesan :</b> {clean_msg}")
            send_or_edit_tele(txt_sms, owner.get('tele_msg_id'))
            
            # Masukin ke Firebase /messages biar web anggota update
            requests.post(f"{FIREBASE_URL}/messages.json", json={"liveSms": num, "messageContent": msg, "timestamp": int(time.time()*1000)})
            # Hapus lookup biar gak dobel notif
            requests.delete(f"{FIREBASE_URL}/active_numbers_lookup/{clean_num}.json")
            print(f"✅ SMS Masuk & Notif Updated: {num}")
    except: pass

def run_grabber():
    print("📡 SMS Grabber Aktif (Dual Mode)...")
    done_ids = []
    while True:
        try:
            # --- GRAB CALLTIME ---
            res_ct = requests.get(f"https://www.calltimepanel.com/yeni/SMS/?_={int(time.time()*1000)}", headers={'Cookie': MY_COOKIE}, timeout=15)
            soup = BeautifulSoup(res_ct.text, 'html.parser')
            for r in soup.select('table tr'):
                tds = r.find_all('td')
                if len(tds) < 4: continue
                n, m = tds[1].text.strip().split('-')[-1].strip(), tds[2].text.strip()
                if f"{n}_{m[:5]}" not in done_ids:
                    process_incoming_sms(n, m); done_ids.append(f"{n}_{m[:5]}")

            # --- GRAB X-MNIT (Tgl hari ini & kemarin) ---
            for tgl in [time.strftime("%Y-%m-%d"), time.strftime("%Y-%m-%d", time.localtime(time.time()-86400))]:
                api_info = f"https://x.mnitnetwork.com/mapi/v1/mdashboard/getnum/info?date={tgl}&page=1&search=&status="
                res_mn = curl_req.get(api_info, headers={'cookie':MNIT_COOKIE,'mauthtoken':MNIT_TOKEN,'user-agent':MY_UA}, impersonate="chrome", timeout=15)
                if res_mn.status_code == 200:
                    for it in res_mn.json().get('data', {}).get('data', []):
                        n, c = it.get('copy'), it.get('code')
                        if n and c:
                            clean_c = re.sub('<[^<]+?>', '', str(c)).strip()
                            if f"{n}_{clean_c}" not in done_ids:
                                process_incoming_sms(n, f"Your code is {clean_c}"); done_ids.append(f"{n}_{clean_c}")
            
            if len(done_ids) > 200: done_ids = done_ids[-100:]
            time.sleep(3)
        except: time.sleep(5)

if __name__ == "__main__":
    send_or_edit_tele("🚀 <b>BOT ENGINE V-FINAL ONLINE!</b>\nSemua panel terhubung. PC boleh dimatikan.")
    threading.Thread(target=run_manager, daemon=True).start()
    threading.Thread(target=run_grabber, daemon=True).start()
    while True: time.sleep(10)
