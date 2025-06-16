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
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///novels.db'  # SQLite数据库
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# 定义数据库模型 - 小说目录表
class NovelCatalog(db.Model):
    __tablename__ = 'novel_catalog'
    id = db.Column(db.Integer, primary_key=True)
    novel_name = db.Column(db.String(100), nullable=False)  # 小说名称
    chapter_id = db.Column(db.String(50), nullable=False)  # 章节ID
    chapter_title = db.Column(db.String(200), nullable=False)  # 章节标题
    chapter_url = db.Column(db.String(500), nullable=False)  # 章节URL
    novel_url = db.Column(db.String(500), nullable=False)  # 小说目录页URL
    
    def to_dict(self):
        return {
            'id': self.id,
            'novel_name': self.novel_name,
            'chapter_id': self.chapter_id,
            'chapter_title': self.chapter_title,
            'chapter_url': self.chapter_url,
            'novel_url': self.novel_url
        }

# 定义数据库模型 - 小说内容表
class NovelContent(db.Model):
    __tablename__ = 'novel_content'
    id = db.Column(db.Integer, primary_key=True)
    chapter_id = db.Column(db.String(50), nullable=False)  # 章节ID
    content = db.Column(db.Text, nullable=False)  # 章节内容
    novel_name = db.Column(db.String(100), nullable=False)  # 小说名称
    
    def to_dict(self):
        return {
            'id': self.id,
            'chapter_id': self.chapter_id,
            'content': self.content,
            'novel_name': self.novel_name
        }

# 创建数据库表
with app.app_context():
    db.create_all()

# 请求头设置
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

# 线程池 - 12线程
THREAD_POOL = ThreadPoolExecutor(max_workers=12)

def clean_content(content):
    """清理小说内容，去除广告和非正文内容"""
    # 去除常见的广告标签
    patterns = [
        r'<div class="ads.*?</div>',
        r'<script.*?</script>',
        r'<a href=.*?</a>',
        r'<p>.*?请收藏.*?</p>',
        r'<p>.*?推荐.*?</p>',
        r'<p>.*?求.*?</p>',
        r'<p>.*?本章未完.*?</p>',
        r'<p>.*?继续阅读.*?</p>',
        r'<p>.*?记住网址.*?</p>',
        r'<p>.*?biq.*?</p>',
        r'<p>.*?笔趣.*?</p>',
        r'<p>.*?\(\)',
    ]
    
    for pattern in patterns:
        content = re.sub(pattern, '', content, flags=re.IGNORECASE | re.DOTALL)
    
    # 去除多余的空行
    content = re.sub(r'\n{3,}', '\n\n', content)
    return content.strip()

def get_novel_info(url):
    """获取小说目录信息"""
    try:
        response = requests.get(url, headers=HEADERS)
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 获取小说名称
        novel_name = soup.find('h1').text.strip()
        
        # 获取所有章节链接
        chapters = []
        chapter_list = soup.find('div', id='list')
        if not chapter_list:
            chapter_list = soup.find('div', class_='listmain')
        
        for a in chapter_list.find_all('a'):
            if 'href' in a.attrs and a.text.strip():
                chapter_url = urljoin(url, a['href'])
                chapter_title = a.text.strip()
                chapter_id = chapter_url.split('/')[-1].split('.')[0]
                
                chapters.append({
                    'chapter_id': chapter_id,
                    'chapter_title': chapter_title,
                    'chapter_url': chapter_url,
                    'novel_name': novel_name,
                    'novel_url': url
                })
        
        return novel_name, chapters
    except Exception as e:
        print(f"获取小说目录信息失败: {e}")
        return None, []

def fetch_chapter_content(chapter_info):
    """获取章节内容"""
    try:
        response = requests.get(chapter_info['chapter_url'], headers=HEADERS)
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 查找内容区域
        content_div = soup.find('div', id='content')
        if not content_div:
            content_div = soup.find('div', class_='content')
        
        if content_div:
            # 清理内容
            content = str(content_div)
            content = clean_content(content)
            
            # 保存到数据库
            with app.app_context():
                # 检查是否已存在
                existing = NovelContent.query.filter_by(
                    chapter_id=chapter_info['chapter_id'],
                    novel_name=chapter_info['novel_name']
                ).first()
                
                if not existing:
                    novel_content = NovelContent(
                        chapter_id=chapter_info['chapter_id'],
                        content=content,
                        novel_name=chapter_info['novel_name']
                    )
                    db.session.add(novel_content)
                    db.session.commit()
            
            return True
        return False
    except Exception as e:
        print(f"获取章节内容失败: {e}")
        return False

