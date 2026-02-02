from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from database import get_db_connection

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def index():
    conn = get_db_connection()
    posts = conn.execute('''
        SELECT p.id, p.title, p.content, p.votes, p.created_at,
               u.username, s.name as subreddit_name
        FROM posts p
        JOIN users u ON p.user_id = u.id
        JOIN subreddits s ON p.subreddit_id = s.id
        ORDER BY p.votes DESC, p.created_at DESC
        LIMIT 50
    ''').fetchall()
    subreddits = conn.execute('SELECT name FROM subreddits ORDER BY name').fetchall()
    conn.close()
    return render_template('index.html', posts=posts, subreddits=subreddits)

@main_bp.route('/r/<string:sub_name>')
def subreddit(sub_name):
    conn = get_db_connection()
    sub = conn.execute('SELECT * FROM subreddits WHERE name = ?', (sub_name,)).fetchone()
    if not sub:
        conn.close()
        flash(f'Сообщество r/{sub_name} не найдено')
        return redirect(url_for('main.index'))

    posts = conn.execute('''
        SELECT p.id, p.title, p.content, p.votes, p.created_at,
               u.username, s.name as subreddit_name
        FROM posts p
        JOIN users u ON p.user_id = u.id
        JOIN subreddits s ON p.subreddit_id = s.id
        WHERE s.name = ?
        ORDER BY p.votes DESC, p.created_at DESC
        LIMIT 50
    ''', (sub_name,)).fetchall()

    subreddits = conn.execute('SELECT name FROM subreddits ORDER BY name').fetchall()
    conn.close()
    return render_template('subreddit.html', sub=sub, posts=posts, subreddits=subreddits)

@main_bp.route('/create_subreddit', methods=['GET', 'POST'])
def create_subreddit():
    if 'user_id' not in session:
        flash('Нужно войти, чтобы создать сообщество')
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip().lower()
        description = request.form.get('description', '').strip()

        if not name or len(name) < 3 or len(name) > 20:
            flash('Название должно быть от 3 до 20 символов')
        elif not name.isalnum():
            flash('Название может содержать только буквы и цифры')
        else:
            conn = get_db_connection()
            try:
                conn.execute('''
                    INSERT INTO subreddits (name, description, created_by)
                    VALUES (?, ?, ?)
                ''', (name, description, session['user_id']))
                conn.commit()
                flash(f'Сообщество r/{name} создано!')
                return redirect(url_for('main.subreddit', sub_name=name))
            except sqlite3.IntegrityError:
                flash(f'Сообщество r/{name} уже существует')
            finally:
                conn.close()

    return render_template('create_subreddit.html')

@main_bp.route('/create_post', methods=['GET', 'POST'])
def create_post():
    if 'user_id' not in session:
        flash('Нужно войти для создания поста')
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    subreddits = conn.execute('SELECT id, name FROM subreddits ORDER BY name').fetchall()

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()
        subreddit_id = request.form.get('subreddit_id')

        if not title or not content or not subreddit_id:
            flash('Заполните все поля')
        else:
            try:
                conn.execute('''
                    INSERT INTO posts (title, content, user_id, subreddit_id)
                    VALUES (?, ?, ?, ?)
                ''', (title, content, session['user_id'], subreddit_id))
                conn.commit()
                flash('Пост опубликован!')
                return redirect(url_for('main.index'))
            except Exception as e:
                flash(f'Ошибка: {str(e)}')

    conn.close()
    return render_template('create_post.html', subreddits=subreddits)

@main_bp.route('/post/<int:post_id>', methods=['GET', 'POST'])
def view_post(post_id):
    conn = get_db_connection()
    post = conn.execute('''
        SELECT p.*, u.username, s.name as subreddit_name
        FROM posts p
        JOIN users u ON p.user_id = u.id
        JOIN subreddits s ON p.subreddit_id = s.id
        WHERE p.id = ?
    ''', (post_id,)).fetchone()

    if not post:
        conn.close()
        flash('Пост не найден')
        return redirect(url_for('main.index'))

    if request.method == 'POST':
        if 'user_id' not in session:
            flash('Нужно войти, чтобы комментировать')
        else:
            content = request.form.get('content', '').strip()
            if content:
                conn.execute('INSERT INTO comments (post_id, user_id, content) VALUES (?, ?, ?)',
                             (post_id, session['user_id'], content))
                conn.commit()
                flash('Комментарий добавлен')
            else:
                flash('Комментарий не может быть пустым')

    comments = conn.execute('''
        SELECT c.*, u.username
        FROM comments c JOIN users u ON c.user_id = u.id
        WHERE c.post_id = ?
        ORDER BY c.created_at ASC
    ''', (post_id,)).fetchall()

    subreddits = conn.execute('SELECT name FROM subreddits ORDER BY name').fetchall()
    conn.close()

    return render_template('post.html', post=post, comments=comments, subreddits=subreddits)

@main_bp.route('/vote/<int:post_id>/<action>')
def vote(post_id, action):
    if 'user_id' not in session:
        flash('Нужно войти для голосования')
        return redirect(url_for('main.index'))

    delta = 1 if action == 'up' else -1
    conn = get_db_connection()
    conn.execute('UPDATE posts SET votes = votes + ? WHERE id = ?', (delta, post_id))
    conn.commit()
    conn.close()
    return redirect(request.referrer or url_for('main.index'))