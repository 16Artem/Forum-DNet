from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime
import time
import os
import json
import logging
import markdown
import uuid
from functools import lru_cache
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Инициализация логгера
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Конфигурация приложения
app = Flask(__name__)
app.secret_key = os.urandom(32).hex()

# Инициализация WebSocket
socketio = SocketIO(app)

# Инициализация лимитера запросов
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)

# Конфигурация путей
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data', 'user_table')
USERS_FILE = os.path.join(DATA_DIR, 'users.json')
AVATARS_DIR = os.path.join(DATA_DIR, 'avatars_ID')
STATIC_IMG_DIR = os.path.join(BASE_DIR, 'static', 'img')
POSTS_DIR = os.path.join(BASE_DIR, 'data', 'posts_table')
UPLOADS_DIR = os.path.join(BASE_DIR, 'uploads')

# Разрешенные расширения файлов
ALLOWED_EXTENSIONS = {
    'png', 'jpg', 'jpeg', 'gif', 'pdf', 'txt', 'zip', 'rar', 
    '7z', 'js', 'py', 'java', 'cpp', 'h', 'cs', 'go', 'rb', 'php', 'sh'
}

# Создание необходимых директорий
os.makedirs(AVATARS_DIR, exist_ok=True)
os.makedirs(STATIC_IMG_DIR, exist_ok=True)
os.makedirs(POSTS_DIR, exist_ok=True)
os.makedirs(UPLOADS_DIR, exist_ok=True)

# ==============================================
# Вспомогательные функции
# ==============================================

