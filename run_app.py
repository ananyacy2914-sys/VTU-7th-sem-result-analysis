import os
import time
import subprocess
from flask import Flask, render_template, request, jsonify
from bs4 import BeautifulSoup
from pymongo import MongoClient
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import UnexpectedAlertPresentException
from dotenv import load_dotenv
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = 'vtu_7th_sem_final_key'

# --- DATABASE CONNECTION ---
MONGO_URI = os.getenv('MONGO_URI')
if not MONGO_URI:
    MONGO_URI = "mongodb+srv://abhi202456_db_user:hlwqDtBfFCpvVweD@cluster0.01ushqs.mongodb.net/vtu_7th_sem_db?retryWrites=true&w=majority&appName=Cluster0"

try:
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    db = client['vtu_7th_sem_db'] 
    students_col = db['students']
    print("✅ Connected to MongoDB Atlas!")
except Exception as e:
    print(f"❌ DB Error: {e}")

# --- BROWSER SETUP (FIXED FOR RENDER) ---
def init_driver():
    """Initialize Chrome driver with proper configuration"""
    print("🚀 Starting Chrome driver initialization...")
    
    chrome_options = Options()
    chrome_options.add_argument("--headless=new") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    chrome_binary_path = os.environ.get('CHROME_BIN')
    
    if chrome_binary_path:
        print(f"🔹 Custom Chrome Path: {chrome_binary_path}")
        
        # Check if Chrome binary exists
        if os.path.exists(chrome_binary_path):
            print(f"✅ Chrome binary found at {chrome_binary_path}")
        else:
            print(f"❌ Chrome binary NOT found at {chrome_binary_path}")
            # List what's actually there
            parent_dir = os.path.dirname(chrome_binary_path)
            if os.path.exists(parent_dir):
                print(f"📂 Contents of {parent_dir}:")
                print(os.listdir(parent_dir))
        
        chrome_options.binary_location = chrome_binary_path

        try:
            result = subprocess.run([chrome_binary_path, "--version"], 
                                  capture_output=True, text=True, timeout=10)
            version_output = result.stdout.strip()
            print(f"🔹 Chrome Version: {version_output}")
            
            chrome_version = version_output.split()[-1]
            service = Service(ChromeDriverManager(driver_version=chrome_version).install())
            print("✅ ChromeDriver installed!")
        except Exception as e:
            print(f"⚠️ Version Detection Failed: {e}")
            service = Service(ChromeDriverManager().install())
    else:
        print("🔹 Using local ChromeDriver (no CHROME_BIN set)")
        service = Service(ChromeDriverManager().install())
    
    try:
        driver = webdriver.Chrome(service=service, options=chrome_options)
        print("✅ Chrome driver initialized successfully!")
        return driver
    except Exception as e:
        print(f"❌ Failed to initialize Chrome driver: {e}")
        import traceback
        traceback.print_exc()
        raise

# ⭐ CRITICAL FIX: Lazy Driver Initialization
_driver = None

def get_driver():
    """Get or create the global driver instance (lazy initialization)"""
    global _driver
    if _driver is None:
        print("🚀 Initializing Chrome driver on first request...")
        _driver = init_driver()
    return _driver

def reset_driver():
    """Reset the driver in case of errors"""
    global _driver
    try:
        if _driver is not None:
            print("🔄 Resetting driver...")
            _driver.quit()
    except Exception as e:
        print(f"⚠️ Error quitting driver: {e}")
    _driver = None

# --- HELPERS ---
def get_credits_2022_cs_7th(sub_code):
    code = sub_code.upper().strip()
    if code.startswith("BCS701"): return 4  
    if code.startswith("BCS702"): return 4  
    if code.startswith("BCS703"): return 4  
    if code.startswith("BCS714"): return 3  
    if code.startswith("BCS755"): return 3  
    if code.startswith("BCSP786"): return 6 
    return 0

def calculate_grade_point(marks):
    try:
        m = int(marks)
        if m >= 90: return 10
        if m >= 80: return 9
        if m >= 70: return 8
        if m >= 60: return 7
        if m >= 55: return 6
        if m >= 50: return 5
        if m >= 40: return 4
        return 0
    except: 
        return 0

def parse_result_page(soup, usn):
    data = {'usn': usn, 'name': "Unknown", 'sgpa': "0.00", 'total_marks': 0, 'class_result': "N/A", 'subjects': []}
    try:
        all_text = list(soup.stripped_strings)
        for i, text in enumerate(all_text):
            if "Student Name" in text:
                data['name'] = all_text[i+2].replace(":", "").strip()
                break
        
        div_rows = soup.find_all('div', class_='divTableRow')
        total_credits = 0
        total_gp = 0
        running_total = 0
        
        for row in div_rows[1:]:
            cells = row.find_all('div', class_='divTableCell')
            if len(cells) >= 6:
                code = cells[0].text.strip()
                sub_name = cells[1].text.strip()
                marks = cells[4].text.strip()
                res = cells[5].text.strip()
                
                credits = get_credits_2022_cs_7th(code)
                gp = calculate_grade_point(marks)
                
                if credits > 0:
                    total_credits += credits
                    total_gp += (credits * gp)
                
                running_total += int(marks)
                data['subjects'].append({'code': code, 'name': sub_name, 'total': marks, 'result': res})

        data['total_marks'] = running_total
        if total_credits > 0:
            sgpa_val = total_gp / total_credits
            data['sgpa'] = "{:.2f}".format(sgpa_val)
            perc = (running_total / 700) * 100 
            data['percentage'] = "{:.2f}%".format(perc)
            
            if perc >= 70: 
                data['class_result'] = "First Class with Distinction"
            elif perc >= 60: 
                data['class_result'] = "First Class"
            elif perc >= 50: 
                data['class_result'] = "Second Class"
            else: 
                data['class_result'] = "Fail"
            
    except Exception as e:
        print(f"⚠️ Parsing error: {e}")
    return data

