import os
import time
import logging
import subprocess
from flask import Flask, render_template, request, jsonify
from bs4 import BeautifulSoup
from pymongo import MongoClient
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import UnexpectedAlertPresentException, WebDriverException, TimeoutException
from dotenv import load_dotenv
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
    logger.info("✅ Connected to MongoDB Atlas!")
except Exception as e:
    logger.error(f"❌ DB Error: {e}")

# --- ZOMBIE PROCESS KILLER ---
def kill_zombies():
    try:
        subprocess.run(['pkill', '-9', '-f', 'chrome'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(['pkill', '-9', '-f', 'chromedriver'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1.5)
    except Exception as e:
        logger.warning(f"Zombie cleanup warning: {e}")

# --- BROWSER SETUP ---
def create_driver():
    kill_zombies()
    
    chrome_options = Options()
    # Essential headless flags
    chrome_options.add_argument("--headless=new") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-application-cache")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--window-size=1280,720")
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    
    # Memory optimization for free tier
    chrome_options.add_argument("--single-process")
    chrome_options.add_argument("--disable-software-rasterizer")
    chrome_options.add_argument("--disable-background-timer-throttling")
    chrome_options.add_argument("--disable-backgrounding-occluded-windows")
    chrome_options.add_argument("--disable-renderer-backgrounding")
    
    # Check for Chrome binary in multiple locations (Render buildpack support)
    chrome_paths = [
        os.environ.get('GOOGLE_CHROME_BIN'),
        os.environ.get('CHROME_BIN'),
        '/app/.chrome-for-testing/chrome-linux64/chrome',  # Render buildpack
        '/usr/bin/google-chrome-stable',
        '/usr/bin/google-chrome',
        '/usr/bin/chromium-browser'
    ]
    
    chrome_found = False
    for path in chrome_paths:
        if path and os.path.exists(path):
            chrome_options.binary_location = path
            logger.info(f"✅ Using Chrome at: {path}")
            chrome_found = True
            break
    
    if not chrome_found:
        logger.warning("⚠️ Chrome binary not found in standard locations")
    
    # Check for ChromeDriver in multiple locations
    driver_paths = [
        os.environ.get('CHROMEDRIVER_PATH'),
        '/app/.chromedriver/bin/chromedriver',  # Render buildpack
        '/usr/local/bin/chromedriver',
        '/usr/bin/chromedriver'
    ]
    
    service = None
    for path in driver_paths:
        if path and os.path.exists(path):
            service = Service(path)
            logger.info(f"✅ Using ChromeDriver: {path}")
            break
    
    if not service:
        logger.info("📥 Downloading ChromeDriver via webdriver-manager...")
        service = Service(ChromeDriverManager().install())
        
    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.set_page_load_timeout(60)
    driver.implicitly_wait(10)
    return driver

# Global Driver Management
_driver = None
_driver_last_used = 0
DRIVER_TIMEOUT = 300  # Reset after 5 minutes

def get_driver():
    global _driver, _driver_last_used
    current_time = time.time()
    
    if _driver is None or (current_time - _driver_last_used) > DRIVER_TIMEOUT:
        reset_driver()
        logger.info("🚀 Starting new browser session...")
        try: 
            _driver = create_driver()
            _driver_last_used = current_time
        except Exception as e:
            logger.error(f"Driver creation failed: {e}")
            kill_zombies()
            time.sleep(2)
            _driver = create_driver()
            _driver_last_used = current_time
    else:
        _driver_last_used = current_time
        
    return _driver

def reset_driver():
    global _driver, _driver_last_used
    if _driver:
        try: 
            _driver.quit()
            logger.info("🛑 Driver quit successfully")
        except Exception as e:
            logger.warning(f"Error quitting driver: {e}")
    _driver = None
    _driver_last_used = 0
    kill_zombies()
    time.sleep(1)
    logger.info("🔄 Driver Reset Complete")

# --- HELPERS ---
def get_credits_2022_cs_7th(sub_code):
    code = sub_code.upper().strip()
    if code.startswith("BCS701"): return 4  
    if code.startswith("BCS702"): return 4  
    if code.startswith("BCS703"): return 4  
    if code.startswith("BCS714"): return 3  
    if code.startswith("BEE755B"): return 3  
    if code.startswith("BCS786"): return 6 
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
        total_credits = 0
        total_gp = 0
        running_total = 0
        has_fail = False
        
        for row in div_rows[1:]:
            cells = row.find_all('div', class_='divTableCell')
            if len(cells) >= 6:
                code = cells[0].text.strip()
                sub_name = cells[1].text.strip()
                marks = cells[4].text.strip()
                res = cells[5].text.strip()
                
                if res == 'F' or int(marks) < 18: 
                    has_fail = True
                
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
            
            if has_fail:
                data['class_result'] = "Fail"
            elif perc >= 70: 
                data['class_result'] = "First Class with Distinction"
            elif perc >= 60: 
                data['class_result'] = "First Class"
            elif perc >= 50: 
                data['class_result'] = "Second Class"
            elif perc >= 40: 
                data['class_result'] = "Pass Class"
            else: 
                data['class_result'] = "Fail"
            
    except Exception as e:
        logger.error(f"Parse error: {e}")
    return data

# --- ROUTES ---
@app.route('/')
def home(): 
    return render_template('index.html')

@app.route('/health')
def health():
    return jsonify({'status': 'healthy', 'timestamp': time.time()})

@app.route('/get_captcha')
def get_captcha():
    max_attempts = 3
    
    for attempt in range(max_attempts):
        driver = None
        try:
            if attempt == 0:
                logger.info("🔄 Resetting driver for fresh captcha session")
                reset_driver()
                
            logger.info(f"🔍 Captcha Attempt {attempt+1}/{max_attempts}: Initializing driver...")
            driver = get_driver()
            
            logger.info("📡 Loading VTU results page...")
            driver.get("https://results.vtu.ac.in/D25J26Ecbcs/index.php")
            
            wait = WebDriverWait(driver, 35)
            wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            logger.info("✅ Page loaded")
            
            time.sleep(1)
            
            img = None
            selectors = [
                "//img[contains(@src, 'captcha')]",
                "//img[contains(@src, 'Captcha')]",
                "//img[contains(@src, 'CAPTCHA')]",
                "//img[@id='captcha']",
                "//img[@name='captcha']",
                "//img[contains(@alt, 'captcha')]"
            ]
            
            for idx, selector in enumerate(selectors):
                try:
                    logger.info(f"Trying selector {idx+1}: {selector}")
                    img = driver.find_element(By.XPATH, selector)
                    if img:
                        logger.info(f"✅ Captcha image found with selector {idx+1}!")
                        break
                except Exception as se:
                    logger.debug(f"Selector {idx+1} failed: {se}")
                    continue
            
            if not img:
                logger.warning("⚠️ Standard selectors failed, trying to find any image...")
                imgs = driver.find_elements(By.TAG_NAME, "img")
                if imgs:
                    img = imgs[0]
                    logger.info(f"Found {len(imgs)} images, using first one")
            
            if not img:
                raise Exception("Captcha image not found with any selector")
            
            driver.execute_script("arguments[0].scrollIntoView(true);", img)
            time.sleep(0.8)
            
            try:
                screenshot = img.screenshot_as_png
            except Exception as screenshot_error:
                logger.warning(f"Element screenshot failed: {screenshot_error}, trying full page")
                screenshot = driver.get_screenshot_as_png()
            
            if screenshot and len(screenshot) > 100:
                logger.info(f"✅ Captcha captured successfully (Attempt {attempt+1}, {len(screenshot)} bytes)")
                return screenshot, 200, {'Content-Type': 'image/png'}
            else:
                raise Exception("Screenshot is empty or too small")
            
        except TimeoutException as te:
            logger.error(f"❌ Timeout on attempt {attempt+1}: {str(te)}")
            reset_driver()
            time.sleep(3)
            
        except WebDriverException as we:
            logger.error(f"❌ WebDriver error on attempt {attempt+1}: {str(we)}")
            reset_driver()
            time.sleep(3)
            
        except Exception as e:
            logger.error(f"❌ Captcha Attempt {attempt+1} Failed: {str(e)}")
            reset_driver()
            time.sleep(2 * (attempt + 1))
            
    logger.error("❌ All captcha attempts exhausted")
    reset_driver()
    return jsonify({
        'error': 'Failed to load captcha after multiple attempts. Please try again in a moment.'
    }), 503

@app.route('/fetch_result', methods=['POST'])
def fetch_result():
    usn = request.form['usn'].strip().upper()  # Already uppercase
    captcha = request.form['captcha'].strip()
    
    if not (usn.startswith('1DB21CS') or usn.startswith('1DB22CS') or usn.startswith('1DB23CS') or usn.startswith('1DB24CS')):
        return jsonify({'status': 'error', 'message': 'Invalid USN Series'})
    
    try:
        driver = get_driver()
        try:
            current_url = driver.current_url
            if "results.vtu.ac.in" not in current_url:
                logger.warning(f"Session on wrong URL: {current_url}")
                raise Exception("Session Timeout")
        except:
            logger.error("Session verification failed")
            return jsonify({'status': 'error', 'message': 'Session expired. Please reload captcha.'})

        usn_field = driver.find_element(By.NAME, "lns")
        usn_field.clear()
        usn_field.send_keys(usn)
        
        captcha_field = driver.find_element(By.NAME, "captchacode")
        captcha_field.clear()
        captcha_field.send_keys(captcha)
        
        try: driver.find_element(By.XPATH, "//input[@type='submit']").click()
        except UnexpectedAlertPresentException:
            alert = driver.switch_to.alert; msg = alert.text; alert.accept(); driver.refresh()
            return jsonify({'status': 'error', 'message': f"Alert: {msg}"})

        time.sleep(2)
        
        try:
            WebDriverWait(driver, 5).until(EC.alert_is_present())
            alert = driver.switch_to.alert; msg = alert.text; alert.accept(); driver.refresh()
            return jsonify({'status': 'error', 'message': f"VTU Says: {msg}"})
        except: pass

        if len(driver.window_handles) > 1: driver.switch_to.window(driver.window_handles[-1])
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        student_data = parse_result_page(soup, usn)
        
        if student_data['name'] != "Unknown":
            students_col.update_one({'usn': usn}, {'$set': student_data}, upsert=True)
            
            my_marks = student_data['total_marks']
            rank = students_col.count_documents({'total_marks': {'$gt': my_marks}}) + 1
            student_data['rank'] = rank

            if len(driver.window_handles) > 1: driver.close(); driver.switch_to.window(driver.window_handles[0])
            try: 
                driver.find_element(By.NAME, "lns").clear()
                driver.find_element(By.NAME, "captchacode").clear()
            except: pass

            return jsonify({'status': 'success', 'data': student_data})
        
        return jsonify({'status': 'error', 'message': 'Parsing failed. Check USN/Captcha.'})

    except Exception as e:
        logger.error(f"Fetch Error: {e}")
        reset_driver()
        return jsonify({'status': 'error', 'message': "Server Error. Try again."})

@app.route('/leaderboard')
def leaderboard():
    try:
        sort_by = request.args.get('sort', 'marks')
        order = request.args.get('order', 'desc')
        search = request.args.get('search', '').strip().upper()  # Add search parameter
        
        # Build query filter
        query = {}
        if search:
            # Search by USN or Name (case-insensitive)
            query = {
                '$or': [
                    {'usn': {'$regex': search, '$options': 'i'}},
                    {'name': {'$regex': search, '$options': 'i'}}
                ]
            }
        
        data = list(students_col.find(query, {'_id': 0}))

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
            
        stats = {
            'total': len(all_students),
            'passed': len(all_students) - failed_count,
            'failed': failed_count
        }

        response_data = []

        if category == 'overall_fail':
            for s in all_students:
                failed_subs = [sub['code'] for sub in s.get('subjects', []) if sub.get('result') == 'F']
                if failed_subs or s.get('class_result') == 'Fail':
                    s_copy = s.copy()
                    s_copy['fail_summary'] = ", ".join(failed_subs) if failed_subs else "Fail"
                    response_data.append(s_copy)
                    
        elif category == 'fcd':
            response_data = [s for s in all_students if "Distinction" in s.get('class_result', '')]
        elif category == 'fc':
            response_data = [s for s in all_students if s.get('class_result') == 'First Class']
        elif category == 'sc':
            response_data = [s for s in all_students if s.get('class_result') == 'Second Class']
        else:
            # Subject specific analysis
            subject_code = category
            subj_total = 0
            subj_pass = 0
            for s in all_students:
                subj = next((item for item in s.get('subjects', []) if item['code'].startswith(subject_code)), None)
                if subj:
                    subj_total += 1
                    if subj['result'] == 'P': 
                        subj_pass += 1
                    else:
                        s_copy = s.copy()
                        s_copy['fail_marks'] = subj['total']
                        response_data.append(s_copy)
            
            stats = {'total': subj_total, 'passed': subj_pass, 'failed': subj_total - subj_pass}

        return jsonify({'status': 'success', 'stats': stats, 'students': response_data})

    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port)