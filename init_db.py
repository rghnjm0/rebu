# file_path: init_db.py
import sqlite3
import hashlib
import os
import sys


def init_database():
    # Создаем папку если её нет
    if not os.path.exists('instance'):
        os.makedirs('instance')

    print("=== INITIALIZING DATABASE ===")

    conn = sqlite3.connect('instance/app.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Таблица пользователей с ролью
    print("Creating users table...")
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT DEFAULT 'user',
        is_banned BOOLEAN DEFAULT 0,
        ban_reason TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        karma INTEGER DEFAULT 0
    )
    ''')

    # Таблица сообществ
    print("Creating communities table...")
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS communities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        display_name TEXT NOT NULL,
        description TEXT,
        owner_id INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        subscribers_count INTEGER DEFAULT 0,
        is_public BOOLEAN DEFAULT 1,
        FOREIGN KEY (owner_id) REFERENCES users (id)
    )
    ''')

    # Таблица подписок
    print("Creating community_subscriptions table...")
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS community_subscriptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        community_id INTEGER NOT NULL,
        subscribed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, community_id),
        FOREIGN KEY (user_id) REFERENCES users (id),
        FOREIGN KEY (community_id) REFERENCES communities (id)
    )
    ''')

    # Таблица постов
    print("Creating posts table...")
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        user_id INTEGER NOT NULL,
        community_id INTEGER,
        post_type TEXT DEFAULT 'text',
        upvotes INTEGER DEFAULT 0,
        downvotes INTEGER DEFAULT 0,
        comments_count INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_deleted BOOLEAN DEFAULT 0,
        deleted_by INTEGER,
        deleted_at TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (id),
        FOREIGN KEY (community_id) REFERENCES communities (id),
        FOREIGN KEY (deleted_by) REFERENCES users (id)
    )
    ''')

    # Таблица комментариев
    print("Creating comments table...")
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        content TEXT NOT NULL,
        user_id INTEGER NOT NULL,
        post_id INTEGER NOT NULL,
        parent_id INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_deleted BOOLEAN DEFAULT 0,
        deleted_by INTEGER,
        deleted_at TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (id),
        FOREIGN KEY (post_id) REFERENCES posts (id),
        FOREIGN KEY (parent_id) REFERENCES comments (id),
        FOREIGN KEY (deleted_by) REFERENCES users (id)
    )
    ''')

    # Таблица голосов
    print("Creating votes table...")
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS votes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        post_id INTEGER NOT NULL,
        vote_type TEXT NOT NULL,
        UNIQUE(user_id, post_id),
        FOREIGN KEY (user_id) REFERENCES users (id),
        FOREIGN KEY (post_id) REFERENCES posts (id)
    )
    ''')

    # Таблица закладок
    print("Creating bookmarks table...")
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS bookmarks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        post_id INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, post_id),
        FOREIGN KEY (user_id) REFERENCES users (id),
        FOREIGN KEY (post_id) REFERENCES posts (id)
    )
    ''')

    # Таблица жалоб
    print("Creating reports table...")
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        reporter_id INTEGER NOT NULL,
        content_type TEXT NOT NULL,
        content_id INTEGER NOT NULL,
        reason TEXT NOT NULL,
        description TEXT,
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        reviewed_by INTEGER,
        reviewed_at TIMESTAMP,
        FOREIGN KEY (reporter_id) REFERENCES users (id),
        FOREIGN KEY (reviewed_by) REFERENCES users (id)
    )
    ''')

    # Таблица пользователей с ролью
    print("Creating users table...")
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        display_name TEXT,  -- добавлено это поле
        role TEXT DEFAULT 'user',
        is_banned BOOLEAN DEFAULT 0,
        ban_reason TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        karma INTEGER DEFAULT 0
    )
    ''')

    # Таблица банов пользователей
    print("Creating user_bans table...")
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS user_bans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        banned_by INTEGER NOT NULL,
        reason TEXT,
        banned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        expires_at TIMESTAMP,
        UNIQUE(user_id),
        FOREIGN KEY (user_id) REFERENCES users (id),
        FOREIGN KEY (banned_by) REFERENCES users (id)
    )
    ''')

    # Добавьте в функцию init_database() и update_database()

    # Таблица тегов
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS tags (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    # Таблица связей постов с тегами
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS post_tags (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id INTEGER NOT NULL,
        tag_id INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(post_id, tag_id),
        FOREIGN KEY (post_id) REFERENCES posts (id) ON DELETE CASCADE,
        FOREIGN KEY (tag_id) REFERENCES tags (id) ON DELETE CASCADE
    )
    ''')

    # Индексы для ускорения поиска
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_post_tags_post ON post_tags(post_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_post_tags_tag ON post_tags(tag_id)')

    # Таблица реакций на посты
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS post_reactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        post_id INTEGER NOT NULL,
        reaction_type TEXT NOT NULL,  -- 'like', 'love', 'laugh', 'sad', 'angry', 'fire', etc.
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, post_id),
        FOREIGN KEY (user_id) REFERENCES users (id),
        FOREIGN KEY (post_id) REFERENCES posts (id) ON DELETE CASCADE
    )
    ''')

    # Индексы
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_reactions_post ON post_reactions(post_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_reactions_user ON post_reactions(user_id)')

    # Таблица логов действий
    print("Creating moderation_logs table...")
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS moderation_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        moderator_id INTEGER NOT NULL,
        action TEXT NOT NULL,
        target_type TEXT NOT NULL,
        target_id INTEGER,
        details TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (moderator_id) REFERENCES users (id)
    )
    ''')

    # Проверяем, есть ли пользователи
    cursor.execute("SELECT COUNT(*) FROM users")
    user_count = cursor.fetchone()[0]

    if user_count == 0:
        print("Creating admin and moderator...")

        # Создаем админа
        admin_hash = hashlib.sha256('admin123'.encode()).hexdigest()
        cursor.execute(
            "INSERT INTO users (username, email, password_hash, role) VALUES (?, ?, ?, ?)",
            ('admin', 'admin@example.com', admin_hash, 'admin')
        )
        admin_id = cursor.lastrowid
        print(f"Admin created with ID: {admin_id} (login: admin, password: admin123)")

        # Создаем модератора
        mod_hash = hashlib.sha256('mod123'.encode()).hexdigest()
        cursor.execute(
            "INSERT INTO users (username, email, password_hash, role) VALUES (?, ?, ?, ?)",
            ('moderator', 'mod@example.com', mod_hash, 'moderator')
        )
        mod_id = cursor.lastrowid
        print(f"Moderator created with ID: {mod_id} (login: moderator, password: mod123)")

        # Создаем тестовое сообщество (принадлежит админу)
        print("Creating test community...")
        cursor.execute(
            "INSERT INTO communities (name, display_name, description, owner_id) VALUES (?, ?, ?, ?)",
            ('testcommunity', 'Тестовое сообщество', 'Это тестовое сообщество для демонстрации', admin_id)
        )
        community_id = cursor.lastrowid
        print(f"Test community created with ID: {community_id}")

        # Подписываем админа и модератора
        cursor.execute(
            "INSERT INTO community_subscriptions (user_id, community_id) VALUES (?, ?)",
            (admin_id, community_id)
        )
        cursor.execute(
            "INSERT INTO community_subscriptions (user_id, community_id) VALUES (?, ?)",
            (mod_id, community_id)
        )
        cursor.execute(
            "UPDATE communities SET subscribers_count = 2 WHERE id = ?",
            (community_id,)
        )

        # Создаем тестовые посты
        cursor.execute(
            "INSERT INTO posts (title, content, user_id, community_id) VALUES (?, ?, ?, ?)",
            ('Добро пожаловать в MiniReddit!',
             'Это тестовый пост от администратора. Вы можете создавать свои собственные посты, комментировать и голосовать.',
             admin_id, community_id)
        )
        post_id = cursor.lastrowid

        cursor.execute(
            "INSERT INTO posts (title, content, user_id, community_id) VALUES (?, ?, ?, ?)",
            ('Пост от модератора',
             'Это пост созданный модератором для демонстрации функционала.',
             mod_id, community_id)
        )
        mod_post_id = cursor.lastrowid

        # Создаем комментарии
        cursor.execute(
            "INSERT INTO comments (content, user_id, post_id) VALUES (?, ?, ?)",
            ('Первый комментарий от администратора!', admin_id, post_id)
        )
        cursor.execute(
            "INSERT INTO comments (content, user_id, post_id) VALUES (?, ?, ?)",
            ('Комментарий от модератора', mod_id, post_id)
        )
        cursor.execute(
            "UPDATE posts SET comments_count = 2 WHERE id = ?",
            (post_id,)
        )

        # Создаем тестовую жалобу (для демонстрации)
        cursor.execute('''
            INSERT INTO reports (reporter_id, content_type, content_id, reason, description)
            VALUES (?, ?, ?, ?, ?)
        ''', (mod_id, 'comment', 1, 'spam', 'Тестовая жалоба для демонстрации'))

        conn.commit()
        print("Test data created successfully!")

    conn.commit()

    # Проверяем содержимое базы данных
    print("\n=== DATABASE CHECK ===")

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    print(f"Tables created: {[t[0] for t in tables]}")

    cursor.execute("SELECT id, username, role FROM users")
    users = cursor.fetchall()
    print(f"\nUsers in database:")
    for user in users:
        print(f"  ID: {user[0]}, Username: {user[1]}, Role: {user[2]}")

    cursor.execute("SELECT COUNT(*) FROM communities")
    communities = cursor.fetchone()[0]
    print(f"\nCommunities in database: {communities}")

    cursor.execute("SELECT COUNT(*) FROM posts")
    posts = cursor.fetchone()[0]
    print(f"Posts in database: {posts}")

    cursor.execute("SELECT COUNT(*) FROM comments")
    comments = cursor.fetchone()[0]
    print(f"Comments in database: {comments}")

    cursor.execute("SELECT COUNT(*) FROM reports WHERE status='pending'")
    pending_reports = cursor.fetchone()[0]
    print(f"Pending reports: {pending_reports}")

    conn.close()
    print("\n=== DATABASE INITIALIZATION COMPLETE ===")
    print("Test credentials:")
    print("  Admin: admin / admin123")
    print("  Moderator: moderator / mod123")
    print("  (Regular users can register themselves)")


def update_database():
    """Добавляет недостающие таблицы в существующую базу данных"""
    print("=== UPDATING DATABASE ===")

    conn = sqlite3.connect('instance/app.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        # Добавляем поле role в users
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'user'")
            print("Added column role to users table")
        except sqlite3.OperationalError:
            print("Column role already exists in users")

        # Добавляем поле is_banned в users
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN is_banned BOOLEAN DEFAULT 0")
            print("Added column is_banned to users table")
        except sqlite3.OperationalError:
            print("Column is_banned already exists in users")

        # Добавляем поле ban_reason в users
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN ban_reason TEXT")
            print("Added column ban_reason to users table")
        except sqlite3.OperationalError:
            print("Column ban_reason already exists in users")

        # Добавляем поля deleted_by и deleted_at в posts
        try:
            cursor.execute("ALTER TABLE posts ADD COLUMN deleted_by INTEGER REFERENCES users(id)")
            print("Added column deleted_by to posts table")
        except sqlite3.OperationalError:
            print("Column deleted_by already exists in posts")

        try:
            cursor.execute("ALTER TABLE posts ADD COLUMN deleted_at TIMESTAMP")
            print("Added column deleted_at to posts table")
        except sqlite3.OperationalError:
            print("Column deleted_at already exists in posts")

        # Добавляем поля deleted_by и deleted_at в comments
        try:
            cursor.execute("ALTER TABLE comments ADD COLUMN deleted_by INTEGER REFERENCES users(id)")
            print("Added column deleted_by to comments table")
        except sqlite3.OperationalError:
            print("Column deleted_by already exists in comments")

        try:
            cursor.execute("ALTER TABLE comments ADD COLUMN deleted_at TIMESTAMP")
            print("Added column deleted_at to comments table")
        except sqlite3.OperationalError:
            print("Column deleted_at already exists in comments")

        # Добавляем поле display_name в users, если его нет
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN display_name TEXT")
            print("Added column display_name to users table")
        except sqlite3.OperationalError:
            print("Column display_name already exists in users")

        # Создаем таблицу user_bans
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_bans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            banned_by INTEGER NOT NULL,
            reason TEXT,
            banned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            UNIQUE(user_id),
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (banned_by) REFERENCES users (id)
        )
        ''')
        print("Table user_bans created or already exists")

        # Создаем таблицу moderation_logs
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS moderation_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            moderator_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            target_type TEXT NOT NULL,
            target_id INTEGER,
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (moderator_id) REFERENCES users (id)
        )
        ''')
        print("Table moderation_logs created or already exists")

        # Создаем таблицу reports если её нет
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reporter_id INTEGER NOT NULL,
            content_type TEXT NOT NULL,
            content_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            description TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            reviewed_by INTEGER,
            reviewed_at TIMESTAMP,
            FOREIGN KEY (reporter_id) REFERENCES users (id),
            FOREIGN KEY (reviewed_by) REFERENCES users (id)
        )
        ''')
        print("Table reports created or already exists")

        # Проверяем наличие админа
        cursor.execute("SELECT id FROM users WHERE role = 'admin'")
        if not cursor.fetchone():
            print("No admin found, creating default admin...")
            admin_hash = hashlib.sha256('admin123'.encode()).hexdigest()
            cursor.execute(
                "INSERT INTO users (username, email, password_hash, role) VALUES (?, ?, ?, ?)",
                ('admin', 'admin@example.com', admin_hash, 'admin')
            )
            print("Default admin created: admin / admin123")

        # Проверяем наличие модератора
        cursor.execute("SELECT id FROM users WHERE role = 'moderator'")
        if not cursor.fetchone():
            print("No moderator found, creating default moderator...")
            mod_hash = hashlib.sha256('mod123'.encode()).hexdigest()
            cursor.execute(
                "INSERT INTO users (username, email, password_hash, role) VALUES (?, ?, ?, ?)",
                ('moderator', 'mod@example.com', mod_hash, 'moderator')
            )
            print("Default moderator created: moderator / mod123")

        conn.commit()

        print("\n=== DATABASE UPDATE COMPLETE ===")

    except Exception as e:
        print(f"Error updating database: {e}")
        import traceback
        traceback.print_exc()

    finally:
        conn.close()


