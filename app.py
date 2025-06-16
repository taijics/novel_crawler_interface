import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, render_template, request, jsonify
from flask_sqlalchemy import SQLAlchemy
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

app = Flask(__name__)

# 配置数据库
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'novels.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# 定义数据库模型

# 小说目录表
class Novel(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), unique=True, nullable=False)  # 小说名称
    source_url = db.Column(db.String(500), nullable=False)  # 小说源URL
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())  # 创建时间
    
    # 定义与章节的一对多关系
    chapters = db.relationship('Chapter', backref='novel', lazy=True)

# 章节内容表
class Chapter(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)  # 章节标题
    url = db.Column(db.String(500), nullable=False)  # 章节URL
    content = db.Column(db.Text, nullable=False)  # 章节内容
    novel_id = db.Column(db.Integer, db.ForeignKey('novel.id'), nullable=False)  # 关联的小说ID
    order_num = db.Column(db.Integer, nullable=False)  # 章节顺序号
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())  # 创建时间

# 创建数据库表
with app.app_context():
    db.create_all()

# 爬虫相关函数

def clean_content(text):
    """清理章节内容，去除广告和非正文内容"""
    # 去除常见的广告标签
    patterns = [
        r'[\s\S]*?biq.*?ge.*?com[\s\S]*?',
        r'请收藏.*?网址',
        r'记住.*?网址',
        r'\(.*?\)',
        r'\[.*?\]',
        r'【.*?】',
        r'<.*?>',
        r'&nbsp;',
        r'本章未完.*?',
        r'继续阅读',
        r'PS:.*?',
        r'求.*?票',
        r'推.*?书',
        r'新书.*?',
        r'推荐.*?',
        r'\(未完待续.*?\)',
    ]
    
    for pattern in patterns:
        text = re.sub(pattern, '', text)
    
    # 去除多余的空格和换行
    text = re.sub(r'\s+', '\n', text).strip()
    
    return text

def get_chapter_content(url):
    """获取章节内容"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 查找章节内容 - 根据网站结构调整
        content_div = soup.find('div', id='content')
        if content_div:
            content = content_div.get_text()
            return clean_content(content)
        else:
            return "内容获取失败"
    except Exception as e:
        print(f"获取章节内容出错: {e}")
        return "内容获取失败"

def crawl_novel(url):
    """爬取小说目录和内容"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 获取小说标题
        title_tag = soup.find('h1')
        if title_tag:
            title = title_tag.get_text().strip()
        else:
            title = "未知小说"
        
        # 检查小说是否已存在
        existing_novel = Novel.query.filter_by(title=title).first()
        if existing_novel:
            return {"status": "exists", "novel_id": existing_novel.id}
        
        # 创建小说记录
        novel = Novel(title=title, source_url=url)
        db.session.add(novel)
        db.session.commit()
        
        # 获取章节列表
        chapter_links = []
        list_div = soup.find('div', id='list')
        if list_div:
            chapters = list_div.find_all('a')
            for idx, chapter in enumerate(chapters, start=1):
                chapter_url = urljoin(url, chapter['href'])
                chapter_title = chapter.get_text().strip()
                chapter_links.append((idx, chapter_title, chapter_url))
        
        # 使用多线程爬取章节内容
        def process_chapter(chapter_data):
            order_num, chapter_title, chapter_url = chapter_data
            content = get_chapter_content(chapter_url)
            chapter = Chapter(
                title=chapter_title,
                url=chapter_url,
                content=content,
                novel_id=novel.id,
                order_num=order_num
            )
            db.session.add(chapter)
        
        # 使用12个线程
        with ThreadPoolExecutor(max_workers=12) as executor:
            executor.map(process_chapter, chapter_links)
        
        db.session.commit()
        
        return {"status": "success", "novel_id": novel.id}
    
    except Exception as e:
        print(f"爬取小说出错: {e}")
        db.session.rollback()
        return {"status": "error", "message": str(e)}

# 网页路由

@app.route('/')
def index():
    """首页，显示小说列表和搜索框"""
    novels = Novel.query.order_by(Novel.created_at.desc()).all()
    return render_template('index.html', novels=novels)

