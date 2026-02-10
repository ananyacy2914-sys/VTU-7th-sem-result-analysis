import os
import time
import asyncio
from flask import Flask, render_template, request, jsonify
from bs4 import BeautifulSoup
from pymongo import MongoClient
from playwright.async_api import async_playwright
from dotenv import load_dotenv

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

# --- PLAYWRIGHT BROWSER SETUP ---
_browser = None
_playwright = None

async def get_browser():
    """Get or create the browser instance"""
    global _browser, _playwright
    if _browser is None:
        print("🚀 Initializing Playwright browser...")
        _playwright = await async_playwright().start()
        _browser = await _playwright.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox']
        )
        print("✅ Browser initialized!")
    return _browser

async def close_browser():
    """Close browser and playwright"""
    global _browser, _playwright
    if _browser:
        await _browser.close()
        _browser = None
    if _playwright:
        await _playwright.stop()
        _playwright = None

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

@app.route('/get_captcha')
def get_captcha():
    async def fetch_captcha():
        try:
            print("📸 Fetching captcha...")
            browser = await get_browser()
            page = await browser.new_page()
            await page.goto("https://results.vtu.ac.in/D25J26Ecbcs/index.php")
            
            # Wait for captcha image
            captcha_img = await page.wait_for_selector("img[src*='captcha']", timeout=10000)
            screenshot = await captcha_img.screenshot()
            await page.close()
            
            print("✅ Captcha captured!")
            return screenshot
        except Exception as e:
            print(f"❌ Captcha error: {e}")
            import traceback
            traceback.print_exc()
            raise
    
    try:
        screenshot = asyncio.run(fetch_captcha())
        return screenshot, 200, {'Content-Type': 'image/png'}
    except:
        return "Captcha failed", 500

@app.route('/fetch_result', methods=['POST'])
def fetch_result():
    usn = request.form['usn'].strip().upper()
    captcha = request.form['captcha'].strip()
    
    if not (usn.startswith('1DB21CS') or usn.startswith('1DB22CS')):
        return jsonify({'status': 'error', 'message': 'Invalid USN format'})
    
    async def fetch():
        try:
            browser = await get_browser()
            page = await browser.new_page()
            await page.goto("https://results.vtu.ac.in/D25J26Ecbcs/index.php")
            
            await page.fill("input[name='lns']", usn)
            await page.fill("input[name='captchacode']", captcha)
            await page.click("input[type='submit']")
            
            await page.wait_for_timeout(2000)
            
            # Handle alerts
            try:
                dialog = await page.wait_for_event('dialog', timeout=2000)
                msg = dialog.message
                await dialog.accept()
                await page.close()
                return {'status': 'error', 'message': f"VTU Says: {msg}"}
            except:
                pass
            
            html = await page.content()
            soup = BeautifulSoup(html, 'html.parser')
            student_data = parse_result_page(soup, usn)
            
            if student_data['name'] != "Unknown":
                students_col.update_one({'usn': usn}, {'$set': student_data}, upsert=True)
                
                my_marks = student_data['total_marks']
                rank = students_col.count_documents({'total_marks': {'$gt': my_marks}}) + 1
                student_data['rank'] = rank
                
                await page.close()
                return {'status': 'success', 'data': student_data}
            
            await page.close()
            return {'status': 'error', 'message': 'Failed to parse result.'}
            
        except Exception as e:
            print(f"❌ Fetch error: {e}")
            return {'status': 'error', 'message': str(e)}
    
    result = asyncio.run(fetch())
    return jsonify(result)

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