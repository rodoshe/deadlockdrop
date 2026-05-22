from flask_mail import Mail, Message
import secrets

from flask import Flask, render_template, request, redirect, url_for, session
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'deadlockdrop_secret'
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'deadlockdrop@gmail.com'
app.config['MAIL_PASSWORD'] = 'mqnxcztjrfkannhh'
mail = Mail(app)
DB = "database.db"

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS features (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                category TEXT DEFAULT 'general',
                votes INTEGER DEFAULT 0,
                status TEXT DEFAULT 'requested'
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                feature_id INTEGER NOT NULL,
                username TEXT NOT NULL,
                body TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (feature_id) REFERENCES features(id)
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS votes (
                user_id INTEGER NOT NULL,
                feature_id INTEGER NOT NULL,
                PRIMARY KEY (user_id, feature_id)
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                reset_token TEXT
            )
        ''')
        conn.commit()

@app.route('/')
def home():
    db = get_db()
    top_features = db.execute('SELECT * FROM features ORDER BY votes DESC LIMIT 3').fetchall()
    total_requests = db.execute('SELECT COUNT(*) FROM features').fetchone()[0]
    total_votes = db.execute('SELECT SUM(votes) FROM features').fetchone()[0] or 0
    shipped_count = db.execute('SELECT COUNT(*) FROM features WHERE status = "added"').fetchone()[0]
    return render_template('home.html',
        top_features=top_features,
        total_requests=total_requests,
        total_votes=total_votes,
        shipped_count=shipped_count
    )

@app.route('/requests')
def index():
    category = request.args.get('category', 'all')
    search = request.args.get('search', '')
    sort = request.args.get('sort', 'votes')
    db = get_db()
    query = 'SELECT * FROM features'
    params = []
    conditions = []
    if category != 'all':
        conditions.append('category = ?')
        params.append(category)
    if search:
        conditions.append('(title LIKE ? OR description LIKE ?)')
        params.extend([f'%{search}%', f'%{search}%'])
    if conditions:
        query += ' WHERE ' + ' AND '.join(conditions)
    if sort == 'newest':
        query += ' ORDER BY id DESC'
    elif sort == 'planned':
        query += ' ORDER BY CASE status WHEN "planned" THEN 0 WHEN "requested" THEN 1 WHEN "added" THEN 2 END'
    else:
        query += ' ORDER BY votes DESC'
    features = db.execute(query, params).fetchall()
    comment_counts = {}
    for f in features:
        count = db.execute('SELECT COUNT(*) FROM comments WHERE feature_id = ?', (f['id'],)).fetchone()[0]
        comment_counts[f['id']] = count
    return render_template('index.html',
        features=features,
        active_category=category,
        search=search,
        sort=sort,
        comment_counts=comment_counts
    )

@app.route('/submit', methods=['POST'])
def submit():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    title = request.form['title']
    description = request.form['description']
    category = request.form['category']
    with get_db() as conn:
        conn.execute('INSERT INTO features (title, description, category) VALUES (?, ?, ?)',
            (title, description, category))
        conn.commit()
    return redirect(url_for('index'))

@app.route('/upvote/<int:id>')
def upvote(id):
    db = get_db()
    # use IP address to track votes for logged out users
    voter_id = session.get('user_id') or request.remote_addr
    already_voted = db.execute(
        'SELECT 1 FROM votes WHERE user_id = ? AND feature_id = ?', (voter_id, id)
    ).fetchone()
    if not already_voted:
        with get_db() as conn:
            conn.execute('UPDATE features SET votes = votes + 1 WHERE id = ?', (id,))
            conn.execute('INSERT INTO votes (user_id, feature_id) VALUES (?, ?)', (voter_id, id))
            conn.commit()
    return redirect(url_for('index'))

@app.route('/feature/<int:id>')
def feature(id):
    db = get_db()
    f = db.execute('SELECT * FROM features WHERE id = ?', (id,)).fetchone()
    comments = db.execute(
        'SELECT * FROM comments WHERE feature_id = ? ORDER BY created_at DESC', (id,)
    ).fetchall()
    return render_template('feature.html', feature=f, comments=comments)

@app.route('/comment/<int:feature_id>', methods=['POST'])
def comment(feature_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    body = request.form['body']
    username = session['username']
    with get_db() as conn:
        conn.execute('INSERT INTO comments (feature_id, username, body) VALUES (?, ?, ?)',
            (feature_id, username, body))
        conn.commit()
    return redirect(url_for('feature', id=feature_id))

@app.route('/register', methods=['GET', 'POST'])
def register():
    error = None
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        db = get_db()
        existing = db.execute('SELECT id FROM users WHERE username = ? OR email = ?', (username, email)).fetchone()
        if existing:
            error = 'Username or email already taken.'
        else:
            with get_db() as conn:
                conn.execute('INSERT INTO users (username, email, password) VALUES (?, ?, ?)',
                    (username, email, generate_password_hash(password, method='pbkdf2:sha256')))
                conn.commit()
            return redirect(url_for('login'))
    return render_template('register.html', error=error)

@app.route('/forgot', methods=['GET', 'POST'])
def forgot():
    message = None
    if request.method == 'POST':
        email = request.form['email']
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        if user:
            token = secrets.token_urlsafe(32)
            with get_db() as conn:
                conn.execute('UPDATE users SET reset_token = ? WHERE email = ?', (token, email))
                conn.commit()
            reset_url = url_for('reset_password', token=token, _external=True)
            msg = Message('DeadlockDrop — Reset Your Password',
                sender='your_gmail@gmail.com',
                recipients=[email])
            msg.body = f'Click the link to reset your password:\n\n{reset_url}\n\nIf you did not request this, ignore this email.'
            mail.send(msg)
        message = 'If that email exists, a reset link has been sent.'
    return render_template('forgot.html', message=message)

@app.route('/reset/<token>', methods=['GET', 'POST'])
def reset_password(token):
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE reset_token = ?', (token,)).fetchone()
    if not user:
        return redirect(url_for('login'))
    error = None
    if request.method == 'POST':
        password = request.form['password']
        with get_db() as conn:
            conn.execute('UPDATE users SET password = ?, reset_token = NULL WHERE id = ?',
                (generate_password_hash(password, method='pbkdf2:sha256'), user['id']))
            conn.commit()
        return redirect(url_for('login'))
    return render_template('reset.html', token=token, error=error)

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        if user and check_password_hash(user['password'], password):
            if username == 'admin' and user['email'] != 'subat0412@gmail.com':
                error = 'Unauthorized.'
            else:
                session['user_id'] = user['id']
                session['username'] = user['username']
                return redirect(url_for('index'))
        else:
            error = 'Invalid username or password.'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

@app.route('/profile')
def profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    db = get_db()
    user_id = session['user_id']
    voted_features = db.execute('''
        SELECT f.* FROM features f
        JOIN votes v ON f.id = v.feature_id
        WHERE v.user_id = ?
        ORDER BY f.votes DESC
    ''', (user_id,)).fetchall()
    comments = db.execute(
        'SELECT * FROM comments WHERE username = ? ORDER BY created_at DESC', (session['username'],)
    ).fetchall()
    return render_template('profile.html', voted_features=voted_features, comments=comments)

@app.route('/admin')
def admin():
    if session.get('username') != 'admin':
        return redirect(url_for('home'))
    db = get_db()
    features = db.execute('SELECT * FROM features ORDER BY votes DESC').fetchall()
    return render_template('admin.html', features=features)

@app.route('/update_status/<int:id>', methods=['POST'])
def update_status(id):
    if session.get('username') != 'admin':
        return redirect(url_for('home'))
    status = request.form['status']
    with get_db() as conn:
        conn.execute('UPDATE features SET status = ? WHERE id = ?', (status, id))
        conn.commit()
    return redirect(url_for('admin'))

@app.route('/delete/<int:id>', methods=['POST'])
def delete_feature(id):
    if session.get('username') != 'admin':
        return redirect(url_for('home'))
    with get_db() as conn:
        conn.execute('DELETE FROM comments WHERE feature_id = ?', (id,))
        conn.execute('DELETE FROM votes WHERE feature_id = ?', (id,))
        conn.execute('DELETE FROM features WHERE id = ?', (id,))
        conn.commit()
    return redirect(url_for('admin'))

@app.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit_feature(id):
    if session.get('username') != 'admin':
        return redirect(url_for('home'))
    db = get_db()
    f = db.execute('SELECT * FROM features WHERE id = ?', (id,)).fetchone()
    if request.method == 'POST':
        title = request.form['title']
        description = request.form['description']
        category = request.form['category']
        with get_db() as conn:
            conn.execute(
                'UPDATE features SET title = ?, description = ?, category = ? WHERE id = ?',
                (title, description, category, id)
            )
            conn.commit()
        return redirect(url_for('admin'))
    return render_template('edit.html', feature=f)

@app.route('/about')
def about():
    return render_template('about.html')
@app.route('/roadmap')
def roadmap():
    db = get_db()
    requested = db.execute('SELECT * FROM features WHERE status = "requested" ORDER BY votes DESC').fetchall()
    planned = db.execute('SELECT * FROM features WHERE status = "planned" ORDER BY votes DESC').fetchall()
    added = db.execute('SELECT * FROM features WHERE status = "added" ORDER BY votes DESC').fetchall()
    return render_template('roadmap.html', requested=requested, planned=planned, added=added)
    
if __name__ == '__main__':
    init_db()
    app.run(debug=True)
    
import os
if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))