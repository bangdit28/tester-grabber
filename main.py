import threading, time, os, re, random, requests

FIREBASE_URL = os.getenv("FIREBASE_URL", "").strip().rstrip('/')
TELE_TOKEN = os.getenv("TELE_TOKEN", "").strip()
TELE_CHAT_ID = os.getenv("TELE_CHAT_ID", "").strip()

def kirim_tele(pesan):
    if not TELE_TOKEN: return
    try: requests.post(f"https://api.telegram.org/bot{TELE_TOKEN}/sendMessage", 
                      data={'chat_id': TELE_CHAT_ID, 'text': pesan, 'parse_mode': 'HTML'}, timeout=10)
    except: pass

def run_manager():
    print(f"🛰️ MANAGER AKTIF. DATABASE: {FIREBASE_URL}")
    while True:
        try:
            # 1. CEK PERINTAH
            r = requests.get(f"{FIREBASE_URL}/perintah_bot.json")
            cmds = r.json()
            if not cmds:
                time.sleep(1.5); continue
            
            # 2. AMBIL INVENTORY
            inv = requests.get(f"{FIREBASE_URL}/inventory.json").json()
            
            for cmd_id, val in cmds.items():
                m_id = val.get('memberId', 'tester')
                inv_id = val.get('inventoryId')
                
                print(f"📥 REQUEST MASUK: User {m_id} minta Stok ID {inv_id}")
                
                # CEK APAKAH STOK ADA DI FIREBASE?
                if not inv or inv_id not in inv:
                    print(f"❌ ERROR: Stok ID {inv_id} GAK ADA di Firebase Inventory lo!")
                    requests.delete(f"{FIREBASE_URL}/perintah_bot/{cmd_id}.json")
                    continue
                
                item = inv[inv_id]
                nomor_hasil = None
                
                # LOGIKA AMBIL STOK MANUAL
                if item.get('type') == 'manual':
                    nums = item.get('stock', [])
                    print(f"📦 Stok '{item['name']}' tersedia: {len(nums)} nomor")
                    
                    if nums:
                        if isinstance(nums, list):
                            nomor_hasil = nums.pop(0)
                            requests.put(f"{FIREBASE_URL}/inventory/{inv_id}/stock.json", json=nums)
                        else:
                            key = list(nums.keys())[0]
                            nomor_hasil = nums[key]
                            requests.delete(f"{FIREBASE_URL}/inventory/{inv_id}/stock/{key}.json")
                
                if nomor_hasil:
                    # TULIS KE MEMBERS
                    data_final = {"number": str(nomor_hasil), "name": item['name'], "timestamp": int(time.time() * 1000)}
                    path_member = f"{FIREBASE_URL}/members/{m_id}/active_numbers.json"
                    
                    res_post = requests.post(path_member, json=data_final)
                    if res_post.status_code == 200:
                        print(f"✅ SUKSES: {nomor_hasil} masuk ke members/{m_id}")
                        kirim_tele(f"✅ <b>NOMOR DIDAPAT!</b>\n👤 User: {m_id}\n📱 Nomor: <code>{nomor_hasil}</code>")
                    else:
                        print(f"❌ GAGAL nulis ke Firebase: {res_post.text}")
                else:
                    print(f"⚠️ GAGAL: Stok {item['name']} mungkin kosong.")
                    kirim_tele(f"⚠️ <b>STOK HABIS!</b>\nLayanan: {item['name']}")

                # HAPUS ANTRIAN
                requests.delete(f"{FIREBASE_URL}/perintah_bot/{cmd_id}.json")
        except Exception as e:
            print(f"MANAGER ERROR: {e}")
            time.sleep(5)

if __name__ == "__main__":
    kirim_tele("🚀 <b>Bot System Online!</b>")
    threading.Thread(target=run_manager, daemon=True).start()
    while True: time.sleep(10)