def allowed_file(filename):
    """Проверяет, разрешено ли расширение файла"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@lru_cache(maxsize=128)
def get_user(user_id):
    """Возвращает данные пользователя с fallback-значениями"""
    users = load_users()
    user = next((u for u in users['users'] if u['user.id'] == user_id), None)
    return {
        'username': user['username'] if user else 'Аноним',
        'avatar': user['avatar'] if user and 'avatar' in user else 'standard_user_avatar.png',
        'role': user.get('role', 'user') if user else 'guest'
    }

def load_users():
    """Загружает список пользователей из файла"""
    try:
        with open(USERS_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading users: {e}")
        return {"users": []}

def save_users(data):
    """Сохраняет список пользователей в файл"""
    try:
        with open(USERS_FILE, 'w') as f:
            json.dump(data, f, indent=4)
        return True
    except Exception as e:
        logger.error(f"Error saving users: {e}")
        return False

def init_users_file():
    """Инициализирует файл пользователей, если он не существует"""
    if not os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'w') as f:
            json.dump({"users": []}, f)

def init_posts_files():
    """Инициализирует файлы с вопросами для всех категорий и подтем"""
    categories = {
        'programming': ['javascript', 'python', 'java', 'cpp', 'csharp', 'go', 'ruby', 'php', 'swift', 'kotlin', 'assembler', 'typescript', 'rust'],
        'data-analysis': ['sql', 'pandas', 'numpy', 'ml', 'analytics', 'bigdata'],
        'design': ['uiux', 'figma', 'photoshop', 'illustrator', 'webdesign', 'mobiledesign'],
        'devops': ['docker', 'kubernetes', 'cicd', 'aws', 'azure', 'sysadmin'],
        'mobile': ['android', 'ios', 'flutter', 'reactnative']
    }
    
    for category, subcategories in categories.items():
        category_dir = os.path.join(POSTS_DIR, category)
        os.makedirs(category_dir, exist_ok=True)
        
        for subcategory in subcategories:
            file_path = os.path.join(category_dir, f"{subcategory}.json")
            if not os.path.exists(file_path):
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump({
                        "category": category,
                        "subcategory": subcategory,
                        "posts": []
                    }, f, indent=4, ensure_ascii=False)

def load_posts(category, subcategory):
    """Загружает вопросы для указанной категории и подкатегории"""
    try:
        file_path = os.path.join(POSTS_DIR, category, f"{subcategory}.json")
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            data['posts'] = [process_post(post) for post in data.get('posts', [])]
            return data
    except Exception as e:
        logger.error(f"Error loading posts: {e}")
        return None

def process_post(post):
    """Обрабатывает пост, добавляя обязательные поля"""
    post.setdefault('answers', [])
    post.setdefault('views', 0)
    post.setdefault('likes', 0)
    post.setdefault('dislikes', 0)
    return post

def load_post_by_id(post_id):
    """Находит вопрос по ID во всех файлах"""
    for root, dirs, files in os.walk(POSTS_DIR):
        for file in files:
            if file.endswith('.json'):
                try:
                    with open(os.path.join(root, file), 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        for post in data.get('posts', []):
                            if post['id'] == post_id:
                                return post, data['category'], data['subcategory']
                except Exception as e:
                    logger.error(f"Error searching post: {e}")
    return None, None, None

def save_post(category, subcategory, post_data):
    """Сохраняет или обновляет вопрос"""
    try:
        file_path = os.path.join(POSTS_DIR, category, f"{subcategory}.json")
        
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if 'id' in post_data:
            for i, post in enumerate(data['posts']):
                if post['id'] == post_data['id']:
                    if 'answers' in post_data:
                        post['answers'] = post_data['answers']
                    if 'views' in post_data:
                        post['views'] = post_data['views']
                    if 'likes' in post_data:
                        post['likes'] = post_data['likes']
                    if 'dislikes' in post_data:
                        post['dislikes'] = post_data['dislikes']
                    break
            else:
                data['posts'].append(post_data)
        else:
            data['posts'].append(post_data)
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
            
        return True
    except Exception as e:
        logger.error(f"Error saving post: {e}")
        return False

def save_uploaded_files(files, post_id):
    """Сохраняет загруженные файлы на сервер"""
    saved_files = []
    for file in files:
        if file and allowed_file(file.filename):
            filename = secure_filename(f"{post_id}_{file.filename}")
            filepath = os.path.join(UPLOADS_DIR, filename)
            file.save(filepath)
            saved_files.append(filename)
    return saved_files

# ==============================================
# Middleware и обработчики WebSocket
# ==============================================

@app.before_request
def check_ban():
    """Проверяет, забанен ли пользователь"""
    if request.path.startswith('/static/') or request.path == '/banned':
        return

    if 'user_id' in session:
        users = load_users()
        user = next((u for u in users['users'] if u['user.id'] == session['user_id']), None)
        if user and user.get('role') == 'banned':
            return redirect(url_for('banned_page'))

@socketio.on('join_question')
def handle_join_question(data):
    """Обрабатывает подключение к комнате вопроса"""
    try:
        question_id = data['question_id']
        join_room(question_id)
        emit('status', {'message': f'Connected to question {question_id}'}, room=request.sid)
    except Exception as e:
        emit('error', {'message': str(e)}, room=request.sid)
        logger.error(f"Error joining room: {e}")

@socketio.on('new_answer')
def handle_new_answer(data):
    """Обрабатывает новый ответ через WebSocket"""
    try:
        question_id = data['question_id']
        content = data['content']
        user_id = session.get('user_id')
        
        if not user_id:
            emit('error', {'message': 'Необходима авторизация'}, room=request.sid)
            return
        
        users = load_users()
        user = next((u for u in users['users'] if u['user.id'] == user_id), None)
        if not user:
            emit('error', {'message': 'Пользователь не найден'}, room=request.sid)
            return
        
        post, category, subcategory = load_post_by_id(question_id)
        if not post:
            emit('error', {'message': 'Вопрос не найден'}, room=request.sid)
            return
        
        answer_id = f"answer_{uuid.uuid4().hex}"
        
        new_answer = {
            'id': answer_id,
            'author': {
                'username': user['username'],
                'avatar': user['avatar'],
                'role': user.get('role', 'user')
            },
            'date': datetime.now().strftime("%d.%m.%Y %H:%M"),
            'content': content,
            'likes': 0,
            'dislikes': 0
        }
        
        updated_post = post.copy()
        updated_post.setdefault('answers', []).append(new_answer)
        
        if save_post(category, subcategory, updated_post):
            emit('new_answer', {
                'answer': new_answer,
                'answers_count': len(updated_post['answers']),
                'sender_id': request.sid
            }, room=question_id, include_self=False)
            
            emit('answer_saved', {
                'answer_id': answer_id,
                'answers_count': len(updated_post['answers'])
            }, room=request.sid)
        else:
            emit('error', {'message': 'Ошибка сохранения ответа'}, room=request.sid)
    except Exception as e:
        emit('error', {'message': 'Внутренняя ошибка сервера'}, room=request.sid)
        logger.error(f"Error handling new answer: {e}")

@socketio.on('connect')
def handle_connect():
    """Обрабатывает подключение клиента через WebSocket"""
    emit('connected', {'status': 'ok'})

@socketio.on('disconnect')
def handle_disconnect():
    """Обрабатывает отключение клиента через WebSocket"""
    logger.info('Client disconnected')

# ==============================================
# Роуты аутентификации и профиля
# ==============================================

@app.route('/')
def home():
    """Перенаправляет на страницу входа или список вопросов"""
    if 'user_id' in session:
        return redirect(url_for('view_questions'))
    return redirect(url_for('login'))

@app.route('/banned')
def banned_page():
    """Отображает страницу бана"""
    return render_template('banned.html')

@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("5/5minutes")
def login():
    """Обрабатывает вход пользователя"""
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        users = load_users()
        user = next((u for u in users['users'] if u['username'] == username), None)

        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['user.id']
            session['username'] = user['username']
            session['role'] = user['role']
            flash('Вход выполнен успешно', 'success')
            return redirect(url_for('profile_settings'))

        flash('Неверные учетные данные', 'error')

    return render_template('Logins_reg_system/login.html')

@app.route('/register', methods=['GET', 'POST'])
@limiter.limit("5/5minutes")
def register():
    """Обрабатывает регистрацию пользователя"""
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        confirm = request.form.get('confirm_password', '').strip()

        if not all([username, password, confirm]):
            flash('Все поля обязательны', 'error')
        elif len(username) < 3:
            flash('Имя слишком короткое', 'error')
        elif len(password) < 6:
            flash('Пароль слишком короткий', 'error')
        elif password != confirm:
            flash('Пароли не совпадают', 'error')
        else:
            users = load_users()
            if any(u['username'] == username for u in users['users']):
                flash('Имя занято', 'error')
            else:
                new_user = {
                    "user.id": len(users['users']) + 1,
                    "avatar": "static/img/standard_user_avatar.png",
                    "registration_date": datetime.now().strftime("%Y-%m-%d"),
                    "username": username,
                    "user.ip": request.remote_addr,
                    "password": generate_password_hash(password),
                    "role": "user"
                }
                users['users'].append(new_user)
                if save_users(users):
                    flash('Регистрация успешна!', 'success')
                    return redirect(url_for('login'))
                flash('Ошибка сохранения', 'error')

    return render_template('Logins_reg_system/register.html')

@app.route('/profile/settings', methods=['GET', 'POST'])
def profile_settings():
    """Отображает и обрабатывает настройки профиля"""
    if 'user_id' not in session:
        return redirect(url_for('login'))

    users = load_users()
    user = next((u for u in users['users'] if u['user.id'] == session['user_id']), None)

    if not user:
        session.clear()
        return redirect(url_for('login'))

    if request.method == 'POST' and 'avatar' in request.files:
        avatar = request.files['avatar']
        if avatar.filename != '':
            try:
                if user['avatar'].startswith('avatars_ID/'):
                    old_avatar = os.path.join(AVATARS_DIR, user['avatar'].split('/')[1])
                    if os.path.exists(old_avatar):
                        os.remove(old_avatar)

                ext = os.path.splitext(avatar.filename)[1]
                new_filename = f"user_{user['user.id']}_{int(time.time())}{ext}"
                avatar_path = os.path.join(AVATARS_DIR, new_filename)

                avatar.save(avatar_path)
                user['avatar'] = f"avatars_ID/{new_filename}"

                if save_users(users):
                    flash('Аватар успешно обновлен', 'success')
                else:
                    flash('Ошибка сохранения данных', 'error')

            except Exception as e:
                logger.error(f"Error updating avatar: {e}")
                flash('Ошибка при обновлении аватара', 'error')

            return redirect(url_for('profile_settings'))

    return render_template('setting_user.html', user=user)

@app.route('/avatar/<path:avatar_path>')
def get_avatar(avatar_path):
    """Отдает аватар пользователя"""
    if avatar_path.startswith('avatars_ID/'):
        return send_from_directory(DATA_DIR, avatar_path)
    else:
        return send_from_directory(os.path.join(BASE_DIR, 'static'), avatar_path)

@app.route('/logout')
def logout():
    """Обрабатывает выход пользователя"""
    session.clear()
    flash('Вы вышли из системы', 'info')
    return redirect(url_for('login'))

# ==============================================
# Роуты вопросов и ответов
# ==============================================

@app.route('/questions')
def view_questions():
    """Отображает список всех вопросов"""
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user = get_user(session['user_id'])
    if not user:
        session.clear()
        return redirect(url_for('login'))

    all_posts = []
    for root, dirs, files in os.walk(POSTS_DIR):
        for file in files:
            if file.endswith('.json'):
                try:
                    with open(os.path.join(root, file), 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        for post in data.get('posts', []):
                            post['author'] = get_user(post['author_id'])
                            post['category'] = data['category']
                            post['subcategory'] = data['subcategory']
                        all_posts.extend(data.get('posts', []))
                except Exception as e:
                    logger.error(f"Error loading posts: {e}")

    return render_template(
        'questions_list.html',
        user=user,
        posts=all_posts
    )

@app.route('/questions/<category>/<subcategory>')
def view_questions_by_category(category, subcategory):
    """Отображает вопросы по конкретной категории"""
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user = get_user(session['user_id'])
    if not user:
        session.clear()
        return redirect(url_for('login'))

    posts_data = load_posts(category, subcategory)
    if not posts_data:
        flash('Вопросы по данной теме не найдены', 'error')
        return redirect(url_for('view_questions'))

    for post in posts_data['posts']:
        post['author'] = get_user(post['author_id'])

    return render_template(
        'questions_list.html',
        user=user,
        category=category,
        subcategory=subcategory,
        posts=posts_data['posts']
    )

@app.route('/question/<post_id>')
def view_question(post_id):
    """Отображает конкретный вопрос с ответами"""
    if 'user_id' not in session:
        return redirect(url_for('login'))

    current_user = get_user(session['user_id'])
    if not current_user:
        session.clear()
        return redirect(url_for('login'))

    post, category, subcategory = load_post_by_id(post_id)
    if not post:
        flash('Вопрос не найден', 'error')
        return redirect(url_for('view_questions'))

    if 'author_id' in post:
        post['author'] = get_user(post['author_id'])
    else:
        post['author'] = {
            'username': 'Аноним',
            'avatar': 'standard_user_avatar.png',
            'role': 'guest'
        }

    return render_template(
        'answed.html',
        user=current_user,
        post=post,
        category=category,
        subcategory=subcategory
    )

@app.route('/questions/create', methods=['GET'])
def create_question():
    """Отображает форму создания вопроса"""
    if 'user_id' not in session:
        return redirect(url_for('login'))

    users = load_users()
    user = next((u for u in users['users'] if u['user.id'] == session['user_id']), None)

    if not user:
        session.clear()
        return redirect(url_for('login'))

    return render_template('create_question.html', user=user)

@app.route('/questions/create', methods=['POST'])
def create_question_post():
    """Обрабатывает создание нового вопроса"""
    if 'user_id' not in session:
        return redirect(url_for('login'))

    users = load_users()
    user = next((u for u in users['users'] if u['user.id'] == session['user_id']), None)

    if not user:
        session.clear()
        return redirect(url_for('login'))

    title = request.form.get('title', '').strip()
    content = request.form.get('content', '').strip()
    category = request.form.get('category', '').strip()
    subcategory = request.form.get('subcategory', '').strip()
    tags = request.form.get('tags', '').strip()
    
    if not all([title, content, category, subcategory]):
        flash('Все обязательные поля должны быть заполнены', 'error')
        return redirect(url_for('create_question'))
    
    post_id = f"post_{uuid.uuid4().hex}"
    files = request.files.getlist('files')
    saved_files = save_uploaded_files(files, post_id)
    
    new_post = {
        'id': post_id,
        'title': title,
        'author_id': session['user_id'],
        'date': datetime.now().strftime("%d.%m.%Y %H:%M"),
        'content': content,
        'views': 0,
        'likes': 0,
        'dislikes': 0,
        'tags': [tag.strip() for tag in tags.split(',') if tag.strip()],
        'files': saved_files,
        'answers': []
    }

    if save_post(category, subcategory, new_post):
        flash('Вопрос успешно создан!', 'success')
        return redirect(url_for('view_question', post_id=post_id))
    else:
        flash('Ошибка при сохранении вопроса', 'error')
        return redirect(url_for('create_question'))

@app.route('/api/questions/<post_id>/answer', methods=['POST'])
@limiter.limit("1 per minute")
def add_answer(post_id):
    """Добавляет ответ на вопрос через API"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Необходима авторизация'}), 401

    content = request.form.get('content', '').strip()
    if not content:
        return jsonify({'success': False, 'error': 'Ответ не может быть пустым'}), 400

    post, category, subcategory = load_post_by_id(post_id)
    if not post:
        return jsonify({'success': False, 'error': 'Вопрос не найден'}), 404

    author = get_user(session['user_id'])
    if not author:
        return jsonify({'success': False, 'error': 'Пользователь не найден'}), 404

    new_answer = {
        'id': f"answer_{uuid.uuid4().hex}",
        'author': {
            'username': author['username'],
            'avatar': author['avatar'],
            'role': author.get('role', 'user')
        },
        'date': datetime.now().strftime("%d.%m.%Y %H:%M"),
        'content': content,
        'likes': 0,
        'dislikes': 0
    }

    updated_post = post.copy()
    updated_post.setdefault('answers', []).append(new_answer)

    if save_post(category, subcategory, updated_post):
        return jsonify({'success': True, 'answer': new_answer})
    else:
        return jsonify({'success': False, 'error': 'Ошибка при сохранении ответа'}), 500

