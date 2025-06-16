novel_crawler/
├── app.py                # Flask主程序
├── models.py             # 数据库模型
├── crawler.py            # 爬虫逻辑
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
    title = db.Column(db.String(100), unique=True, nullable=False)  # 小说标题
    source_url = db.Column(db.String(255), nullable=False)         # 来源URL
    created_at = db.Column(db.DateTime, default=datetime.now)      # 创建时间
    
    # 一对多关系：一本小说有多个章节
    chapters = db.relationship('Chapter', backref='novel', lazy=True)

class Chapter(db.Model):
    """小说章节表"""
    __tablename__ = 'chapters'
    
    id = db.Column(db.Integer, primary_key=True)
    novel_id = db.Column(db.Integer, db.ForeignKey('novels.id'), nullable=False)  # 关联小说ID
    title = db.Column(db.String(100), nullable=False)              # 章节标题
    url = db.Column(db.String(255), nullable=False)                # 章节URL
    order = db.Column(db.Integer, nullable=False)                  # 章节顺序
    
    # 一对一关系：一个章节对应一个内容
    content = db.relationship('ChapterContent', uselist=False, backref='chapter')

class ChapterContent(db.Model):
    """章节内容表"""
    __tablename__ = 'chapter_contents'
    
    id = db.Column(db.Integer, primary_key=True)
    chapter_id = db.Column(db.Integer, db.ForeignKey('chapters.id'), nullable=False)  # 关联章节ID
    content = db.Column(db.Text, nullable=False)                   # 章节正文内容

import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
import re
from urllib.parse import urljoin

class NovelCrawler:
    def __init__(self, base_url):
        self.base_url = base_url
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
    
    def get_soup(self, url):
        """获取页面并解析为BeautifulSoup对象"""
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            response.encoding = 'utf-8'
            return BeautifulSoup(response.text, 'html.parser')
        except Exception as e:
            print(f"Error fetching {url}: {e}")
            return None
    
    def extract_novel_info(self, url):
        """从目录页提取小说信息"""
        soup = self.get_soup(url)
        if not soup:
            return None
        
        # 提取小说标题
        title = soup.find('h1').text.strip() if soup.find('h1') else '未知标题'
        
        # 提取章节列表
        chapters = []
        chapter_elements = soup.select('#list dd a')  # 根据实际网站结构调整选择器
        for idx, a in enumerate(chapter_elements, start=1):
            chapter_url = urljoin(self.base_url, a['href'])
            chapters.append({
                'title': a.text.strip(),
                'url': chapter_url,
                'order': idx
            })
        
        return {
            'title': title,
            'source_url': url,
            'chapters': chapters
        }
    
    def clean_content(self, text):
        """清理章节内容，去除广告和非正文内容"""
        # 去除常见的广告标签
        text = re.sub(r'<div class="ad.*?</div>', '', text, flags=re.DOTALL)
        text = re.sub(r'<script.*?</script>', '', text, flags=re.DOTALL)
        text = re.sub(r'<a href=.*?</a>', '', text, flags=re.DOTALL)
        
        # 去除多余的空格和换行
        text = re.sub(r'\s+', '\n', text).strip()
        
        return text
    
    def fetch_chapter_content(self, chapter):
        """获取单个章节内容"""
        soup = self.get_soup(chapter['url'])
        if not soup:
            return None
        
        # 提取正文内容 - 根据实际网站结构调整选择器
        content_div = soup.find('div', id='content')
        if not content_div:
            return None
        
        # 清理内容
        content = self.clean_content(str(content_div))
        return {
            'chapter_id': chapter['id'],
            'content': content
        }
    
    def crawl_novel(self, url):
        """爬取整本小说"""
        # 1. 获取小说基本信息
        novel_info = self.extract_novel_info(url)
        if not novel_info:
            return None
        
        # 2. 多线程爬取所有章节内容
        chapters_with_content = []
        with ThreadPoolExecutor(max_workers=12) as executor:
            # 提交所有章节任务
            futures = [executor.submit(self.fetch_chapter_content, chapter) 
                      for chapter in novel_info['chapters']]
            
            # 收集结果
            for future in as_completed(futures):
                result = future.result()
                if result:
                    chapters_with_content.append(result)
        
        # 将内容关联到章节
        for chapter in novel_info['chapters']:
            for content in chapters_with_content:
                if content['chapter_id'] == chapter['id']:
                    chapter['content'] = content['content']
                    break
        
        return novel_info

from flask import Flask, render_template, request, jsonify
from models import db, Novel, Chapter, ChapterContent
from crawler import NovelCrawler
import os
from datetime import datetime

app = Flask(__name__)

# 配置数据库
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'novels.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# 初始化数据库
db.init_app(app)
with app.app_context():
    db.create_all()

@app.route('/')
def index():
    """首页，展示小说搜索界面"""
    return render_template('index.html')

