import os
import time
import tempfile
import shutil
import subprocess
from flask import Flask, render_template, request, jsonify
from bs4 import BeautifulSoup
from pymongo import MongoClient
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# --- CLEANUP ---
try:
    subprocess.run(["pkill", "-f", "chromedriver"], check=False)
except: 
    pass

app = Flask(__name__)
app.secret_key = 'vtu_final_secret'

# --- DATABASE CONNECTION ---
MONGO_URI = os.environ.get('MONGO_URI', 'mongodb://127.0.0.1:27017/')

# Initialize variables globally
db = None
students_col = None
db_connected = False

def connect_db():
    """Attempt to connect to MongoDB with better error handling"""
    global db, students_col, db_connected
    try:
        print(f"🔄 Attempting to connect to MongoDB...")
        # Use a 10-second timeout
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=10000)
        
        # Test the connection
        client.admin.command('ping')
        
        # If successful, set up database and collection
        db = client['university_db']
        students_col = db['students']
        db_connected = True
        
        print(f"✅ Database Connected Successfully!")
        return True
        
    except Exception as e:
        db_connected = False
        print(f"❌ DATABASE CONNECTION FAILED!")
        print(f"❌ Error Details: {str(e)}")
        return False

# Attempt connection on startup
connect_db()

# --- BROWSER ---
driver = None

def init_driver():
    """Initialize Chrome WebDriver with headless configuration"""
    global driver
    if driver is None:
        print("🔵 Initializing Invisible Browser...")
        chrome_options = Options()
        
        # Headless mode
        chrome_options.add_argument("--headless=new")
        
        # Required for Docker/containerized environments
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        
        # Window and display settings
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--disable-popup-blocking")
        
        # Set binary location (for Chromium in container)
        # Note: Render often sets CHROME_BIN env var
        if os.environ.get('CHROME_BIN'):
            chrome_options.binary_location = os.environ.get('CHROME_BIN')
        else:
            chrome_options.binary_location = "/usr/bin/chromium"
        
        # User data directory
        user_data_dir = tempfile.mkdtemp()
        chrome_options.add_argument(f"--user-data-dir={user_data_dir}")
        
        try:
            driver = webdriver.Chrome(options=chrome_options)
            print("✅ Browser Started Successfully")
        except Exception as e:
            print(f"❌ Browser initialization failed: {e}")
            print("🔍 Trying with default Chrome binary...")
            chrome_options.binary_location = None
            driver = webdriver.Chrome(options=chrome_options)
            print("✅ Browser Started Successfully (fallback)")

@app.route('/')
def home():
    """Render the main page"""
    return render_template('index.html')

@app.route('/get_captcha')
def get_captcha():
    """Fetch and return the captcha image from VTU website"""
    global driver
    try:
        if driver is None: 
            init_driver()
            
        try:
            driver.get("https://results.vtu.ac.in/D25J26Ecbcs/index.php")
        except Exception as e:
            if driver: 
                try: driver.quit() 
                except: pass
            driver = None
            init_driver()
            driver.get("https://results.vtu.ac.in/D25J26Ecbcs/index.php")
        
        wait = WebDriverWait(driver, 15)
        captcha_img = wait.until(EC.presence_of_element_located((By.XPATH, "//img[contains(@src, 'captcha')]")))
        
        time.sleep(1.5)
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", captcha_img)
        time.sleep(0.5)
        
        return captcha_img.screenshot_as_png, 200, {'Content-Type': 'image/png'}
        
    except Exception as e:
        print(f"❌ Captcha Error: {e}")
        return "Browser Error", 500

@app.route('/leaderboard')
def get_leaderboard():
    """Return the top 100 students by total marks"""
    global students_col, db_connected
    
    if not db_connected or students_col is None:
        if not connect_db():
            return jsonify({
                'status': 'error', 
                'message': 'Database connection unavailable.'
            })
    
    try:
        # Fetch top 100 students including 'percentage'
        top_students = list(
            students_col.find(
                {}, 
                {'_id': 0, 'usn': 1, 'name': 1, 'total_marks': 1, 'sgpa': 1, 'percentage': 1}
            ).sort('total_marks', -1).limit(100)
        )
        
        # Add rank numbers
        for index, student in enumerate(top_students):
            student['rank'] = index + 1
            # Handle cases where old data might not have percentage
            if 'percentage' not in student:
                student['percentage'] = "N/A"
            
        return jsonify({'status': 'success', 'data': top_students})
        
    except Exception as e:
        return jsonify({
            'status': 'error', 
            'message': f'Failed to fetch leaderboard: {str(e)}'
        })

