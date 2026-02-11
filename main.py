import threading, time, os, re, random, requests, json
from bs4 import BeautifulSoup
from curl_cffi import requests as curl_req

# === CONFIGURATION ===
FIREBASE_URL = os.getenv("FIREBASE_URL", "").strip().rstrip('/')
MY_COOKIE = os.getenv("MY_COOKIE", "").strip()
MNIT_COOKIE = os.getenv("MNIT_COOKIE", "").strip()
MNIT_TOKEN = os.getenv("MNIT_TOKEN", "").strip()
MY_UA = os.getenv("MY_UA", "").strip()
TELE_TOKEN = os.getenv("TELE_TOKEN", "").strip()
TELE_CHAT_ID = os.getenv("TELE_CHAT_ID", "").strip()

def send_or_edit_tele(text, msg_id=None):
    if not TELE_TOKEN or not TELE_CHAT_ID: return None
    try:
        if msg_id:
            url = f"https://api.telegram.org/bot{TELE_TOKEN}/editMessageText"
            payload = {'chat_id': TELE_CHAT_ID, 'message_id': msg_id, 'text': text, 'parse_mode': 'HTML'}
        else:
            url = f"https://api.telegram.org/bot{TELE_TOKEN}/sendMessage"
            payload = {'chat_id': TELE_CHAT_ID, 'text': text, 'parse_mode': 'HTML'}
        res = requests.post(url, data=payload, timeout=10).json()
        return res.get('result', {}).get('message_id')
    except: return None

# ==========================================
# 1. MANAGER: PENGAMBIL NOMOR (FIX STOK & MULTI)
# ==========================================
def run_manager():
    print("🛰️ MANAGER: Antrian System Aktif...")
    while True:
        try:
            # Ambil antrian perintah
            r = requests.get(f"{FIREBASE_URL}/perintah_bot.json")
            cmds = r.json()
            if not cmds or not isinstance(cmds, dict):
                time.sleep(1); continue
            
            # Ambil Inventory terbaru
            inv = requests.get(f"{FIREBASE_URL}/inventory.json").json()
            
            for cmd_id, val in cmds.items():
                if not isinstance(val, dict): continue
                
                m_id = val.get('memberId', 'Unknown')
                m_name = val.get('memberName', 'User')
                inv_id = val.get('inventoryId')
                
                item = inv.get(inv_id) if inv else None
                if not item:
                    requests.delete(f"{FIREBASE_URL}/perintah_bot/{cmd_id}.json")
                    continue

                nomor_hasil = None
                situs = "CallTime" if "PREFIX" not in str(item.get('type')).upper() else "x.mnitnetwork"
                
                # --- LOGIKA AMBIL STOK MANUAL ---
                if "PREFIX" not in str(item.get('type')).upper():
                    # Cek field stock, stok, atau numbers
                    nums = item.get('stock') or item.get('stok') or item.get('numbers') or []
                    if nums:
                        if isinstance(nums, list) and len(nums) > 0:
                            nomor_hasil = nums.pop(0)
                            # Update sisa stok ke Firebase agar bisa diambil lagi berikutnya
                            requests.put(f"{FIREBASE_URL}/inventory/{inv_id}/stock.json", json=nums)
                        elif isinstance(nums, dict) and len(nums) > 0:
                            key = list(nums.keys())[0]
                            nomor_hasil = nums[key]
                            requests.delete(f"{FIREBASE_URL}/inventory/{inv_id}/stock/{key}.json")
                
                # --- LOGIKA AMBIL X-MNIT ---
                else:
                    target_range = item.get('prefixes') or item.get('prefix') or "2367261XXXX"
                    h = {'content-type':'application/json','cookie':MNIT_COOKIE,'mauthtoken':MNIT_TOKEN,'user-agent':MY_UA}
                    res = curl_req.post("https://x.mnitnetwork.com/mapi/v1/mdashboard/getnum/number", headers=h, json={"range":target_range}, impersonate="chrome", timeout=20)
                    if res.status_code == 200:
                        nomor_hasil = res.json().get('data', {}).get('copy')

                if nomor_hasil:
                    # Notif Telegram 1: Berhasil Ambil
                    txt_start = (f"📞 <b>BERHASIL AMBIL NOMOR!</b>\n\n👤 <b>Nama :</b> {m_name}\n"
                                 f"📱 <b>Nomor :</b> <code>{nomor_hasil}</code>\n📌 <b>Situs :</b> {situs}\n"
                                 f"🌍 <b>Negara :</b> {item.get('serviceName') or item.get('name')}\n💬 <b>Pesan :</b> menunggu sms . . .")
                    tele_id = send_or_edit_tele(txt_start)

                    # Save to Firebase
                    clean_n = str(nomor_hasil).replace('+', '').strip()
                    data_final = {
                        "number": str(nomor_hasil), "name": m_name, "country": item.get('serviceName') or item.get('name'),
                        "situs": situs, "tele_msg_id": tele_id, "timestamp": int(time.time() * 1000)
                    }
                    # Masuk ke dashboard web
                    requests.patch(f"{FIREBASE_URL}/members/{m_id}/active_numbers/{clean_n}.json", json=data_final)
                    # Masuk ke pencarian grabber
                    requests.patch(f"{FIREBASE_URL}/active_numbers_lookup/{clean_n}.json", json=data_final)
                    print(f"✅ Nomor {nomor_hasil} dialokasikan ke {m_name}")

                # HAPUS PERINTAH DARI ANTRIAN (Agar bisa klik lagi)
                requests.delete(f"{FIREBASE_URL}/perintah_bot/{cmd_id}.json")
            
            time.sleep(1)
        except Exception as e:
            print(f"Manager Error: {e}")
            time.sleep(5)

