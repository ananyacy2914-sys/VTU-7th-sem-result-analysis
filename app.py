import os
from flask import Flask, render_template, request, jsonify
from bs4 import BeautifulSoup
from pymongo import MongoClient
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time

app = Flask(__name__)
app.secret_key = 'vtu_final_secret'

# --- DATABASE ---
# Use an Environment Variable for DB URL if available (for production), else localhost
MONGO_URI = os.environ.get('MONGO_URI', 'mongodb://127.0.0.1:27017/')
client = MongoClient(MONGO_URI)
db = client['university_db']
students_col = db['students']

# --- BROWSER ---
driver = None

def init_driver():
    global driver
    if driver is None:
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        
        # --- SMART DRIVER SETUP ---
        # If we are on Render/Linux (Docker), use the specific Chrome path.
        # If we are on Mac (Local), let Selenium find it automatically.
        if os.path.exists("/usr/bin/google-chrome"):
            chrome_options.binary_location = "/usr/bin/google-chrome"

        driver = webdriver.Chrome(options=chrome_options)

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/get_captcha')
def get_captcha():
    global driver
    try:
        init_driver()
        if "results.vtu.ac.in" not in driver.current_url:
             driver.get("https://results.vtu.ac.in/D25J26Ecbcs/index.php")
        else:
             driver.refresh()
        
        wait = WebDriverWait(driver, 20)
        captcha_img = wait.until(EC.presence_of_element_located((By.XPATH, "//img[contains(@src, 'captcha')]")))
        driver.execute_script("arguments[0].scrollIntoView();", captcha_img)
        return captcha_img.screenshot_as_png, 200, {'Content-Type': 'image/jpeg'}
    except Exception as e:
        print(f"Browser Error: {e}")
        # Reset driver if it crashes
        if driver:
            try: driver.quit()
            except: pass
            driver = None
        return "Browser Error", 500

# --- LEADERBOARD API ---
@app.route('/leaderboard')
def get_leaderboard():
    try:
        # Sort by Total Marks (Descending) -> Limit 100
        top_students = list(students_col.find({}, {'_id': 0, 'usn': 1, 'name': 1, 'total_marks': 1, 'sgpa': 1}).sort('total_marks', -1).limit(100))
        
        for index, student in enumerate(top_students):
            student['rank'] = index + 1
            
        return jsonify({'status': 'success', 'data': top_students})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/fetch_result', methods=['POST'])
def fetch_result():
    usn = request.form['usn'].strip().upper()
    captcha_text = request.form['captcha'].strip()

    try:
        if not driver:
            # Try to re-init if session was lost
            init_driver()
            if not driver:
                return jsonify({'status': 'error', 'message': 'Session expired. Refresh page.'})

        driver.find_element(By.NAME, "lns").clear()
        driver.find_element(By.NAME, "lns").send_keys(usn)
        driver.find_element(By.NAME, "captchacode").clear()
        driver.find_element(By.NAME, "captchacode").send_keys(captcha_text)
        
        existing_windows = driver.window_handles
        driver.find_element(By.XPATH, "//input[@type='submit']").click()
        time.sleep(2)

        try:
            alert = driver.switch_to.alert
            txt = alert.text
            alert.accept()
            if "Invalid captcha" in txt: return jsonify({'status': 'error', 'message': 'Invalid Captcha'})
            if "not available" in txt: return jsonify({'status': 'error', 'message': 'Result Not Found'})
        except: pass

        new_windows = driver.window_handles
        if len(new_windows) > len(existing_windows):
            for w in new_windows:
                if w not in existing_windows:
                    driver.switch_to.window(w)
                    break

        soup = BeautifulSoup(driver.page_source, 'html.parser')
        student_data = parse_result_page(soup, usn)
        
        if student_data['name'] != "Unknown":
            students_col.update_one({'usn': usn}, {'$set': student_data}, upsert=True)
            
            # --- RANK LOGIC (BY TOTAL MARKS) ---
            my_total = student_data.get('total_marks', 0)
            uni_rank = students_col.count_documents({'total_marks': {'$gt': my_total}}) + 1
            
            coll_code = usn[:3]
            coll_rank = students_col.count_documents({
                'total_marks': {'$gt': my_total},
                'usn': {'$regex': f'^{coll_code}'}
            }) + 1

            if len(driver.window_handles) > 1:
                driver.close()
                driver.switch_to.window(driver.window_handles[0])
            
            return jsonify({
                'status': 'success', 
                'data': student_data,
                'ranks': {'uni_rank': uni_rank, 'coll_rank': coll_rank}
            })
        else:
            return jsonify({'status': 'error', 'message': 'Parsing Failed'})

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({'status': 'error', 'message': 'Server Error'})

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

if __name__ == '__main__':
    # Use environment variable for port (Render uses $PORT)
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port, debug=True)