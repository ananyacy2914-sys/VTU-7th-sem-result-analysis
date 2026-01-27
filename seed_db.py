from pymongo import MongoClient
import random

# Connect to MongoDB
client = MongoClient('mongodb://127.0.0.1:27017/')
db = client['university_db']
students_col = db['students']

# Clear old data
students_col.delete_many({})

# Generate 50 Dummy Students
dummy_data = []
for i in range(1, 51):
    usn = f"1RV21CS{str(i).zfill(3)}"
    sgpa = round(random.uniform(5.0, 10.0), 2)
    dummy_data.append({
        'usn': usn,
        'name': f"Student {i}",
        'sgpa': sgpa,
        'college_code': "RV"
    })

students_col.insert_many(dummy_data)
print(f"✅ Successfully inserted {len(dummy_data)} dummy students!")