# ==============================================
# API endpoints
# ==============================================

@app.route('/api/subthemes/<category>')
def get_subthemes(category):
    """Возвращает список подтем для указанной категории"""
    subthemes = {
        'programming': [
            {'id': 'javascript', 'name': 'JavaScript'},
            {'id': 'python', 'name': 'Python'},
            {'id': 'java', 'name': 'Java'},
            {'id': 'cpp', 'name': 'C/C++'},
            {'id': 'csharp', 'name': 'C#'},
            {'id': 'go', 'name': 'Go'},
            {'id': 'ruby', 'name': 'Ruby'},
            {'id': 'php', 'name': 'PHP'},
            {'id': 'swift', 'name': 'Swift'},
            {'id': 'kotlin', 'name': 'Kotlin'},
            {'id': 'assembler', 'name': 'Assembler'},
            {'id': 'typescript', 'name': 'TypeScript'},
            {'id': 'rust', 'name': 'Rust'}
        ],
        'data-analysis': [
            {'id': 'sql', 'name': 'SQL'},
            {'id': 'pandas', 'name': 'Pandas'},
            {'id': 'numpy', 'name': 'NumPy'},
            {'id': 'ml', 'name': 'Машинное обучение'},
            {'id': 'analytics', 'name': 'Аналитика'},
            {'id': 'bigdata', 'name': 'Big Data'}
        ],
        'design': [
            {'id': 'uiux', 'name': 'UI/UX'},
            {'id': 'figma', 'name': 'Figma'},
            {'id': 'photoshop', 'name': 'Adobe Photoshop'},
            {'id': 'illustrator', 'name': 'Illustrator'},
            {'id': 'webdesign', 'name': 'Web Design'},
            {'id': 'mobiledesign', 'name': 'Mobile Design'}
        ],
        'devops': [
            {'id': 'docker', 'name': 'Docker'},
            {'id': 'kubernetes', 'name': 'Kubernetes'},
            {'id': 'cicd', 'name': 'CI/CD'},
            {'id': 'aws', 'name': 'AWS'},
            {'id': 'azure', 'name': 'Azure'},
            {'id': 'sysadmin', 'name': 'Системное Администрирование'}
        ],
        'mobile': [
            {'id': 'android', 'name': 'Android'},
            {'id': 'ios', 'name': 'iOS'},
            {'id': 'flutter', 'name': 'Flutter'},
            {'id': 'reactnative', 'name': 'React Native'}
        ]
    }
    return jsonify(subthemes.get(category, []))

