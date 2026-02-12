import threading, time, os, re, random, requests, json
from bs4 import BeautifulSoup
from curl_cffi import requests as curl_req

# === CONFIG ===
FIREBASE_URL = os.getenv("FIREBASE_URL", "").strip().rstrip('/')
MY_COOKIE = os.getenv("MY_COOKIE", "").strip()
MNIT_COOKIE = os.getenv("MNIT_COOKIE", "").strip()
MNIT_TOKEN = os.getenv("MNIT_TOKEN", "").strip()
MY_UA = os.getenv("MY_UA", "").strip()
TELE_TOKEN = os.getenv("TELE_TOKEN", "").strip()
TELE_CHAT_ID = os.getenv("TELE_CHAT_ID", "").strip()

def send_tele(text, msg_id=None):
    if not TELE_TOKEN or not TELE_CHAT_ID: return None
    try:
        method = "editMessageText" if msg_id else "sendMessage"
        url = f"https://api.telegram.org/bot{TELE_TOKEN}/{method}"
        payload = {'chat_id': TELE_CHAT_ID, 'text': text, 'parse_mode': 'HTML'}
        if msg_id: payload['message_id'] = msg_id
        res = requests.post(url, data=payload, timeout=10).json()
        return res.get('result', {}).get('message_id')
    except: return None

# ==========================================
# 1. MANAGER: AMBIL NOMOR
# ==========================================
def run_manager():
    print("🚀 MANAGER: System Online...")
    while True:
        try:
            r = requests.get(f"{FIREBASE_URL}/perintah_bot.json")
            cmds = r.json()
            if not cmds or not isinstance(cmds, dict):
                time.sleep(1); continue
            
            inv = requests.get(f"{FIREBASE_URL}/inventory.json").json()
            for cmd_id, val in cmds.items():
                requests.delete(f"{FIREBASE_URL}/perintah_bot/{cmd_id}.json")
                m_id, m_name, inv_id = val.get('memberId'), val.get('memberName', 'User'), val.get('inventoryId')
                
                item = inv.get(inv_id) if inv else None
                if not item: continue

                nomor_hasil = None
                situs = "CallTime" if "PREFIX" not in str(item.get('type')).upper() else "x.mnitnetwork"
                
                if situs == "CallTime":
                    nums = item.get('stock') or item.get('stok') or []
                    if nums and len(nums) > 0:
                        nomor_hasil = nums.pop(0)
                        requests.put(f"{FIREBASE_URL}/inventory/{inv_id}/stock.json", json=nums)
                else:
                    target = item.get('prefixes') or item.get('prefix')
                    h = {'content-type':'application/json','cookie':MNIT_COOKIE,'mauthtoken':MNIT_TOKEN,'user-agent':MY_UA}
                    res = curl_req.post("https://x.mnitnetwork.com/mapi/v1/mdashboard/getnum/number", headers=h, json={"range":target}, impersonate="chrome", timeout=20)
                    if res.status_code == 200: nomor_hasil = res.json().get('data', {}).get('copy')

                if nomor_hasil:
                    # SIMPAN LOOKUP (Angka doang buat grabber)
                    clean_n = re.sub(r'\D', '', str(nomor_hasil))
                    txt_start = (f"📞 <b>BERHASIL AMBIL NOMOR!</b>\n\n👤 <b>Nama :</b> {m_name}\n"
                                 f"📱 <b>Nomor :</b> <code>{nomor_hasil}</code>\n📌 <b>Situs :</b> {situs}\n"
                                 f"🌍 <b>Negara :</b> {item.get('serviceName') or item.get('name')}\n💬 <b>Pesan :</b> menunggu sms . . .")
                    tele_id = send_tele(txt_start)

                    data_final = {"number": str(nomor_hasil), "name": m_name, "country": item.get('serviceName') or item.get('name'), "situs": situs, "tele_msg_id": tele_id, "timestamp": int(time.time() * 1000)}
                    requests.patch(f"{FIREBASE_URL}/members/{m_id}/active_numbers/{clean_n}.json", json=data_final)
                    requests.patch(f"{FIREBASE_URL}/active_numbers_lookup/{clean_n}.json", json=data_final)
            time.sleep(1)
        except: time.sleep(5)

