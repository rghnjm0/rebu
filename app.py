from flask import Flask, render_template, redirect, url_for, flash, request, session, g
import sqlite3
import hashlib
from datetime import datetime
import os
import re

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here-change-in-production'
app.config['DATABASE'] = 'instance/app.db'


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

    # Только латинские буквы, цифры и нижнее подчеркивание
    if not re.match(r'^[a-zA-Z0-9_]+$', name):
        return False, "Имя сообщества может содержать только латинские буквы, цифры и _"

    return True, ""


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

    return dict(
        is_bookmarked=is_bookmarked,
        get_popular_communities=get_popular_communities,
        get_user_subscriptions_count=get_user_subscriptions_count
    )


# Поиск постов
@app.route('/search')
def search_posts():
    query = request.args.get('q', '').strip()

    if not query:
        return redirect(url_for('index'))

    db = get_db()
    cursor = db.cursor()

    # Поиск по заголовку и содержимому
    search_pattern = f'%{query}%'

    cursor.execute('''
        SELECT p.*, u.username, c.name as community_name, c.display_name as community_display_name,
               (p.upvotes - p.downvotes) as score
        FROM posts p
        JOIN users u ON p.user_id = u.id
        LEFT JOIN communities c ON p.community_id = c.id
        WHERE p.title LIKE ? OR p.content LIKE ?
        ORDER BY p.created_at DESC
        LIMIT 50
    ''', (search_pattern, search_pattern))

    posts = cursor.fetchall()

    # Проверяем, голосовал ли пользователь
    user_votes = {}
    if 'user_id' in session:
        cursor.execute('SELECT post_id, vote_type FROM votes WHERE user_id = ?', (session['user_id'],))
        votes = cursor.fetchall()
        user_votes = {vote['post_id']: vote['vote_type'] for vote in votes}

    # Проверяем закладки
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


# Главная страница - ВСЕ ПОСТЫ
@app.route('/')
def index():
    db = get_db()
    cursor = db.cursor()

    # Проверяем и создаем недостающие таблицы
    check_and_create_tables()

    # Отладка
    print(f"\n=== DEBUG INDEX PAGE ===")
    print(f"Session user_id: {session.get('user_id')}")
    print(f"Session username: {session.get('username')}")

    # Всегда показываем ВСЕ посты, отсортированные по дате
    cursor.execute('''
        SELECT p.*, u.username, c.name as community_name, c.display_name as community_display_name,
               (p.upvotes - p.downvotes) as score
        FROM posts p
        JOIN users u ON p.user_id = u.id
        LEFT JOIN communities c ON p.community_id = c.id
        ORDER BY p.created_at DESC
        LIMIT 20
    ''')

    posts = cursor.fetchall()
    print(f"DEBUG: Found {len(posts)} posts in database")

    if posts:
        print("DEBUG: Post details:")
        for post in posts:
            print(
                f"  - ID: {post['id']}, Title: '{post['title'][:30]}...', User: {post['username']}, Created: {post['created_at']}")

    # Проверяем, голосовал ли текущий пользователь за посты
    user_votes = {}
    if 'user_id' in session:
        cursor.execute('''
            SELECT post_id, vote_type FROM votes 
            WHERE user_id = ?
        ''', (session['user_id'],))
        votes = cursor.fetchall()
        user_votes = {vote['post_id']: vote['vote_type'] for vote in votes}# Проверяем, добавлены ли посты в закладки
    user_bookmarks = set()
    if 'user_id' in session:
        cursor.execute('''
            SELECT post_id FROM bookmarks 
            WHERE user_id = ?
        ''', (session['user_id'],))
        bookmarks = cursor.fetchall()
        user_bookmarks = {bookmark['post_id'] for bookmark in bookmarks}

    return render_template('index.html', posts=posts, user_votes=user_votes, user_bookmarks=user_bookmarks)


