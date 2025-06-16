import os
import requests
import re

DEEPSEEK_API_URL = 'https://api.deepseek.com/v1/chat/completions'
API_KEY = os.getenv('DEEPSEEK_API_KEY')

with open('prompt.txt', 'r', encoding='utf-8') as f:
    user_prompt = f.read()

payload = {
    "model": "deepseek-coder",
    "messages": [
        {"role": "system", "content": "你是一个Python开发专家，熟练Flask、爬虫、SQLAlchemy等，代码要有详细注释。"},
        {"role": "user", "content": user_prompt}
    ],
    "temperature": 0.2
}
headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}
resp = requests.post(DEEPSEEK_API_URL, json=payload, headers=headers)
result = resp.json()
code = result['choices'][0]['message']['content']
matches = re.findall(r"```(?:python)?\s*(.*?)```", code, re.DOTALL)
final_code = "\n".join(matches) if matches else code
with open('app.py', 'w', encoding='utf-8') as f:
    f.write(final_code)
print("AI 代码已写入 app.py")