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

# --- 1. CLEANUP ---
try:
    # Kills old driver processes to prevent memory leaks on Render
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
        # 5-second timeout prevents the app from hanging if the connection is slow
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        client.admin.command('ping') 
        db = client['university_db']
        students_col = db['students']
        print("✅ Database Connected Successfully")
        return True
    except Exception as e:
        print(f"❌ DATABASE CONNECTION FAILED: {e}")
        return False

# Initial connection attempt
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
        
        # Ensures Selenium finds the Chromium binary on Render's Linux environment
        if os.environ.get('CHROME_BIN'):
            chrome_options.binary_location = os.environ.get('CHROME_BIN')
            
        user_data_dir = tempfile.mkdtemp()
        chrome_options.add_argument(f"--user-data-dir={user_data_dir}")
        
        driver = webdriver.Chrome(options=chrome_options)
        print("✅ Browser Initialized")

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
        
        # Fill VTU Form
        driver.find_element(By.NAME, "lns").clear()
        driver.find_element(By.NAME, "lns").send_keys(usn)
        driver.find_element(By.NAME, "captchacode").clear()
        driver.find_element(By.NAME, "captchacode").send_keys(captcha_text)
        driver.find_element(By.XPATH, "//input[@type='submit']").click()
        time.sleep(2)

        # Switch to the result window if it opens separately
        if len(driver.window_handles) > 1:
            driver.switch_to.window(driver.window_handles[-1])

        soup = BeautifulSoup(driver.page_source, 'html.parser')
        student_data = parse_result_page(soup, usn)
        
        if student_data['name'] != "Unknown":
            # SAVE TO ATLAS: This allows any student to add themselves to the leaderboard
            students_col.update_one({'usn': usn}, {'$set': student_data}, upsert=True)
            
            if len(driver.window_handles) > 1:
                driver.close()
                driver.switch_to.window(driver.window_handles[0])
                
            return jsonify({'status': 'success', 'data': student_data})
        else:
            return jsonify({'status': 'error', 'message': 'Parsing Failed. Verify USN/Captcha.'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/fetch_result', methods=['POST'])
def fetch_result():
    global students_col, driver
    if students_col is None: connect_db()
    
    usn = request.form.get('usn', '').strip().upper()
    captcha_text = request.form.get('captcha', '').strip()

    try:
        if driver is None: init_driver()
        
        # 1. Clear and Enter Details
        driver.find_element(By.NAME, "lns").clear()
        driver.find_element(By.NAME, "lns").send_keys(usn)
        driver.find_element(By.NAME, "captchacode").clear()
        driver.find_element(By.NAME, "captchacode").send_keys(captcha_text)
        
        # 2. Click Submit
        driver.find_element(By.XPATH, "//input[@type='submit']").click()
        
        # --- CRITICAL ALERT HANDLING ---
        time.sleep(1) # Wait for potential popup
        try:
            alert = driver.switch_to.alert
            alert_text = alert.text
            alert.accept() # Dismiss the alert
            print(f"⚠️ Website Alert: {alert_text}")
            return jsonify({'status': 'error', 'message': f'Website says: {alert_text}'})
        except:
            # No alert appeared, proceed to parse
            pass

        # 3. Handle Results Window
        if len(driver.window_handles) > 1:
            driver.switch_to.window(driver.window_handles[-1])

        soup = BeautifulSoup(driver.page_source, 'html.parser')
        student_data = parse_result_page(soup, usn)
        
        if student_data['name'] != "Unknown":
            # 4. Save to Database
            students_col.update_one({'usn': usn}, {'$set': student_data}, upsert=True)
            
            # Close the result tab and return to main
            if len(driver.window_handles) > 1:
                driver.close()
                driver.switch_to.window(driver.window_handles[0])
                
            return jsonify({'status': 'success', 'data': student_data})
        else:
            return jsonify({'status': 'error', 'message': 'Result not found or parsing failed.'})
            
    except Exception as e:
        # If a crash happens, try to reset the driver
        print(f"❌ Fetch Error: {e}")
        return jsonify({'status': 'error', 'message': 'System error. Please reload captcha and try again.'})
# --- 5. PARSING HELPER ---
def parse_result_page(soup, usn):
    data = {"usn": usn, "name": "Unknown", "total_marks": 0, "sgpa": "0.00"}
    try:
        all_text = list(soup.stripped_strings)
        for i, text in enumerate(all_text):
            if "Student Name" in text and i+2 < len(all_text):
                data['name'] = all_text[i+2].replace(":", "").strip()
                break
        # Marks extraction logic would go here
    except: pass
    return data

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port)