@app.route('/crawl', methods=['POST'])
def crawl():
    """处理爬取请求"""
    url = request.form.get('url')
    if not url:
        return jsonify({"status": "error", "message": "URL不能为空"})
    
    # 启动爬虫线程
    def crawl_task():
        crawl_novel(url)
    
    thread = threading.Thread(target=crawl_task)
    thread.start()
    
    return jsonify({"status": "processing", "message": "爬取任务已开始，请稍后刷新页面查看结果"})

# API接口

@app.route('/api/novels', methods=['GET'])
def get_novels():
    """获取所有小说列表"""
    novels = Novel.query.order_by(Novel.title).all()
    result = [{
        "id": novel.id,
        "title": novel.title,
        "source_url": novel.source_url,
        "created_at": novel.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        "chapter_count": len(novel.chapters)
    } for novel in novels]
    return jsonify({"status": "success", "data": result})

@app.route('/api/novel/<novel_id_or_name>', methods=['GET'])
def get_novel(novel_id_or_name):
    """根据小说ID或名称获取目录"""
    # 先尝试按ID查找
    if novel_id_or_name.isdigit():
        novel = Novel.query.get(int(novel_id_or_name))
    else:
        # 按名称查找
        novel = Novel.query.filter_by(title=novel_id_or_name).first()
    
    if not novel:
        return jsonify({"status": "error", "message": "小说不存在"})
    
    chapters = Chapter.query.filter_by(novel_id=novel.id).order_by(Chapter.order_num).all()
    result = [{
        "id": chapter.id,
        "title": chapter.title,
        "order_num": chapter.order_num,
        "url": chapter.url
    } for chapter in chapters]
    
    return jsonify({
        "status": "success",
        "novel": {
            "id": novel.id,
            "title": novel.title,
            "source_url": novel.source_url
        },
        "chapters": result
    })

@app.route('/api/chapter/<int:chapter_id>', methods=['GET'])
def get_chapter(chapter_id):
    """根据章节ID获取内容"""
    chapter = Chapter.query.get(chapter_id)
    if not chapter:
        return jsonify({"status": "error", "message": "章节不存在"})
    
    return jsonify({
        "status": "success",
        "chapter": {
            "id": chapter.id,
            "title": chapter.title,
            "novel_id": chapter.novel_id,
            "novel_title": chapter.novel.title,
            "content": chapter.content,
            "order_num": chapter.order_num
        }
    })

# 模板文件

@app.route('/novel/<int:novel_id>')
def novel_detail(novel_id):
    """小说详情页"""
    novel = Novel.query.get_or_404(novel_id)
    chapters = Chapter.query.filter_by(novel_id=novel.id).order_by(Chapter.order_num).all()
    return render_template('novel_detail.html', novel=novel, chapters=chapters)

@app.route('/chapter/<int:chapter_id>')
def chapter_detail(chapter_id):
    """章节详情页"""
    chapter = Chapter.query.get_or_404(chapter_id)
    return render_template('chapter_detail.html', chapter=chapter)

# 创建模板目录
templates_dir = os.path.join(basedir, 'templates')
if not os.path.exists(templates_dir):
    os.makedirs(templates_dir)

