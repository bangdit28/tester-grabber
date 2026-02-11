import threading, time, os, re, random, requests
from curl_cffi import requests as curl_req

# === CONFIG ===
FIREBASE_URL = os.getenv("FIREBASE_URL", "").strip().rstrip('/')
TELE_TOKEN = os.getenv("TELE_TOKEN", "").strip()
TELE_CHAT_ID = os.getenv("TELE_CHAT_ID", "").strip()
MNIT_COOKIE = os.getenv("MNIT_COOKIE", "").strip()
MNIT_TOKEN = os.getenv("MNIT_TOKEN", "").strip()
MY_UA = os.getenv("MY_UA", "").strip()

def kirim_tele(pesan):
    """Fungsi kirim notif ke Telegram - WAJIB BUNYI"""
    if not TELE_TOKEN or not TELE_CHAT_ID:
        print("⚠️ ERROR: Token Tele atau Chat ID kosong di Koyeb!")
        return
    try:
        url = f"https://api.telegram.org/bot{TELE_TOKEN}/sendMessage"
        # Biar angka OTP/Nomor enak diliat (Monospace)
        clean_msg = pesan.replace('+', '')
        otp_match = re.search(r'\d{4,8}', clean_msg)
        if otp_match:
            clean_msg = pesan.replace(otp_match.group(0), f"<code>{otp_match.group(0)}</code>")
            
        requests.post(url, data={'chat_id': TELE_CHAT_ID, 'text': pesan, 'parse_mode': 'HTML'}, timeout=10)
        print(f"📡 Telegram Sent: {pesan[:30]}...")
    except Exception as e:
        print(f"❌ Gagal kirim Telegram: {e}")

def run_manager():
    print(f"🛰️ MANAGER STANDBY. Target: {FIREBASE_URL}")
    while True:
        try:
            # 1. Ambil Antrian
            r = requests.get(f"{FIREBASE_URL}/perintah_bot.json")
            cmds = r.json()
            if not cmds or not isinstance(cmds, dict):
                time.sleep(1); continue
            
            # 2. Ambil Inventory
            inv = requests.get(f"{FIREBASE_URL}/inventory.json").json()
            
            for cmd_id, val in cmds.items():
                if not isinstance(val, dict):
                    requests.delete(f"{FIREBASE_URL}/perintah_bot/{cmd_id}.json")
                    continue
                
                m_id = val.get('memberId', 'UnknownUser')
                inv_id = val.get('inventoryId')
                print(f"📥 REQUEST MASUK: User {m_id} minta stok {inv_id}")

                # CEK APAKAH STOK ADA DI DATABASE
                if not inv or inv_id not in inv:
                    kirim_tele(f"❌ <b>GAGAL!</b>\nUser: {m_id}\nAlasan: Stok ID {inv_id} tidak ditemukan di Firebase.")
                    requests.delete(f"{FIREBASE_URL}/perintah_bot/{cmd_id}.json")
                    continue
                
                item = inv[inv_id]
                nomor_hasil = None
                nama_layanan = item.get('name', 'Unknown Service')
                
                # --- LOGIKA AMBIL NOMOR ---
                if item.get('type') == 'manual':
                    nums = item.get('stock', [])
                    if nums:
                        if isinstance(nums, list):
                            nomor_hasil = nums.pop(0)
                            requests.put(f"{FIREBASE_URL}/inventory/{inv_id}/stock.json", json=nums)
                        else:
                            key = list(nums.keys())[0]; nomor_hasil = nums[key]
                            requests.delete(f"{FIREBASE_URL}/inventory/{inv_id}/stock/{key}.json")
                
                elif item.get('type') == 'xmnit':
                    # Ambil prefix secara acak
                    prefixes = item.get('prefixes', [])
                    if not isinstance(prefixes, list):
                        prefixes = [str(prefixes)]
                    target = random.choice(prefixes)
                    
                    h = {'content-type':'application/json','cookie':MNIT_COOKIE,'mauthtoken':MNIT_TOKEN,'user-agent':MY_UA}
                    res = curl_req.post("https://x.mnitnetwork.com/mapi/v1/mdashboard/getnum/number", headers=h, json={"range":target}, impersonate="chrome", timeout=20)
                    if res.status_code == 200:
                        nomor_hasil = res.json().get('data', {}).get('copy')

                # --- HASIL AKHIR ---
                if nomor_hasil:
                    # SIMPAN KE WEB (members/[ID]/active_numbers)
                    data_final = {
                        "number": str(nomor_hasil),
                        "name": nama_layanan,
                        "timestamp": int(time.time() * 1000)
                    }
                    # Kita pake .patch biar gak bikin folder acak baru
                    # Path: members/[m_id]/active_numbers/[nomor]
                    clean_num = str(nomor_hasil).replace('+', '').strip()
                    path_web = f"{FIREBASE_URL}/members/{m_id}/active_numbers/{clean_num}.json"
                    
                    res_save = requests.patch(path_web, json=data_final)
                    
                    if res_save.status_code == 200:
                        kirim_tele(f"✅ <b>NOMOR DIDAPAT!</b>\n👤 Anggota: {m_id}\n📱 Nomor: <code>{nomor_hasil}</code>\n📦 Layanan: {nama_layanan}")
                        print(f"✅ Berhasil kirim nomor ke {m_id}")
                    else:
                        kirim_tele(f"❌ <b>DB ERROR!</b>\nUser: {m_id}\nNomor: {nomor_hasil}\nError: {res_save.text}")
                else:
                    kirim_tele(f"⚠️ <b>STOK HABIS!</b>\nLayanan: {nama_layanan}\nAnggota: {m_id}")

                # HAPUS ANTRIAN AGAR WEB BERHENTI MUTER
                requests.delete(f"{FIREBASE_URL}/perintah_bot/{cmd_id}.json")
            
            time.sleep(1)
        except Exception as e:
            print(f"MANAGER ERROR: {e}")
            time.sleep(5)

if __name__ == "__main__":
    # Test kirim pesan saat bot pertama kali nyala
    kirim_tele("🚀 <b>BOT SYSTEM ONLINE!</b>\nSistem siap menerima perintah dari Web.")
    
    t1 = threading.Thread(target=run_manager, daemon=True)
    t1.start()
    while True:
        time.sleep(10)
