# file_path: app.py
from flask import Flask, render_template, redirect, url_for, flash, request, session, g
import sqlite3
import hashlib
from datetime import datetime
import os
import re
from functools import wraps
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here-change-in-production'
app.config['DATABASE'] = 'instance/app.db'
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

# Создаем папку для загрузок, если её нет
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])


# ========== ДЕКОРАТОРЫ ДЛЯ ПРОВЕРКИ ПРАВ ==========

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Необходимо войти в систему', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)

    return decorated_function


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Необходимо войти в систему', 'warning')
            return redirect(url_for('login'))

        db = get_db()
        cursor = db.cursor()
        cursor.execute('SELECT role FROM users WHERE id = ?', (session['user_id'],))
        user = cursor.fetchone()

        if not user or user['role'] != 'admin':
            flash('Доступ запрещен. Требуются права администратора.', 'danger')
            return redirect(url_for('index'))

        return f(*args, **kwargs)

    return decorated_function


def moderator_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Необходимо войти в систему', 'warning')
            return redirect(url_for('login'))

        db = get_db()
        cursor = db.cursor()
        cursor.execute('SELECT role FROM users WHERE id = ?', (session['user_id'],))
        user = cursor.fetchone()

        if not user or user['role'] not in ['admin', 'moderator']:
            flash('Доступ запрещен. Требуются права модератора.', 'danger')
            return redirect(url_for('index'))

        return f(*args, **kwargs)

    return decorated_function