# Регистрация
@app.route('/register', methods=['GET', 'POST'])
def register():
    if 'user_id' in session:
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        confirm_password = request.form['confirm_password']

        # НОВОЕ: Проверка согласия с условиями
        if 'accept_terms' not in request.form:
            flash('Для регистрации необходимо принять Пользовательское соглашение и Политику конфиденциальности', 'danger')
            return redirect(url_for('register'))

        # Проверка паролей
        if password != confirm_password:
            flash('Пароли не совпадают', 'danger')
            return redirect(url_for('register'))

        db = get_db()
        cursor = db.cursor()

        # Проверка существования пользователя
        cursor.execute('SELECT id FROM users WHERE username = ? OR email = ?',
                       (username, email))
        if cursor.fetchone():
            flash('Пользователь с таким именем или email уже существует', 'danger')
            return redirect(url_for('register'))

        # Создание пользователя
        password_hash = hash_password(password)
        cursor.execute(
            'INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)',
            (username, email, password_hash)
        )
        db.commit()

        flash('Регистрация успешна! Теперь вы можете войти.', 'success')
        return redirect(url_for('login'))

    return render_template('register_login.html', mode='register')


# Вход
@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        db = get_db()
        cursor = db.cursor()

        cursor.execute(
            'SELECT id, username, password_hash FROM users WHERE username = ?',
            (username,)
        )
        user = cursor.fetchone()

        if user and user['password_hash'] == hash_password(password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            flash('Вход выполнен успешно!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Неверное имя пользователя или пароль', 'danger')

    return render_template('register_login.html', mode='login')


# Выход
@app.route('/logout')
def logout():
    session.clear()
    flash('Вы вышли из системы', 'info')
    return redirect(url_for('index'))


# НОВЫЙ МАРШРУТ: Пользовательское соглашение
@app.route('/terms')
def terms():
    return render_template('terms.html')


# НОВЫЙ МАРШРУТ: Политика конфиденциальности (заглушка)
@app.route('/privacy')
def privacy_policy():
    # Можно создать отдельный шаблон или перенаправить на соглашение
    return redirect(url_for('terms'))


# Создание поста
@app.route('/create', methods=['GET', 'POST'])
def create_post():
    if 'user_id' not in session:
        flash('Для создания поста необходимо войти в систему', 'warning')
        return redirect(url_for('login'))

    db = get_db()
    cursor = db.cursor()

    # Получаем сообщества пользователя
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

        # Проверяем, существует ли сообщество, если указано
        if community_id:
            cursor.execute('SELECT id, name FROM communities WHERE id = ?', (community_id,))
            community = cursor.fetchone()
            if not community:
                flash('Указанное сообщество не существует', 'danger')
                return redirect(url_for('create_post'))

        try:
            # Создание поста
            cursor.execute(
                'INSERT INTO posts (title, content, user_id, post_type, community_id) VALUES (?, ?, ?, ?, ?)',
                (title, content, session['user_id'], post_type, community_id if community_id else None)
            )
            post_id = cursor.lastrowid

            db.commit()

        except Exception as e:
            db.rollback()
            flash(f'Ошибка при создании поста: {str(e)}', 'danger')
            return redirect(url_for('create_post'))

        flash('Пост создан успешно!', 'success')
        return redirect(url_for('index'))

    return render_template('create_post.html', communities=user_communities)


# Создание сообщества
@app.route('/create_community', methods=['GET', 'POST'])
def create_community():
    if 'user_id' not in session:
        flash('Для создания сообщества необходимо войти в систему', 'warning')
        return redirect(url_for('login'))

    if request.method == 'POST':
        name = request.form['name'].strip()
        display_name = request.form['display_name'].strip()
        description = request.form['description'].strip()
        is_public = 'is_public' in request.form

        # Валидация имени
        is_valid, error_message = validate_community_name(name)
        if not is_valid:
            flash(error_message, 'danger')
            return redirect(url_for('create_community'))

        if not display_name:
            flash('Отображаемое имя обязательно', 'danger')
            return redirect(url_for('create_community'))

        db = get_db()
        cursor = db.cursor()

        # Проверка существования сообщества
        cursor.execute('SELECT id FROM communities WHERE name = ?', (name,))
        if cursor.fetchone():
            flash('Сообщество с таким именем уже существует', 'danger')
            return redirect(url_for('create_community'))

        # Создание сообщества
        cursor.execute(
            'INSERT INTO communities (name, display_name, description, owner_id, is_public) VALUES (?, ?, ?, ?, ?)',
            (name, display_name, description, session['user_id'], is_public)
        )
        community_id = cursor.lastrowid

        # Автоматически подписываем создателя
        cursor.execute(
            'INSERT INTO community_subscriptions (user_id, community_id) VALUES (?, ?)',
            (session['user_id'], community_id)
        )

        # Обновляем счетчик подписчиков
        cursor.execute(
            'UPDATE communities SET subscribers_count = subscribers_count + 1 WHERE id = ?',
            (community_id,)
        )

        db.commit()

        flash(f'Сообщество r/{name} создано успешно!', 'success')
        return redirect(url_for('community_detail', community_name=name))

    return render_template('create_community.html')


# Страница сообщества
@app.route('/r/<string:community_name>')
def community_detail(community_name):
    db = get_db()
    cursor = db.cursor()

    # Получаем информацию о сообществе
    cursor.execute('''
        SELECT c.*, u.username as owner_name
        FROM communities c
        JOIN users u ON c.owner_id = u.id
        WHERE c.name = ?
    ''', (community_name,))

    community = cursor.fetchone()
    if not community:
        flash('Сообщество не найдено', 'danger')
        return redirect(url_for('index'))

    # Проверяем, подписан ли текущий пользователь
    is_subscribed = False
    if 'user_id' in session:
        cursor.execute(
            'SELECT id FROM community_subscriptions WHERE user_id = ? AND community_id = ?',
            (session['user_id'], community['id'])
        )
        is_subscribed = cursor.fetchone() is not None

    # Получаем посты сообщества
    cursor.execute('''
        SELECT p.*, u.username, 
               (p.upvotes - p.downvotes) as score
        FROM posts p
        JOIN users u ON p.user_id = u.id
        WHERE p.community_id = ?
        ORDER BY p.created_at DESC
        LIMIT 20
    ''', (community['id'],))

    posts = cursor.fetchall()

    # Проверяем, голосовал ли текущий пользователь за посты
    user_votes = {}
    if 'user_id' in session:
        cursor.execute('''
            SELECT post_id, vote_type FROM votes 
            WHERE user_id = ?
        ''', (session['user_id'],))
        votes = cursor.fetchall()
        user_votes = {vote['post_id']: vote['vote_type'] for vote in votes}

    # Проверяем, добавлены ли посты в закладки
    user_bookmarks = set()
    if 'user_id' in session:
        cursor.execute('''
            SELECT post_id FROM bookmarks 
            WHERE user_id = ?
        ''', (session['user_id'],))
        bookmarks = cursor.fetchall()
        user_bookmarks = {bookmark['post_id'] for bookmark in bookmarks}

    # Получаем количество подписчиков
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


# Подписка/отписка от сообщества
@app.route('/r/<string:community_name>/subscribe')
def toggle_subscription(community_name):
    if 'user_id' not in session:
        flash('Для подписки необходимо войти в систему', 'warning')
        return redirect(url_for('login'))

    db = get_db()
    cursor = db.cursor()

    # Получаем ID сообщества
    cursor.execute('SELECT id FROM communities WHERE name = ?', (community_name,))
    community = cursor.fetchone()

    if not community:
        flash('Сообщество не найдено', 'danger')
        return redirect(url_for('index'))

    # Проверяем, подписан ли уже пользователь
    cursor.execute(
        'SELECT id FROM community_subscriptions WHERE user_id = ? AND community_id = ?',
        (session['user_id'], community['id'])
    )
    subscription = cursor.fetchone()

    if subscription:
        # Отписываемся
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
        # Подписываемся
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


# Список сообществ
@app.route('/communities')
def communities_list():
    db = get_db()
    cursor = db.cursor()
    # Получаем все сообщества с количеством подписчиков
    cursor.execute('''
            SELECT c.*, COUNT(cs.id) as subscribers_count
            FROM communities c
            LEFT JOIN community_subscriptions cs ON c.id = cs.community_id
            GROUP BY c.id
            ORDER BY subscribers_count DESC, c.created_at DESC
        ''')

    communities = cursor.fetchall()

    # Проверяем подписки пользователя
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


# Мои сообщества (на которые подписан)
@app.route('/my_communities')
def my_communities():
    if 'user_id' not in session:
        flash('Для просмотра ваших сообществ необходимо войти в систему', 'warning')
        return redirect(url_for('login'))

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


# Детали поста
@app.route('/post/<int:post_id>')
def post_detail(post_id):
    db = get_db()
    cursor = db.cursor()

    # Получаем пост с информацией о сообществе
    cursor.execute(''' 
            SELECT p.*, u.username, c.name as community_name, c.display_name as community_display_name,
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

    # Получаем комментарии
    cursor.execute('''
            SELECT c.*, u.username
            FROM comments c
            JOIN users u ON c.user_id = u.id
            WHERE c.post_id = ?
            ORDER BY c.created_at ASC
        ''', (post_id,))

    comments = cursor.fetchall()

    # Проверяем, голосовал ли пользователь
    user_vote = None
    if 'user_id' in session:
        cursor.execute(
            'SELECT vote_type FROM votes WHERE user_id = ? AND post_id = ?',
            (session['user_id'], post_id)
        )
        vote = cursor.fetchone()
        if vote:
            user_vote = vote['vote_type']

    # Проверяем, добавлен ли пост в закладки
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
                           user_bookmarked=user_bookmarked)


# Добавление комментария
@app.route('/post/<int:post_id>/comment', methods=['POST'])
def add_comment(post_id):
    if 'user_id' not in session:
        flash('Для комментирования необходимо войти в систему', 'warning')
        return redirect(url_for('login'))

    content = request.form['content']
    if not content.strip():
        flash('Комментарий не может быть пустым', 'danger')
        return redirect(url_for('post_detail', post_id=post_id))

    db = get_db()
    cursor = db.cursor()

    cursor.execute(
        'INSERT INTO comments (content, user_id, post_id) VALUES (?, ?, ?)',
        (content, session['user_id'], post_id)
    )# Увеличиваем счетчик комментариев
    cursor.execute(
        'UPDATE posts SET comments_count = comments_count + 1 WHERE id = ?',
        (post_id,)
    )

    db.commit()

    flash('Комментарий добавлен', 'success')
    return redirect(url_for('post_detail', post_id=post_id))


# Голосование за пост
@app.route('/vote/<int:post_id>/<string:vote_type>')
def vote_post(post_id, vote_type):
    if 'user_id' not in session:
        flash('Для голосования необходимо войти в систему', 'warning')
        return redirect(url_for('login'))

    if vote_type not in ['up', 'down']:
        return redirect(url_for('index'))

    db = get_db()
    cursor = db.cursor()

    # Проверяем, существует ли пост
    cursor.execute('SELECT id FROM posts WHERE id = ?', (post_id,))
    if not cursor.fetchone():
        flash('Пост не найден', 'danger')
        return redirect(url_for('index'))

    # Проверяем, не голосовал ли уже пользователь
    cursor.execute(
        'SELECT vote_type FROM votes WHERE user_id = ? AND post_id = ?',
        (session['user_id'], post_id)
    )
    existing_vote = cursor.fetchone()

    if existing_vote:
        # Если уже голосовал тем же способом - удаляем голос
        if existing_vote['vote_type'] == vote_type:
            cursor.execute(
                'DELETE FROM votes WHERE user_id = ? AND post_id = ?',
                (session['user_id'], post_id)
            )
            # Уменьшаем счетчик
            if vote_type == 'up':
                cursor.execute('UPDATE posts SET upvotes = upvotes - 1 WHERE id = ?', (post_id,))
            else:
                cursor.execute('UPDATE posts SET downvotes = downvotes - 1 WHERE id = ?', (post_id,))
        else:
            # Если голосовал другим способом - меняем голос
            cursor.execute(
                'UPDATE votes SET vote_type = ? WHERE user_id = ? AND post_id = ?',
                (vote_type, session['user_id'], post_id)
            )
            # Обновляем счетчики
            if vote_type == 'up':
                cursor.execute('UPDATE posts SET upvotes = upvotes + 1, downvotes = downvotes - 1 WHERE id = ?',
                               (post_id,))
            else:
                cursor.execute('UPDATE posts SET downvotes = downvotes + 1, upvotes = upvotes - 1 WHERE id = ?',
                               (post_id,))
    else:
        # Новый голос
        cursor.execute(
            'INSERT INTO votes (user_id, post_id, vote_type) VALUES (?, ?, ?)',
            (session['user_id'], post_id, vote_type)
        )
        # Увеличиваем счетчик
        if vote_type == 'up':
            cursor.execute('UPDATE posts SET upvotes = upvotes + 1 WHERE id = ?', (post_id,))
        else:
            cursor.execute('UPDATE posts SET downvotes = downvotes + 1 WHERE id = ?', (post_id,))

    db.commit()
    return redirect(request.referrer or url_for('index'))


# Горячие посты (сортировка по рейтингу)
@app.route('/hot')
def hot_posts():
    db = get_db()
    cursor = db.cursor()

    cursor.execute('''
        SELECT p.*, u.username, c.name as community_name, c.display_name as community_display_name,
               (p.upvotes - p.downvotes) as score
        FROM posts p
        JOIN users u ON p.user_id = u.id
        LEFT JOIN communities c ON p.community_id = c.id
        ORDER BY score DESC, p.created_at DESC
        LIMIT 20
    ''')

    posts = cursor.fetchall()

    # Проверяем, голосовал ли текущий пользователь за посты
    user_votes = {}
    if 'user_id' in session:
        cursor.execute('''
            SELECT post_id, vote_type FROM votes 
            WHERE user_id = ?
        ''', (session['user_id'],))
        votes = cursor.fetchall()
        user_votes = {vote['post_id']: vote['vote_type'] for vote in votes}

    # Проверяем, добавлены ли посты в закладки
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


# Закладки
@app.route('/bookmarks')
def bookmarks():
    if 'user_id' not in session:
        flash('Для просмотра закладок необходимо войти в систему', 'warning')
        return redirect(url_for('login'))

    db = get_db()
    cursor = db.cursor()

    cursor.execute('''
            SELECT p.*, u.username, c.name as community_name, c.display_name as community_display_name,
                   (p.upvotes - p.downvotes) as score
            FROM posts p
            JOIN users u ON p.user_id = u.id
            LEFT JOIN communities c ON p.community_id = c.id
            JOIN bookmarks b ON p.id = b.post_id
            WHERE b.user_id = ?
            ORDER BY b.created_at DESC
        ''', (session['user_id'],))

    bookmarked_posts = cursor.fetchall()

    # Проверяем, голосовал ли текущий пользователь за посты
    user_votes = {}
    cursor.execute('''
            SELECT post_id, vote_type FROM votes 
            WHERE user_id = ?
        ''', (session['user_id'],))
    votes = cursor.fetchall()
    user_votes = {vote['post_id']: vote['vote_type'] for vote in votes}

    # Все посты в закладках уже отмечены как закладки
    user_bookmarks = {post['id'] for post in bookmarked_posts}

    return render_template('bookmarks.html',
                           posts=bookmarked_posts,
                           user_votes=user_votes,
                           user_bookmarks=user_bookmarks)


# Добавление/удаление закладки
@app.route('/bookmark/<int:post_id>')
def toggle_bookmark(post_id):
    if 'user_id' not in session:
        flash('Для добавления в закладки необходимо войти в систему', 'warning')
        return redirect(url_for('login'))

    db = get_db()
    cursor = db.cursor()

    # Проверяем, существует ли пост
    cursor.execute('SELECT id FROM posts WHERE id = ?', (post_id,))
    if not cursor.fetchone():
        flash('Пост не найден', 'danger')
        return redirect(url_for('index'))

    # Проверяем, есть ли уже закладка
    cursor.execute(
        'SELECT id FROM bookmarks WHERE user_id = ? AND post_id = ?',
        (session['user_id'], post_id)
    )
    bookmark = cursor.fetchone()

    if bookmark:
        # Удаляем закладку
        cursor.execute(
            'DELETE FROM bookmarks WHERE user_id = ? AND post_id = ?',
            (session['user_id'], post_id)
        )
        flash('Закладка удалена', 'info')
    else:
        # Добавляем закладку
        cursor.execute(
            'INSERT INTO bookmarks (user_id, post_id) VALUES (?, ?)',
            (session['user_id'], post_id)
        )
        flash('Пост добавлен в закладки', 'success')

    db.commit()
    return redirect(request.referrer or url_for('index'))


# Поиск сообществ
@app.route('/search/communities')
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

    communities = cursor.fetchall()# Проверяем подписки пользователя
    user_subscriptions = set()
    if 'user_id' in session:
        cursor.execute('SELECT community_id FROM community_subscriptions WHERE user_id = ?', (session['user_id'],))
        subscriptions = cursor.fetchall()
        user_subscriptions = {sub['community_id'] for sub in subscriptions}

    return render_template('communities_list.html',
                           communities=communities,
                           user_subscriptions=user_subscriptions,
                           search_query=query)


# Маршрут для проверки базы данных (только для отладки)
@app.route('/debug/db')
def debug_database():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    db = get_db()
    cursor = db.cursor()

    result = []

    # Проверяем таблицы
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    result.append(f"Tables in database: {[t[0] for t in tables]}")

    # Проверяем посты
    cursor.execute("SELECT COUNT(*) FROM posts")
    post_count = cursor.fetchone()[0]
    result.append(f"Total posts in database: {post_count}")

    cursor.execute('''
        SELECT p.id, p.title, p.user_id, u.username, p.created_at 
        FROM posts p 
        LEFT JOIN users u ON p.user_id = u.id 
        ORDER BY p.created_at DESC
    ''')
    posts = cursor.fetchall()
    result.append("\nAll posts:")
    for post in posts:
        result.append(f"ID: {post[0]}, Title: '{post[1]}', User: {post[3]} (ID:{post[2]}), Created: {post[4]}")

    # Проверяем пользователей
    cursor.execute("SELECT id, username FROM users")
    users = cursor.fetchall()
    result.append(f"\nUsers: {users}")

    # Проверяем сообщества
    cursor.execute("SELECT id, name, display_name FROM communities")
    communities = cursor.fetchall()
    result.append(f"\nCommunities: {communities}")

    return '<br>'.join(result)


# Проверка подключения к базе данных
@app.route('/debug/check')
def debug_check():
    try:
        db = get_db()
        cursor = db.cursor()

        # Проверяем соединение
        cursor.execute("SELECT 1")
        test = cursor.fetchone()

        return f"Database connection OK. Test result: {test[0]}"
    except Exception as e:
        return f"Database connection ERROR: {str(e)}"


if __name__ == '__main__':
    # Создаем БД если её нет
    if not os.path.exists('instance/app.db'):
        import init_db

        init_db.init_database()
        print("=== DATABASE CREATED ===")
    else:
        # Обновляем существующую базу данных
        import init_db

        init_db.update_database()
        print("=== DATABASE UPDATED ===")

    # Проверяем структуру базы данных
    print("\n=== STARTING APPLICATION ===")
    print("Debug routes available:")
    print("  /debug/db - Show database state")
    print("  /debug/check - Check database connection")
    print("=" * 30)

    app.run(debug=True, port=5000, host='0.0.0.0')