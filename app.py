novel_crawler/
├── app.py                # Flask主程序
├── models.py             # 数据库模型
├── crawler.py            # 爬虫核心逻辑
├── templates/
│   └── index.html        # 前端页面
└── requirements.txt      # 依赖文件

from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class Novel(db.Model):
    """小说基本信息表"""
    __tablename__ = 'novels'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False, unique=True)  # 小说标题
    source_url = db.Column(db.String(255))  # 来源URL
    created_at = db.Column(db.DateTime, default=datetime.utcnow)  # 创建时间
    
    chapters = db.relationship('Chapter', backref='novel', lazy=True)  # 关联章节
    
    def __repr__(self):
        return f'<Novel {self.title}>'

class Chapter(db.Model):
    """小说章节表"""
    __tablename__ = 'chapters'
    
    id = db.Column(db.Integer, primary_key=True)
    novel_id = db.Column(db.Integer, db.ForeignKey('novels.id'), nullable=False)  # 关联小说ID
    title = db.Column(db.String(200))  # 章节标题
    url = db.Column(db.String(255))  # 章节URL
    order = db.Column(db.Integer)  # 章节顺序
    content = db.Column(db.Text)  # 章节内容
    created_at = db.Column(db.DateTime, default=datetime.utcnow)  # 创建时间
    
    def __repr__(self):
        return f'<Chapter {self.title}>'

import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin
import re
from models import db, Novel, Chapter

class NovelCrawler:
    def __init__(self, base_url):
        self.base_url = base_url
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
    
    def clean_content(self, text):
        """清理章节内容，去除广告和非正文内容"""
        # 去除常见的广告标签
        text = re.sub(r'<div class="ad.*?>.*?</div>', '', text, flags=re.DOTALL)
        text = re.sub(r'<script.*?>.*?</script>', '', text, flags=re.DOTALL)
        text = re.sub(r'<a href=.*?>.*?</a>', '', text)
        # 去除多余的空格和换行
        text = re.sub(r'\s+', '\n', text).strip()
        return text
    
    def get_chapter_content(self, url):
        """获取单个章节内容"""
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            response.encoding = 'utf-8'
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 根据目标网站结构调整选择器
            content_div = soup.find('div', id='content')
            if content_div:
                content = self.clean_content(str(content_div))
                return content
            return "内容获取失败"
        except Exception as e:
            print(f"获取章节内容失败: {url}, 错误: {e}")
            return None
    
    def crawl_novel(self, novel_url):
        """爬取整本小说"""
        try:
            response = requests.get(novel_url, headers=self.headers)
            response.encoding = 'utf-8'
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 获取小说标题
            title = soup.find('h1').text.strip()
            
            # 检查小说是否已存在
            existing_novel = Novel.query.filter_by(title=title).first()
            if existing_novel:
                return existing_novel
            
            # 创建新小说记录
            novel = Novel(title=title, source_url=novel_url)
            db.session.add(novel)
            db.session.commit()
            
            # 获取目录列表
            chapter_links = []
            list_div = soup.find('div', id='list')
            if list_div:
                for a in list_div.find_all('a', href=True):
                    if 'html' in a['href']:  # 确保是章节链接
                        chapter_url = urljoin(novel_url, a['href'])
                        chapter_links.append({
                            'title': a.text.strip(),
                            'url': chapter_url
                        })
            
            # 使用多线程爬取所有章节内容
            chapters_data = []
            with ThreadPoolExecutor(max_workers=12) as executor:
                future_to_url = {
                    executor.submit(self.get_chapter_content, chap['url']): chap 
                    for chap in chapter_links
                }
                
                for future in as_completed(future_to_url):
                    chap_info = future_to_url[future]
                    content = future.result()
                    if content:
                        chapters_data.append({
                            'title': chap_info['title'],
                            'url': chap_info['url'],
                            'content': content
                        })
            
            # 保存章节到数据库
            for i, chap_data in enumerate(chapters_data):
                chapter = Chapter(
                    novel_id=novel.id,
                    title=chap_data['title'],
                    url=chap_data['url'],
                    order=i+1,
                    content=chap_data['content']
                )
                db.session.add(chapter)
            
            db.session.commit()
            return novel
            
        except Exception as e:
            db.session.rollback()
            print(f"爬取小说失败: {e}")
            return None

