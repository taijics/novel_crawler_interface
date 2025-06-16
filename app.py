import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, render_template, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from bs4 import BeautifulSoup
import requests

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///novels.db'  # SQLite数据库
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# 定义小说目录模型
class NovelCatalog(db.Model):
    __tablename__ = 'novel_catalog'
    id = db.Column(db.Integer, primary_key=True)
    novel_id = db.Column(db.String(50), nullable=False)  # 小说ID
    novel_name = db.Column(db.String(100), nullable=False)  # 小说名称
    chapter_id = db.Column(db.String(50), nullable=False)  # 章节ID
    chapter_title = db.Column(db.String(200), nullable=False)  # 章节标题
    chapter_url = db.Column(db.String(500), nullable=False)  # 章节URL
    
    def to_dict(self):
        return {
            'id': self.id,
            'novel_id': self.novel_id,
            'novel_name': self.novel_name,
            'chapter_id': self.chapter_id,
            'chapter_title': self.chapter_title,
            'chapter_url': self.chapter_url
        }

# 定义小说内容模型
class NovelContent(db.Model):
    __tablename__ = 'novel_content'
    id = db.Column(db.Integer, primary_key=True)
    chapter_id = db.Column(db.String(50), nullable=False)  # 章节ID
    content = db.Column(db.Text, nullable=False)  # 章节内容
    
    def to_dict(self):
        return {
            'id': self.id,
            'chapter_id': self.chapter_id,
            'content': self.content
        }

# 创建数据库表
with app.app_context():
    db.create_all()

# 请求头设置
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

def clean_content(content):
    """
    清理小说内容，去除广告和非正文部分
    :param content: 原始内容
    :return: 清理后的内容
    """
    # 去除常见的广告文本
    ads = [
        '请收藏本站：https://www.biqvkk.cc',
        '笔趣阁',
        '天才一秒记住本站地址',
        '最快更新！无广告！',
        '章节错误,点此报送',
        '报送后维护人员会在两分钟内校正章节内容'
    ]
    for ad in ads:
        content = content.replace(ad, '')
    
    # 使用正则表达式去除HTML标签和特殊字符
    content = re.sub(r'<[^>]+>', '', content)
    content = re.sub(r'\s+', '\n', content.strip())
    
    return content

def get_novel_info(url):
    """
    获取小说基本信息
    :param url: 小说目录页URL
    :return: 小说名称, 章节列表
    """
    try:
        response = requests.get(url, headers=HEADERS)
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 获取小说名称
        novel_name = soup.find('h1').text.strip()
        
        # 获取章节列表
        chapters = []
        chapter_list = soup.find('div', id='list')
        if chapter_list:
            for a in chapter_list.find_all('a'):
                chapter_url = a['href']
                if not chapter_url.startswith('http'):
                    chapter_url = 'https://www.biqvkk.cc' + chapter_url
                chapters.append({
                    'title': a.text.strip(),
                    'url': chapter_url,
                    'id': chapter_url.split('/')[-1].replace('.html', '')
                })
        
        return novel_name, chapters
    except Exception as e:
        print(f"获取小说信息出错: {e}")
        return None, []

def fetch_chapter_content(chapter):
    """
    获取章节内容
    :param chapter: 章节信息字典
    :return: 章节ID, 清理后的内容
    """
    try:
        response = requests.get(chapter['url'], headers=HEADERS)
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 获取正文内容
        content_div = soup.find('div', id='content')
        if content_div:
            content = content_div.get_text('\n')
            cleaned_content = clean_content(content)
            return chapter['id'], cleaned_content
        return chapter['id'], "内容获取失败"
    except Exception as e:
        print(f"获取章节内容出错: {e}")
        return chapter['id'], "内容获取失败"

def crawl_novel(url):
    """
    爬取小说并存入数据库
    :param url: 小说目录页URL
    """
    # 获取小说基本信息
    novel_name, chapters = get_novel_info(url)
    if not novel_name or not chapters:
        return False, "获取小说信息失败"
    
    # 生成小说ID (使用URL的最后一部分作为ID)
    novel_id = url.split('/')[-2]
    
    # 检查是否已经存在该小说
    existing = NovelCatalog.query.filter_by(novel_id=novel_id).first()
    if existing:
        return True, f"小说《{novel_name}》已存在"
    
    # 使用线程池获取章节内容
    chapter_contents = []
    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = [executor.submit(fetch_chapter_content, chapter) for chapter in chapters]
        for future in futures:
            chapter_id, content = future.result()
            chapter_contents.append((chapter_id, content))
    
    # 将数据存入数据库
    try:
        # 存入目录
        for chapter in chapters:
            catalog_entry = NovelCatalog(
                novel_id=novel_id,
                novel_name=novel_name,
                chapter_id=chapter['id'],
                chapter_title=chapter['title'],
                chapter_url=chapter['url']
            )
            db.session.add(catalog_entry)
        
        # 存入内容
        for chapter_id, content in chapter_contents:
            content_entry = NovelContent(
                chapter_id=chapter_id,
                content=content
            )
            db.session.add(content_entry)
        
        db.session.commit()
        return True, f"小说《{novel_name}》爬取完成，共{len(chapters)}章"
    except Exception as e:
        db.session.rollback()
        return False, f"保存数据出错: {e}"

@app.route('/')
def index():
    """首页，显示爬取界面"""
    return render_template('index.html')

@app.route('/api/crawl', methods=['POST'])
def api_crawl():
    """
    爬取小说API接口
    :param url: 小说目录页URL
    """
    url = request.form.get('url')
    if not url:
        return jsonify({'success': False, 'message': '请输入小说目录页URL'})
    
    success, message = crawl_novel(url)
    return jsonify({'success': success, 'message': message})

@app.route('/api/novels', methods=['GET'])
def api_get_novels():
    """
    获取小说列表API接口
    """
    # 获取所有不同的小说
    novels = db.session.query(
        NovelCatalog.novel_id,
        NovelCatalog.novel_name
    ).distinct().all()
    
    novel_list = [{'id': novel[0], 'name': novel[1]} for novel in novels]
    return jsonify({'success': True, 'data': novel_list})

@app.route('/api/catalog/<novel_identifier>', methods=['GET'])
def api_get_catalog(novel_identifier):
    """
    获取小说目录API接口
    :param novel_identifier: 小说ID或名称
    """
    # 判断是ID还是名称
    if novel_identifier.isdigit():
        catalog = NovelCatalog.query.filter_by(novel_id=novel_identifier).all()
    else:
        catalog = NovelCatalog.query.filter_by(novel_name=novel_identifier).all()
    
    if not catalog:
        return jsonify({'success': False, 'message': '未找到该小说'})
    
    catalog_list = [item.to_dict() for item in catalog]
    return jsonify({
        'success': True,
        'data': {
            'novel_id': catalog[0].novel_id,
            'novel_name': catalog[0].novel_name,
            'chapters': catalog_list
        }
    })

@app.route('/api/content/<chapter_id>', methods=['GET'])
def api_get_content(chapter_id):
    """
    获取章节内容API接口
    :param chapter_id: 章节ID
    """
    content = NovelContent.query.filter_by(chapter_id=chapter_id).first()
    if not content:
        return jsonify({'success': False, 'message': '未找到该章节内容'})
    
    return jsonify({'success': True, 'data': content.to_dict()})

if __name__ == '__main__':
    app.run(debug=True)

bash
pip install flask flask-sqlalchemy beautifulsoup4 requests

bash
python app.py