# 创建HTML模板文件
index_html = """
<!DOCTYPE html>
<html>
<head>
    <title>小说爬虫服务</title>
    <style>
        body { font-family: Arial, sans-serif; max-width: 1200px; margin: 0 auto; padding: 20px; }
        h1 { text-align: center; }
        .search-box { margin: 20px 0; text-align: center; }
        input[type="text"] { width: 60%; padding: 8px; }
        button { padding: 8px 16px; }
        .novel-list { margin-top: 30px; }
        .novel-item { border: 1px solid #ddd; padding: 15px; margin-bottom: 15px; border-radius: 5px; }
        .novel-title { font-size: 1.2em; font-weight: bold; margin-bottom: 5px; }
        .novel-meta { color: #666; font-size: 0.9em; margin-bottom: 10px; }
        .novel-link { color: #06c; text-decoration: none; }
        .status { padding: 5px 10px; border-radius: 3px; }
        .status-processing { background-color: #ffeb3b; }
        .status-success { background-color: #4caf50; color: white; }
        .status-error { background-color: #f44336; color: white; }
    </style>
</head>
<body>
    <h1>小说爬虫服务</h1>
    
    <div class="search-box">
        <form id="crawlForm">
            <input type="text" name="url" placeholder="输入小说目录页URL，例如：https://www.biqvkk.cc/10_10864/4029000.html" required>
            <button type="submit">开始爬取</button>
        </form>
        <div id="message" style="margin-top: 10px;"></div>
    </div>
    
    <div class="novel-list">
        <h2>已爬取的小说列表</h2>
        {% for novel in novels %}
        <div class="novel-item">
            <div class="novel-title">
                <a href="/novel/{{ novel.id }}" class="novel-link">{{ novel.title }}</a>
            </div>
            <div class="novel-meta">
                章节数: {{ novel.chapters|length }} | 创建时间: {{ novel.created_at.strftime('%Y-%m-%d %H:%M') }}
            </div>
            <a href="/api/novel/{{ novel.id }}" target="_blank">查看API数据</a>
        </div>
        {% else %}
        <p>暂无小说数据</p>
        {% endfor %}
    </div>
    
    <script>
        document.getElementById('crawlForm').addEventListener('submit', function(e) {
            e.preventDefault();
            const formData = new FormData(this);
            const messageDiv = document.getElementById('message');
            messageDiv.innerHTML = '<span class="status status-processing">处理中...</span>';
            
            fetch('/crawl', {
                method: 'POST',
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                if (data.status === 'processing') {
                    messageDiv.innerHTML = `<span class="status status-processing">${data.message}</span>`;
                    setTimeout(() => {
                        window.location.reload();
                    }, 3000);
                } else if (data.status === 'error') {
                    messageDiv.innerHTML = `<span class="status status-error">${data.message}</span>`;
                }
            })
            .catch(error => {
                messageDiv.innerHTML = `<span class="status status-error">请求失败: ${error}</span>`;
            });
        });
    </script>
</body>
</html>
"""

novel_detail_html = """
<!DOCTYPE html>
<html>
<head>
    <title>{{ novel.title }} - 目录</title>
    <style>
        body { font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }
        h1 { text-align: center; }
        .back-link { display: block; margin-bottom: 20px; }
        .chapter-list { list-style-type: none; padding: 0; }
        .chapter-item { padding: 8px 0; border-bottom: 1px solid #eee; }
        .chapter-link { color: #06c; text-decoration: none; }
        .chapter-link:hover { text-decoration: underline; }
    </style>
</head>
<body>
    <a href="/" class="back-link">← 返回首页</a>
    <h1>{{ novel.title }}</h1>
    
    <ul class="chapter-list">
        {% for chapter in chapters %}
        <li class="chapter-item">
            <a href="/chapter/{{ chapter.id }}" class="chapter-link">{{ chapter.order_num }}. {{ chapter.title }}</a>
        </li>
        {% endfor %}
    </ul>
</body>
</html>
"""

chapter_detail_html = """
<!DOCTYPE html>
<html>
<head>
    <title>{{ chapter.title }} - {{ chapter.novel.title }}</title>
    <style>
        body { font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }
        h1 { text-align: center; font-size: 1.5em; }
        h2 { text-align: center; font-size: 1.2em; color: #666; margin-top: 0; }
        .nav-links { display: flex; justify-content: space-between; margin: 20px 0; }
        .nav-link { color: #06c; text-decoration: none; }
        .content { line-height: 1.8; white-space: pre-line; }
    </style>
</head>
<body>
    <div class="nav-links">
        <a href="/novel/{{ chapter.novel.id }}" class="nav-link">← 返回目录</a>
    </div>
    
    <h1>{{ chapter.title }}</h1>
    <h2>{{ chapter.novel.title }}</h2>
    
    <div class="content">
        {{ chapter.content }}
    </div>
    
    <div class="nav-links">
        <a href="/novel/{{ chapter.novel.id }}" class="nav-link">← 返回目录</a>
    </div>
</body>
</html>
"""

# 写入模板文件
with open(os.path.join(templates_dir, 'index.html'), 'w', encoding='utf-8') as f:
    f.write(index_html)

with open(os.path.join(templates_dir, 'novel_detail.html'), 'w', encoding='utf-8') as f:
    f.write(novel_detail_html)

with open(os.path.join(templates_dir, 'chapter_detail.html'), 'w', encoding='utf-8') as f:
    f.write(chapter_detail_html)

if __name__ == '__main__':
    app.run(debug=True)
