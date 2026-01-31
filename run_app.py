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

# --- CLEANUP ---
try:
    subprocess.run(["pkill", "-f", "chromedriver"], check=False)
except: 
    pass

app = Flask(__name__)
app.secret_key = 'vtu_final_secret'

# --- DATABASE CONNECTION ---
MONGO_URI = os.environ.get('MONGO_URI', 'mongodb://127.0.0.1:27017/')

db = None
students_col = None
db_connected = False

def connect_db():
    global db, students_col, db_connected
    try:
        print("🔄 Connecting to MongoDB...")
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=10000)
        client.admin.command('ping')
        db = client['university_db']
        students_col = db['students']
        db_connected = True
        print("✅ Database Connected Successfully!")
        return True
    except Exception as e:
        db_connected = False
        print(f"❌ DATABASE CONNECTION FAILED: {str(e)}")
        return False

connect_db()

# --- BROWSER INITIALIZATION ---
driver = None

def init_driver():
    global driver
    if driver is None:
        print("🔵 Initializing Invisible Browser...")
        chrome_options = Options()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--window-size=1920,1080")
        
        prefs = {"profile.default_content_setting_values.popups": 1}
        chrome_options.add_experimental_option("prefs", prefs)
        chrome_options.add_argument("--disable-popup-blocking")
        
        if os.environ.get('CHROME_BIN'):
            chrome_options.binary_location = os.environ.get('CHROME_BIN')
        else:
            chrome_options.binary_location = "/usr/bin/chromium"
        
        user_data_dir = tempfile.mkdtemp()
        chrome_options.add_argument(f"--user-data-dir={user_data_dir}")
        
        try:
            driver = webdriver.Chrome(options=chrome_options)
            print("✅ Browser Started Successfully")
        except Exception as e:
            print(f"❌ Browser Error: {e}")
            chrome_options.binary_location = None
            driver = webdriver.Chrome(options=chrome_options)

# --- ROUTES ---

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/get_captcha')
def get_captcha():
    global driver
    try:
        if driver is None: init_driver()
        try:
            driver.get("https://results.vtu.ac.in/D25J26Ecbcs/index.php")
        except:
            if driver: 
                try: driver.quit()
                except: pass
            driver = None
            init_driver()
            driver.get("https://results.vtu.ac.in/D25J26Ecbcs/index.php")

        wait = WebDriverWait(driver, 15)
        captcha_img = wait.until(EC.presence_of_element_located((By.XPATH, "//img[contains(@src, 'captcha')]")))
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", captcha_img)
        time.sleep(0.5)
        return captcha_img.screenshot_as_png, 200, {'Content-Type': 'image/png'}
    except Exception as e:
        return "Browser Error", 500

@app.route('/leaderboard')
def get_leaderboard():
    global students_col, db_connected
    if not db_connected: connect_db()
    
    sort_by = request.args.get('sort', 'total_marks')
    order = request.args.get('order', 'desc')

    try:
        all_students = list(students_col.find(
            {}, 
            {'_id': 0, 'usn': 1, 'name': 1, 'total_marks': 1, 'sgpa': 1, 'sgpa_float': 1, 'percentage': 1}
        ))
        
        all_students.sort(key=lambda x: x.get('total_marks', 0), reverse=True)
        for index, student in enumerate(all_students):
            student['rank'] = index + 1
            if 'percentage' not in student: 
                marks = student.get('total_marks', 0)
                student['percentage'] = "{:.2f}%".format((marks / 900) * 100)

        reverse_order = True if order == 'desc' else False
        
        if sort_by == 'sgpa':
            all_students.sort(key=lambda x: x.get('sgpa_float', 0.0), reverse=reverse_order)
        elif sort_by == 'total_marks':
            all_students.sort(key=lambda x: x.get('total_marks', 0), reverse=reverse_order)
        elif sort_by == 'rank':
            all_students.sort(key=lambda x: x.get('rank', 9999), reverse=not reverse_order)

        return jsonify({'status': 'success', 'data': all_students[:100]})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/analysis')
