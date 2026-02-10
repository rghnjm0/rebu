import sqlite3
import hashlib
import os
import re
import sys


def init_database():
    # Создаем папку если её нет
    if not os.path.exists('instance'):
        os.makedirs('instance')

    print("=== INITIALIZING DATABASE ===")

    conn = sqlite3.connect('instance/app.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Таблица пользователей
    print("Creating users table...")
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
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

    # Таблица подписок пользователей на сообщества
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
        FOREIGN KEY (user_id) REFERENCES users (id),
        FOREIGN KEY (community_id) REFERENCES communities (id)
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
        FOREIGN KEY (user_id) REFERENCES users (id),
        FOREIGN KEY (post_id) REFERENCES posts (id),
        FOREIGN KEY (parent_id) REFERENCES comments (id)
    )
    ''')

    # Таблица голосов (лайков/дизлайков)
    print("Creating votes table...")
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS votes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        post_id INTEGER NOT NULL,
        vote_type TEXT NOT NULL, -- 'up' or 'down'
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

    # Проверяем, есть ли тестовый пользователь
    cursor.execute("SELECT COUNT(*) FROM users")
    user_count = cursor.fetchone()[0]

    if user_count == 0:
        print("Creating test user...")
        # Создаем тестового пользователя (пароль: test123)
        password_hash = hashlib.sha256('test123'.encode()).hexdigest()
        try:
            cursor.execute(
                "INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
                ('testuser', 'test@example.com', password_hash)
            )
            user_id = cursor.lastrowid
            print(f"Test user created with ID: {user_id}")

            # Создаем тестовое сообщество
            print("Creating test community...")
            cursor.execute(
                "INSERT INTO communities (name, display_name, description, owner_id) VALUES (?, ?, ?, ?)",
                ('testcommunity', 'Тестовое сообщество', 'Это тестовое сообщество для демонстрации', user_id)
            )
            community_id = cursor.lastrowid
            print(f"Test community created with ID: {community_id}")

            # Подписываем пользователя на сообщество
            print("Creating test subscription...")
            cursor.execute(
                "INSERT INTO community_subscriptions (user_id, community_id) VALUES (?, ?)",
                (user_id, community_id)
            )

            # Создаем тестовый пост
            print("Creating test post...")
            cursor.execute(
                "INSERT INTO posts (title, content, user_id, community_id) VALUES (?, ?, ?, ?)",
                ('Добро пожаловать в MiniReddit!',
                 'Это тестовый пост. Вы можете создавать свои собственные посты, комментировать и голосовать.',
                 user_id, community_id)
            )
            post_id = cursor.lastrowid
            print(f"Test post created with ID: {post_id}")

            # Создаем тестовый комментарий
            print("Creating test comment...")
            cursor.execute(
                "INSERT INTO comments (content, user_id, post_id) VALUES (?, ?, ?)",
                ('Первый комментарий! Привет всем!', user_id, post_id)
            )

            # Обновляем счетчик комментариев
            cursor.execute(
                "UPDATE posts SET comments_count = 1 WHERE id = ?",
                (post_id,)
            )

        except sqlite3.IntegrityError as e:
            print(f"Error creating test data: {e}")

    conn.commit()

    # Проверяем содержимое базы данных
    print("\n=== DATABASE CHECK ===")

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    print(f"Tables created: {[t[0] for t in tables]}")

    cursor.execute("SELECT COUNT(*) FROM users")
    users = cursor.fetchone()[0]
    print(f"Users in database: {users}")

    cursor.execute("SELECT COUNT(*) FROM communities")
    communities = cursor.fetchone()[0]
    print(f"Communities in database: {communities}")

    cursor.execute("SELECT COUNT(*) FROM posts")
    posts = cursor.fetchone()[0]
    print(f"Posts in database: {posts}")

    cursor.execute("SELECT COUNT(*) FROM comments")
    comments = cursor.fetchone()[0]
    print(f"Comments in database: {comments}")

    conn.close()
    print("=== DATABASE INITIALIZATION COMPLETE ===")


def update_database():
    """Добавляет недостающие таблицы в существующую базу данных"""
    print("=== UPDATING DATABASE ===")

    conn = sqlite3.connect('instance/app.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        # Список таблиц для проверки
        tables = [
            ('users', '''
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    karma INTEGER DEFAULT 0
                )
            '''),
            ('communities', '''
                CREATE TABLE communities (
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
            '''),
            ('community_subscriptions', '''
                CREATE TABLE community_subscriptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    community_id INTEGER NOT NULL,
                    subscribed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, community_id),
                    FOREIGN KEY (user_id) REFERENCES users (id),
                    FOREIGN KEY (community_id) REFERENCES communities (id)
                )
            '''),
            ('posts', '''
                CREATE TABLE posts (
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
                    FOREIGN KEY (user_id) REFERENCES users (id),
                    FOREIGN KEY (community_id) REFERENCES communities (id)
                )
            '''),
            ('comments', '''
                CREATE TABLE comments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    post_id INTEGER NOT NULL,
                    parent_id INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id),
                    FOREIGN KEY (post_id) REFERENCES posts (id),
                    FOREIGN KEY (parent_id) REFERENCES comments (id)
                )
            '''),
            ('votes', '''
                CREATE TABLE votes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    post_id INTEGER NOT NULL,
                    vote_type TEXT NOT NULL, -- 'up' or 'down'
                    UNIQUE(user_id, post_id),
                    FOREIGN KEY (user_id) REFERENCES users (id),
                    FOREIGN KEY (post_id) REFERENCES posts (id)
                )
            '''),
            ('bookmarks', '''
                CREATE TABLE bookmarks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    post_id INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, post_id),
                    FOREIGN KEY (user_id) REFERENCES users (id),
                    FOREIGN KEY (post_id) REFERENCES posts (id)
                )
            ''')
        ]

        # Проверяем и добавляем недостающие таблицы
        for table_name, create_sql in tables:
            cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'")
            if not cursor.fetchone():
                print(f"Creating missing table: {table_name}")
                cursor.execute(create_sql)
            else:
                print(f"Table {table_name} already exists")

        # Проверяем структуру таблицы posts
        print("\nChecking posts table structure...")
        cursor.execute("PRAGMA table_info(posts)")
        columns = [column[1] for column in cursor.fetchall()]
        print(f"Posts table columns: {columns}")

        # Добавляем недостающие колонки в posts
        required_columns = ['id', 'title', 'content', 'user_id', 'community_id',
                            'post_type', 'upvotes', 'downvotes', 'comments_count', 'created_at']

        for column in required_columns:
            if column not in columns:
                if column == 'community_id':
                    cursor.execute("ALTER TABLE posts ADD COLUMN community_id INTEGER REFERENCES communities(id)")
                    print(f"Added column {column} to posts table")
                elif column == 'comments_count':
                    cursor.execute("ALTER TABLE posts ADD COLUMN comments_count INTEGER DEFAULT 0")
                    print(f"Added column {column} to posts table")
                elif column == 'post_type':
                    cursor.execute("ALTER TABLE posts ADD COLUMN post_type TEXT DEFAULT 'text'")
                    print(f"Added column {column} to posts table")

        # Проверяем структуру таблицы comments
        print("\nChecking comments table structure...")
        cursor.execute("PRAGMA table_info(comments)")
        comment_columns = [column[1] for column in cursor.fetchall()]
        print(f"Comments table columns: {comment_columns}")

        if 'parent_id' not in comment_columns:
            cursor.execute("ALTER TABLE comments ADD COLUMN parent_id INTEGER REFERENCES comments(id)")
            print("Added column parent_id to comments table")

        # Проверяем структуру таблицы users
        print("\nChecking users table structure...")
        cursor.execute("PRAGMA table_info(users)")
        user_columns = [column[1] for column in cursor.fetchall()]
        print(f"Users table columns: {user_columns}")

        if 'karma' not in user_columns:
            cursor.execute("ALTER TABLE users ADD COLUMN karma INTEGER DEFAULT 0")
            print("Added column karma to users table")

        # Проверяем существование тестовых данных
        print("\nChecking test data...")
        cursor.execute("SELECT COUNT(*) FROM users WHERE username = 'testuser'")
        test_user_exists = cursor.fetchone()[0] > 0

        if not test_user_exists:
            print("Creating test user...")
            password_hash = hashlib.sha256('test123'.encode()).hexdigest()
            cursor.execute(
                "INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
                ('testuser', 'test@example.com', password_hash)
            )
            user_id = cursor.lastrowid
            print(f"Test user created with ID: {user_id}")

            # Создаем тестовое сообщество
            cursor.execute("SELECT COUNT(*) FROM communities WHERE name = 'testcommunity'")
            test_community_exists = cursor.fetchone()[0] > 0

            if not test_community_exists:
                cursor.execute(
                    "INSERT INTO communities (name, display_name, description, owner_id) VALUES (?, ?, ?, ?)",
                    ('testcommunity', 'Тестовое сообщество', 'Это тестовое сообщество для демонстрации', user_id)
                )
                community_id = cursor.lastrowid
                print(f"Test community created with ID: {community_id}")

                # Подписываем пользователя
                cursor.execute(
                    "INSERT INTO community_subscriptions (user_id, community_id) VALUES (?, ?)",
                    (user_id, community_id)
                )

                # Создаем тестовый пост
                cursor.execute("SELECT COUNT(*) FROM posts WHERE title LIKE '%Добро пожаловать%'")
                test_post_exists = cursor.fetchone()[0] > 0

                if not test_post_exists:
                    cursor.execute(
                        "INSERT INTO posts (title, content, user_id, community_id) VALUES (?, ?, ?, ?)",
                        ('Добро пожаловать в MiniReddit!',
                         'Это тестовый пост. Вы можете создавать свои собственные посты, комментировать и голосовать.',
                         user_id, community_id)
                    )
                    post_id = cursor.lastrowid
                    print(f"Test post created with ID: {post_id}")

                    # Создаем тестовый комментарий
                    cursor.execute(
                        "INSERT INTO comments (content, user_id, post_id) VALUES (?, ?, ?)",
                        ('Первый комментарий! Привет всем!', user_id, post_id)
                    )

                    # Обновляем счетчик комментариев
                    cursor.execute(
                        "UPDATE posts SET comments_count = 1 WHERE id = ?",
                        (post_id,)
                    )

        conn.commit()

        # Выводим итоговую статистику
        print("\n=== DATABASE STATUS ===")
        cursor.execute("SELECT COUNT(*) FROM users")
        users = cursor.fetchone()[0]
        print(f"Total users: {users}")

        cursor.execute("SELECT COUNT(*) FROM communities")
        communities = cursor.fetchone()[0]
        print(f"Total communities: {communities}")

        cursor.execute("SELECT COUNT(*) FROM posts")
        posts = cursor.fetchone()[0]
        print(f"Total posts: {posts}")

        cursor.execute("SELECT COUNT(*) FROM comments")
        comments = cursor.fetchone()[0]
        print(f"Total comments: {comments}")

        print("=== DATABASE UPDATE COMPLETE ===")

    except Exception as e:
        print(f"Error updating database: {e}")
        import traceback
        traceback.print_exc()

    finally:
        conn.close()


def reset_database():
    """Полностью сбрасывает базу данных (для отладки)"""
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

    # Таблицы
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    print(f"Tables ({len(tables)}):")
    for table in tables:
        print(f"  - {table[0]}")

    print("\nData counts:")

    # Пользователи
    cursor.execute("SELECT id, username, email, created_at FROM users")
    users = cursor.fetchall()
    print(f"Users ({len(users)}):")
    for user in users:
        print(f"  ID: {user[0]}, Username: {user[1]}, Email: {user[2]}, Created: {user[3]}")

    # Сообщества
    cursor.execute("SELECT id, name, display_name, owner_id FROM communities")
    communities = cursor.fetchall()
    print(f"\nCommunities ({len(communities)}):")
    for community in communities:
        print(f"  ID: {community[0]}, Name: {community[1]}, Display: {community[2]}, Owner: {community[3]}")

    # Посты
    cursor.execute("SELECT id, title, user_id, community_id, created_at FROM posts ORDER BY created_at DESC")
    posts = cursor.fetchall()
    print(f"\nPosts ({len(posts)}):")
    for post in posts:
        print(f"  ID: {post[0]}, Title: '{post[1][:50]}...', User: {post[2]}, Community: {post[3]}, Created: {post[4]}")

    conn.close()


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