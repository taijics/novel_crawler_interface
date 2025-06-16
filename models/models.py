from sqlalchemy import create_engine, Column, Integer, String, Text, ForeignKey, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship

# 1. 初始化数据库，默认用 SQLite。如需用 MySQL，改 connection string 即可。
engine = create_engine('sqlite:///novel.db', echo=True)  # 替换为你的数据库配置
Base = declarative_base()
SessionLocal = sessionmaker(bind=engine)

# 2. 小说目录表
class Chapter(Base):
    __tablename__ = 'chapters'
    id = Column(Integer, primary_key=True, autoincrement=True)
    novel_name = Column(String(100), index=True)       # 小说名称
    chapter_title = Column(String(200))                # 章节标题
    chapter_url = Column(String(300), unique=True)     # 章节原始URL
    __table_args__ = (
        UniqueConstraint('novel_name', 'chapter_title', name='_novel_chapter_uc'),
    )

    # 便于查询章节内容
    content = relationship("Content", back_populates="chapter", uselist=False)

# 3. 小说章节内容表
class Content(Base):
    __tablename__ = 'contents'
    id = Column(Integer, primary_key=True, autoincrement=True)
    chapter_id = Column(Integer, ForeignKey('chapters.id'), unique=True)
    content = Column(Text)                             # 章节正文内容

    chapter = relationship("Chapter", back_populates="content")

# 4. 自动建表
def init_db():
    Base.metadata.create_all(engine)

# 5. 用法示例（首次运行时建表）
if __name__ == "__main__":
    init_db()