def get_analysis():
    global students_col, db_connected
    if not db_connected: connect_db()
    
    subject_code = request.args.get('subject')
    stats = {'total': 0, 'pass': 0, 'fail': 0}
    result_list = []

    try:
        if subject_code.startswith('class_'):
            # --- CLASS EQUIVALENCE LOGIC (LIST FILTER) ---
            students = list(students_col.find({}, {'_id': 0, 'usn': 1, 'name': 1, 'total_marks': 1, 'subjects': 1}))
            class_type = subject_code.split('_')[1]
            
            for s in students:
                has_failed = any(sub['result'] != 'P' for sub in s['subjects'])
                if has_failed: continue 

                try:
                    perc = (s.get('total_marks', 0) / 900) * 100
                except: perc = 0
                
                match = False
                status_label = ""
                
                if class_type == 'fcd' and perc >= 70:
                    match = True; status_label = "Distinction"
                elif class_type == 'fc' and 60 <= perc < 70:
                    match = True; status_label = "First Class"
                elif class_type == 'sc' and 50 <= perc < 60:
                    match = True; status_label = "Second Class"
                elif class_type == 'p' and 40 <= perc < 50:
                    match = True; status_label = "Pass Class"

                if match:
                    result_list.append({
                        'usn': s['usn'], 'name': s['name'],
                        'marks': f"{perc:.2f}%", 'status': status_label
                    })
            
            stats['total'] = len(result_list)
            stats['pass'] = len(result_list)
            stats['fail'] = 0

        elif subject_code and subject_code != 'overall':
            # --- SPECIFIC SUBJECT FAILURE ---
            query = {"subjects.code": subject_code}
            students = list(students_col.find(query, {'_id': 0, 'usn': 1, 'name': 1, 'subjects': 1}))
            stats['total'] = len(students)
            
            for s in students:
                subject_data = next((sub for sub in s['subjects'] if sub['code'] == subject_code), None)
                if subject_data:
                    if subject_data['result'] == 'P':
                        stats['pass'] += 1
                    else:
                        stats['fail'] += 1
                        result_list.append({
                            'usn': s['usn'], 'name': s['name'],
                            'marks': subject_data['total'], 'status': subject_data['result']
                        })
        else:
            # --- OVERALL FAILURES ---
            students = list(students_col.find({}, {'_id': 0, 'usn': 1, 'name': 1, 'subjects': 1}))
            stats['total'] = len(students)
            
            for s in students:
                has_failed = False
                failed_subjects = []
                for sub in s['subjects']:
                    if sub['result'] != 'P':
                        has_failed = True
                        failed_subjects.append(f"{sub['code']} ({sub['total']})")
                
                if has_failed:
                    stats['fail'] += 1
                    result_list.append({
                        'usn': s['usn'], 'name': s['name'],
                        'marks': ', '.join(failed_subjects), 'status': 'FAIL'
                    })
                else:
                    stats['pass'] += 1

        return jsonify({'status': 'success', 'stats': stats, 'data': result_list})
    
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/fetch_result', methods=['POST'])
def fetch_result():
    global students_col, db_connected
    if not db_connected: connect_db()
    
    usn = request.form['usn'].strip().upper()
    captcha_text = request.form['captcha'].strip()
    
    if not (usn.startswith('1DB23CS') or usn.startswith('1DB24CS')):
        return jsonify({'status': 'error', 'message': 'Invalid USN! Only 1DB23CS... allowed'})
    
    if len(usn) != 10:
        return jsonify({'status': 'error', 'message': 'Invalid USN Length'})
    
    try:
        if not driver: init_driver()
        if "results.vtu.ac.in" not in driver.current_url:
            driver.get("https://results.vtu.ac.in/D25J26Ecbcs/index.php")
        
        wait = WebDriverWait(driver, 15)
        
        wait.until(EC.presence_of_element_located((By.NAME, "lns"))).send_keys(usn)
        wait.until(EC.presence_of_element_located((By.NAME, "captchacode"))).send_keys(captcha_text)
        
        submit_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//input[@type='submit']")))
        driver.execute_script("arguments[0].click();", submit_btn)
        
        time.sleep(2)
        try:
            WebDriverWait(driver, 3).until(EC.alert_is_present())
            alert = driver.switch_to.alert
            txt = alert.text
            alert.accept()
            return jsonify({'status': 'error', 'message': f"VTU Says: {txt}"})
        except: pass

        result_found = False
        try:
            for i in range(10):
                if len(driver.window_handles) > 1:
                    driver.switch_to.window(driver.window_handles[-1])
                    result_found = True
                    break
                time.sleep(1)
        except: pass
        
        if not result_found:
            soup_check = BeautifulSoup(driver.page_source, 'html.parser')
            if "Student Name" in soup_check.get_text():
                result_found = True
            else:
                return jsonify({'status': 'error', 'message': 'Result Window did not open. Reload Captcha.'})

        soup = BeautifulSoup(driver.page_source, 'html.parser')
        student_data = parse_result_page(soup, usn)
        
        if student_data['name'] != "Unknown":
            if db_connected:
                students_col.update_one({'usn': usn}, {'$set': student_data}, upsert=True)
                my_total = student_data.get('total_marks', 0)
                uni_rank = students_col.count_documents({'total_marks': {'$gt': my_total}}) + 1
            else:
                uni_rank = "N/A"

            if len(driver.window_handles) > 1:
                driver.close()
                driver.switch_to.window(driver.window_handles[0])
            
            return jsonify({'status': 'success', 'data': student_data, 'ranks': {'uni_rank': uni_rank, 'coll_rank': "N/A"}})
        else:
            if len(driver.window_handles) > 1:
                driver.close()
                driver.switch_to.window(driver.window_handles[0])
            return jsonify({'status': 'error', 'message': 'Could not parse result.'})

    except Exception as e:
        return jsonify({'status': 'error', 'message': f'System Error: {str(e)}'})

