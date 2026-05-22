from flask_mail import Mail, Message
import secrets
import os
import psycopg2
from psycopg2.extras import RealDictCursor

from flask import Flask, render_template, request, redirect, url_for, session
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'deadlockdrop_secret'
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'deadlockdrop@gmail.com'
app.config['MAIL_PASSWORD'] = 'mqnxcztjrfkannhh'
mail = Mail(app)

DATABASE_URL = os.environ.get('DATABASE_URL')

def get_db():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS features (id SERIAL PRIMARY KEY, title TEXT NOT NULL, description TEXT, category TEXT DEFAULT 'general', votes INTEGER DEFAULT 0, status TEXT DEFAULT 'requested')''')
    cur.execute('''CREATE TABLE IF NOT EXISTS comments (id SERIAL PRIMARY KEY, feature_id INTEGER NOT NULL, username TEXT NOT NULL, body TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, username TEXT UNIQUE NOT NULL, email TEXT, password TEXT NOT NULL, reset_token TEXT)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS votes (user_id TEXT NOT NULL, feature_id INTEGER NOT NULL, PRIMARY KEY (user_id, feature_id))''')
    conn.commit()
    cur.close()
    conn.close()

@app.route('/')
def home():
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT * FROM features ORDER BY votes DESC LIMIT 3')
    top_features = cur.fetchall()
    cur.execute('SELECT COUNT(*) FROM features')
    total_requests = cur.fetchone()['count']
    cur.execute('SELECT SUM(votes) FROM features')
    total_votes = cur.fetchone()['sum'] or 0
    cur.execute('SELECT COUNT(*) FROM features WHERE status = %s', ('added',))
    shipped_count = cur.fetchone()['count']
    cur.close()
    conn.close()
    return render_template('home.html', top_features=top_features, total_requests=total_requests, total_votes=total_votes, shipped_count=shipped_count)

@app.route('/requests')
def index():
    category = request.args.get('category', 'all')
    search = request.args.get('search', '')
    sort = request.args.get('sort', 'votes')
    conn = get_db()
    cur = conn.cursor()
    query = 'SELECT * FROM features'
    params = []
    conditions = []
    if category != 'all':
        conditions.append('category = %s')
        params.append(category)
    if search:
        conditions.append('(title LIKE %s OR description LIKE %s)')
        params.extend([f'%{search}%', f'%{search}%'])
    if conditions:
        query += ' WHERE ' + ' AND '.join(conditions)
    if sort == 'newest':
        query += ' ORDER BY id DESC'
    elif sort == 'planned':
        query += " ORDER BY CASE status WHEN 'planned' THEN 0 WHEN 'requested' THEN 1 WHEN 'added' THEN 2 END"
    else:
        query += ' ORDER BY votes DESC'
    cur.execute(query, params)
    features = cur.fetchall()
    comment_counts = {}
    for f in features:
        cur.execute('SELECT COUNT(*) FROM comments WHERE feature_id = %s', (f['id'],))
        comment_counts[f['id']] = cur.fetchone()['count']
    cur.close()
    conn.close()
    return render_template('index.html', features=features, active_category=category, search=search, sort=sort, comment_counts=comment_counts)

@app.route('/submit', methods=['POST'])
def submit():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    title = request.form['title']
    description = request.form['description']
    category = request.form['category']
    conn = get_db()
    cur = conn.cursor()
    cur.execute('INSERT INTO features (title, description, category) VALUES (%s, %s, %s)', (title, description, category))
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for('index'))

@app.route('/upvote/<int:id>')
def upvote(id):
    voter_id = str(session.get('user_id') or request.remote_addr)
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT 1 FROM votes WHERE user_id = %s AND feature_id = %s', (voter_id, id))
    already_voted = cur.fetchone()
    if not already_voted:
        cur.execute('UPDATE features SET votes = votes + 1 WHERE id = %s', (id,))
        cur.execute('INSERT INTO votes (user_id, feature_id) VALUES (%s, %s)', (voter_id, id))
        conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for('index'))

@app.route('/feature/<int:id>')
def feature(id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT * FROM features WHERE id = %s', (id,))
    f = cur.fetchone()
    cur.execute('SELECT * FROM comments WHERE feature_id = %s ORDER BY created_at DESC', (id,))
    comments = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('feature.html', feature=f, comments=comments)

@app.route('/comment/<int:feature_id>', methods=['POST'])
def comment(feature_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    body = request.form['body']
    username = session['username']
    conn = get_db()
    cur = conn.cursor()
    cur.execute('INSERT INTO comments (feature_id, username, body) VALUES (%s, %s, %s)', (feature_id, username, body))
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for('feature', id=feature_id))

@app.route('/register', methods=['GET', 'POST'])
def register():
    error = None
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT id FROM users WHERE username = %s OR email = %s', (username, email))
        existing = cur.fetchone()
        if existing:
            error = 'Username or email already taken.'
        else:
            cur.execute('INSERT INTO users (username, email, password) VALUES (%s, %s, %s)',
                (username, email, generate_password_hash(password, method='pbkdf2:sha256')))
            conn.commit()
            cur.close()
            conn.close()
            return redirect(url_for('login'))
        cur.close()
        conn.close()
    return render_template('register.html', error=error)

@app.route('/forgot', methods=['GET', 'POST'])
def forgot():
    message = None
    if request.method == 'POST':
        email = request.form['email']
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT * FROM users WHERE email = %s', (email,))
        user = cur.fetchone()
        if user:
            token = secrets.token_urlsafe(32)
            cur.execute('UPDATE users SET reset_token = %s WHERE email = %s', (token, email))
            conn.commit()
            reset_url = url_for('reset_password', token=token, _external=True)
            msg = Message('DeadlockDrop — Reset Your Password', sender='deadlockdrop@gmail.com', recipients=[email])
            msg.body = f'Click the link to reset your password:\n\n{reset_url}\n\nIf you did not request this, ignore this email.'
            mail.send(msg)
        cur.close()
        conn.close()
        message = 'If that email exists, a reset link has been sent.'
    return render_template('forgot.html', message=message)

@app.route('/reset/<token>', methods=['GET', 'POST'])
def reset_password(token):
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT * FROM users WHERE reset_token = %s', (token,))
    user = cur.fetchone()
    if not user:
        cur.close()
        conn.close()
        return redirect(url_for('login'))
    error = None
    if request.method == 'POST':
        password = request.form['password']
        cur.execute('UPDATE users SET password = %s, reset_token = NULL WHERE id = %s',
            (generate_password_hash(password, method='pbkdf2:sha256'), user['id']))
        conn.commit()
        cur.close()
        conn.close()
        return redirect(url_for('login'))
    cur.close()
    conn.close()
    return render_template('reset.html', token=token, error=error)

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT * FROM users WHERE username = %s', (username,))
        user = cur.fetchone()
        if user and check_password_hash(user['password'], password):
            if username == 'admin' and user['email'] != 'subat0412@gmail.com':
                error = 'Unauthorized.'
            else:
                session['user_id'] = user['id']
                session['username'] = user['username']
                cur.close()
                conn.close()
                return redirect(url_for('index'))
        else:
            error = 'Invalid username or password.'
        cur.close()
        conn.close()
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

@app.route('/profile')
def profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    cur = conn.cursor()
    cur.execute('''SELECT f.* FROM features f JOIN votes v ON f.id = v.feature_id WHERE v.user_id = %s ORDER BY f.votes DESC''', (str(session['user_id']),))
    voted_features = cur.fetchall()
    cur.execute('SELECT * FROM comments WHERE username = %s ORDER BY created_at DESC', (session['username'],))
    comments = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('profile.html', voted_features=voted_features, comments=comments)

@app.route('/admin')
def admin():
    if session.get('username') != 'admin':
        return redirect(url_for('home'))
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT * FROM features ORDER BY votes DESC')
    features = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('admin.html', features=features)

@app.route('/update_status/<int:id>', methods=['POST'])
def update_status(id):
    if session.get('username') != 'admin':
        return redirect(url_for('home'))
    status = request.form['status']
    conn = get_db()
    cur = conn.cursor()
    cur.execute('UPDATE features SET status = %s WHERE id = %s', (status, id))
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for('admin'))

@app.route('/delete/<int:id>', methods=['POST'])
def delete_feature(id):
    if session.get('username') != 'admin':
        return redirect(url_for('home'))
    conn = get_db()
    cur = conn.cursor()
    cur.execute('DELETE FROM comments WHERE feature_id = %s', (id,))
    cur.execute('DELETE FROM votes WHERE feature_id = %s', (id,))
    cur.execute('DELETE FROM features WHERE id = %s', (id,))
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for('admin'))

@app.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit_feature(id):
    if session.get('username') != 'admin':
        return redirect(url_for('home'))
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT * FROM features WHERE id = %s', (id,))
    f = cur.fetchone()
    if request.method == 'POST':
        title = request.form['title']
        description = request.form['description']
        category = request.form['category']
        cur.execute('UPDATE features SET title = %s, description = %s, category = %s WHERE id = %s', (title, description, category, id))
        conn.commit()
        cur.close()
        conn.close()
        return redirect(url_for('admin'))
    cur.close()
    conn.close()
    return render_template('edit.html', feature=f)

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/roadmap')
def roadmap():
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT * FROM features WHERE status = %s ORDER BY votes DESC', ('requested',))
    requested = cur.fetchall()
    cur.execute('SELECT * FROM features WHERE status = %s ORDER BY votes DESC', ('planned',))
    planned = cur.fetchall()
    cur.execute('SELECT * FROM features WHERE status = %s ORDER BY votes DESC', ('added',))
    added = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('roadmap.html', requested=requested, planned=planned, added=added)

init_db()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=True)