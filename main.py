import threading, time, os, re, random, requests
from curl_cffi import requests as curl_req

# === CONFIG ===
FIREBASE_URL = os.getenv("FIREBASE_URL", "").strip().rstrip('/')
TELE_TOKEN = os.getenv("TELE_TOKEN", "").strip()
TELE_CHAT_ID = os.getenv("TELE_CHAT_ID", "").strip()
MNIT_COOKIE = os.getenv("MNIT_COOKIE", "").strip()
MNIT_TOKEN = os.getenv("MNIT_TOKEN", "").strip()
MY_UA = os.getenv("MY_UA", "").strip()
MY_COOKIE = os.getenv("MY_COOKIE", "").strip()

def kirim_tele(pesan):
    if not TELE_TOKEN or not TELE_CHAT_ID: return
    try:
        url = f"https://api.telegram.org/bot{TELE_TOKEN}/sendMessage"
        requests.post(url, data={'chat_id': TELE_CHAT_ID, 'text': pesan, 'parse_mode': 'HTML'}, timeout=10)
    except: pass

def run_manager():
    print(f"🛰️ MANAGER AKTIF. MENGARAH KE: {FIREBASE_URL}")
    while True:
        try:
            # 1. Ambil Antrian Perintah
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
                
                m_id = val.get('memberId', 'Unknown')
                inv_id = val.get('inventoryId')
                print(f"📥 REQUEST: {m_id} minta stok {inv_id}")

                if not inv or inv_id not in inv:
                    requests.delete(f"{FIREBASE_URL}/perintah_bot/{cmd_id}.json")
                    continue
                
                item = inv[inv_id]
                nomor_hasil = None
                
                # SESUAIKAN DENGAN SCREENSHOT FIREBASE LO
                nama_layanan = item.get('serviceName') or item.get('name') or "Unknown Service"
                tipe = item.get('type') # 'PREFIX' atau 'STOCK' (sesuai setting admin lo)

                # --- LOGIKA AMBIL NOMOR ---
                # Jika tipe adalah STOCK (Manual CallTime)
                if tipe == "STOCK" or tipe == "manual":
                    nums = item.get('stock') or []
                    if nums:
                        if isinstance(nums, list):
                            nomor_hasil = nums.pop(0)
                            requests.put(f"{FIREBASE_URL}/inventory/{inv_id}/stock.json", json=nums)
                        elif isinstance(nums, dict):
                            key = list(nums.keys())[0]
                            nomor_hasil = nums[key]
                            requests.delete(f"{FIREBASE_URL}/inventory/{inv_id}/stock/{key}.json")
                
                # Jika tipe adalah PREFIX (X-MNIT)
                elif tipe == "PREFIX" or tipe == "xmnit":
                    raw_prefix = item.get('prefixes') or ""
                    # Bersihkan XXXX dari prefix (misal 2367261XXXX jadi 2367261)
                    target_range = str(raw_prefix).replace('X', '').replace('x', '').strip()
                    
                    if target_range:
                        h = {'content-type':'application/json','cookie':MNIT_COOKIE,'mauthtoken':MNIT_TOKEN,'user-agent':MY_UA}
                        try:
                            # Tembak MNIT
                            res = curl_req.post("https://x.mnitnetwork.com/mapi/v1/mdashboard/getnum/number", 
                                               headers=h, json={"range": target_range}, impersonate="chrome", timeout=20)
                            if res.status_code == 200:
                                res_json = res.json()
                                nomor_hasil = res_json.get('data', {}).get('copy')
                        except Exception as e:
                            print(f"Error MNIT: {e}")

                # --- PENGIRIMAN HASIL ---
                if nomor_hasil:
                    # Simpan ke dashboard anggota
                    data_final = {"number": str(nomor_hasil), "name": nama_layanan, "timestamp": int(time.time() * 1000)}
                    clean_num = str(nomor_hasil).replace('+', '').strip()
                    path_web = f"{FIREBASE_URL}/members/{m_id}/active_numbers/{clean_num}.json"
                    requests.patch(path_web, json=data_final)
                    
                    # Notif Telegram (WAJIB BUNYI)
                    kirim_tele(f"✅ <b>NOMOR DIDAPAT!</b>\n👤 Anggota: <code>{m_id}</code>\n📱 Nomor: <code>{nomor_hasil}</code>\n📦 Layanan: {nama_layanan}")
                    print(f"✅ BERHASIL: {nomor_hasil}")
                else:
                    kirim_tele(f"⚠️ <b>GAGAL / STOK HABIS!</b>\nLayanan: {nama_layanan}\nAnggota: {m_id}\nTipe: {tipe}")

                # Hapus antrian perintah
                requests.delete(f"{FIREBASE_URL}/perintah_bot/{cmd_id}.json")
            
            time.sleep(1)
        except Exception as e:
            print(f"MANAGER ERROR: {e}")
            time.sleep(5)

if __name__ == "__main__":
    # Test Bot Hidup
    kirim_tele("🚀 <b>BOT SYSTEM ONLINE!</b>\nSiap memproses antrian...")
    
    t1 = threading.Thread(target=run_manager, daemon=True)
    t1.start()
    while True: time.sleep(10)