def reset_database():
    """Полностью сбрасывает базу данных"""
    print("=== RESETTING DATABASE ===")

    if os.path.exists('instance/app.db'):
        os.remove('instance/app.db')
        print("Old database removed")

    init_database()


def show_database_status():
    """Показывает текущее состояние базы данных"""
    if not os.path.exists('instance/app.db'):
        print("Database does not exist!")
        return

    conn = sqlite3.connect('instance/app.db')
    cursor = conn.cursor()

    print("=== DATABASE STATUS ===")

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    print(f"Tables ({len(tables)}):")
    for table in tables:
        print(f"  - {table[0]}")

    print("\n=== USERS ===")
    cursor.execute("SELECT id, username, role, is_banned, created_at FROM users")
    users = cursor.fetchall()
    for user in users:
        banned = " [BANNED]" if user[3] else ""
        print(f"  ID: {user[0]}, Username: {user[1]}, Role: {user[2]}{banned}, Created: {user[4]}")

    print("\n=== COMMUNITIES ===")
    cursor.execute('''
        SELECT c.id, c.name, c.display_name, u.username, c.subscribers_count
        FROM communities c
        JOIN users u ON c.owner_id = u.id
    ''')
    communities = cursor.fetchall()
    for c in communities:
        print(f"  ID: {c[0]}, Name: {c[1]}, Owner: {c[3]}, Subscribers: {c[4]}")

    print("\n=== REPORTS ===")
    cursor.execute('''
        SELECT r.id, r.content_type, r.content_id, r.reason, r.status, u.username
        FROM reports r
        JOIN users u ON r.reporter_id = u.id
        WHERE r.status = 'pending'
    ''')
    reports = cursor.fetchall()
    for r in reports:
        print(f"  ID: {r[0]}, Type: {r[1]}, Reason: {r[3]}, Reporter: {r[5]}")

    print("\n=== POSTS ===")
    cursor.execute('''
        SELECT p.id, p.title, u.username, p.created_at, p.is_deleted
        FROM posts p
        JOIN users u ON p.user_id = u.id
        ORDER BY p.created_at DESC
        LIMIT 5
    ''')
    posts = cursor.fetchall()
    for p in posts:
        deleted = " [DELETED]" if p[4] else ""
        print(f"  ID: {p[0]}, Title: {p[1][:30]}..., Author: {p[2]}{deleted}")

    conn.close()


