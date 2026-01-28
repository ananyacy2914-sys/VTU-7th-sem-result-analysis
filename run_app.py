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
        # 5-second timeout ensures the app doesn't hang if Atlas is slow
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        client.admin.command('ping') 
        db = client['university_db']
        students_col = db['students']
        print("✅ Database Connected")
        return True
    except Exception as e:
        print(f"❌ DB Connection Error: {e}")
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

        # Handle popup if it exists
        if len(driver.window_handles) > 1:
            driver.switch_to.window(driver.window_handles[-1])

        soup = BeautifulSoup(driver.page_source, 'html.parser')
        student_data = parse_result_page(soup, usn)
        
        if student_data['name'] != "Unknown":
            # SAVE TO DATABASE - This makes it visible to all users on the leaderboard
            students_col.update_one({'usn': usn}, {'$set': student_data}, upsert=True)
            
            # Clean up: close the result tab if it opened separately
            if len(driver.window_handles) > 1:
                driver.close()
                driver.switch_to.window(driver.window_handles[0])
                
            return jsonify({'status': 'success', 'data': student_data})
        else:
            return jsonify({'status': 'error', 'message': 'Failed to parse result. Verify USN/Captcha.'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/leaderboard')
def leaderboard():
    global students_col
    if students_col is None: connect_db()
    # Fetch, sort by marks descending, and limit to top 100
    students = list(students_col.find({}, {'_id': 0}).sort('total_marks', -1).limit(100))
    for i, s in enumerate(students):
        s['rank'] = i + 1
    return jsonify({"status": "success", "data": students})

# --- 5. HELPERS ---
def parse_result_page(soup, usn):
    # This must contain your logic for extracting Name and Marks
    # Below is a basic placeholder to prevent errors
    data = {"usn": usn, "name": "Unknown", "total_marks": 0, "sgpa": "0.00"}
    try:
        all_text = list(soup.stripped_strings)
        for i, text in enumerate(all_text):
            if "Student Name" in text and i+2 < len(all_text):
                data['name'] = all_text[i+2].replace(":", "").strip()
                break
        # Add your mark calculation logic here
    except: pass
    return data

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port)