def not_banned(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' in session:
            db = get_db()
            cursor = db.cursor()
            cursor.execute('SELECT is_banned FROM users WHERE id = ?', (session['user_id'],))
            user = cursor.fetchone()

            if user and user['is_banned']:
                session.clear()
                flash('Ваш аккаунт заблокирован. Обратитесь к администратору.', 'danger')
                return redirect(url_for('login'))

        return f(*args, **kwargs)

    return decorated_function


# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(app.config['DATABASE'])
        g.db.row_factory = sqlite3.Row
    return g.db


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def validate_community_name(name):
    """Проверяет допустимость имени сообщества"""
    if not 3 <= len(name) <= 20:
        return False, "Имя сообщества должно быть от 3 до 20 символов"

    if not re.match(r'^[a-zA-Z0-9_]+$', name):
        return False, "Имя сообщества может содержать только латинские буквы, цифры и _"

    return True, ""


def get_user_role(user_id):
    """Получает роль пользователя по ID"""
    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT role FROM users WHERE id = ?', (user_id,))
    user = cursor.fetchone()
    return user['role'] if user else None


def is_admin(user_id):
    """Проверяет, является ли пользователь администратором"""
    role = get_user_role(user_id)
    return role == 'admin'


def is_moderator_global(user_id):
    """Проверяет, является ли пользователь глобальным модератором или админом"""
    role = get_user_role(user_id)
    return role in ['admin', 'moderator']


def get_user_communities(user_id):
    """Получает сообщества, на которые подписан пользователь"""
    db = get_db()
    cursor = db.cursor()

    cursor.execute('''
        SELECT c.* FROM communities c
        JOIN community_subscriptions cs ON c.id = cs.community_id
        WHERE cs.user_id = ?
        ORDER BY c.name
    ''', (user_id,))

    return cursor.fetchall()


def is_subscribed_to_community(user_id, community_id):
    """Проверяет, подписан ли пользователь на сообщество"""
    db = get_db()
    cursor = db.cursor()

    cursor.execute(
        'SELECT id FROM community_subscriptions WHERE user_id = ? AND community_id = ?',
        (user_id, community_id)
    )

    return cursor.fetchone() is not None


def can_moderate_post(user_id, post_id):
    """Проверяет, может ли пользователь модерировать пост"""
    if is_moderator_global(user_id):
        return True

    return False


def can_moderate_comment(user_id, comment_id):
    """Проверяет, может ли пользователь модерировать комментарий"""
    if is_moderator_global(user_id):
        return True

    return False


def log_moderation_action(moderator_id, action, target_type, target_id=None, details=None):
    """Логирует действие модератора"""
    db = get_db()
    cursor = db.cursor()
    cursor.execute('''
        INSERT INTO moderation_logs (moderator_id, action, target_type, target_id, details)
        VALUES (?, ?, ?, ?, ?)
    ''', (moderator_id, action, target_type, target_id, details))
    db.commit()


def allowed_file(filename):
    """Проверяет, разрешен ли тип файла"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def check_and_create_tables():
    """Проверяет и создает недостающие таблицы"""
    db = get_db()
    cursor = db.cursor()

    try:
        # Проверяем существование таблицы bookmarks
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='bookmarks'")
        if not cursor.fetchone():
            cursor.execute('''
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
            print("Таблица bookmarks создана!")

        # Проверяем существование таблицы communities
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='communities'")
        if not cursor.fetchone():
            cursor.execute('''
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
            ''')
            print("Таблица communities создана!")

        # Проверяем существование таблицы reports
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='reports'")
        if not cursor.fetchone():
            cursor.execute('''
            CREATE TABLE reports (
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
            print("Таблица reports создана!")

        # Проверяем существование таблицы user_bans
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_bans'")
        if not cursor.fetchone():
            cursor.execute('''
            CREATE TABLE user_bans (
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
            print("Таблица user_bans создана!")

        # Проверяем существование таблицы moderation_logs
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='moderation_logs'")
        if not cursor.fetchone():
            cursor.execute('''
            CREATE TABLE moderation_logs (
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
            print("Таблица moderation_logs создана!")

        # Добавляем поле role в users, если его нет
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'user'")
            print("Добавлено поле role в users")
        except sqlite3.OperationalError:
            pass

        # Добавляем поле is_banned в users, если его нет
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN is_banned BOOLEAN DEFAULT 0")
            print("Добавлено поле is_banned в users")
        except sqlite3.OperationalError:
            pass

        # Добавляем поле ban_reason в users, если его нет
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN ban_reason TEXT")
            print("Добавлено поле ban_reason в users")
        except sqlite3.OperationalError:
            pass

        # Добавляем поле is_deleted в posts, если его нет
        try:
            cursor.execute("ALTER TABLE posts ADD COLUMN is_deleted BOOLEAN DEFAULT 0")
            print("Добавлено поле is_deleted в posts")
        except sqlite3.OperationalError:
            pass

        # Добавляем поле deleted_by в posts, если его нет
        try:
            cursor.execute("ALTER TABLE posts ADD COLUMN deleted_by INTEGER REFERENCES users(id)")
            print("Добавлено поле deleted_by в posts")
        except sqlite3.OperationalError:
            pass

        # Добавляем поле deleted_at в posts, если его нет
        try:
            cursor.execute("ALTER TABLE posts ADD COLUMN deleted_at TIMESTAMP")
            print("Добавлено поле deleted_at в posts")
        except sqlite3.OperationalError:
            pass

        # Добавляем поле is_deleted в comments, если его нет
        try:
            cursor.execute("ALTER TABLE comments ADD COLUMN is_deleted BOOLEAN DEFAULT 0")
            print("Добавлено поле is_deleted в comments")
        except sqlite3.OperationalError:
            pass

        # Добавляем поле deleted_by в comments, если его нет
        try:
            cursor.execute("ALTER TABLE comments ADD COLUMN deleted_by INTEGER REFERENCES users(id)")
            print("Добавлено поле deleted_by в comments")
        except sqlite3.OperationalError:
            pass

        # Добавляем поле deleted_at в comments, если его нет
        try:
            cursor.execute("ALTER TABLE comments ADD COLUMN deleted_at TIMESTAMP")
            print("Добавлено поле deleted_at в comments")
        except sqlite3.OperationalError:
            pass

    except Exception as e:
        print(f"Ошибка при проверке таблиц: {e}")


@app.teardown_appcontext
def close_db(error):
    db = g.pop('db', None)
    if db is not None:
        db.close()


@app.context_processor
def utility_processor():
    def is_bookmarked(post_id):
        if 'user_id' not in session:
            return False

        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            'SELECT id FROM bookmarks WHERE user_id = ? AND post_id = ?',
            (session['user_id'], post_id)
        )
        return cursor.fetchone() is not None

    def get_popular_communities():
        db = get_db()
        cursor = db.cursor()
        cursor.execute('''
            SELECT c.*, COUNT(cs.id) as subscribers
            FROM communities c
            LEFT JOIN community_subscriptions cs ON c.id = cs.community_id
            GROUP BY c.id
            ORDER BY subscribers DESC, c.created_at DESC
            LIMIT 10
        ''')
        return cursor.fetchall()

    def get_user_subscriptions_count():
        if 'user_id' not in session:
            return 0

        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            'SELECT COUNT(*) as count FROM community_subscriptions WHERE user_id = ?',
            (session['user_id'],)
        )
        return cursor.fetchone()['count']

    def get_moderation_count():
        """Возвращает количество ожидающих жалоб для модератора"""
        if 'user_id' not in session:
            return 0

        db = get_db()
        cursor = db.cursor()

        if is_admin(session['user_id']):
            cursor.execute("SELECT COUNT(*) as count FROM reports WHERE status = 'pending'")
        elif is_moderator_global(session['user_id']):
            cursor.execute("SELECT COUNT(*) as count FROM reports WHERE status = 'pending'")
        else:
            return 0

        result = cursor.fetchone()
        return result['count'] if result else 0

    def get_user_role_display():
        """Возвращает отображаемое название роли пользователя"""
        if 'user_id' not in session:
            return None
        role = get_user_role(session['user_id'])
        roles = {
            'admin': 'Администратор',
            'moderator': 'Модератор',
            'user': 'Пользователь'
        }
        return roles.get(role, 'Пользователь')

    return dict(
        is_bookmarked=is_bookmarked,
        get_popular_communities=get_popular_communities,
        get_user_subscriptions_count=get_user_subscriptions_count,
        get_moderation_count=get_moderation_count,
        get_user_role_display=get_user_role_display,
        is_admin=lambda: is_admin(session.get('user_id')),
        is_moderator_global=lambda: is_moderator_global(session.get('user_id'))
    )


# ========== ОСНОВНЫЕ МАРШРУТЫ ==========

@app.route('/')
@not_banned
def index():
    db = get_db()
    cursor = db.cursor()

    check_and_create_tables()

    cursor.execute('''
        SELECT p.*, u.username, u.role as author_role, c.name as community_name, c.display_name as community_display_name,
               (p.upvotes - p.downvotes) as score
        FROM posts p
        JOIN users u ON p.user_id = u.id
        LEFT JOIN communities c ON p.community_id = c.id
        WHERE p.is_deleted = 0
        ORDER BY p.created_at DESC
        LIMIT 20
    ''')

    posts = cursor.fetchall()

    user_votes = {}
    if 'user_id' in session:
        cursor.execute('''
            SELECT post_id, vote_type FROM votes 
            WHERE user_id = ?
        ''', (session['user_id'],))
        votes = cursor.fetchall()
        user_votes = {vote['post_id']: vote['vote_type'] for vote in votes}

    user_bookmarks = set()
    if 'user_id' in session:
        cursor.execute('''
            SELECT post_id FROM bookmarks 
            WHERE user_id = ?
        ''', (session['user_id'],))
        bookmarks = cursor.fetchall()
        user_bookmarks = {bookmark['post_id'] for bookmark in bookmarks}

    return render_template('index.html', posts=posts, user_votes=user_votes, user_bookmarks=user_bookmarks)


@app.route('/hot')
@not_banned
def hot_posts():
    db = get_db()
    cursor = db.cursor()

    cursor.execute('''
        SELECT p.*, u.username, u.role as author_role, c.name as community_name, c.display_name as community_display_name,
               (p.upvotes - p.downvotes) as score
        FROM posts p
        JOIN users u ON p.user_id = u.id
        LEFT JOIN communities c ON p.community_id = c.id
        WHERE p.is_deleted = 0
        ORDER BY score DESC, p.created_at DESC
        LIMIT 20
    ''')

    posts = cursor.fetchall()

    user_votes = {}
    if 'user_id' in session:
        cursor.execute('''
            SELECT post_id, vote_type FROM votes 
            WHERE user_id = ?
        ''', (session['user_id'],))
        votes = cursor.fetchall()
        user_votes = {vote['post_id']: vote['vote_type'] for vote in votes}

    user_bookmarks = set()
    if 'user_id' in session:
        cursor.execute('''
            SELECT post_id FROM bookmarks 
            WHERE user_id = ?
        ''', (session['user_id'],))
        bookmarks = cursor.fetchall()
        user_bookmarks = {bookmark['post_id'] for bookmark in bookmarks}

    return render_template('index.html',
                           posts=posts,
                           user_votes=user_votes,
                           user_bookmarks=user_bookmarks,
                           title='Горячее')


@app.route('/register', methods=['GET', 'POST'])
@not_banned
def register():
    if 'user_id' in session:
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        confirm_password = request.form['confirm_password']

        if 'accept_terms' not in request.form:
            flash('Для регистрации необходимо принять Пользовательское соглашение', 'danger')
            return redirect(url_for('register'))

        if password != confirm_password:
            flash('Пароли не совпадают', 'danger')
            return redirect(url_for('register'))

        db = get_db()
        cursor = db.cursor()

        cursor.execute('SELECT id FROM users WHERE username = ? OR email = ?',
                       (username, email))
        if cursor.fetchone():
            flash('Пользователь с таким именем или email уже существует', 'danger')
            return redirect(url_for('register'))

        password_hash = hash_password(password)
        cursor.execute(
            'INSERT INTO users (username, email, password_hash, role) VALUES (?, ?, ?, ?)',
            (username, email, password_hash, 'user')
        )
        db.commit()

        flash('Регистрация успешна! Теперь вы можете войти.', 'success')
        return redirect(url_for('login'))

    return render_template('register_login.html', mode='register')


@app.route('/login', methods=['GET', 'POST'])
@not_banned
def login():
    if 'user_id' in session:
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        db = get_db()
        cursor = db.cursor()

        cursor.execute(
            'SELECT id, username, password_hash, role, is_banned FROM users WHERE username = ?',
            (username,)
        )
        user = cursor.fetchone()

        if not user:
            flash('Неверное имя пользователя или пароль', 'danger')
            return render_template('register_login.html', mode='login')

        if user['is_banned']:
            cursor.execute('SELECT reason FROM user_bans WHERE user_id = ?', (user['id'],))
            ban = cursor.fetchone()
            reason = f" Причина: {ban['reason']}" if ban else ""
            flash(f'Ваш аккаунт заблокирован.{reason}', 'danger')
            return render_template('register_login.html', mode='login')

        if user['password_hash'] == hash_password(password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']

            role_names = {'admin': 'Администратор', 'moderator': 'Модератор', 'user': 'Пользователь'}
            role_display = role_names.get(user['role'], 'Пользователь')

            flash(f'Вход выполнен успешно! Добро пожаловать, {role_display}!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Неверное имя пользователя или пароль', 'danger')

    return render_template('register_login.html', mode='login')


@app.route('/logout')
def logout():
    session.clear()
    flash('Вы вышли из системы', 'info')
    return redirect(url_for('index'))


@app.route('/terms')
def terms():
    return render_template('terms.html')


@app.route('/privacy')
def privacy_policy():
    return redirect(url_for('terms'))


# ========== ПОСТЫ ==========

@app.route('/create', methods=['GET', 'POST'])
@login_required
@not_banned
def create_post():
    db = get_db()
    cursor = db.cursor()

    cursor.execute('''
        SELECT c.* FROM communities c
        JOIN community_subscriptions cs ON c.id = cs.community_id
        WHERE cs.user_id = ?
        ORDER BY c.name
    ''', (session['user_id'],))
    user_communities = cursor.fetchall()

    if request.method == 'POST':
        title = request.form['title'].strip()
        content = request.form['content'].strip()
        post_type = request.form.get('post_type', 'text')
        community_id = request.form.get('community_id', '')

        if not title or not content:
            flash('Заполните все обязательные поля', 'danger')
            return redirect(url_for('create_post'))

        if community_id:
            cursor.execute('SELECT id, name FROM communities WHERE id = ?', (community_id,))
            community = cursor.fetchone()
            if not community:
                flash('Указанное сообщество не существует', 'danger')
                return redirect(url_for('create_post'))

        # Обработка загруженных изображений
        image_tags = []
        if 'images' in request.files:
            files = request.files.getlist('images')
            for file in files:
                if file and file.filename and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    # Добавляем уникальный суффикс
                    name, ext = os.path.splitext(filename)
                    filename = f"{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext}"
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    file.save(filepath)

                    # Создаем Markdown тег для изображения
                    image_url = url_for('static', filename=f'uploads/{filename}')
                    image_tags.append(f'![{name}]({image_url})')

                    print(f"Image uploaded: {filename}")

        # Добавляем теги изображений в конец контента
        if image_tags:
            content += '\n\n' + '\n'.join(image_tags)

        try:
            cursor.execute(
                'INSERT INTO posts (title, content, user_id, post_type, community_id, is_deleted) VALUES (?, ?, ?, ?, ?, 0)',
                (title, content, session['user_id'], post_type, community_id if community_id else None)
            )
            post_id = cursor.lastrowid
            db.commit()

            log_moderation_action(
                session['user_id'],
                'create_post',
                'post',
                post_id,
                f'Created post: {title[:50]}'
            )

            flash('Пост создан успешно!', 'success')
            return redirect(url_for('index'))
        except Exception as e:
            db.rollback()
            flash(f'Ошибка при создании поста: {str(e)}', 'danger')
            return redirect(url_for('create_post'))

    return render_template('create_post.html', communities=user_communities)


@app.route('/post/<int:post_id>')
@not_banned
def post_detail(post_id):
    db = get_db()
    cursor = db.cursor()

    cursor.execute(''' 
        SELECT p.*, u.username, u.role as author_role, c.name as community_name, c.display_name as community_display_name,
               (p.upvotes - p.downvotes) as score
        FROM posts p
        JOIN users u ON p.user_id = u.id
        LEFT JOIN communities c ON p.community_id = c.id
        WHERE p.id = ?
    ''', (post_id,))

    post = cursor.fetchone()

    if not post:
        flash('Пост не найден', 'danger')
        return redirect(url_for('index'))

    cursor.execute('''
        SELECT c.*, u.username, u.role as author_role
        FROM comments c
        JOIN users u ON c.user_id = u.id
        WHERE c.post_id = ? AND c.is_deleted = 0
        ORDER BY c.created_at ASC
    ''', (post_id,))

    comments = cursor.fetchall()

    user_vote = None
    can_moderate = False
    is_author = False

    if 'user_id' in session:
        cursor.execute(
            'SELECT vote_type FROM votes WHERE user_id = ? AND post_id = ?',
            (session['user_id'], post_id)
        )
        vote = cursor.fetchone()
        if vote:
            user_vote = vote['vote_type']

        can_moderate = can_moderate_post(session['user_id'], post_id)
        is_author = post['user_id'] == session['user_id']

    user_bookmarked = False
    if 'user_id' in session:
        cursor.execute(
            'SELECT id FROM bookmarks WHERE user_id = ? AND post_id = ?',
            (session['user_id'], post_id)
        )
        user_bookmarked = cursor.fetchone() is not None

    return render_template('post_detail.html',
                           post=post,
                           comments=comments,
                           user_vote=user_vote,
                           user_bookmarked=user_bookmarked,
                           can_moderate=can_moderate,
                           is_author=is_author)


@app.route('/vote/<int:post_id>/<string:vote_type>')
@login_required
@not_banned
def vote_post(post_id, vote_type):
    if vote_type not in ['up', 'down']:
        return redirect(url_for('index'))

    db = get_db()
    cursor = db.cursor()

    cursor.execute('SELECT id, is_deleted FROM posts WHERE id = ?', (post_id,))
    post = cursor.fetchone()
    if not post:
        flash('Пост не найден', 'danger')
        return redirect(url_for('index'))

    if post['is_deleted']:
        flash('Нельзя голосовать за удаленный пост', 'warning')
        return redirect(request.referrer or url_for('index'))

    cursor.execute(
        'SELECT vote_type FROM votes WHERE user_id = ? AND post_id = ?',
        (session['user_id'], post_id)
    )
    existing_vote = cursor.fetchone()

    if existing_vote:
        if existing_vote['vote_type'] == vote_type:
            cursor.execute(
                'DELETE FROM votes WHERE user_id = ? AND post_id = ?',
                (session['user_id'], post_id)
            )
            if vote_type == 'up':
                cursor.execute('UPDATE posts SET upvotes = upvotes - 1 WHERE id = ?', (post_id,))
            else:
                cursor.execute('UPDATE posts SET downvotes = downvotes - 1 WHERE id = ?', (post_id,))
        else:
            cursor.execute(
                'UPDATE votes SET vote_type = ? WHERE user_id = ? AND post_id = ?',
                (vote_type, session['user_id'], post_id)
            )
            if vote_type == 'up':
                cursor.execute('UPDATE posts SET upvotes = upvotes + 1, downvotes = downvotes - 1 WHERE id = ?',
                               (post_id,))
            else:
                cursor.execute('UPDATE posts SET downvotes = downvotes + 1, upvotes = upvotes - 1 WHERE id = ?',
                               (post_id,))
    else:
        cursor.execute(
            'INSERT INTO votes (user_id, post_id, vote_type) VALUES (?, ?, ?)',
            (session['user_id'], post_id, vote_type)
        )
        if vote_type == 'up':
            cursor.execute('UPDATE posts SET upvotes = upvotes + 1 WHERE id = ?', (post_id,))
        else:
            cursor.execute('UPDATE posts SET downvotes = downvotes + 1 WHERE id = ?', (post_id,))

    db.commit()
    return redirect(request.referrer or url_for('index'))


@app.route('/post/<int:post_id>/comment', methods=['POST'])
@login_required
@not_banned
def add_comment(post_id):
    content = request.form['content']
    if not content.strip():
        flash('Комментарий не может быть пустым', 'danger')
        return redirect(url_for('post_detail', post_id=post_id))

    db = get_db()
    cursor = db.cursor()

    cursor.execute('SELECT is_deleted FROM posts WHERE id = ?', (post_id,))
    post = cursor.fetchone()
    if post and post['is_deleted']:
        flash('Нельзя комментировать удаленный пост', 'warning')
        return redirect(url_for('post_detail', post_id=post_id))

    cursor.execute(
        'INSERT INTO comments (content, user_id, post_id, is_deleted) VALUES (?, ?, ?, 0)',
        (content, session['user_id'], post_id)
    )

    cursor.execute(
        'UPDATE posts SET comments_count = comments_count + 1 WHERE id = ?',
        (post_id,)
    )

    db.commit()
    flash('Комментарий добавлен', 'success')
    return redirect(url_for('post_detail', post_id=post_id))


# ========== СООБЩЕСТВА ==========

@app.route('/create_community', methods=['GET', 'POST'])
@login_required
@not_banned
def create_community():
    if request.method == 'POST':
        name = request.form['name'].strip()
        display_name = request.form['display_name'].strip()
        description = request.form['description'].strip()
        is_public = 'is_public' in request.form

        is_valid, error_message = validate_community_name(name)
        if not is_valid:
            flash(error_message, 'danger')
            return redirect(url_for('create_community'))

        if not display_name:
            flash('Отображаемое имя обязательно', 'danger')
            return redirect(url_for('create_community'))

        db = get_db()
        cursor = db.cursor()

        cursor.execute('SELECT id FROM communities WHERE name = ?', (name,))
        if cursor.fetchone():
            flash('Сообщество с таким именем уже существует', 'danger')
            return redirect(url_for('create_community'))

        cursor.execute(
            'INSERT INTO communities (name, display_name, description, owner_id, is_public) VALUES (?, ?, ?, ?, ?)',
            (name, display_name, description, session['user_id'], is_public)
        )
        community_id = cursor.lastrowid

        cursor.execute(
            'INSERT INTO community_subscriptions (user_id, community_id) VALUES (?, ?)',
            (session['user_id'], community_id)
        )

        cursor.execute(
            'UPDATE communities SET subscribers_count = subscribers_count + 1 WHERE id = ?',
            (community_id,)
        )

        db.commit()

        log_moderation_action(
            session['user_id'],
            'create_community',
            'community',
            community_id,
            f'Created community: {name}'
        )

        flash(f'Сообщество r/{name} создано успешно!', 'success')
        return redirect(url_for('community_detail', community_name=name))

    return render_template('create_community.html')


@app.route('/r/<string:community_name>')
@not_banned
def community_detail(community_name):
    db = get_db()
    cursor = db.cursor()

    cursor.execute('''
        SELECT c.*, u.username as owner_name, u.role as owner_role
        FROM communities c
        JOIN users u ON c.owner_id = u.id
        WHERE c.name = ?
    ''', (community_name,))

    community = cursor.fetchone()
    if not community:
        flash('Сообщество не найдено', 'danger')
        return redirect(url_for('index'))

    is_subscribed = False

    if 'user_id' in session:
        cursor.execute(
            'SELECT id FROM community_subscriptions WHERE user_id = ? AND community_id = ?',
            (session['user_id'], community['id'])
        )
        is_subscribed = cursor.fetchone() is not None

    cursor.execute('''
        SELECT p.*, u.username, u.role as author_role,
               (p.upvotes - p.downvotes) as score
        FROM posts p
        JOIN users u ON p.user_id = u.id
        WHERE p.community_id = ? AND p.is_deleted = 0
        ORDER BY p.created_at DESC
        LIMIT 20
    ''', (community['id'],))

    posts = cursor.fetchall()

    user_votes = {}
    if 'user_id' in session:
        cursor.execute('''
            SELECT post_id, vote_type FROM votes 
            WHERE user_id = ?
        ''', (session['user_id'],))
        votes = cursor.fetchall()
        user_votes = {vote['post_id']: vote['vote_type'] for vote in votes}

    user_bookmarks = set()
    if 'user_id' in session:
        cursor.execute('''
            SELECT post_id FROM bookmarks 
            WHERE user_id = ?
        ''', (session['user_id'],))
        bookmarks = cursor.fetchall()
        user_bookmarks = {bookmark['post_id'] for bookmark in bookmarks}

    cursor.execute(
        'SELECT COUNT(*) as count FROM community_subscriptions WHERE community_id = ?',
        (community['id'],)
    )
    subscribers_count = cursor.fetchone()['count']

    return render_template('community_detail.html',
                           community=community,
                           posts=posts,
                           user_votes=user_votes,
                           user_bookmarks=user_bookmarks,
                           is_subscribed=is_subscribed,
                           subscribers_count=subscribers_count)


@app.route('/r/<string:community_name>/subscribe')
@login_required
@not_banned
def toggle_subscription(community_name):
    db = get_db()
    cursor = db.cursor()

    cursor.execute('SELECT id FROM communities WHERE name = ?', (community_name,))
    community = cursor.fetchone()

    if not community:
        flash('Сообщество не найдено', 'danger')
        return redirect(url_for('index'))

    cursor.execute(
        'SELECT id FROM community_subscriptions WHERE user_id = ? AND community_id = ?',
        (session['user_id'], community['id'])
    )
    subscription = cursor.fetchone()

    if subscription:
        cursor.execute(
            'DELETE FROM community_subscriptions WHERE user_id = ? AND community_id = ?',
            (session['user_id'], community['id'])
        )
        cursor.execute(
            'UPDATE communities SET subscribers_count = subscribers_count - 1 WHERE id = ?',
            (community['id'],)
        )
        flash('Вы отписались от сообщества', 'info')
    else:
        cursor.execute(
            'INSERT INTO community_subscriptions (user_id, community_id) VALUES (?, ?)',
            (session['user_id'], community['id'])
        )
        cursor.execute(
            'UPDATE communities SET subscribers_count = subscribers_count + 1 WHERE id = ?',
            (community['id'],)
        )
        flash('Вы подписались на сообщество!', 'success')

    db.commit()
    return redirect(url_for('community_detail', community_name=community_name))


@app.route('/communities')
@not_banned
def communities_list():
    db = get_db()
    cursor = db.cursor()

    cursor.execute('''
        SELECT c.*, COUNT(cs.id) as subscribers_count, u.username as owner_name
        FROM communities c
        LEFT JOIN community_subscriptions cs ON c.id = cs.community_id
        JOIN users u ON c.owner_id = u.id
        GROUP BY c.id
        ORDER BY subscribers_count DESC, c.created_at DESC
    ''')

    communities = cursor.fetchall()

    user_subscriptions = set()
    if 'user_id' in session:
        cursor.execute('''
            SELECT community_id FROM community_subscriptions WHERE user_id = ?
        ''', (session['user_id'],))
        subscriptions = cursor.fetchall()
        user_subscriptions = {sub['community_id'] for sub in subscriptions}

    return render_template('communities_list.html',
                           communities=communities,
                           user_subscriptions=user_subscriptions)


@app.route('/my_communities')
@login_required
@not_banned
def my_communities():
    db = get_db()
    cursor = db.cursor()

    cursor.execute('''
        SELECT c.*, COUNT(DISTINCT cs.id) as subscribers_count
        FROM communities c
        JOIN community_subscriptions cs ON c.id = cs.community_id
        WHERE cs.user_id = ?
        GROUP BY c.id
        ORDER BY c.name
    ''', (session['user_id'],))

    communities = cursor.fetchall()

    return render_template('my_communities.html', communities=communities)


# ========== ЗАКЛАДКИ ==========

@app.route('/bookmarks')
@login_required
@not_banned
def bookmarks():
    db = get_db()
    cursor = db.cursor()

    cursor.execute('''
        SELECT p.*, u.username, c.name as community_name, c.display_name as community_display_name,
               (p.upvotes - p.downvotes) as score
        FROM posts p
        JOIN users u ON p.user_id = u.id
        LEFT JOIN communities c ON p.community_id = c.id
        JOIN bookmarks b ON p.id = b.post_id
        WHERE b.user_id = ? AND p.is_deleted = 0
        ORDER BY b.created_at DESC
    ''', (session['user_id'],))

    bookmarked_posts = cursor.fetchall()

    user_votes = {}
    cursor.execute('''
        SELECT post_id, vote_type FROM votes 
        WHERE user_id = ?
    ''', (session['user_id'],))
    votes = cursor.fetchall()
    user_votes = {vote['post_id']: vote['vote_type'] for vote in votes}

    user_bookmarks = {post['id'] for post in bookmarked_posts}

    return render_template('bookmarks.html',
                           posts=bookmarked_posts,
                           user_votes=user_votes,
                           user_bookmarks=user_bookmarks)


@app.route('/bookmark/<int:post_id>')
@login_required
@not_banned
def toggle_bookmark(post_id):
    db = get_db()
    cursor = db.cursor()

    cursor.execute('SELECT id, is_deleted FROM posts WHERE id = ?', (post_id,))
    post = cursor.fetchone()
    if not post:
        flash('Пост не найден', 'danger')
        return redirect(url_for('index'))

    if post['is_deleted']:
        flash('Нельзя добавить в закладки удаленный пост', 'warning')
        return redirect(request.referrer or url_for('index'))

    cursor.execute(
        'SELECT id FROM bookmarks WHERE user_id = ? AND post_id = ?',
        (session['user_id'], post_id)
    )
    bookmark = cursor.fetchone()

    if bookmark:
        cursor.execute(
            'DELETE FROM bookmarks WHERE user_id = ? AND post_id = ?',
            (session['user_id'], post_id)
        )
        flash('Закладка удалена', 'info')
    else:
        cursor.execute(
            'INSERT INTO bookmarks (user_id, post_id) VALUES (?, ?)',
            (session['user_id'], post_id)
        )
        flash('Пост добавлен в закладки', 'success')

    db.commit()
    return redirect(request.referrer or url_for('index'))


# ========== ПОИСК ==========

@app.route('/search')
@not_banned
def search_posts():
    query = request.args.get('q', '').strip()

    if not query:
        return redirect(url_for('index'))

    db = get_db()
    cursor = db.cursor()

    search_pattern = f'%{query}%'

    cursor.execute('''
        SELECT p.*, u.username, u.role as author_role, c.name as community_name, c.display_name as community_display_name,
               (p.upvotes - p.downvotes) as score
        FROM posts p
        JOIN users u ON p.user_id = u.id
        LEFT JOIN communities c ON p.community_id = c.id
        WHERE (p.title LIKE ? OR p.content LIKE ?) AND p.is_deleted = 0
        ORDER BY p.created_at DESC
        LIMIT 50
    ''', (search_pattern, search_pattern))

    posts = cursor.fetchall()

    user_votes = {}
    if 'user_id' in session:
        cursor.execute('SELECT post_id, vote_type FROM votes WHERE user_id = ?', (session['user_id'],))
        votes = cursor.fetchall()
        user_votes = {vote['post_id']: vote['vote_type'] for vote in votes}

    user_bookmarks = set()
    if 'user_id' in session:
        cursor.execute('SELECT post_id FROM bookmarks WHERE user_id = ?', (session['user_id'],))
        bookmarks = cursor.fetchall()
        user_bookmarks = {bookmark['post_id'] for bookmark in bookmarks}

    return render_template('search_results.html',
                           posts=posts,
                           user_votes=user_votes,
                           user_bookmarks=user_bookmarks,
                           search_query=query)


@app.route('/search/communities')
@not_banned
def search_communities():
    query = request.args.get('q', '').strip()

    if not query:
        return redirect(url_for('communities_list'))

    db = get_db()
    cursor = db.cursor()

    cursor.execute('''
        SELECT c.*, COUNT(cs.id) as subscribers_count
        FROM communities c
        LEFT JOIN community_subscriptions cs ON c.id = cs.community_id
        WHERE c.name LIKE ? OR c.display_name LIKE ? OR c.description LIKE ?
        GROUP BY c.id
        ORDER BY subscribers_count DESC
    ''', (f'%{query}%', f'%{query}%', f'%{query}%'))

    communities = cursor.fetchall()

    user_subscriptions = set()
    if 'user_id' in session:
        cursor.execute('SELECT community_id FROM community_subscriptions WHERE user_id = ?', (session['user_id'],))
        subscriptions = cursor.fetchall()
        user_subscriptions = {sub['community_id'] for sub in subscriptions}

    return render_template('communities_list.html',
                           communities=communities,
                           user_subscriptions=user_subscriptions,
                           search_query=query)


# ========== ЖАЛОБЫ ==========

@app.route('/report/<string:content_type>/<int:content_id>', methods=['GET', 'POST'])
@login_required
@not_banned
def report_content(content_type, content_id):
    if content_type not in ['post', 'comment']:
        flash('Неверный тип контента', 'danger')
        return redirect(url_for('index'))

    db = get_db()
    cursor = db.cursor()

    if content_type == 'post':
        cursor.execute('''
            SELECT p.id, p.title, p.user_id, u.username 
            FROM posts p
            JOIN users u ON p.user_id = u.id
            WHERE p.id = ? AND p.is_deleted = 0
        ''', (content_id,))
    else:
        cursor.execute('''
            SELECT c.id, c.content, c.user_id, u.username, c.post_id
            FROM comments c
            JOIN users u ON c.user_id = u.id
            WHERE c.id = ? AND c.is_deleted = 0
        ''', (content_id,))

    content = cursor.fetchone()
    if not content:
        flash('Контент не найден или уже удален', 'danger')
        return redirect(url_for('index'))

    if content['user_id'] == session['user_id']:
        flash('Нельзя жаловаться на собственный контент', 'warning')
        if content_type == 'post':
            return redirect(url_for('post_detail', post_id=content_id))
        else:
            return redirect(url_for('post_detail', post_id=content['post_id']))

    cursor.execute('''
        SELECT id FROM reports 
        WHERE reporter_id = ? AND content_type = ? AND content_id = ? AND status = 'pending'
    ''', (session['user_id'], content_type, content_id))

    if cursor.fetchone():
        flash('Вы уже отправили жалобу на этот контент. Она ожидает рассмотрения.', 'info')
        if content_type == 'post':
            return redirect(url_for('post_detail', post_id=content_id))
        else:
            return redirect(url_for('post_detail', post_id=content['post_id']))

    if request.method == 'POST':
        reason = request.form.get('reason')
        description = request.form.get('description', '')

        if not reason:
            flash('Выберите причину жалобы', 'danger')
        else:
            cursor.execute('''
                INSERT INTO reports (reporter_id, content_type, content_id, reason, description)
                VALUES (?, ?, ?, ?, ?)
            ''', (session['user_id'], content_type, content_id, reason, description))

            db.commit()
            flash('Жалоба отправлена модераторам. Спасибо за помощь!', 'success')

            if content_type == 'post':
                return redirect(url_for('post_detail', post_id=content_id))
            else:
                return redirect(url_for('post_detail', post_id=content['post_id']))

    return render_template('report_content.html',
                           content_type=content_type,
                           content=content)


@app.route('/moderation/reports')
@login_required
@not_banned
def moderation_reports():
    """Панель модератора со списком жалоб"""
    if not is_moderator_global(session['user_id']):
        flash('Доступ запрещен. Требуются права модератора.', 'danger')
        return redirect(url_for('index'))

    db = get_db()
    cursor = db.cursor()

    cursor.execute('''
        SELECT r.*, 
               u.username as reporter_name,
               CASE 
                   WHEN r.content_type = 'post' THEN p.title
                   ELSE c.content
               END as content_title,
               CASE 
                   WHEN r.content_type = 'post' THEN p.user_id
                   ELSE c.user_id
               END as author_id,
               CASE 
                   WHEN r.content_type = 'post' THEN pu.username
                   ELSE cu.username
               END as author_name,
               CASE 
                   WHEN r.content_type = 'post' THEN p.is_deleted
                   ELSE c.is_deleted
               END as is_deleted
        FROM reports r
        JOIN users u ON r.reporter_id = u.id
        LEFT JOIN posts p ON r.content_type = 'post' AND r.content_id = p.id
        LEFT JOIN users pu ON p.user_id = pu.id
        LEFT JOIN comments c ON r.content_type = 'comment' AND r.content_id = c.id
        LEFT JOIN users cu ON c.user_id = cu.id
        WHERE r.status = 'pending'
        ORDER BY r.created_at DESC
    ''')

    reports = cursor.fetchall()

    return render_template('moderation_reports.html', reports=reports)


@app.route('/moderation/report/<int:report_id>/<string:action>', methods=['POST'])
@login_required
@not_banned
def handle_report(report_id, action):
    """Обработка жалобы модератором"""
    if action not in ['dismiss', 'delete_post', 'delete_comment']:
        flash('Неверное действие', 'danger')
        return redirect(url_for('moderation_reports'))

    if not is_moderator_global(session['user_id']):
        flash('Доступ запрещен. Требуются права модератора.', 'danger')
        return redirect(url_for('index'))

    db = get_db()
    cursor = db.cursor()

    cursor.execute('''
        SELECT r.*, p.community_id as post_community_id, 
               p.user_id as post_author_id, p.is_deleted as post_deleted,
               c.post_id as comment_post_id, c.user_id as comment_author_id, 
               c.is_deleted as comment_deleted
        FROM reports r
        LEFT JOIN posts p ON r.content_type = 'post' AND r.content_id = p.id
        LEFT JOIN comments c ON r.content_type = 'comment' AND r.content_id = c.id
        WHERE r.id = ?
    ''', (report_id,))

    report = cursor.fetchone()
    if not report:
        flash('Жалоба не найдена', 'danger')
        return redirect(url_for('moderation_reports'))

    if action == 'dismiss':
        cursor.execute('''
            UPDATE reports SET status = 'dismissed', reviewed_by = ?, reviewed_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (session['user_id'], report_id))

        log_moderation_action(
            session['user_id'],
            'dismiss_report',
            'report',
            report_id,
            f'Dismissed report #{report_id}'
        )

        flash('Жалоба отклонена', 'success')

    elif action == 'delete_post' and report['content_type'] == 'post':
        if report['post_deleted']:
            flash('Пост уже удален', 'info')
        else:
            cursor.execute('''
                UPDATE posts SET is_deleted = 1, deleted_by = ?, deleted_at = CURRENT_TIMESTAMP 
                WHERE id = ?
            ''', (session['user_id'], report['content_id']))
            cursor.execute('''
                UPDATE reports SET status = 'action_taken', reviewed_by = ?, reviewed_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (session['user_id'], report_id))

            log_moderation_action(
                session['user_id'],
                'delete_post',
                'post',
                report['content_id'],
                f'Deleted post from report #{report_id}'
            )

            flash('Пост удален', 'success')

    elif action == 'delete_comment' and report['content_type'] == 'comment':
        if report['comment_deleted']:
            flash('Комментарий уже удален', 'info')
        else:
            cursor.execute('''
                UPDATE comments SET is_deleted = 1, deleted_by = ?, deleted_at = CURRENT_TIMESTAMP 
                WHERE id = ?
            ''', (session['user_id'], report['content_id']))
            cursor.execute('''
                UPDATE reports SET status = 'action_taken', reviewed_by = ?, reviewed_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (session['user_id'], report_id))

            log_moderation_action(
                session['user_id'],
                'delete_comment',
                'comment',
                report['content_id'],
                f'Deleted comment from report #{report_id}'
            )

            flash('Комментарий удален', 'success')

    db.commit()
    return redirect(url_for('moderation_reports'))


@app.route('/moderate/post/<int:post_id>/<string:action>')
@login_required
@not_banned
def moderate_post(post_id, action):
    """Модерировать пост (удалить/восстановить)"""
    if action not in ['delete', 'restore']:
        flash('Неверное действие', 'danger')
        return redirect(url_for('index'))

    if not is_moderator_global(session['user_id']):
        flash('У вас нет прав для модерации этого поста', 'danger')
        return redirect(request.referrer or url_for('index'))

    db = get_db()
    cursor = db.cursor()

    if action == 'delete':
        cursor.execute('''
            UPDATE posts SET is_deleted = 1, deleted_by = ?, deleted_at = CURRENT_TIMESTAMP 
            WHERE id = ?
        ''', (session['user_id'], post_id))

        log_moderation_action(
            session['user_id'],
            'delete_post',
            'post',
            post_id,
            'Deleted post'
        )

        flash('Пост удален', 'success')
    else:
        cursor.execute('UPDATE posts SET is_deleted = 0, deleted_by = NULL, deleted_at = NULL WHERE id = ?', (post_id,))

        log_moderation_action(
            session['user_id'],
            'restore_post',
            'post',
            post_id,
            'Restored post'
        )

        flash('Пост восстановлен', 'success')

    db.commit()
    return redirect(request.referrer or url_for('index'))


@app.route('/moderate/comment/<int:comment_id>/<string:action>')
@login_required
@not_banned
def moderate_comment(comment_id, action):
    """Модерировать комментарий (удалить/восстановить)"""
    if action not in ['delete', 'restore']:
        flash('Неверное действие', 'danger')
        return redirect(url_for('index'))

    if not is_moderator_global(session['user_id']):
        flash('У вас нет прав для модерации этого комментария', 'danger')
        return redirect(request.referrer or url_for('index'))

    db = get_db()
    cursor = db.cursor()

    cursor.execute('SELECT post_id FROM comments WHERE id = ?', (comment_id,))
    comment = cursor.fetchone()

    if action == 'delete':
        cursor.execute('''
            UPDATE comments SET is_deleted = 1, deleted_by = ?, deleted_at = CURRENT_TIMESTAMP 
            WHERE id = ?
        ''', (session['user_id'], comment_id))

        log_moderation_action(
            session['user_id'],
            'delete_comment',
            'comment',
            comment_id,
            'Deleted comment'
        )

        flash('Комментарий удален', 'success')
    else:
        cursor.execute('UPDATE comments SET is_deleted = 0, deleted_by = NULL, deleted_at = NULL WHERE id = ?',
                       (comment_id,))

        log_moderation_action(
            session['user_id'],
            'restore_comment',
            'comment',
            comment_id,
            'Restored comment'
        )

        flash('Комментарий восстановлен', 'success')

    db.commit()
    return redirect(request.referrer or url_for('index'))


# ========== АДМИНИСТРИРОВАНИЕ ==========

@app.route('/admin')
@admin_required
def admin_panel():
    db = get_db()
    cursor = db.cursor()

    # Статистика
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'")
    admin_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'moderator'")
    moderator_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM users WHERE is_banned = 1")
    banned_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM communities")
    communities_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM posts WHERE is_deleted = 0")
    posts_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM comments WHERE is_deleted = 0")
    comments_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM reports WHERE status = 'pending'")
    pending_reports = cursor.fetchone()[0]

    # Последние действия
    cursor.execute('''
        SELECT ml.*, u.username
        FROM moderation_logs ml
        JOIN users u ON ml.moderator_id = u.id
        ORDER BY ml.created_at DESC
        LIMIT 20
    ''')
    recent_actions = cursor.fetchall()

    return render_template('admin_panel.html',
                           total_users=total_users,
                           admin_count=admin_count,
                           moderator_count=moderator_count,
                           banned_count=banned_count,
                           communities_count=communities_count,
                           posts_count=posts_count,
                           comments_count=comments_count,
                           pending_reports=pending_reports,
                           recent_actions=recent_actions)


@app.route('/admin/users')
@admin_required
def admin_users():
    db = get_db()
    cursor = db.cursor()

    cursor.execute('''
        SELECT u.*, 
               COUNT(DISTINCT p.id) as posts_count,
               COUNT(DISTINCT c.id) as comments_count
        FROM users u
        LEFT JOIN posts p ON u.id = p.user_id AND p.is_deleted = 0
        LEFT JOIN comments c ON u.id = c.user_id AND c.is_deleted = 0
        GROUP BY u.id
        ORDER BY u.created_at DESC
    ''')

    users = cursor.fetchall()

    return render_template('admin_users.html', users=users)


@app.route('/admin/user/<int:user_id>/role', methods=['POST'])
@admin_required
def admin_change_role(user_id):
    new_role = request.form.get('role')

    if new_role not in ['user', 'moderator', 'admin']:
        flash('Недопустимая роль', 'danger')
        return redirect(url_for('admin_users'))

    db = get_db()
    cursor = db.cursor()

    cursor.execute('SELECT username FROM users WHERE id = ?', (user_id,))
    user = cursor.fetchone()

    if not user:
        flash('Пользователь не найден', 'danger')
        return redirect(url_for('admin_users'))

    if user_id == session['user_id']:
        flash('Нельзя изменить свою собственную роль', 'danger')
        return redirect(url_for('admin_users'))

    cursor.execute('UPDATE users SET role = ? WHERE id = ?', (new_role, user_id))

    log_moderation_action(
        session['user_id'],
        'change_role',
        'user',
        user_id,
        f'Changed role to {new_role} for user {user["username"]}'
    )

    db.commit()

    role_names = {'admin': 'Администратора', 'moderator': 'Модератора', 'user': 'Пользователя'}
    flash(f'Роль пользователя изменена на {role_names.get(new_role, "Пользователя")}', 'success')

    return redirect(url_for('admin_users'))


@app.route('/admin/user/<int:user_id>/ban', methods=['POST'])
@admin_required
def admin_ban_user(user_id):
    reason = request.form.get('reason', '')

    db = get_db()
    cursor = db.cursor()

    cursor.execute('SELECT username FROM users WHERE id = ?', (user_id,))
    user = cursor.fetchone()

    if not user:
        flash('Пользователь не найден', 'danger')
        return redirect(url_for('admin_users'))

    if user_id == session['user_id']:
        flash('Нельзя забанить самого себя', 'danger')
        return redirect(url_for('admin_users'))

    cursor.execute('UPDATE users SET is_banned = 1, ban_reason = ? WHERE id = ?', (reason, user_id))

    cursor.execute('''
        INSERT OR REPLACE INTO user_bans (user_id, banned_by, reason)
        VALUES (?, ?, ?)
    ''', (user_id, session['user_id'], reason))

    log_moderation_action(
        session['user_id'],
        'ban_user',
        'user',
        user_id,
        f'Banned user {user["username"]}. Reason: {reason}'
    )

    db.commit()

    flash(f'Пользователь {user["username"]} забанен', 'success')

    return redirect(url_for('admin_users'))


@app.route('/admin/user/<int:user_id>/unban', methods=['POST'])
@admin_required
def admin_unban_user(user_id):
    db = get_db()
    cursor = db.cursor()

    cursor.execute('SELECT username FROM users WHERE id = ?', (user_id,))
    user = cursor.fetchone()

    if not user:
        flash('Пользователь не найден', 'danger')
        return redirect(url_for('admin_users'))

    cursor.execute('UPDATE users SET is_banned = 0, ban_reason = NULL WHERE id = ?', (user_id,))
    cursor.execute('DELETE FROM user_bans WHERE user_id = ?', (user_id,))

    log_moderation_action(
        session['user_id'],
        'unban_user',
        'user',
        user_id,
        f'Unbanned user {user["username"]}'
    )

    db.commit()

    flash(f'Пользователь {user["username"]} разбанен', 'success')

    return redirect(url_for('admin_users'))


@app.route('/admin/logs')
@admin_required
def admin_logs():
    db = get_db()
    cursor = db.cursor()

    cursor.execute('''
        SELECT ml.*, u.username
        FROM moderation_logs ml
        JOIN users u ON ml.moderator_id = u.id
        ORDER BY ml.created_at DESC
        LIMIT 100
    ''')

    logs = cursor.fetchall()

    return render_template('admin_logs.html', logs=logs)


# ========== ОТЛАДОЧНЫЕ МАРШРУТЫ ==========

@app.route('/debug/db')
def debug_database():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    db = get_db()
    cursor = db.cursor()

    result = []

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    result.append(f"Tables in database: {[t[0] for t in tables]}")

    cursor.execute("SELECT COUNT(*) FROM posts")
    post_count = cursor.fetchone()[0]
    result.append(f"Total posts in database: {post_count}")

    cursor.execute('''
        SELECT p.id, p.title, p.user_id, u.username, p.created_at, p.is_deleted
        FROM posts p 
        LEFT JOIN users u ON p.user_id = u.id 
        ORDER BY p.created_at DESC
        LIMIT 10
    ''')
    posts = cursor.fetchall()
    result.append("\nRecent posts:")
    for post in posts:
        deleted = " [DELETED]" if post[5] else ""
        result.append(
            f"ID: {post[0]}, Title: '{post[1]}', User: {post[3]}, Deleted: {post[5]}, Created: {post[4]}{deleted}")

    cursor.execute("SELECT id, username, role, is_banned FROM users")
    users = cursor.fetchall()
    result.append(f"\nUsers:")
    for user in users:
        banned = " [BANNED]" if user[3] else ""
        result.append(f"ID: {user[0]}, Username: {user[1]}, Role: {user[2]}{banned}")

    cursor.execute("SELECT COUNT(*) FROM reports WHERE status='pending'")
    pending_reports = cursor.fetchone()[0]
    result.append(f"\nPending reports: {pending_reports}")

    return '<br>'.join(result)


@app.route('/debug/check')
def debug_check():
    try:
        db = get_db()
        cursor = db.cursor()

        cursor.execute("SELECT 1")
        test = cursor.fetchone()

        return f"Database connection OK. Test result: {test[0]}"
    except Exception as e:
        return f"Database connection ERROR: {str(e)}"


if __name__ == '__main__':
    if not os.path.exists('instance/app.db'):
        import init_db

        init_db.init_database()
        print("=== DATABASE CREATED ===")
    else:
        import init_db

        init_db.update_database()
        print("=== DATABASE UPDATED ===")

    print("\n=== STARTING APPLICATION ===")
    print("Debug routes available:")
    print("  /debug/db - Show database state")
    print("  /debug/check - Check database connection")
    print("=" * 30)

    app.run(debug=True, port=5000, host='0.0.0.0')