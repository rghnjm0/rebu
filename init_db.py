import sqlite3
import hashlib
from werkzeug.security import generate_password_hash
import os
import sys


def init_database():
    if not os.path.exists('instance'):
        os.makedirs('instance')
    print("=== INITIALIZING DATABASE ===")
    conn = sqlite3.connect('instance/app.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    print("Creating users table...")
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        display_name TEXT,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT DEFAULT 'user',
        is_banned BOOLEAN DEFAULT 0,
        ban_reason TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        karma INTEGER DEFAULT 0,
        bio TEXT DEFAULT '',
        avatar_color TEXT DEFAULT '#e8402a'
    )
    ''')

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

    print("Creating comments table...")
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        content TEXT NOT NULL,
        user_id INTEGER NOT NULL,
        post_id INTEGER NOT NULL,
        parent_id INTEGER,
        upvotes INTEGER DEFAULT 0,
        downvotes INTEGER DEFAULT 0,
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

    print("Creating comment_votes table...")
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS comment_votes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        comment_id INTEGER NOT NULL,
        vote_type TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, comment_id),
        FOREIGN KEY (user_id) REFERENCES users (id),
        FOREIGN KEY (comment_id) REFERENCES comments (id)
    )
    ''')

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

    cursor.execute("SELECT COUNT(*) FROM users")
    user_count = cursor.fetchone()[0]

    if user_count == 0:
        print("Creating admin and moderator...")
        admin_hash = generate_password_hash('admin123')
        cursor.execute(
            "INSERT INTO users (username, display_name, email, password_hash, role) VALUES (?, ?, ?, ?, ?)",
            ('admin', 'Administrator', 'admin@example.com', admin_hash, 'admin')
        )
        admin_id = cursor.lastrowid
        print(f"Admin created with ID: {admin_id} (login: admin, password: admin123)")

        mod_hash = generate_password_hash('mod123')
        cursor.execute(
            "INSERT INTO users (username, display_name, email, password_hash, role) VALUES (?, ?, ?, ?, ?)",
            ('moderator', 'Moderator', 'mod@example.com', mod_hash, 'moderator')
        )
        mod_id = cursor.lastrowid
        print(f"Moderator created with ID: {mod_id} (login: moderator, password: mod123)")

        print("Creating test community...")
        cursor.execute(
            "INSERT INTO communities (name, display_name, description, owner_id) VALUES (?, ?, ?, ?)",
            ('testcommunity', 'Тестовое сообщество', 'Это тестовое сообщество для демонстрации', admin_id)
        )
        community_id = cursor.lastrowid
        print(f"Test community created with ID: {community_id}")

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

        cursor.execute(
            "INSERT INTO posts (title, content, user_id, community_id) VALUES (?, ?, ?, ?)",
            ('Добро пожаловать в Rebu!',
             '<p>Это тестовый пост от администратора. Вы можете создавать свои собственные посты, комментировать и голосовать.</p><p>Попробуйте <strong>ответить на комментарий</strong> — это новая функция!</p>',
             admin_id, community_id)
        )
        post_id = cursor.lastrowid

        cursor.execute(
            "INSERT INTO posts (title, content, user_id, community_id) VALUES (?, ?, ?, ?)",
            ('Пост от модератора',
             '<p>Это пост созданный модератором для демонстрации функционала.</p><p>Здесь можно использовать <strong>форматирование</strong> и даже <a href="#">ссылки</a>.</p>',
             mod_id, community_id)
        )
        mod_post_id = cursor.lastrowid

        cursor.execute(
            "INSERT INTO comments (content, user_id, post_id) VALUES (?, ?, ?)",
            ('Первый комментарий от администратора!', admin_id, post_id)
        )
        comment1_id = cursor.lastrowid

        cursor.execute(
            "INSERT INTO comments (content, user_id, post_id, parent_id) VALUES (?, ?, ?, ?)",
            ('Ответ на комментарий администратора от модератора. Это демонстрация вложенных комментариев!',
             mod_id, post_id, comment1_id)
        )

        cursor.execute(
            "INSERT INTO comments (content, user_id, post_id) VALUES (?, ?, ?)",
            ('Еще один комментарий от модератора', mod_id, post_id)
        )

        cursor.execute(
            "UPDATE posts SET comments_count = 3 WHERE id = ?",
            (post_id,)
        )

        cursor.execute('''
            INSERT INTO reports (reporter_id, content_type, content_id, reason, description)
            VALUES (?, ?, ?, ?, ?)
        ''', (mod_id, 'comment', comment1_id, 'spam', 'Тестовая жалоба для демонстрации'))

        conn.commit()
        print("Test data created successfully!")

    conn.commit()

    print("\n=== DATABASE CHECK ===")
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    print(f"Tables created: {[t[0] for t in tables]}")
    cursor.execute("SELECT id, username, display_name, role FROM users")
    users = cursor.fetchall()
    print(f"\nUsers in database:")
    for user in users:
        print(f"  ID: {user[0]}, Username: {user[1]}, Display Name: {user[2]}, Role: {user[3]}")
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
    print("=== UPDATING DATABASE ===")
    conn = sqlite3.connect('instance/app.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    try:
        # Добавляем display_name в users
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN display_name TEXT")
            print("Added column display_name to users table")
            cursor.execute("UPDATE users SET display_name = username WHERE display_name IS NULL")
            conn.commit()
        except:
            pass

        try:
            cursor.execute("ALTER TABLE users ADD COLUMN bio TEXT DEFAULT ''")
            print("Added column bio to users table")
        except:
            pass

        try:
            cursor.execute("ALTER TABLE users ADD COLUMN avatar_color TEXT DEFAULT '#e8402a'")
            print("Added column avatar_color to users table")
        except:
            pass

        try:
            cursor.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'user'")
            print("Added column role to users table")
        except:
            pass

        try:
            cursor.execute("ALTER TABLE users ADD COLUMN is_banned BOOLEAN DEFAULT 0")
            print("Added column is_banned to users table")
        except:
            pass

        try:
            cursor.execute("ALTER TABLE users ADD COLUMN ban_reason TEXT")
            print("Added column ban_reason to users table")
        except:
            pass

        try:
            cursor.execute("ALTER TABLE posts ADD COLUMN is_deleted BOOLEAN DEFAULT 0")
            print("Added column is_deleted to posts table")
        except:
            pass

        try:
            cursor.execute("ALTER TABLE posts ADD COLUMN deleted_by INTEGER REFERENCES users(id)")
            print("Added column deleted_by to posts table")
        except:
            pass

        try:
            cursor.execute("ALTER TABLE posts ADD COLUMN deleted_at TIMESTAMP")
            print("Added column deleted_at to posts table")
        except:
            pass

        try:
            cursor.execute("ALTER TABLE comments ADD COLUMN is_deleted BOOLEAN DEFAULT 0")
            print("Added column is_deleted to comments table")
        except:
            pass

        try:
            cursor.execute("ALTER TABLE comments ADD COLUMN deleted_by INTEGER REFERENCES users(id)")
            print("Added column deleted_by to comments table")
        except:
            pass

        try:
            cursor.execute("ALTER TABLE comments ADD COLUMN deleted_at TIMESTAMP")
            print("Added column deleted_at to comments table")
        except:
            pass

        try:
            cursor.execute("ALTER TABLE comments ADD COLUMN parent_id INTEGER REFERENCES comments(id)")
            print("Added column parent_id to comments table")
        except:
            pass

        try:
            cursor.execute("ALTER TABLE comments ADD COLUMN upvotes INTEGER DEFAULT 0")
            cursor.execute("ALTER TABLE comments ADD COLUMN downvotes INTEGER DEFAULT 0")
            print("Added upvotes/downvotes to comments table")
        except:
            pass

        cursor.execute('''
        CREATE TABLE IF NOT EXISTS comment_votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            comment_id INTEGER NOT NULL,
            vote_type TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, comment_id),
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (comment_id) REFERENCES comments (id)
        )
        ''')
        print("Table comment_votes created or already exists")

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

        print("Creating indexes...")
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_posts_created ON posts(created_at DESC)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_posts_community ON posts(community_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_posts_user ON posts(user_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_comments_post ON comments(post_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_comments_parent ON comments(parent_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_comment_votes_comment ON comment_votes(comment_id)')
        print("Indexes created successfully")

        cursor.execute("SELECT id FROM users WHERE role = 'admin'")
        if not cursor.fetchone():
            print("No admin found, creating default admin...")
            admin_hash = generate_password_hash('admin123')
            cursor.execute(
                "INSERT INTO users (username, display_name, email, password_hash, role) VALUES (?, ?, ?, ?, ?)",
                ('admin', 'Administrator', 'admin@example.com', admin_hash, 'admin')
            )
            print("Default admin created: admin / admin123")

        cursor.execute("SELECT id FROM users WHERE role = 'moderator'")
        if not cursor.fetchone():
            print("No moderator found, creating default moderator...")
            mod_hash = generate_password_hash('mod123')
            cursor.execute(
                "INSERT INTO users (username, display_name, email, password_hash, role) VALUES (?, ?, ?, ?, ?)",
                ('moderator', 'Moderator', 'mod@example.com', mod_hash, 'moderator')
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
    print("=== RESETTING DATABASE ===")
    if os.path.exists('instance/app.db'):
        os.remove('instance/app.db')
        print("Old database removed")
    init_database()


def show_database_status():
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
    cursor.execute("SELECT id, username, display_name, role, is_banned, created_at FROM users")
    users = cursor.fetchall()
    for user in users:
        banned = " [BANNED]" if user[4] else ""
        print(f"  ID: {user[0]}, Username: {user[1]}, Display: {user[2]}, Role: {user[3]}{banned}, Created: {user[5]}")
    print("\n=== COMMUNITIES ===")
    cursor.execute('''
        SELECT c.id, c.name, c.display_name, u.username, c.subscribers_count
        FROM communities c
        JOIN users u ON c.owner_id = u.id
    ''')
    communities = cursor.fetchall()
    for c in communities:
        print(f"  ID: {c[0]}, Name: {c[1]}, Owner: {c[3]}, Subscribers: {c[4]}")
    print("\n=== COMMENTS (with nesting) ===")
    cursor.execute('''
        SELECT c.id, c.content[:50] as content, u.username, 
               c.parent_id, c.post_id
        FROM comments c
        JOIN users u ON c.user_id = u.id
        ORDER BY c.created_at DESC
        LIMIT 10
    ''')
    comments = cursor.fetchall()
    for c in comments:
        parent = f" (reply to {c[3]})" if c[3] else ""
        print(f"  ID: {c[0]}, Author: {c[2]}, Content: {c[1]}{parent}")
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