@app.route('/api/questions/create', methods=['POST'])
@limiter.limit("5 per minute")
def api_create_question():
    """Создает новый вопрос через API"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Необходима авторизация'}), 401

    try:
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()
        category = request.form.get('category', '').strip()
        subcategory = request.form.get('subcategory', '').strip()
        tags = request.form.get('tags', '').strip()
        
        if not all([title, content, category, subcategory]):
            return jsonify({'success': False, 'error': 'Все обязательные поля должны быть заполнены'}), 400
        
        post_id = f"post_{uuid.uuid4().hex}"
        files = request.files.getlist('files')
        saved_files = save_uploaded_files(files, post_id)
        
        new_post = {
            'id': post_id,
            'title': title,
            'author_id': session['user_id'],
            'date': datetime.now().strftime("%d.%m.%Y %H:%M"),
            'content': content,
            'views': 0,
            'likes': 0,
            'dislikes': 0,
            'tags': [tag.strip() for tag in tags.split(',') if tag.strip()],
            'files': saved_files,
            'answers': []
        }

        if save_post(category, subcategory, new_post):
            socketio.emit('new_question', {
                'category': category,
                'subcategory': subcategory,
                'post_id': post_id
            })
            
            return jsonify({
                'success': True,
                'post_id': post_id,
                'redirect': url_for('view_question', post_id=post_id)
            })
        else:
            return jsonify({'success': False, 'error': 'Ошибка при сохранении вопроса'}), 500

    except Exception as e:
        logger.error(f"Error creating question: {e}")
        return jsonify({'success': False, 'error': 'Внутренняя ошибка сервера'}), 500

@app.route('/htmx/questions', methods=['GET'])
def htmx_questions():
    """Возвращает список вопросов для HTMX"""
    if 'user_id' not in session:
        return "", 401

    category = request.args.get('category')
    subcategory = request.args.get('subcategory')

    if category and subcategory:
        posts_data = load_posts(category, subcategory)
        if not posts_data:
            return render_template('partials/no_questions.html')

        for post in posts_data['posts']:
            post['author'] = get_user(post['author_id'])

        return render_template(
            'partials/questions_list_partial.html',
            posts=posts_data['posts']
        )
    else:
        all_posts = []
        for root, dirs, files in os.walk(POSTS_DIR):
            for file in files:
                if file.endswith('.json'):
                    try:
                        with open(os.path.join(root, file), 'r', encoding='utf-8') as f:
                            data = json.load(f)
                            for post in data.get('posts', []):
                                post['author'] = get_user(post['author_id'])
                            all_posts.extend(data.get('posts', []))
                    except Exception as e:
                        logger.error(f"Error loading posts: {e}")

        return render_template(
            'partials/questions_list_partial.html',
            posts=all_posts
        )

@app.route('/vote', methods=['POST'])
@limiter.limit("10 per 60 seconds")
def vote():
    """Обрабатывает голосование за вопрос"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    try:
        data = request.get_json()
        question_id = data.get('question_id')
        vote_type = data.get('vote_type')
        
        if not question_id or vote_type not in ['like', 'dislike']:
            return jsonify({'success': False, 'error': 'Invalid data'}), 400
        
        post, category, subcategory = load_post_by_id(question_id)
        if not post:
            return jsonify({'success': False, 'error': 'Question not found'}), 404
        
        if vote_type == 'like':
            post['likes'] = post.get('likes', 0) + 1
            if 'dislikes' in post and post['dislikes'] > 0:
                post['dislikes'] -= 1
        else:
            post['dislikes'] = post.get('dislikes', 0) + 1
            if 'likes' in post and post['likes'] > 0:
                post['likes'] -= 1
        
        if save_post(category, subcategory, post):
            post['author'] = get_user(post['author_id'])
            return render_template('partials/question_card.html', post=post)
        else:
            return jsonify({'success': False, 'error': 'Save error'}), 500
            
    except Exception as e:
        logger.error(f"Error processing vote: {e}")
        return jsonify({'success': False, 'error': 'Server error'}), 500

# ==============================================
# Прочие роуты
# ==============================================

@app.route('/forum')
def forum_home():
    """Главная страница форума"""
    if 'user_id' not in session:
        return redirect(url_for('login'))

    users = load_users()
    user = next((u for u in users['users'] if u['user.id'] == session['user_id']), None)

    if not user:
        session.clear()
        return redirect(url_for('login'))

    return render_template('index.html', user=user)

@app.route('/favicon.ico')
def favicon():
    """Отдает favicon"""
    return send_from_directory(
        os.path.join(app.root_path, 'static'),
        'favicon.ico',
        mimetype='image/vnd.microsoft.icon'
    )

@app.template_filter('markdown')
def markdown_filter(text):
    """Фильтр для преобразования markdown в HTML"""
    return markdown.markdown(text)

# ==============================================
# Запуск приложения
# ==============================================

if __name__ == '__main__':
    init_users_file()
    init_posts_files()
    
    socketio.run(
        app, 
        host='0.0.0.0', 
        port=5000, 
        debug=True
    )