def save_catalog_to_db(novel_name, chapters, novel_url):
    """保存目录信息到数据库"""
    with app.app_context():
        # 先删除旧的目录信息
        NovelCatalog.query.filter_by(novel_name=novel_name).delete()
        
        # 添加新的目录信息
        for chapter in chapters:
            catalog = NovelCatalog(
                novel_name=novel_name,
                chapter_id=chapter['chapter_id'],
                chapter_title=chapter['chapter_title'],
                chapter_url=chapter['chapter_url'],
                novel_url=novel_url
            )
            db.session.add(catalog)
        
        db.session.commit()

def crawl_novel(url):
    """爬取小说"""
    start_time = time.time()
    
    # 获取小说目录信息
    novel_name, chapters = get_novel_info(url)
    if not novel_name or not chapters:
        return False, "获取小说目录失败"
    
    # 保存目录到数据库
    save_catalog_to_db(novel_name, chapters, url)
    
    # 使用线程池获取所有章节内容
    futures = []
    for chapter in chapters:
        futures.append(THREAD_POOL.submit(fetch_chapter_content, chapter))
    
    # 等待所有线程完成
    for future in futures:
        future.result()
    
    end_time = time.time()
    return True, f"爬取完成，耗时 {end_time - start_time:.2f} 秒"

@app.route('/')
def index():
    """首页"""
    return render_template('index.html')

@app.route('/api/novels', methods=['GET'])
def get_novels():
    """获取小说列表接口"""
    novels = db.session.query(NovelCatalog.novel_name, NovelCatalog.novel_url).distinct().all()
    novel_list = [{'name': novel[0], 'url': novel[1]} for novel in novels]
    return jsonify({'code': 0, 'data': novel_list})

@app.route('/api/catalog', methods=['GET'])
def get_catalog():
    """获取小说目录接口"""
    novel_name = request.args.get('novel_name')
    novel_id = request.args.get('novel_id')
    
    if not novel_name and not novel_id:
        return jsonify({'code': 1, 'msg': '参数错误'})
    
    query = NovelCatalog.query
    if novel_name:
        query = query.filter_by(novel_name=novel_name)
    if novel_id:
        query = query.filter_by(id=novel_id)
    
    catalogs = query.order_by(NovelCatalog.id).all()
    return jsonify({'code': 0, 'data': [catalog.to_dict() for catalog in catalogs]})

@app.route('/api/content', methods=['GET'])
def get_content():
    """获取章节内容接口"""
    chapter_id = request.args.get('chapter_id')
    if not chapter_id:
        return jsonify({'code': 1, 'msg': '参数错误'})
    
    content = NovelContent.query.filter_by(chapter_id=chapter_id).first()
    if not content:
        return jsonify({'code': 2, 'msg': '章节不存在'})
    
    return jsonify({'code': 0, 'data': content.to_dict()})

@app.route('/api/crawl', methods=['POST'])
def start_crawl():
    """开始爬取小说接口"""
    url = request.form.get('url')
    novel_name = request.form.get('novel_name')
    
    if not url:
        return jsonify({'code': 1, 'msg': 'URL不能为空'})
    
    # 检查是否已存在
    if novel_name and NovelCatalog.query.filter_by(novel_name=novel_name).first():
        return jsonify({'code': 2, 'msg': '小说已存在'})
    
    # 启动爬虫线程
    threading.Thread(target=crawl_novel, args=(url,)).start()
    
    return jsonify({'code': 0, 'msg': '开始爬取'})