# Добавьте после создания таблиц в init_db.py

def create_indexes():
    """Создает индексы для ускорения запросов"""
    conn = sqlite3.connect('instance/app.db')
    cursor = conn.cursor()

    print("Creating indexes...")

    # Индексы для таблицы posts
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_posts_created ON posts(created_at DESC)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_posts_community ON posts(community_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_posts_user ON posts(user_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_posts_deleted ON posts(is_deleted)')

    # Индексы для таблицы votes
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_votes_user ON votes(user_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_votes_post ON votes(post_id)')

    # Индексы для таблицы bookmarks
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_bookmarks_user ON bookmarks(user_id)')

    # Индексы для таблицы comments
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_comments_post ON comments(post_id)')

    conn.commit()
    conn.close()
    print("Indexes created successfully!")

if __name__ == '__main__':
    if len(sys.argv) > 1:
        if sys.argv[1] == 'reset':
            reset_database()
        elif sys.argv[1] == 'update':
            update_database()
        elif sys.argv[1] == 'status':
            show_database_status()
        else:
            print(f"Unknown command: {sys.argv[1]}")
            print("Available commands:")
            print("  python init_db.py          - Initialize new database")
            print("  python init_db.py reset    - Reset database completely")
            print("  python init_db.py update   - Update existing database")
            print("  python init_db.py status   - Show database status")
    else:
        init_database()