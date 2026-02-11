import os
import time
import logging
import subprocess
import threading # NEW: For handling concurrent users
from flask import Flask, render_template, request, jsonify
from bs4 import BeautifulSoup
from pymongo import MongoClient
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import UnexpectedAlertPresentException, WebDriverException
from dotenv import load_dotenv
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

app = Flask(__name__)
app.secret_key = 'vtu_7th_sem_final_key'

# --- TRAFFIC CONTROL ---
# This lock prevents two users from crashing the browser by using it at the same time
driver_lock = threading.Lock()

# --- DATABASE CONNECTION ---
MONGO_URI = os.getenv('MONGO_URI')
if not MONGO_URI:
    MONGO_URI = "mongodb+srv://abhi202456_db_user:hlwqDtBfFCpvVweD@cluster0.01ushqs.mongodb.net/vtu_7th_sem_db?retryWrites=true&w=majority&appName=Cluster0"

try:
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    db = client['vtu_7th_sem_db'] 
    students_col = db['students']
    logger.info("✅ Connected to MongoDB Atlas!")
except Exception as e:
    logger.error(f"❌ DB Error: {e}")

# --- ZOMBIE PROCESS KILLER ---
def kill_zombies():
    try:
        subprocess.run(['pkill', '-9', '-f', 'chrome'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(['pkill', '-9', '-f', 'chromedriver'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except: pass

# --- BROWSER SETUP ---
def create_driver():
    kill_zombies()
    
    chrome_options = Options()
    chrome_options.add_argument("--headless=new") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--window-size=1920,1080")
    
    # Render Path Check
    chrome_bin = os.environ.get('CHROME_BIN')
    if not chrome_bin:
        possible_paths = ['/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser']
        for p in possible_paths:
            if os.path.exists(p):
                chrome_bin = p
                break

    if chrome_bin:
        chrome_options.binary_location = chrome_bin
        try:
            result = subprocess.run([chrome_bin, "--version"], capture_output=True, text=True)
            ver = result.stdout.strip().split()[-1]
            service = Service(ChromeDriverManager(driver_version=ver).install())
        except:
            service = Service(ChromeDriverManager().install())
    else:
        service = Service(ChromeDriverManager().install())
        
    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.set_page_load_timeout(60)
    return driver

# Global Driver
_driver = None

def get_driver():
    global _driver
    if _driver is None:
        try: _driver = create_driver()
        except: _driver = create_driver()
    return _driver

def reset_driver():
    global _driver
    if _driver:
        try: _driver.quit()
        except: pass
    _driver = None
    kill_zombies()

# --- ROUTES ---
@app.route('/')
def home(): return render_template('index.html')

@app.route('/reload_captcha')
def reload_captcha():
    with driver_lock: # LOCK: Only one reset at a time
        reset_driver()
        return get_captcha_internal()

@app.route('/get_captcha')
def get_captcha():
    with driver_lock: # LOCK: Queue users
        return get_captcha_internal()

def get_captcha_internal():
    for attempt in range(3):
        try:
            driver = get_driver()
            driver.get("https://results.vtu.ac.in/D25J26Ecbcs/index.php")
            wait = WebDriverWait(driver, 20)
            img = wait.until(EC.presence_of_element_located((By.XPATH, "//img[contains(@src, 'captcha')]")))
            return img.screenshot_as_png, 200, {'Content-Type': 'image/png'}
        except Exception as e:
            logger.warning(f"⚠️ Captcha Fail: {e}")
            reset_driver()
    return "Error", 500

@app.route('/fetch_result', methods=['POST'])
def fetch_result():
    usn = request.form['usn'].strip().upper()
    captcha = request.form['captcha'].strip()
    
    with driver_lock: # LOCK: Critical Section
        try:
            driver = get_driver()
            
            # 1. Validate Session
            try:
                if "results.vtu.ac.in" not in driver.current_url: raise Exception("Timeout")
            except: return jsonify({'status': 'error', 'message': 'Session timeout. Reload.'})

            # 2. Fill Form
            driver.find_element(By.NAME, "lns").clear()
            driver.find_element(By.NAME, "lns").send_keys(usn)
            driver.find_element(By.NAME, "captchacode").clear()
            driver.find_element(By.NAME, "captchacode").send_keys(captcha)
            
            try: driver.find_element(By.XPATH, "//input[@type='submit']").click()
            except UnexpectedAlertPresentException:
                alert = driver.switch_to.alert; msg = alert.text; alert.accept(); driver.refresh()
                return jsonify({'status': 'error', 'message': f"Alert: {msg}"})

            time.sleep(2)
            
            try:
                WebDriverWait(driver, 3).until(EC.alert_is_present())
                alert = driver.switch_to.alert; msg = alert.text; alert.accept(); driver.refresh()
                return jsonify({'status': 'error', 'message': f"VTU Says: {msg}"})
            except: pass

            if len(driver.window_handles) > 1: driver.switch_to.window(driver.window_handles[-1])
            
            # 3. Parse
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            student_data = parse_result_page(soup, usn)
            
            # 4. Save & Clean
            if student_data['name'] != "Unknown":
                students_col.update_one({'usn': usn}, {'$set': student_data}, upsert=True)
                my_marks = student_data['total_marks']
                rank = students_col.count_documents({'total_marks': {'$gt': my_marks}}) + 1
                student_data['rank'] = rank

                if len(driver.window_handles) > 1: driver.close(); driver.switch_to.window(driver.window_handles[0])
                # Clear fields to keep session clean
                try: driver.find_element(By.NAME, "lns").clear(); driver.find_element(By.NAME, "captchacode").clear()
                except: pass
                
                return jsonify({'status': 'success', 'data': student_data})
            
            return jsonify({'status': 'error', 'message': 'Parsing failed.'})

        except Exception as e:
            logger.error(f"Fetch Error: {e}")
            reset_driver()
            return jsonify({'status': 'error', 'message': "Server Error. Try again."})

# --- KEEP YOUR EXISTING HELPERS & ANALYSIS ROUTES BELOW ---
# (Paste the get_credits, calculate_grade_point, parse_result_page, leaderboard, and get_analysis functions from previous code here)
# ... [Helpers Code] ...
# ... [Analysis Route Code] ...

# --- Helper Functions (Standard) ---
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
    except: return 0

def parse_result_page(soup, usn):
    data = {'usn': usn, 'name': "Unknown", 'sgpa': "0.00", 'total_marks': 0, 'class_result': "N/A", 'subjects': []}
    try:
        all_text = list(soup.stripped_strings)
        for i, text in enumerate(all_text):
            if "Student Name" in text:
                data['name'] = all_text[i+2].replace(":", "").strip()
                break
        
        div_rows = soup.find_all('div', class_='divTableRow')
        total_credits = 0; total_gp = 0; running_total = 0
        has_fail = False
        
        for row in div_rows[1:]:
            cells = row.find_all('div', class_='divTableCell')
            if len(cells) >= 6:
                code = cells[0].text.strip()
                sub_name = cells[1].text.strip()
                marks = cells[4].text.strip()
                res = cells[5].text.strip()
                
                try: marks_int = int(marks)
                except: marks_int = 0
                
                if res in ['F', 'A', 'X'] or (res == 'P' and marks_int < 18): has_fail = True
                
                credits = get_credits_2022_cs_7th(code)
                gp = calculate_grade_point(marks)
                
                if credits > 0:
                    total_credits += credits
                    total_gp += (credits * gp)
                
                running_total += marks_int
                data['subjects'].append({'code': code, 'name': sub_name, 'total': marks, 'result': res})

        data['total_marks'] = running_total
        if total_credits > 0:
            sgpa_val = total_gp / total_credits
            data['sgpa'] = "{:.2f}".format(sgpa_val)
            perc = (running_total / 700) * 100 
            data['percentage'] = "{:.2f}%".format(perc)
            
            if has_fail: data['class_result'] = "Fail"
            elif perc >= 70: data['class_result'] = "First Class with Distinction"
            elif perc >= 60: data['class_result'] = "First Class"
            elif perc >= 50: data['class_result'] = "Second Class"
            elif perc >= 40: data['class_result'] = "Pass Class"
            else: data['class_result'] = "Fail"
            
    except: pass
    return data

@app.route('/leaderboard')
def leaderboard():
    try:
        sort_by = request.args.get('sort', 'marks')
        order = request.args.get('order', 'desc')
        data = list(students_col.find({}, {'_id': 0}))
        def get_sort_val(s, k):
            try: return float(s.get(k, 0))
            except: return 0.0
        
        reverse_order = (order == 'desc')
        if sort_by == 'sgpa': data.sort(key=lambda x: get_sort_val(x, 'sgpa'), reverse=reverse_order)
        else: data.sort(key=lambda x: get_sort_val(x, 'total_marks'), reverse=reverse_order)

        for i, s in enumerate(data): s['rank'] = i + 1
        return jsonify({'status': 'success', 'data': data})
    except Exception as e: return jsonify({'status': 'error', 'message': str(e)})

@app.route('/get_analysis')
def get_analysis():
    try:
        category = request.args.get('category', 'overall_fail')
        all_students = list(students_col.find({}, {'_id': 0}))
        failed_count = 0
        for s in all_students:
            is_fail = s.get('class_result') == 'Fail' or any(sub.get('result') == 'F' for sub in s.get('subjects', []))
            if is_fail: failed_count += 1
            
        stats = {'total': len(all_students), 'passed': len(all_students) - failed_count, 'failed': failed_count}
        response_data = []

        if category == 'overall_fail':
            for s in all_students:
                failed_subs = [sub['code'] for sub in s.get('subjects', []) if sub.get('result') == 'F']
                if failed_subs or s.get('class_result') == 'Fail':
                    s_copy = s.copy()
                    s_copy['fail_summary'] = ", ".join(failed_subs) if failed_subs else "Fail"
                    response_data.append(s_copy)
        elif category in ['fcd', 'fc', 'sc']:
            lookup = {'fcd': "Distinction", 'fc': "First Class", 'sc': "Second Class"}
            response_data = [s for s in all_students if lookup[category] in s.get('class_result', '')]
        else:
            subj_total = 0; subj_pass = 0
            for s in all_students:
                subj = next((item for item in s.get('subjects', []) if item['code'] == category), None)
                if subj:
                    subj_total += 1
                    if subj['result'] == 'P': subj_pass += 1
                    else:
                        s_copy = s.copy()
                        s_copy['fail_marks'] = subj['total']
                        response_data.append(s_copy)
            stats = {'total': subj_total, 'passed': subj_pass, 'failed': subj_total - subj_pass}

        return jsonify({'status': 'success', 'stats': stats, 'students': response_data})
    except Exception as e: return jsonify({'status': 'error', 'message': str(e)})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port)