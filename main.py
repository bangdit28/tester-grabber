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

def kirim_notif_tele(member_name, num, country, msg):
    """Hanya kirim notif saat SMS masuk"""
    if not TELE_TOKEN or not TELE_CHAT_ID: return
    try:
        # Format OTP biar monospaced (bisa diklik salin)
        otp_match = re.search(r'\d{4,8}', msg)
        clean_msg = msg
        if otp_match:
            otp = otp_match.group(0)
            clean_msg = msg.replace(otp, f"<code>{otp}</code>")

        text = (
            f"📩 <b>SMS MASUK!</b>\n\n"
            f"👤 <b>Nama :</b> {member_name}\n"
            f"📱 <b>Nomor :</b> <code>{num}</code>\n"
            f"🌍 <b>Negara :</b> {country}\n"
            f"💬 <b>Pesan :</b> {clean_msg}"
        )
        url = f"https://api.telegram.org/bot{TELE_TOKEN}/sendMessage"
        requests.post(url, data={'chat_id': TELE_CHAT_ID, 'text': text, 'parse_mode': 'HTML'}, timeout=10)
    except: pass

# ==========================================
# 1. MANAGER: PROSES AMBIL NOMOR (SILENT)
# ==========================================
def run_manager():
    print("🚀 MANAGER: Antrian Active (Silent Mode)...")
    while True:
        try:
            r = requests.get(f"{FIREBASE_URL}/perintah_bot.json")
            cmds = r.json()
            if not cmds or not isinstance(cmds, dict):
                time.sleep(1); continue
            
            inv = requests.get(f"{FIREBASE_URL}/inventory.json").json()
            for cmd_id, val in cmds.items():
                requests.delete(f"{FIREBASE_URL}/perintah_bot/{cmd_id}.json")
                
                m_id = val.get('memberId', 'tester')
                m_name = val.get('memberName', 'Tester')
                inv_id = val.get('inventoryId')
                
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
                    target_range = item.get('prefixes') or item.get('prefix')
                    h = {'content-type':'application/json','cookie':MNIT_COOKIE,'mauthtoken':MNIT_TOKEN,'user-agent':MY_UA}
                    res = curl_req.post("https://x.mnitnetwork.com/mapi/v1/mdashboard/getnum/number", headers=h, json={"range":target_range}, impersonate="chrome", timeout=20)
                    if res.status_code == 200: nomor_hasil = res.json().get('data', {}).get('copy')

                if nomor_hasil:
                    # Simpan data buat lookup grabber (Hanya Angka)
                    clean_n = re.sub(r'\D', '', str(nomor_hasil))
                    data_final = {
                        "number": str(nomor_hasil), 
                        "name": m_name, 
                        "country": item.get('serviceName') or item.get('name'),
                        "timestamp": int(time.time() * 1000)
                    }
                    # Update Web Anggota
                    requests.patch(f"{FIREBASE_URL}/members/{m_id}/active_numbers/{clean_n}.json", json=data_final)
                    # Update Lookup (Kunci buat Grabber SMS)
                    requests.patch(f"{FIREBASE_URL}/active_numbers_lookup/{clean_n}.json", json=data_final)
                    print(f"✅ Nomor {nomor_hasil} dialokasikan ke {m_name}")
            
            time.sleep(1)
        except Exception as e:
            print(f"Error Manager: {e}"); time.sleep(5)

# ==========================================
# 2. GRABBER: PENGAMBIL SMS (BERISIK)
# ==========================================
def process_incoming_sms(num, full_msg):
    try:
        clean_num = re.sub(r'\D', '', str(num))
        # Cari pemilik nomor di lookup
        owner_res = requests.get(f"{FIREBASE_URL}/active_numbers_lookup/{clean_num}.json")
        owner = owner_res.json()
        
        if owner:
            # 1. Kirim Chat Baru ke Telegram
            kirim_notif_tele(owner['name'], owner['number'], owner['country'], full_msg)
            
            # 2. Update Firebase Web
            requests.post(f"{FIREBASE_URL}/messages.json", json={
                "liveSms": owner['number'], 
                "messageContent": full_msg, 
                "timestamp": int(time.time() * 1000)
            })
            
            # 3. Hapus lookup biar gak dobel notif
            requests.delete(f"{FIREBASE_URL}/active_numbers_lookup/{clean_num}.json")
            print(f"✅ SMS Masuk dikirim ke Tele: {clean_num}")
    except: pass

def run_grabber():
    print("📡 GRABBER: Scanning OTP...")
    done_ids = set()
    h_mnit = {'cookie': MNIT_COOKIE,'mauthtoken': MNIT_TOKEN,'user-agent': MY_UA,'accept': 'application/json','x-requested-with': 'XMLHttpRequest'}
    
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
                    process_incoming_sms(n, m); done_ids.add(f"{n}_{m[:5]}")

            # --- SCAN X-MNIT (Gunakan Tanggal Dinamis) ---
            tgl = time.strftime("%Y-%m-%d")
            url_mn = f"https://x.mnitnetwork.com/mapi/v1/mdashboard/getnum/info?date={tgl}&page=1&search=&status="
            res_mn = curl_req.get(url_mn, headers=h_mnit, impersonate="chrome", timeout=15)
            if res_mn.status_code == 200:
                data_mnit = res_mn.json()
                items = data_mnit.get('data', {}).get('numbers', [])
                for it in items:
                    num, otp_raw = it.get('number'), it.get('otp')
                    if num and otp_raw and "Waiting" not in otp_raw:
                        uid = f"{num}_{otp_raw[:15]}"
                        if uid not in done_ids:
                            process_incoming_sms(num, otp_raw)
                            done_ids.add(uid)
            
            if len(done_ids) > 200: done_ids.clear()
            time.sleep(3)
        except: time.sleep(5)

if __name__ == "__main__":
    # Notif bot aktif (Sekali aja pas startup)
    url_tele = f"https://api.telegram.org/bot{TELE_TOKEN}/sendMessage"
    requests.post(url_tele, data={'chat_id': TELE_CHAT_ID, 'text': "🚀 <b>BOT SMS GRABBER AKTIF!</b>\nStandby 24 Jam.", 'parse_mode': 'HTML'})
    
    threading.Thread(target=run_manager, daemon=True).start()
    threading.Thread(target=run_grabber, daemon=True).start()
    while True: time.sleep(10)