# --- HELPERS ---
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
    except: return 0

def parse_result_page(soup, usn):
    data = {
        'usn': usn, 'name': "Unknown", 'sgpa': "0.00", 'sgpa_float': 0.0, 
        'percentage': "0.00%", 'total_marks': 0, 'class_result': "N/A", 
        'subjects': []
    }
    try:
        all_text = list(soup.stripped_strings)
        for i, text in enumerate(all_text):
            if "Student Name" in text:
                if i+2 < len(all_text) and len(all_text[i+2]) > 2 and ":" not in all_text[i+2]:
                    data['name'] = all_text[i+2].strip()
                    break
                elif i+1 < len(all_text) and len(all_text[i+1]) > 3:
                    data['name'] = all_text[i+1].replace(":", "").strip()
                    break
        
        div_rows = soup.find_all('div', class_='divTableRow')
        total_credits = 0; total_gp = 0; running_total_marks = 0 
        
        for row in div_rows:
            cells = row.find_all('div', class_='divTableCell')
            if len(cells) >= 6:
                try:
                    code = cells[0].text.strip()
                    marks = cells[4].text.strip()
                    credits = get_credits_2022_cs_5th(code)
                    gp = calculate_grade_point(marks)
                    if credits > 0: total_credits += credits; total_gp += (credits * gp)
                    running_total_marks += int(marks)
                    data['subjects'].append({'code': code, 'name': cells[1].text.strip(), 'total': marks, 'result': cells[5].text.strip()})
                except: continue
        
        data['total_marks'] = running_total_marks
        
        perc_val = 0.0
        if total_credits > 0:
            sgpa_val = total_gp / total_credits
            data['sgpa'] = "{:.2f}".format(sgpa_val)
            data['sgpa_float'] = float(sgpa_val)
            perc_val = (running_total_marks / 900) * 100
            data['percentage'] = "{:.2f}%".format(perc_val)
        
        # --- CALCULATE CLASS ---
        has_failed = False
        if len(data['subjects']) > 0:
            for sub in data['subjects']:
                if sub['result'] != 'P': has_failed = True; break
            
            if has_failed:
                data['class_result'] = "Fail"
            else:
                if perc_val >= 70: data['class_result'] = "First Class with Distinction"
                elif 60 <= perc_val < 70: data['class_result'] = "First Class"
                elif 50 <= perc_val < 60: data['class_result'] = "Second Class"
                elif 40 <= perc_val < 50: data['class_result'] = "Pass Class"
                else: data['class_result'] = "Fail"

    except Exception as e: print(e)
    return data

@app.route('/health')
def health_check():
    return jsonify({'status': 'healthy', 'database_connected': db_connected})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port)