# ==========================================
# 2. GRABBER: SMS (ULTRA PEKA)
# ==========================================
def process_incoming_sms(num, raw_msg):
    try:
        # Kunci: Samakan format nomor (Hanya Angka)
        clean_num = re.sub(r'\D', '', str(num))
        print(f"🔍 Mencari pemilik nomor: {clean_num}")
        
        owner = requests.get(f"{FIREBASE_URL}/active_numbers_lookup/{clean_num}.json").json()
        if owner:
            # Ambil OTP ijo dari teks
            clean_otp = re.sub('<[^<]+?>', '', str(raw_msg))
            otp_match = re.search(r'\d{4,8}', clean_otp)
            display_msg = clean_otp
            if otp_match:
                otp_val = otp_match.group(0)
                display_msg = clean_otp.replace(otp_val, f"<code>{otp_val}</code>")

            text_sms = (f"📩 <b>SMS MASUK!</b>\n\n👤 <b>Nama :</b> {owner['name']}\n"
                       f"📱 <b>Nomor :</b> <code>{owner['number']}</code>\n📌 <b>Situs :</b> {owner['situs']}\n"
                       f"🌍 <b>Negara :</b> {owner['country']}\n💬 <b>Pesan :</b> {display_msg}")
            
            # Edit Notif Tele
            send_tele(text_sms, owner.get('tele_msg_id'))
            # Update Web
            requests.post(f"{FIREBASE_URL}/messages.json", json={"liveSms": owner['number'], "messageContent": clean_otp, "timestamp": int(time.time() * 1000)})
            # Hapus biar gak dobel
            requests.delete(f"{FIREBASE_URL}/active_numbers_lookup/{clean_num}.json")
            print(f"✅ SMS {clean_num} BERHASIL DIKIRIM!")
    except Exception as e:
        print(f"Error Process: {e}")

def run_grabber():
    print("📡 GRABBER: Scanning OTP...")
    done_uids = set()
    h_mnit = {'cookie': MNIT_COOKIE,'mauthtoken': MNIT_TOKEN,'user-agent': MY_UA,'accept': 'application/json','x-requested-with': 'XMLHttpRequest'}
    
    while True:
        try:
            # --- CALLTIME ---
            res_ct = requests.get(f"https://www.calltimepanel.com/yeni/SMS/?_={int(time.time()*1000)}", headers={'Cookie': MY_COOKIE}, timeout=15)
            soup = BeautifulSoup(res_ct.text, 'html.parser')
            for r in soup.select('table tr'):
                tds = r.find_all('td')
                if len(tds) < 4: continue
                n, m = tds[1].text.strip().split('-')[-1].strip(), tds[2].text.strip()
                if f"{n}_{m[:5]}" not in done_uids:
                    process_incoming_sms(n, m); done_uids.add(f"{n}_{m[:5]}")

            # --- X-MNIT (LOGIKA SINKRON F12) ---
            tgl = time.strftime("%Y-%m-%d")
            url_mn = f"https://x.mnitnetwork.com/mapi/v1/mdashboard/getnum/info?date={tgl}&page=1&search=&status="
            res_mn = curl_req.get(url_mn, headers=h_mnit, impersonate="chrome", timeout=15)
            
            if res_mn.status_code == 200:
                items = res_mn.json().get('data', {}).get('data', [])
                for it in items:
                    num, otp_raw = it.get('number'), it.get('otp')
                    if num and otp_raw and "Waiting" not in otp_raw:
                        uid = f"{num}_{otp_raw[:15]}"
                        if uid not in done_uids:
                            print(f"🔥 MNIT NEMU KODE: {num}")
                            process_incoming_sms(num, otp_raw)
                            done_uids.add(uid)
            
            if len(done_uids) > 200: done_uids.clear()
            time.sleep(3)
        except: time.sleep(5)

if __name__ == "__main__":
    threading.Thread(target=run_manager, daemon=True).start()
    threading.Thread(target=run_grabber, daemon=True).start()
    while True: time.sleep(10)
