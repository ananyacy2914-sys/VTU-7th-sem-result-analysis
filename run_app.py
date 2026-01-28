import os
import time
import tempfile
import subprocess
from flask import Flask, render_template, request, jsonify
from bs4 import BeautifulSoup
from pymongo import MongoClient
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import UnexpectedAlertPresentException, NoAlertPresentException

# --- 1. CLEANUP ---
try:
    subprocess.run(["pkill", "-f", "chromedriver"], check=False)
except: pass

app = Flask(__name__)
app.secret_key = 'vtu_final_secret'

# --- 2. DATABASE CONNECTION ---
MONGO_URI = os.environ.get('MONGO_URI', 'mongodb://127.0.0.1:27017/')
db = None
students_col = None

def connect_db():
    global db, students_col
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        client.admin.command('ping') 
        db = client['university_db']
        students_col = db['students']
        print("✅ Database Connected Successfully")
        return True
    except Exception as e:
        print(f"❌ DATABASE CONNECTION FAILED: {e}")
        return False

connect_db()

# --- 3. BROWSER INITIALIZATION ---
driver = None

def init_driver():
    global driver
    if driver is None:
        chrome_options = Options()
        chrome_options.add_argument("--headless=new") 
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--window-size=1920,1080")
        
        # --- CRITICAL FIX: Force Allow Popups via Prefs ---
        # This tells Chrome explicitly "Allow popups from all sites"
        prefs = {"profile.default_content_setting_values.popups": 1}
        chrome_options.add_experimental_option("prefs", prefs)
        chrome_options.add_argument("--disable-popup-blocking")
        
        if os.environ.get('CHROME_BIN'):
            chrome_options.binary_location = os.environ.get('CHROME_BIN')
            
        user_data_dir = tempfile.mkdtemp()
        chrome_options.add_argument(f"--user-data-dir={user_data_dir}")
        
        driver = webdriver.Chrome(options=chrome_options)
        print("✅ Browser Initialized with Popups Forced Allowed")

# --- 4. ROUTES ---

@app.route("/")
def home():
    return render_template("index.html")

@app.route('/get_captcha')
def get_captcha():
    global driver
    try:
        if driver is None: init_driver()
        driver.get("https://results.vtu.ac.in/D25J26Ecbcs/index.php")
        wait = WebDriverWait(driver, 15)
        captcha_img = wait.until(EC.presence_of_element_located((By.XPATH, "//img[contains(@src, 'captcha')]")))
        return captcha_img.screenshot_as_png, 200, {'Content-Type': 'image/jpeg'}
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/fetch_result', methods=['POST'])
def fetch_result():
    global students_col, driver
    if students_col is None: connect_db()
    
    usn = request.form.get('usn', '').strip().upper()
    captcha_text = request.form.get('captcha', '').strip()

    try:
        if driver is None: init_driver()
        
        # 1. Fill Form
        driver.find_element(By.NAME, "lns").clear()
        driver.find_element(By.NAME, "lns").send_keys(usn)
        driver.find_element(By.NAME, "captchacode").clear()
        driver.find_element(By.NAME, "captchacode").send_keys(captcha_text)
        
        # --- FIX 2: Hard Click via JavaScript ---
        # This bypasses any overlay that might block a normal click
        submit_btn = driver.find_element(By.XPATH, "//input[@type='submit']")
        driver.execute_script("arguments[0].click();", submit_btn)
        
        # 2. Check for "Invalid Captcha" Alert
        try:
            WebDriverWait(driver, 3).until(EC.alert_is_present())
            alert = driver.switch_to.alert
            alert_text = alert.text
            alert.accept()
            return jsonify({'status': 'error', 'message': f"VTU Says: {alert_text}"})
        except:
            pass

        # 3. Handle Result Window (Wait for popup)
        try:
            # Wait up to 20 seconds for the new window to appear
            WebDriverWait(driver, 20).until(lambda d: len(d.window_handles) > 1)
            driver.switch_to.window(driver.window_handles[-1])
        except:
            print(f"DEBUG: Popup failed. Current URL: {driver.current_url}")
            return jsonify({'status': 'error', 'message': 'Result window did not open. Please try again.'})

        # 4. Parse Content
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        student_data = parse_result_page(soup, usn)
        
        # 5. Close Result Window & Return
        if len(driver.window_handles) > 1:
            driver.close()
            driver.switch_to.window(driver.window_handles[0])
        
        if student_data['name'] != "Unknown":
            students_col.update_one({'usn': usn}, {'$set': student_data}, upsert=True)
            return jsonify({'status': 'success', 'data': student_data})
        else:
            return jsonify({'status': 'error', 'message': 'Parsed name is Unknown. Result format might have changed.'})

    except UnexpectedAlertPresentException:
        try:
            alert = driver.switch_to.alert
            alert.accept()
        except: pass
        return jsonify({'status': 'error', 'message': 'Invalid Captcha or Session Timeout'})
            
    except Exception as e:
        if driver:
            try: driver.quit()
            except: pass
            driver = None
        return jsonify({'status': 'error', 'message': 'System Error. Please reload and try again.'})