from flask import Flask, render_template, request, jsonify
from models import db, Novel, Chapter
from crawler import NovelCrawler
import os

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///novels.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# 初始化数据库
db.init_app(app)
with app.app_context():
    db.create_all()

@app.route('/', methods=['GET', 'POST'])
def index():
    """主页，用于输入小说URL"""
    if request.method == 'POST':
        novel_url = request.form.get('novel_url')
        if novel_url:
            crawler = NovelCrawler(novel_url)
            novel = crawler.crawl_novel(novel_url)
            if novel:
                return render_template('index.html', message=f"成功爬取小说: {novel.title}")
            return render_template('index.html', error="爬取小说失败")
    return render_template('index.html')

# API接口
@app.route('/api/novels', methods=['GET'])
def get_novels():
    """获取所有小说列表"""
    novels = Novel.query.all()
    return jsonify([{
        'id': novel.id,
        'title': novel.title,
        'source_url': novel.source_url,
        'created_at': novel.created_at.isoformat()
    } for novel in novels])

@app.route('/api/novels/<int:novel_id>/chapters', methods=['GET'])
@app.route('/api/novels/<string:novel_title>/chapters', methods=['GET'])
def get_chapters(novel_id=None, novel_title=None):
    """根据小说ID或标题获取目录"""
    if novel_id:
        novel = Novel.query.get(novel_id)
    elif novel_title:
        novel = Novel.query.filter_by(title=novel_title).first()
    
    if not novel:
        return jsonify({'error': '小说不存在'}), 404
    
    chapters = Chapter.query.filter_by(novel_id=novel.id).order_by(Chapter.order).all()
    return jsonify([{
        'id': chapter.id,
        'title': chapter.title,
        'order': chapter.order
    } for chapter in chapters])

@app.route('/api/chapters/<int:chapter_id>', methods=['GET'])
def get_chapter_content(chapter_id):
    """根据章节ID获取内容"""
    chapter = Chapter.query.get(chapter_id)
    if not chapter:
        return jsonify({'error': '章节不存在'}), 404
    
    return jsonify({
        'id': chapter.id,
        'title': chapter.title,
        'novel_title': chapter.novel.title,
        'content': chapter.content
    })

if __name__ == '__main__':
    app.run(debug=True)

html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>小说爬虫服务</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
        }
        .form-group {
            margin-bottom: 15px;
        }
        input[type="text"] {
            width: 100%;
            padding: 8px;
            box-sizing: border-box;
        }
        button {
            padding: 8px 15px;
            background-color: #4CAF50;
            color: white;
            border: none;
            cursor: pointer;
        }
        .message {
            color: green;
            margin-top: 10px;
        }
        .error {
            color: red;
            margin-top: 10px;
        }
    </style>
</head>
<body>
    <h1>小说爬虫服务</h1>
    <form method="POST">
        <div class="form-group">
            <label for="novel_url">输入小说目录页URL:</label>
            <input type="text" id="novel_url" name="novel_url" 
                   placeholder="例如: https://www.biqvkk.cc/10_10864/4029000.html" required>
        </div>
        <button type="submit">开始爬取</button>
    </form>
    
    {% if message %}
    <div class="message">{{ message }}</div>
    {% endif %}
    
    {% if error %}
    <div class="error">{{ error }}</div>
    {% endif %}
    
    <h2>API接口说明</h2>
    <ul>
        <li>获取所有小说: GET /api/novels</li>
        <li>获取小说目录: GET /api/novels/&lt;id&gt;/chapters 或 /api/novels/&lt;title&gt;/chapters</li>
        <li>获取章节内容: GET /api/chapters/&lt;id&gt;</li>
    </ul>
</body>
</html>

flask==2.0.1
flask-sqlalchemy==2.5.1
requests==2.26.0
beautifulsoup4==4.9.3
lxml==4.6.3

bash
pip install -r requirements.txt

bash
python app.py