@app.route('/fetch_result', methods=['POST'])
def fetch_result():
    """Fetch student result from VTU website and store in database"""
    global students_col, db_connected
    
    if not db_connected or students_col is None:
        if not connect_db():
            return jsonify({
                'status': 'error', 
                'message': 'Database connection failed.'
            })
    
    usn = request.form['usn'].strip().upper()
    captcha_text = request.form['captcha'].strip()
    
    # Validation logic
    if not (usn.startswith('1DB23CS') or usn.startswith('1DB24CS')):
        return jsonify({
            'status': 'error', 
            'message': 'Invalid USN! Only 1DB23CS or 1DB24CS USNs are allowed'
        })
    
    if len(usn) != 10:
        return jsonify({
            'status': 'error', 
            'message': 'Invalid USN format! USN should be 10 characters'
        })
    
    try:
        if not driver: 
            init_driver()
        
        current_url = driver.current_url
        if "results.vtu.ac.in" not in current_url:
            driver.get("https://results.vtu.ac.in/D25J26Ecbcs/index.php")
            time.sleep(3)
        
        wait = WebDriverWait(driver, 15)
        
        usn_field = wait.until(EC.presence_of_element_located((By.NAME, "lns")))
        usn_field.clear()
        usn_field.send_keys(usn)
        
        captcha_field = wait.until(EC.presence_of_element_located((By.NAME, "captchacode")))
        captcha_field.clear()
        captcha_field.send_keys(captcha_text)
        
        submit_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//input[@type='submit']")))
        submit_btn.click()
        time.sleep(4)

        try:
            alert = driver.switch_to.alert
            txt = alert.text
            alert.accept()
            
            if "Invalid captcha" in txt or "invalid" in txt.lower(): 
                return jsonify({'status': 'error', 'message': 'Invalid Captcha'})
            if "not available" in txt.lower(): 
                return jsonify({'status': 'error', 'message': 'Result Not Found'})
            
            return jsonify({'status': 'error', 'message': f'{txt}'})
        except Exception: 
            pass

        if len(driver.window_handles) > 1:
            driver.switch_to.window(driver.window_handles[-1])

        soup = BeautifulSoup(driver.page_source, 'html.parser')
        student_data = parse_result_page(soup, usn)
        
        if student_data['name'] != "Unknown":
            try:
                students_col.update_one(
                    {'usn': usn}, 
                    {'$set': student_data}, 
                    upsert=True
                )
                
                my_total = student_data.get('total_marks', 0)
                uni_rank = students_col.count_documents({'total_marks': {'$gt': my_total}}) + 1
                
                coll_code = usn[:3]
                coll_rank = students_col.count_documents({
                    'total_marks': {'$gt': my_total},
                    'usn': {'$regex': f'^{coll_code}'}
                }) + 1
                
            except Exception as db_error:
                uni_rank = "N/A"
                coll_rank = "N/A"

            if len(driver.window_handles) > 1:
                driver.close()
                driver.switch_to.window(driver.window_handles[0])
            
            return jsonify({
                'status': 'success', 
                'data': student_data,
                'ranks': {'uni_rank': uni_rank, 'coll_rank': coll_rank}
            })
        else:
            return jsonify({'status': 'error', 'message': 'Could not parse result page'})

    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Server Error: {str(e)}'})

def get_credits_2022_cs_5th(sub_code):
    """Return credits for a given subject code"""
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
    """Convert marks to grade points"""
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
    """Parse the VTU result page and extract student data"""
    data = {
        'usn': usn, 
        'name': "Unknown", 
        'sgpa': "0.00", 
        'sgpa_float': 0.0, 
        'percentage': "0.00%", # Default
        'total_marks': 0, 
        'subjects': []
    }
    
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
                except: 
                    continue
        
        data['total_marks'] = running_total_marks
        
        # Calculate SGPA & Percentage
        if total_credits > 0:
            sgpa_val = total_gp / total_credits
            data['sgpa'] = "{:.2f}".format(sgpa_val)
            data['sgpa_float'] = float(sgpa_val)
            
            # Formula: (SGPA - 0.75) * 10
            perc_val = (sgpa_val - 0.75) * 10
            if perc_val < 0: perc_val = 0
            data['percentage'] = "{:.2f}%".format(perc_val)
            
    except Exception as e: 
        print(f"❌ Parse Error: {e}")
        
    return data

@app.route('/health')
def health_check():
    return jsonify({
        'status': 'healthy',
        'database_connected': db_connected,
        'browser_initialized': driver is not None
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    print("=" * 60)
    print("🚀 VTU Result App Starting...")
    print(f"🌐 Port: {port}")
    print("=" * 60)
    app.run(host='0.0.0.0', port=port, debug=False)