@app.route('/leaderboard')
def leaderboard():
    global students_col
    if students_col is None: connect_db()
    try:
        students = list(students_col.find({}, {'_id': 0}).sort('total_marks', -1).limit(100))
        for i, s in enumerate(students):
            s['rank'] = i + 1
        return jsonify({"status": "success", "data": students})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

# --- 5. PARSING HELPER ---
def get_credits_2022_cs_5th(sub_code):
    code = sub_code.upper().strip()
    if "BCS501" in code: return 3  
    if "BCS502" in code: return 4  
    if "BCS503" in code: return 4  
    if "BCSL504" in code: return 1 
    if "BCS515" in code or "BCS505" in code: return 3 
    if "BCS586" in code: return 2  
    if "BRMK557" in code: return 3 
    if "BESK508" in code or "BCS508" in code: return 1 
    return 0 

def calculate_grade_point(marks):
    try:
        m = int(marks)
        if 90 <= m <= 100: return 10
        if 80 <= m < 90: return 9
        if 70 <= m < 80: return 8
        if 60 <= m < 70: return 7
        if 55 <= m < 60: return 6
        if 50 <= m < 55: return 5
        if 40 <= m < 50: return 4
        return 0 
    except:
        return 0

def parse_result_page(soup, usn):
    data = {'usn': usn, 'name': "Unknown", 'sgpa': "0.00", 'sgpa_float': 0.0, 'total_marks': 0, 'subjects': []}
    try:
        all_text = list(soup.stripped_strings)
        for i, text in enumerate(all_text):
            if "Student Name" in text and i+3 < len(all_text):
                candidate = all_text[i+2]
                if len(candidate) > 2 and ":" not in candidate:
                    data['name'] = candidate
                    break
                elif len(all_text[i+1]) > 3:
                     data['name'] = all_text[i+1].replace(":", "").strip()
                     break

        div_rows = soup.find_all('div', class_='divTableRow')
        total_credits = 0
        total_gp = 0
        running_total_marks = 0 
        
        for row in div_rows:
            cells = row.find_all('div', class_='divTableCell')
            if len(cells) >= 6:
                try:
                    code = cells[0].text.strip()
                    marks = cells[4].text.strip()
                    credits = get_credits_2022_cs_5th(code)
                    gp = calculate_grade_point(marks)
                    if credits > 0:
                        total_credits += credits
                        total_gp += (credits * gp)
                    running_total_marks += int(marks)
                    data['subjects'].append({
                        'code': code,
                        'name': cells[1].text.strip(),
                        'total': marks,
                        'result': cells[5].text.strip()
                    })
                except: continue
        
        data['total_marks'] = running_total_marks
        if total_credits > 0:
            sgpa_val = total_gp / total_credits
            data['sgpa'] = "{:.2f}".format(sgpa_val)
            data['sgpa_float'] = float(sgpa_val)
    except Exception as e: print(e)
    return data

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port)