# ==========================================
# 2. GRABBER: SMS (FIX X-MNIT GRAB)
# ==========================================
def process_incoming_sms(num, msg):
    try:
        clean_num = str(num).replace('+', '').strip()
        # Ambil data siapa yang punya nomor ini
        owner = requests.get(f"{FIREBASE_URL}/active_numbers_lookup/{clean_num}.json").json()
        if owner:
            # Format OTP monospaced
            otp_match = re.search(r'\d{4,8}', msg)
            clean_msg = msg
            if otp_match:
                otp = otp_match.group(0)
                clean_msg = msg.replace(otp, f"<code>{otp}</code>")

            # Update Notif Telegram (EDIT)
            txt_sms = (f"📩 <b>SMS MASUK!</b>\n\n👤 <b>Nama :</b> {owner['name']}\n"
                       f"📱 <b>Nomor :</b> <code>{num}</code>\n📌 <b>Situs :</b> {owner['situs']}\n"
                       f"🌍 <b>Negara :</b> {owner['country']}\n💬 <b>Pesan :</b> {clean_msg}")
            send_or_edit_tele(txt_sms, owner.get('tele_msg_id'))
            
            # Kirim ke Global Messages buat Web lo
            requests.post(f"{FIREBASE_URL}/messages.json", json={"liveSms": num, "messageContent": msg, "timestamp": int(time.time() * 1000)})
            # Hapus lookup biar gak dobel proses
            requests.delete(f"{FIREBASE_URL}/active_numbers_lookup/{clean_num}.json")
    except: pass

def run_grabber():
    print("📡 GRABBER: Scanning OTP (Dual Mode)...")
    done_ids = []
    headers_mnit = {'cookie': MNIT_COOKIE, 'mauthtoken': MNIT_TOKEN, 'user-agent': MY_UA, 'x-requested-with': 'XMLHttpRequest'}
    
    while True:
        try:
            # --- SCAN CALLTIME ---
            res_ct = requests.get(f"https://www.calltimepanel.com/yeni/SMS/?_={int(time.time()*1000)}", headers={'Cookie': MY_COOKIE}, timeout=15)
            soup = BeautifulSoup(res_ct.text, 'html.parser')
            for r in soup.select('table tr'):
                tds = r.find_all('td')
                if len(tds) < 4: continue
                n, m = tds[1].text.strip().split('-')[-1].strip(), tds[2].text.strip()
                if f"{n}_{m[:5]}" not in done_ids:
                    process_incoming_sms(n, m); done_ids.append(f"{n}_{m[:5]}")

            # --- SCAN X-MNIT (Cek tgl hari ini & kemarin) ---
            for tgl in [time.strftime("%Y-%m-%d"), time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))]:
                url_mn = f"https://x.mnitnetwork.com/mapi/v1/mdashboard/getnum/info?date={tgl}&page=1&search=&status="
                res_mn = curl_req.get(url_mn, headers=headers_mnit, impersonate="chrome", timeout=15)
                if res_mn.status_code == 200:
                    items = res_mn.json().get('data', {}).get('data', [])
                    for it in items:
                        num, code = it.get('copy'), it.get('code')
                        if num and code:
                            # Bersihkan tag HTML dari kode (kalo ada)
                            c_code = re.sub('<[^<]+?>', '', str(code)).strip()
                            if f"{num}_{c_code}" not in done_ids:
                                process_incoming_sms(num, f"Your code is {c_code}")
                                done_ids.append(f"{num}_{c_code}")
            
            if len(done_ids) > 300: done_ids = done_ids[-150:]
            time.sleep(3) # Cek tiap 3 detik
        except: time.sleep(5)

if __name__ == "__main__":
    # Kirim notif bahwa bot sudah hidup
    send_or_edit_tele("🚀 <b>BOT ENGINE V-FINAL AKTIF!</b>\nSistem sinkron 24 jam. Selamat bekerja team!")
    
    threading.Thread(target=run_manager, daemon=True).start()
    threading.Thread(target=run_grabber, daemon=True).start()
    while True: time.sleep(10)
