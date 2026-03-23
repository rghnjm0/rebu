from flask import Flask, render_template, redirect, url_for, flash, request, session, g, jsonify
import sqlite3
import hashlib
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os
import re
from functools import wraps
from werkzeug.utils import secure_filename
import uuid
import math
import json

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or os.urandom(32)
app.config['DATABASE'] = 'instance/app.db'
app.config['UPLOAD_FOLDER'] = 'static/uploads/posts'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
POSTS_PER_PAGE = 20

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


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


def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(app.config['DATABASE'])
        g.db.row_factory = sqlite3.Row
    return g.db


def hash_password(password):
    return generate_password_hash(password)


def verify_password(stored_hash, password):
    if check_password_hash(stored_hash, password):
        return True
    old_hash = hashlib.sha256(password.encode()).hexdigest()
    return stored_hash == old_hash


def validate_community_name(name):
    if not 3 <= len(name) <= 20:
        return False, "Имя сообщества должно быть от 3 до 20 символов"
    if not re.match(r'^[a-zA-Z0-9_]+$', name):
        return False, "Имя сообщества может содержать только латинские буквы, цифры и _"
    return True, ""


def get_user_role(user_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT role FROM users WHERE id = ?', (user_id,))
    user = cursor.fetchone()
    return user['role'] if user else None


def is_admin(user_id):
    role = get_user_role(user_id)
    return role == 'admin'


def is_moderator_global(user_id):
    role = get_user_role(user_id)
    return role in ['admin', 'moderator']


def get_user_votes(user_id):
    if not user_id:
        return {}
    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT post_id, vote_type FROM votes WHERE user_id = ?', (user_id,))
    return {row['post_id']: row['vote_type'] for row in cursor.fetchall()}


def get_user_bookmarks_set(user_id):
    if not user_id:
        return set()
    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT post_id FROM bookmarks WHERE user_id = ?', (user_id,))
    return {row['post_id'] for row in cursor.fetchall()}


def get_user_comment_votes(user_id):
    if not user_id:
        return {}
    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT comment_id, vote_type FROM comment_votes WHERE user_id = ?', (user_id,))
    return {row['comment_id']: row['vote_type'] for row in cursor.fetchall()}


def hot_score(upvotes, downvotes, created_at_str):
    score = upvotes - downvotes
    try:
        created_at = datetime.strptime(str(created_at_str)[:19], '%Y-%m-%d %H:%M:%S')
    except Exception:
        return score
    age_hours = max((datetime.utcnow() - created_at).total_seconds() / 3600, 0.1)
    return score / math.pow(age_hours + 2, 1.5)


def ensure_profile_columns():
    db = get_db()
    cursor = db.cursor()
    for col, default in [('bio', "''"), ('avatar_color', "'#e8402a'")]:
        try:
            cursor.execute(f"ALTER TABLE users ADD COLUMN {col} TEXT DEFAULT {default}")
            db.commit()
        except Exception:
            pass


def update_user_karma(user_id, delta):
    db = get_db()
    cursor = db.cursor()
    cursor.execute('UPDATE users SET karma = karma + ? WHERE id = ?', (delta, user_id))
    db.commit()


def get_user_communities(user_id):
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
    db = get_db()
    cursor = db.cursor()
    cursor.execute(
        'SELECT id FROM community_subscriptions WHERE user_id = ? AND community_id = ?',
        (user_id, community_id)
    )
    return cursor.fetchone() is not None


def can_moderate_post(user_id, post_id):
    if is_moderator_global(user_id):
        return True
    return False


def can_moderate_comment(user_id, comment_id):
    if is_moderator_global(user_id):
        return True
    return False


def log_moderation_action(moderator_id, action, target_type, target_id=None, details=None):
    db = get_db()
    cursor = db.cursor()
    cursor.execute('''
        INSERT INTO moderation_logs (moderator_id, action, target_type, target_id, details)
        VALUES (?, ?, ?, ?, ?)
    ''', (moderator_id, action, target_type, target_id, details))
    db.commit()


def build_comments_tree(comments):
    comments_dict = {}
    for comment in comments:
        comment = dict(comment)
        comment['replies'] = []
        comment['level'] = 0
        comments_dict[comment['id']] = comment

    root_comments = []
    for comment in comments_dict.values():
        if comment['parent_id'] is None or comment['parent_id'] == 0:
            root_comments.append(comment)
        else:
            parent = comments_dict.get(comment['parent_id'])
            if parent:
                parent['replies'].append(comment)
                comment['level'] = parent.get('level', 0) + 1

    return root_comments


def check_and_create_tables():
    db = get_db()
    cursor = db.cursor()
    try:
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

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='comment_votes'")
        if not cursor.fetchone():
            cursor.execute('''
            CREATE TABLE comment_votes (
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

        try:
            cursor.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'user'")
        except sqlite3.OperationalError:
            pass
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN is_banned BOOLEAN DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN ban_reason TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            cursor.execute("ALTER TABLE posts ADD COLUMN is_deleted BOOLEAN DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        try:
            cursor.execute("ALTER TABLE posts ADD COLUMN deleted_by INTEGER REFERENCES users(id)")
        except sqlite3.OperationalError:
            pass
        try:
            cursor.execute("ALTER TABLE posts ADD COLUMN deleted_at TIMESTAMP")
        except sqlite3.OperationalError:
            pass
        try:
            cursor.execute("ALTER TABLE comments ADD COLUMN is_deleted BOOLEAN DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        try:
            cursor.execute("ALTER TABLE comments ADD COLUMN deleted_by INTEGER REFERENCES users(id)")
        except sqlite3.OperationalError:
            pass
        try:
            cursor.execute("ALTER TABLE comments ADD COLUMN deleted_at TIMESTAMP")
        except sqlite3.OperationalError:
            pass
        try:
            cursor.execute("ALTER TABLE comments ADD COLUMN parent_id INTEGER REFERENCES comments(id)")
        except sqlite3.OperationalError:
            pass
        try:
            cursor.execute("ALTER TABLE comments ADD COLUMN upvotes INTEGER DEFAULT 0")
            cursor.execute("ALTER TABLE comments ADD COLUMN downvotes INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass

        cursor.execute('CREATE INDEX IF NOT EXISTS idx_comments_post ON comments(post_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_comments_parent ON comments(parent_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_comment_votes_comment ON comment_votes(comment_id)')

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
        if 'user_id' not in session:
            return None
        role = get_user_role(session['user_id'])
        roles = {'admin': 'Администратор', 'moderator': 'Модератор', 'user': 'Пользователь'}
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


@app.route('/')
@not_banned
def index():
    db = get_db()
    cursor = db.cursor()
    check_and_create_tables()
    page = request.args.get('page', 1, type=int)
    offset = (page - 1) * POSTS_PER_PAGE
    cursor.execute('''
        SELECT p.*, u.username, u.role as author_role, c.name as community_name, c.display_name as community_display_name,
               (p.upvotes - p.downvotes) as score
        FROM posts p
        JOIN users u ON p.user_id = u.id
        LEFT JOIN communities c ON p.community_id = c.id
        WHERE p.is_deleted = 0
        ORDER BY p.created_at DESC
        LIMIT ? OFFSET ?
    ''', (POSTS_PER_PAGE, offset))
    posts = cursor.fetchall()
    cursor.execute('SELECT COUNT(*) FROM posts WHERE is_deleted = 0')
    total_posts = cursor.fetchone()[0]
    total_pages = math.ceil(total_posts / POSTS_PER_PAGE) if total_posts > 0 else 1
    user_id = session.get('user_id')
    return render_template('index.html', posts=posts,
                           user_votes=get_user_votes(user_id),
                           user_bookmarks=get_user_bookmarks_set(user_id),
                           page=page, total_pages=total_pages)


@app.route('/hot')
@not_banned
def hot_posts():
    db = get_db()
    cursor = db.cursor()
    page = request.args.get('page', 1, type=int)
    cursor.execute('''
        SELECT p.*, u.username, u.role as author_role, c.name as community_name, c.display_name as community_display_name,
               (p.upvotes - p.downvotes) as score
        FROM posts p
        JOIN users u ON p.user_id = u.id
        LEFT JOIN communities c ON p.community_id = c.id
        WHERE p.is_deleted = 0
        ORDER BY p.created_at DESC
        LIMIT 500
    ''')
    all_posts = cursor.fetchall()
    sorted_posts = sorted(all_posts,
                          key=lambda p: hot_score(p['upvotes'], p['downvotes'], p['created_at']),
                          reverse=True)
    total_pages = math.ceil(len(sorted_posts) / POSTS_PER_PAGE) if sorted_posts else 1
    offset = (page - 1) * POSTS_PER_PAGE
    posts = sorted_posts[offset:offset + POSTS_PER_PAGE]
    user_id = session.get('user_id')
    return render_template('index.html',
                           posts=posts,
                           user_votes=get_user_votes(user_id),
                           user_bookmarks=get_user_bookmarks_set(user_id),
                           title='Горячее',
                           page=page, total_pages=total_pages)


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

        if len(username) < 3 or len(username) > 30:
            flash('Имя пользователя должно быть от 3 до 30 символов', 'danger')
            return redirect(url_for('register'))

        if password != confirm_password:
            flash('Пароли не совпадают', 'danger')
            return redirect(url_for('register'))

        if len(password) < 6:
            flash('Пароль должен быть не менее 6 символов', 'danger')
            return redirect(url_for('register'))

        db = get_db()
        cursor = db.cursor()

        cursor.execute('SELECT id FROM users WHERE username = ? OR email = ?',
                       (username, email))
        if cursor.fetchone():
            flash('Пользователь с таким именем или email уже существует', 'danger')
            return redirect(url_for('register'))

        password_hash = generate_password_hash(password)
        cursor.execute(
            'INSERT INTO users (username, display_name, email, password_hash, role) VALUES (?, ?, ?, ?, ?)',
            (username, username, email, password_hash, 'user')
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
            'SELECT id, username, display_name, password_hash, role, is_banned, avatar_color FROM users WHERE username = ?',
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
        if verify_password(user['password_hash'], password):
            if user['password_hash'] == hashlib.sha256(password.encode()).hexdigest():
                db = get_db()
                db.cursor().execute('UPDATE users SET password_hash = ? WHERE id = ?',
                                    (hash_password(password), user['id']))
                db.commit()
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['display_name'] = user['display_name'] or user['username']
            session['role'] = user['role']
            session['avatar_color'] = user['avatar_color'] or '#e8402a'
            flash(f'Добро пожаловать, {session["display_name"]}!', 'success')
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
        import re as _re
        content_text = _re.sub(r'<[^>]+>', '', content).strip()
        if not title or not content_text:
            flash('Заполните все обязательные поля', 'danger')
            return redirect(url_for('create_post'))
        if community_id:
            cursor.execute('SELECT id, name FROM communities WHERE id = ?', (community_id,))
            community = cursor.fetchone()
            if not community:
                flash('Указанное сообщество не существует', 'danger')
                return redirect(url_for('create_post'))
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
            return redirect(url_for('post_detail', post_id=post_id))
        except Exception as e:
            db.rollback()
            flash(f'Ошибка при создании поста: {str(e)}', 'danger')
            return redirect(url_for('create_post'))
    preselect_community = request.args.get('community', '')
    return render_template('create_post.html', communities=user_communities, preselect_community=preselect_community)


@app.route('/upload_image', methods=['POST'])
def upload_image():
    """Загрузка изображений для TinyMCE и через форму"""
    # Проверяем авторизацию
    if 'user_id' not in session:
        return jsonify({'error': 'Необходимо войти в систему'}), 401

    # Проверяем наличие файла
    if 'file' not in request.files:
        return jsonify({'error': 'Файл не передан'}), 400

    file = request.files['file']

    # Проверяем, выбран ли файл
    if not file or file.filename == '':
        return jsonify({'error': 'Файл не выбран'}), 400

    # Проверяем расширение
    if not allowed_file(file.filename):
        return jsonify({'error': 'Недопустимый формат. Поддерживаются: png, jpg, jpeg, gif, webp'}), 400

    try:
        # Создаем безопасное имя файла
        original_name = secure_filename(file.filename)
        name, ext = os.path.splitext(original_name)
        unique_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}{ext}"

        # Создаем папку если её нет
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

        # Сохраняем файл
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_name)
        file.save(filepath)

        # Проверяем, что файл действительно сохранился
        if not os.path.exists(filepath):
            return jsonify({'error': 'Ошибка сохранения файла'}), 500

        # Формируем URL для доступа к файлу
        file_url = url_for('static', filename=f'uploads/posts/{unique_name}')

        print(f"Файл сохранен: {filepath}")
        print(f"URL для доступа: {file_url}")

        return jsonify({'location': file_url}), 200

    except Exception as e:
        print(f"Ошибка при загрузке: {str(e)}")
        return jsonify({'error': f'Ошибка при загрузке: {str(e)}'}), 500

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


@app.route('/vote_comment/<int:comment_id>/<string:vote_type>')
@login_required
@not_banned
def vote_comment(comment_id, vote_type):
    if vote_type not in ['up', 'down']:
        return redirect(url_for('index'))
    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT id, user_id, is_deleted, post_id FROM comments WHERE id = ?', (comment_id,))
    comment = cursor.fetchone()
    if not comment:
        flash('Комментарий не найден', 'danger')
        return redirect(url_for('index'))
    if comment['is_deleted']:
        flash('Нельзя голосовать за удаленный комментарий', 'warning')
        return redirect(request.referrer or url_for('index'))
    if comment['user_id'] == session['user_id']:
        flash('Нельзя голосовать за свой комментарий', 'warning')
        return redirect(request.referrer or url_for('index'))
    cursor.execute(
        'SELECT vote_type FROM comment_votes WHERE user_id = ? AND comment_id = ?',
        (session['user_id'], comment_id)
    )
    existing_vote = cursor.fetchone()
    if existing_vote:
        if existing_vote['vote_type'] == vote_type:
            cursor.execute(
                'DELETE FROM comment_votes WHERE user_id = ? AND comment_id = ?',
                (session['user_id'], comment_id)
            )
            if vote_type == 'up':
                cursor.execute('UPDATE comments SET upvotes = upvotes - 1 WHERE id = ?', (comment_id,))
            else:
                cursor.execute('UPDATE comments SET downvotes = downvotes - 1 WHERE id = ?', (comment_id,))
        else:
            cursor.execute(
                'UPDATE comment_votes SET vote_type = ? WHERE user_id = ? AND comment_id = ?',
                (vote_type, session['user_id'], comment_id)
            )
            if vote_type == 'up':
                cursor.execute('UPDATE comments SET upvotes = upvotes + 1, downvotes = downvotes - 1 WHERE id = ?',
                               (comment_id,))
            else:
                cursor.execute('UPDATE comments SET downvotes = downvotes + 1, upvotes = upvotes - 1 WHERE id = ?',
                               (comment_id,))
    else:
        cursor.execute(
            'INSERT INTO comment_votes (user_id, comment_id, vote_type) VALUES (?, ?, ?)',
            (session['user_id'], comment_id, vote_type)
        )
        if vote_type == 'up':
            cursor.execute('UPDATE comments SET upvotes = upvotes + 1 WHERE id = ?', (comment_id,))
        else:
            cursor.execute('UPDATE comments SET downvotes = downvotes + 1 WHERE id = ?', (comment_id,))
    delta = 1 if vote_type == 'up' else -1
    if existing_vote and existing_vote['vote_type'] != vote_type:
        delta = 2 if vote_type == 'up' else -2
    update_user_karma(comment['user_id'], delta)
    db.commit()
    return redirect(request.referrer or url_for('post_detail', post_id=comment['post_id']))


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
        SELECT c.*, u.username, u.role as author_role,
               u.bio, u.avatar_color,
               (c.upvotes - c.downvotes) as score
        FROM comments c
        JOIN users u ON c.user_id = u.id
        WHERE c.post_id = ? AND c.is_deleted = 0
        ORDER BY c.created_at ASC
    ''', (post_id,))
    comments = cursor.fetchall()
    comments_tree = build_comments_tree(comments)
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
    user_comment_votes = get_user_comment_votes(session.get('user_id'))
    return render_template('post_detail.html',
                           post=post,
                           comments_tree=comments_tree,
                           comments=comments,
                           user_vote=user_vote,
                           user_bookmarked=user_bookmarked,
                           can_moderate=can_moderate,
                           is_author=is_author,
                           user_comment_votes=user_comment_votes)


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

@app.route('/post/<int:post_id>/comment/<int:parent_id>/reply', methods=['POST'])
@login_required
@not_banned
def reply_to_comment(post_id, parent_id):
    """Ответ на комментарий (разрешено отвечать на свои комментарии)"""
    content = request.form['content']
    if not content.strip():
        flash('Ответ не может быть пустым', 'danger')
        return redirect(url_for('post_detail', post_id=post_id))

    db = get_db()
    cursor = db.cursor()

    # Проверяем, существует ли пост
    cursor.execute('SELECT is_deleted FROM posts WHERE id = ?', (post_id,))
    post = cursor.fetchone()
    if post and post['is_deleted']:
        flash('Нельзя комментировать удаленный пост', 'warning')
        return redirect(url_for('post_detail', post_id=post_id))

    # Проверяем, существует ли родительский комментарий
    cursor.execute('SELECT id, is_deleted, user_id FROM comments WHERE id = ?', (parent_id,))
    parent = cursor.fetchone()
    if not parent:
        flash('Комментарий, на который вы отвечаете, не найден', 'danger')
        return redirect(url_for('post_detail', post_id=post_id))

    if parent['is_deleted']:
        flash('Нельзя отвечать на удаленный комментарий', 'warning')
        return redirect(url_for('post_detail', post_id=post_id))

    # Разрешено отвечать на любые комментарии, включая свои
    # (убираем проверку parent['user_id'] != session['user_id'])

    # Добавляем ответ
    cursor.execute(
        'INSERT INTO comments (content, user_id, post_id, parent_id, is_deleted) VALUES (?, ?, ?, ?, 0)',
        (content, session['user_id'], post_id, parent_id)
    )

    # Обновляем счетчик комментариев в посте
    cursor.execute(
        'UPDATE posts SET comments_count = comments_count + 1 WHERE id = ?',
        (post_id,)
    )

    db.commit()
    flash('Ответ добавлен', 'success')
    return redirect(url_for('post_detail', post_id=post_id))


@app.route('/comment/<int:comment_id>/delete', methods=['POST'])
@login_required
@not_banned
def delete_comment(comment_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT user_id, post_id, is_deleted FROM comments WHERE id = ?', (comment_id,))
    comment = cursor.fetchone()
    if not comment or comment['is_deleted']:
        flash('Комментарий не найден', 'danger')
        return redirect(url_for('index'))
    if comment['user_id'] != session['user_id'] and not is_moderator_global(session['user_id']):
        flash('Нет прав на удаление этого комментария', 'danger')
        return redirect(request.referrer or url_for('index'))
    cursor.execute('''
        UPDATE comments SET is_deleted = 1, deleted_by = ?, deleted_at = CURRENT_TIMESTAMP
        WHERE id = ?
    ''', (session['user_id'], comment_id))
    cursor.execute('UPDATE posts SET comments_count = MAX(0, comments_count - 1) WHERE id = ?', (comment['post_id'],))
    cursor.execute('''
        UPDATE comments SET is_deleted = 1, deleted_by = ?, deleted_at = CURRENT_TIMESTAMP
        WHERE parent_id = ?
    ''', (session['user_id'], comment_id))
    cursor.execute('SELECT COUNT(*) FROM comments WHERE parent_id = ?', (comment_id,))
    replies_count = cursor.fetchone()[0]
    cursor.execute('UPDATE posts SET comments_count = MAX(0, comments_count - ?) WHERE id = ?',
                   (replies_count, comment['post_id']))
    db.commit()
    flash('Комментарий и все ответы на него удалены', 'success')
    return redirect(request.referrer or url_for('post_detail', post_id=comment['post_id']))


@app.route('/post/<int:post_id>/edit', methods=['GET', 'POST'])
@login_required
@not_banned
def edit_post(post_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT * FROM posts WHERE id = ? AND is_deleted = 0', (post_id,))
    post = cursor.fetchone()
    if not post:
        flash('Пост не найден', 'danger')
        return redirect(url_for('index'))
    if post['user_id'] != session['user_id'] and not is_moderator_global(session['user_id']):
        flash('Нет прав для редактирования', 'danger')
        return redirect(url_for('post_detail', post_id=post_id))
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()
        import re as _re
        content_text = _re.sub(r'<[^>]+>', '', content).strip()
        if not title or not content_text:
            flash('Заполните все поля', 'danger')
            return redirect(url_for('edit_post', post_id=post_id))
        cursor.execute('UPDATE posts SET title = ?, content = ? WHERE id = ?',
                       (title, content, post_id))
        db.commit()
        flash('Пост обновлён', 'success')
        return redirect(url_for('post_detail', post_id=post_id))
    return render_template('edit_post.html', post=post)


@app.route('/post/<int:post_id>/delete', methods=['POST'])
@login_required
@not_banned
def delete_own_post(post_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute('''
        SELECT p.*, u.username 
        FROM posts p
        JOIN users u ON p.user_id = u.id
        WHERE p.id = ? AND p.is_deleted = 0
    ''', (post_id,))
    post = cursor.fetchone()
    if not post:
        flash('Пост не найден', 'danger')
        return redirect(url_for('index'))
    if post['user_id'] != session['user_id'] and not is_admin(session['user_id']):
        flash('У вас нет прав на удаление этого поста', 'danger')
        return redirect(url_for('post_detail', post_id=post_id))
    cursor.execute('''
        UPDATE posts 
        SET is_deleted = 1, deleted_by = ?, deleted_at = CURRENT_TIMESTAMP 
        WHERE id = ?
    ''', (session['user_id'], post_id))
    log_moderation_action(
        session['user_id'],
        'delete_own_post',
        'post',
        post_id,
        f'Deleted own post: {post["title"][:50]}'
    )
    db.commit()
    flash('Ваш пост успешно удален', 'success')
    return redirect(url_for('index'))


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
    is_owner = False
    if 'user_id' in session:
        cursor.execute(
            'SELECT id FROM community_subscriptions WHERE user_id = ? AND community_id = ?',
            (session['user_id'], community['id'])
        )
        is_subscribed = cursor.fetchone() is not None
        is_owner = community['owner_id'] == session['user_id']
    sort = request.args.get('sort', 'new')
    page = request.args.get('page', 1, type=int)
    offset = (page - 1) * POSTS_PER_PAGE
    order_clause = 'p.created_at DESC' if sort != 'hot' else '(p.upvotes - p.downvotes) DESC, p.created_at DESC'
    cursor.execute(f'''
        SELECT p.*, u.username, u.role as author_role,
               (p.upvotes - p.downvotes) as score
        FROM posts p
        JOIN users u ON p.user_id = u.id
        WHERE p.community_id = ? AND p.is_deleted = 0
        ORDER BY {order_clause}
        LIMIT ? OFFSET ?
    ''', (community['id'], POSTS_PER_PAGE, offset))
    posts = cursor.fetchall()
    cursor.execute('SELECT COUNT(*) FROM posts WHERE community_id = ? AND is_deleted = 0',
                   (community['id'],))
    total_posts = cursor.fetchone()[0]
    total_pages = math.ceil(total_posts / POSTS_PER_PAGE) if total_posts > 0 else 1
    cursor.execute('SELECT COUNT(*) as count FROM community_subscriptions WHERE community_id = ?',
                   (community['id'],))
    subscribers_count = cursor.fetchone()['count']
    user_id = session.get('user_id')
    return render_template('community_detail.html',
                           community=community,
                           posts=posts,
                           user_votes=get_user_votes(user_id),
                           user_bookmarks=get_user_bookmarks_set(user_id),
                           is_subscribed=is_subscribed,
                           is_owner=is_owner,
                           subscribers_count=subscribers_count,
                           sort=sort,
                           page=page,
                           total_pages=total_pages)


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
    user_bookmarks = {post['id'] for post in bookmarked_posts}
    return render_template('bookmarks.html',
                           posts=bookmarked_posts,
                           user_votes=get_user_votes(session['user_id']),
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


# Добавьте новую функцию для изменения отображаемого имени
@app.route('/settings/display_name', methods=['POST'])
@login_required
@not_banned
def change_display_name():
    """Изменить отображаемое имя (никнейм)"""
    new_display_name = request.form.get('display_name', '').strip()

    if not new_display_name:
        flash('Отображаемое имя не может быть пустым', 'danger')
        return redirect(url_for('edit_profile'))

    if len(new_display_name) < 2 or len(new_display_name) > 50:
        flash('Отображаемое имя должно быть от 2 до 50 символов', 'danger')
        return redirect(url_for('edit_profile'))

    # Проверяем на недопустимые символы
    import re
    if not re.match(r'^[a-zA-Zа-яА-Я0-9\s\-_\.,!?]+$', new_display_name):
        flash('Отображаемое имя может содержать буквы, цифры, пробелы и знаки препинания', 'danger')
        return redirect(url_for('edit_profile'))

    db = get_db()
    cursor = db.cursor()

    cursor.execute('UPDATE users SET display_name = ? WHERE id = ?',
                   (new_display_name, session['user_id']))
    db.commit()

    # Обновляем display_name в сессии
    session['display_name'] = new_display_name

    flash('Отображаемое имя успешно изменено!', 'success')
    return redirect(url_for('edit_profile'))


@app.route('/u/<string:username>')
@not_banned
def user_profile(username):
    db = get_db()
    cursor = db.cursor()

    cursor.execute(
        'SELECT id, username, display_name, role, karma, created_at, is_banned, bio, avatar_color FROM users WHERE username = ?',
        (username,))
    profile_user = cursor.fetchone()

    if not profile_user:
        flash('Пользователь не найден', 'danger')
        return redirect(url_for('index'))

    page = request.args.get('page', 1, type=int)
    tab = request.args.get('tab', 'posts')
    offset = (page - 1) * POSTS_PER_PAGE

    if tab == 'comments':
        cursor.execute("""
            SELECT c.*, p.title as post_title, p.id as post_id,
                   (c.upvotes - c.downvotes) as score
            FROM comments c
            JOIN posts p ON c.post_id = p.id
            WHERE c.user_id = ? AND c.is_deleted = 0
            ORDER BY c.created_at DESC
            LIMIT ? OFFSET ?
        """, (profile_user['id'], POSTS_PER_PAGE, offset))
        items = cursor.fetchall()
        cursor.execute('SELECT COUNT(*) FROM comments WHERE user_id = ? AND is_deleted = 0',
                       (profile_user['id'],))
        total_items = cursor.fetchone()[0]
    else:
        cursor.execute("""
            SELECT p.*, u.username, u.display_name, u.role as author_role,
                   c.name as community_name, c.display_name as community_display_name,
                   (p.upvotes - p.downvotes) as score
            FROM posts p
            JOIN users u ON p.user_id = u.id
            LEFT JOIN communities c ON p.community_id = c.id
            WHERE p.user_id = ? AND p.is_deleted = 0
            ORDER BY p.created_at DESC
            LIMIT ? OFFSET ?
        """, (profile_user['id'], POSTS_PER_PAGE, offset))
        items = cursor.fetchall()
        cursor.execute('SELECT COUNT(*) FROM posts WHERE user_id = ? AND is_deleted = 0',
                       (profile_user['id'],))
        total_items = cursor.fetchone()[0]

    total_pages = math.ceil(total_items / POSTS_PER_PAGE) if total_items > 0 else 1

    cursor.execute('SELECT COUNT(*) FROM posts WHERE user_id = ? AND is_deleted = 0',
                   (profile_user['id'],))
    posts_count = cursor.fetchone()[0]

    cursor.execute('SELECT COUNT(*) FROM comments WHERE user_id = ? AND is_deleted = 0',
                   (profile_user['id'],))
    comments_count = cursor.fetchone()[0]

    user_id = session.get('user_id')
    return render_template('user_profile.html',
                           profile_user=profile_user,
                           items=items,
                           tab=tab,
                           posts_count=posts_count,
                           comments_count=comments_count,
                           page=page,
                           total_pages=total_pages,
                           is_own_profile=(user_id == profile_user['id']),
                           user_votes=get_user_votes(user_id) if tab == 'posts' else {},
                           user_bookmarks=get_user_bookmarks_set(user_id) if tab == 'posts' else set())


@app.route('/settings/profile', methods=['GET', 'POST'])
@login_required
@not_banned
def edit_profile():
    db = get_db()
    cursor = db.cursor()

    cursor.execute(
        'SELECT id, username, display_name, email, bio, avatar_color, karma, created_at FROM users WHERE id = ?',
        (session['user_id'],))
    user = cursor.fetchone()

    if not user:
        return redirect(url_for('index'))

    if request.method == 'POST':
        action = request.form.get('action', 'profile')

        if action == 'profile':
            bio = request.form.get('bio', '').strip()[:300]
            avatar_color = request.form.get('avatar_color', '#e8402a')
            import re as _re
            if not _re.match(r'^#[0-9a-fA-F]{6}$', avatar_color):
                avatar_color = '#e8402a'
            cursor.execute('UPDATE users SET bio = ?, avatar_color = ? WHERE id = ?',
                           (bio, avatar_color, session['user_id']))
            db.commit()
            session['avatar_color'] = avatar_color
            flash('Профиль обновлён', 'success')

        elif action == 'display_name':
            new_display_name = request.form.get('display_name', '').strip()
            if not new_display_name:
                flash('Отображаемое имя не может быть пустым', 'danger')
            elif len(new_display_name) < 2 or len(new_display_name) > 50:
                flash('Отображаемое имя должно быть от 2 до 50 символов', 'danger')
            else:
                import re as _re
                if not _re.match(r'^[a-zA-Zа-яА-Я0-9\s\-_\.,!?]+$', new_display_name):
                    flash('Отображаемое имя может содержать буквы, цифры, пробелы и знаки препинания', 'danger')
                else:
                    cursor.execute('UPDATE users SET display_name = ? WHERE id = ?',
                                   (new_display_name, session['user_id']))
                    db.commit()
                    session['display_name'] = new_display_name
                    flash('Отображаемое имя успешно изменено!', 'success')

        elif action == 'email':
            new_email = request.form.get('email', '').strip()
            if not new_email or '@' not in new_email:
                flash('Введите корректный email', 'danger')
            else:
                cursor.execute('SELECT id FROM users WHERE email = ? AND id != ?',
                               (new_email, session['user_id']))
                if cursor.fetchone():
                    flash('Этот email уже используется', 'danger')
                else:
                    cursor.execute('UPDATE users SET email = ? WHERE id = ?',
                                   (new_email, session['user_id']))
                    db.commit()
                    flash('Email обновлён', 'success')

        elif action == 'password':
            current_pw = request.form.get('current_password', '')
            new_pw = request.form.get('new_password', '')
            confirm_pw = request.form.get('confirm_password', '')

            cursor.execute('SELECT password_hash FROM users WHERE id = ?', (session['user_id'],))
            row = cursor.fetchone()
            if not verify_password(row['password_hash'], current_pw):
                flash('Неверный текущий пароль', 'danger')
            elif len(new_pw) < 6:
                flash('Новый пароль должен быть не менее 6 символов', 'danger')
            elif new_pw != confirm_pw:
                flash('Пароли не совпадают', 'danger')
            else:
                cursor.execute('UPDATE users SET password_hash = ? WHERE id = ?',
                               (hash_password(new_pw), session['user_id']))
                db.commit()
                flash('Пароль изменён', 'success')

        return redirect(url_for('edit_profile'))

    return render_template('edit_profile.html', user=user)

@app.route('/search')
@not_banned
def search_posts():
    query = request.args.get('q', '').strip()
    if not query:
        return redirect(url_for('index'))
    db = get_db()
    cursor = db.cursor()
    search_pattern = f'%{query}%'
    page = request.args.get('page', 1, type=int)
    offset = (page - 1) * POSTS_PER_PAGE
    cursor.execute('''
        SELECT p.*, u.username, u.role as author_role, c.name as community_name, c.display_name as community_display_name,
               (p.upvotes - p.downvotes) as score
        FROM posts p
        JOIN users u ON p.user_id = u.id
        LEFT JOIN communities c ON p.community_id = c.id
        WHERE (p.title LIKE ? OR p.content LIKE ?) AND p.is_deleted = 0
        ORDER BY p.created_at DESC
        LIMIT ? OFFSET ?
    ''', (search_pattern, search_pattern, POSTS_PER_PAGE, offset))
    posts = cursor.fetchall()
    cursor.execute('SELECT COUNT(*) FROM posts WHERE (title LIKE ? OR content LIKE ?) AND is_deleted = 0',
                   (search_pattern, search_pattern))
    total_posts = cursor.fetchone()[0]
    total_pages = math.ceil(total_posts / POSTS_PER_PAGE) if total_posts > 0 else 1
    user_id = session.get('user_id')
    return render_template('search_results.html',
                           posts=posts,
                           user_votes=get_user_votes(user_id),
                           user_bookmarks=get_user_bookmarks_set(user_id),
                           search_query=query,
                           page=page, total_pages=total_pages)


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
    pending_count = len([r for r in reports if r['status'] == 'pending']) if reports else 0
    return render_template('moderation_reports.html', reports=reports, pending_count=pending_count)


@app.route('/moderation/report/<int:report_id>/<string:action>', methods=['POST'])
@login_required
@not_banned
def handle_report(report_id, action):
    if action not in ['dismiss', 'remove_content']:
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
    elif action == 'remove_content':
        if report['content_type'] == 'post':
            if report['post_deleted']:
                flash('Пост уже удален', 'info')
            else:
                cursor.execute('''
                    UPDATE posts SET is_deleted = 1, deleted_by = ?, deleted_at = CURRENT_TIMESTAMP 
                    WHERE id = ?
                ''', (session['user_id'], report['content_id']))
                flash('Пост удален', 'success')
        else:
            if report['comment_deleted']:
                flash('Комментарий уже удален', 'info')
            else:
                cursor.execute('''
                    UPDATE comments SET is_deleted = 1, deleted_by = ?, deleted_at = CURRENT_TIMESTAMP 
                    WHERE id = ?
                ''', (session['user_id'], report['content_id']))
                cursor.execute('UPDATE posts SET comments_count = MAX(0, comments_count - 1) WHERE id = ?',
                               (report['comment_post_id'],))
                flash('Комментарий удален', 'success')
        cursor.execute('''
            UPDATE reports SET status = 'action_taken', reviewed_by = ?, reviewed_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (session['user_id'], report_id))
        log_moderation_action(
            session['user_id'],
            'remove_content',
            report['content_type'],
            report['content_id'],
            f'Removed content from report #{report_id}'
        )
    db.commit()
    return redirect(url_for('moderation_reports'))


@app.route('/moderate/post/<int:post_id>/<string:action>')
@login_required
@not_banned
def moderate_post(post_id, action):
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
        cursor.execute('UPDATE posts SET comments_count = MAX(0, comments_count - 1) WHERE id = ?',
                       (comment['post_id'],))
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
        cursor.execute('UPDATE posts SET comments_count = comments_count + 1 WHERE id = ?',
                       (comment['post_id'],))
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


@app.route('/admin')
@admin_required
def admin_panel():
    db = get_db()
    cursor = db.cursor()
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


@app.route('/faq')
@not_banned
def faq():
    return render_template('faq.html')


if __name__ == '__main__':
    if not os.path.exists('instance/app.db'):
        import init_db

        init_db.init_database()
        print("=== DATABASE CREATED ===")
    else:
        import init_db

        init_db.update_database()
        print("=== DATABASE UPDATED ===")
    with app.app_context():
        ensure_profile_columns()
    app.run(debug=os.environ.get('FLASK_DEBUG', 'false').lower() == 'true', port=5000, host='0.0.0.0')