@app.route('/api/novels', methods=['GET', 'POST'])
def handle_novels():
    """小说列表接口"""
    if request.method == 'GET':
        # 获取所有小说列表
        novels = Novel.query.all()
        return jsonify([{
            'id': novel.id,
            'title': novel.title,
            'source_url': novel.source_url,
            'created_at': novel.created_at.strftime('%Y-%m-%d %H:%M:%S')
        } for novel in novels])
    
    elif request.method == 'POST':
        # 添加新小说
        data = request.json
        url = data.get('url')
        
        if not url:
            return jsonify({'error': 'URL is required'}), 400
        
        # 检查是否已存在
        existing = Novel.query.filter_by(source_url=url).first()
        if existing:
            return jsonify({
                'message': 'Novel already exists',
                'novel_id': existing.id
            }), 200
        
        # 爬取小说
        crawler = NovelCrawler(url)
        novel_info = crawler.crawl_novel(url)
        if not novel_info:
            return jsonify({'error': 'Failed to crawl novel'}), 500
        
        # 保存到数据库
        novel = Novel(
            title=novel_info['title'],
            source_url=novel_info['source_url']
        )
        db.session.add(novel)
        db.session.commit()
        
        # 保存章节
        for chapter_data in novel_info['chapters']:
            chapter = Chapter(
                novel_id=novel.id,
                title=chapter_data['title'],
                url=chapter_data['url'],
                order=chapter_data['order']
            )
            db.session.add(chapter)
            db.session.commit()
            
            # 保存章节内容
            if 'content' in chapter_data:
                content = ChapterContent(
                    chapter_id=chapter.id,
                    content=chapter_data['content']
                )
                db.session.add(content)
        
        db.session.commit()
        
        return jsonify({
            'message': 'Novel added successfully',
            'novel_id': novel.id
        }), 201

@app.route('/api/novels/<int:novel_id>/chapters', methods=['GET'])
def get_chapters(novel_id):
    """获取小说章节列表"""
    novel = Novel.query.get_or_404(novel_id)
    chapters = Chapter.query.filter_by(novel_id=novel_id).order_by(Chapter.order).all()
    
    return jsonify([{
        'id': chapter.id,
        'title': chapter.title,
        'order': chapter.order
    } for chapter in chapters])

@app.route('/api/chapters/<int:chapter_id>/content', methods=['GET'])
def get_chapter_content(chapter_id):
    """获取章节内容"""
    chapter = Chapter.query.get_or_404(chapter_id)
    content = ChapterContent.query.filter_by(chapter_id=chapter_id).first()
    
    if not content:
        return jsonify({'error': 'Content not found'}), 404
    
    return jsonify({
        'chapter_id': chapter.id,
        'title': chapter.title,
        'content': content.content
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
        .container {
            display: flex;
            flex-direction: column;
            gap: 20px;
        }
        .form-group {
            display: flex;
            gap: 10px;
        }
        input {
            flex: 1;
            padding: 8px;
        }
        button {
            padding: 8px 16px;
            background: #007bff;
            color: white;
            border: none;
            cursor: pointer;
        }
        button:hover {
            background: #0056b3;
        }
        #result {
            margin-top: 20px;
        }
        .novel-list {
            margin-top: 20px;
        }
        .chapter-list {
            margin-top: 10px;
            padding-left: 20px;
        }
        .content {
            white-space: pre-line;
            margin-top: 10px;
            padding: 10px;
            border: 1px solid #ddd;
            background: #f9f9f9;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>小说爬虫服务</h1>
        
        <div class="form-group">
            <input type="text" id="novelUrl" placeholder="输入小说目录页URL，例如：https://www.biqvkk.cc/10_10864/4029000.html">
            <button onclick="addNovel()">爬取小说</button>
        </div>
        
        <div id="result"></div>
        
        <div class="novel-list">
            <h2>小说列表</h2>
            <div id="novels"></div>
        </div>
    </div>

    <script>
        // 加载小说列表
        fetch('/api/novels')
            .then(response => response.json())
            .then(data => displayNovels(data));
        
        function displayNovels(novels) {
            const novelsDiv = document.getElementById('novels');
            novelsDiv.innerHTML = '';
            
            if (novels.length === 0) {
                novelsDiv.innerHTML = '<p>暂无小说</p>';
                return;
            }
            
            novels.forEach(novel => {
                const novelDiv = document.createElement('div');
                novelDiv.innerHTML = `
                    <h3>
                        <a href="#" onclick="loadChapters(${novel.id})">${novel.title}</a>
                        <small>${new Date(novel.created_at).toLocaleString()}</small>
                    </h3>
                    <div id="chapters-${novel.id}" class="chapter-list"></div>
                `;
                novelsDiv.appendChild(novelDiv);
            });
        }
        
        function loadChapters(novelId) {
            fetch(`/api/novels/${novelId}/chapters`)
                .then(response => response.json())
                .then(chapters => {
                    const chaptersDiv = document.getElementById(`chapters-${novelId}`);
                    chaptersDiv.innerHTML = '';
                    
                    const list = document.createElement('ul');
                    chapters.forEach(chapter => {
                        const item = document.createElement('li');
                        item.innerHTML = `<a href="#" onclick="loadContent(${chapter.id})">${chapter.title}</a>`;
                        list.appendChild(item);
                    });
                    chaptersDiv.appendChild(list);
                });
        }
        
        function loadContent(chapterId) {
            fetch(`/api/chapters/${chapterId}/content`)
                .then(response => response.json())
                .then(data => {
                    const resultDiv = document.getElementById('result');
                    resultDiv.innerHTML = `
                        <h2>${data.title}</h2>
                        <div class="content">${data.content}</div>
                    `;
                });
        }
        
        function addNovel() {
            const url = document.getElementById('novelUrl').value.trim();
            if (!url) {
                alert('请输入小说目录页URL');
                return;
            }
            
            fetch('/api/novels', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ url })
            })
            .then(response => response.json())
            .then(data => {
                if (data.error) {
                    alert(data.error);
                } else {
                    alert(`小说添加成功，ID: ${data.novel_id}`);
                    location.reload(); // 刷新页面
                }
            })
            .catch(error => {
                console.error('Error:', error);
                alert('添加小说失败');
            });
        }
    </script>
</body>
</html>

flask==2.0.1
flask-sqlalchemy==2.5.1
requests==2.26.0
beautifulsoup4==4.10.0
lxml==4.6.3

bash
pip install -r requirements.txt

bash
python app.py