if __name__ == '__main__':
    # 创建模板目录
    if not os.path.exists('templates'):
        os.makedirs('templates')
    
    # 创建默认的index.html模板
    if not os.path.exists('templates/index.html'):
        with open('templates/index.html', 'w', encoding='utf-8') as f:
            f.write('''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>小说爬虫服务</title>
    <style>
        body { font-family: Arial, sans-serif; max-width: 1000px; margin: 0 auto; padding: 20px; }
        .container { margin-top: 30px; }
        .form-group { margin-bottom: 15px; }
        input[type="text"] { width: 100%; padding: 8px; box-sizing: border-box; }
        button { padding: 8px 15px; background: #007bff; color: white; border: none; cursor: pointer; }
        button:hover { background: #0056b3; }
        .novel-list { margin-top: 20px; }
        .novel-item { padding: 10px; border-bottom: 1px solid #eee; }
        .novel-item:hover { background: #f5f5f5; }
        .chapter-list { margin-top: 20px; }
        .chapter-item { padding: 8px; border-bottom: 1px dashed #ddd; }
        .content { margin-top: 20px; white-space: pre-line; line-height: 1.6; }
    </style>
</head>
<body>
    <h1>小说爬虫服务</h1>
    
    <div class="container">
        <h2>爬取新小说</h2>
        <div class="form-group">
            <input type="text" id="novelUrl" placeholder="输入小说目录页URL，例如：https://www.biqvkk.cc/10_10864/4029000.html">
        </div>
        <button onclick="startCrawl()">开始爬取</button>
        
        <h2>小说列表</h2>
        <div class="novel-list" id="novelList"></div>
        
        <div class="chapter-list" id="chapterList" style="display: none;">
            <h3>目录</h3>
            <div id="chapters"></div>
        </div>
        
        <div class="content" id="content" style="display: none;">
            <h3>内容</h3>
            <div id="chapterContent"></div>
        </div>
    </div>
    
    <script>
        // 加载小说列表
        function loadNovels() {
            fetch('/api/novels')
                .then(response => response.json())
                .then(data => {
                    if (data.code === 0) {
                        const novelList = document.getElementById('novelList');
                        novelList.innerHTML = '';
                        
                        if (data.data.length === 0) {
                            novelList.innerHTML = '<p>暂无小说</p>';
                            return;
                        }
                        
                        data.data.forEach(novel => {
                            const div = document.createElement('div');
                            div.className = 'novel-item';
                            div.innerHTML = `<a href="#" onclick="loadChapters('${novel.name}')">${novel.name}</a>`;
                            novelList.appendChild(div);
                        });
                    }
                });
        }
        
        // 加载章节列表
        function loadChapters(novelName) {
            fetch(`/api/catalog?novel_name=${encodeURIComponent(novelName)}`)
                .then(response => response.json())
                .then(data => {
                    if (data.code === 0) {
                        const chapterList = document.getElementById('chapterList');
                        const chapters = document.getElementById('chapters');
                        chapters.innerHTML = '';
                        
                        data.data.forEach(chapter => {
                            const div = document.createElement('div');
                            div.className = 'chapter-item';
                            div.innerHTML = `<a href="#" onclick="loadContent('${chapter.chapter_id}')">${chapter.chapter_title}</a>`;
                            chapters.appendChild(div);
                        });
                        
                        chapterList.style.display = 'block';
                        document.getElementById('content').style.display = 'none';
                    }
                });
        }
        
        // 加载章节内容
        function loadContent(chapterId) {
            fetch(`/api/content?chapter_id=${chapterId}`)
                .then(response => response.json())
                .then(data => {
                    if (data.code === 0) {
                        const contentDiv = document.getElementById('content');
                        const chapterContent = document.getElementById('chapterContent');
                        chapterContent.innerHTML = data.data.content;
                        contentDiv.style.display = 'block';
                    }
                });
        }
        
        // 开始爬取
        function startCrawl() {
            const url = document.getElementById('novelUrl').value.trim();
            if (!url) {
                alert('请输入URL');
                return;
            }
            
            fetch('/api/crawl', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                body: `url=${encodeURIComponent(url)}`
            })
            .then(response => response.json())
            .then(data => {
                if (data.code === 0) {
                    alert('开始爬取，请稍后刷新查看');
                } else {
                    alert(data.msg);
                }
            });
        }
        
        // 页面加载时获取小说列表
        window.onload = loadNovels;
    </script>
</body>
</html>''')
    
    app.run(debug=True)