# --- ROUTES ---
@app.route('/')
def home(): 
    return render_template('index.html')

# Debug route
@app.route('/debug')
def debug():
    """Debug route to check Chrome installation"""
    chrome_bin = os.environ.get('CHROME_BIN', 'Not set')
    debug_info = {
        'chrome_bin_env': chrome_bin,
        'chrome_exists': os.path.exists(chrome_bin) if chrome_bin != 'Not set' else False,
    }
    
    if chrome_bin != 'Not set':
        parent_dir = os.path.dirname(chrome_bin)
        if os.path.exists(parent_dir):
            debug_info['parent_dir_contents'] = os.listdir(parent_dir)
    
    try:
        driver = get_driver()
        driver.get("https://www.google.com")
        debug_info['driver_status'] = 'SUCCESS'
        debug_info['page_title'] = driver.title
    except Exception as e:
        debug_info['driver_status'] = 'FAILED'
        debug_info['error'] = str(e)
        import traceback
        debug_info['traceback'] = traceback.format_exc()
    
    return jsonify(debug_info)

@app.route('/get_captcha')
def get_captcha():
    try:
        print("📸 Attempting to fetch captcha...")
        driver = get_driver()
        driver.get("https://results.vtu.ac.in/D25J26Ecbcs/index.php")
        wait = WebDriverWait(driver, 15)
        img = wait.until(EC.presence_of_element_located((By.XPATH, "//img[contains(@src, 'captcha')]")))
        time.sleep(0.5)
        print("✅ Captcha screenshot captured")
        return img.screenshot_as_png, 200, {'Content-Type': 'image/png'}
    except Exception as e:
        print(f"❌ Captcha error: {e}")
        import traceback
        traceback.print_exc()
        reset_driver()
        return "Captcha loading failed. Check logs.", 500

@app.route('/fetch_result', methods=['POST'])
def fetch_result():
    usn = request.form['usn'].strip().upper()
    captcha = request.form['captcha'].strip()
    
    if not (usn.startswith('1DB21CS') or usn.startswith('1DB22CS')):
        return jsonify({'status': 'error', 'message': 'Invalid USN format'})
    
    try:
        driver = get_driver()
        
        if "results.vtu.ac.in" not in driver.current_url:
            return jsonify({'status': 'error', 'message': 'Session timeout. Reload Captcha.'})

        driver.find_element(By.NAME, "lns").send_keys(usn)
        driver.find_element(By.NAME, "captchacode").send_keys(captcha)
        
        try: 
            driver.find_element(By.XPATH, "//input[@type='submit']").click()
        except UnexpectedAlertPresentException:
            alert = driver.switch_to.alert
            msg = alert.text
            alert.accept()
            driver.refresh()
            return jsonify({'status': 'error', 'message': f"Alert: {msg}"})

        time.sleep(1.5)
        
        try:
            WebDriverWait(driver, 3).until(EC.alert_is_present())
            alert = driver.switch_to.alert
            msg = alert.text
            alert.accept()
            driver.refresh()
            return jsonify({'status': 'error', 'message': f"VTU Says: {msg}"})
        except: 
            pass

        if len(driver.window_handles) > 1: 
            driver.switch_to.window(driver.window_handles[-1])
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        student_data = parse_result_page(soup, usn)
        
        if student_data['name'] != "Unknown":
            students_col.update_one({'usn': usn}, {'$set': student_data}, upsert=True)
            
            my_marks = student_data['total_marks']
            rank = students_col.count_documents({'total_marks': {'$gt': my_marks}}) + 1
            student_data['rank'] = rank

            if len(driver.window_handles) > 1: 
                driver.close()
                driver.switch_to.window(driver.window_handles[0])
            
            try: 
                driver.find_element(By.NAME, "lns").clear()
                driver.find_element(By.NAME, "captchacode").clear()
            except: 
                pass

            return jsonify({'status': 'success', 'data': student_data})
        
        return jsonify({'status': 'error', 'message': 'Failed to parse result.'})

    except Exception as e:
        print(f"❌ Fetch error: {e}")
        try: 
            driver = get_driver()
            driver.get("https://results.vtu.ac.in/D25J26Ecbcs/index.php")
        except: 
            reset_driver()
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/leaderboard')
def leaderboard():
    try:
        sort_by = request.args.get('sort', 'marks')
        order = request.args.get('order', 'desc')

        data = list(students_col.find({}, {'_id': 0}))

        def get_sort_val(s, k):
            try: 
                return float(s.get(k, 0))
            except: 
                return 0.0

        reverse_order = (order == 'desc')
        if sort_by == 'sgpa':
            data.sort(key=lambda x: get_sort_val(x, 'sgpa'), reverse=reverse_order)
        else:
            data.sort(key=lambda x: get_sort_val(x, 'total_marks'), reverse=reverse_order)

        for i, s in enumerate(data): 
            s['rank'] = i + 1
        
        return jsonify({'status': 'success', 'data': data})
    except Exception as e:
        print(f"❌ Leaderboard error: {e}")
        return jsonify({'status': 'error', 'message': str(e)})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port)