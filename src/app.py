import os
import uuid
import requests
import psycopg2
import logging
import secrets
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
from flask import Flask, render_template, request, redirect, url_for, session, flash, abort, g
from fastapi import HTTPException
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import generate_password_hash, check_password_hash
import secrets
from cryptography.fernet import Fernet
from psycopg2 import pool
import json
from datetime import datetime
from collections import defaultdict
import math
from datetime import datetime, timedelta, timezone
import os

#load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev_secret_key")
csrf = CSRFProtect(app)
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is not set")
DATABASE_URL = "postgresql://neondb_owner:npg_sVpiT5WUa2ZC@ep-red-sea-as840pmv-pooler.c-4.eu-central-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
db_pool = None



def get_cipher():
    import base64
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    salt = b'fixed_salt'
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(app.secret_key.encode()))
    return Fernet(key)

def encrypt_key(plain_text):
    if not plain_text:
        return ""
    f = get_cipher()
    return f.encrypt(plain_text.encode()).decode()

def decrypt_key(cipher_text):
    if not cipher_text:
        return ""
    f = get_cipher()
    try:
        return f.decrypt(cipher_text.encode()).decode()
    except Exception as e:
        logger.error(f"Decryption error: {e}")
        return "DECRYPTION_ERROR"

def init_pool():
    global db_pool
    if db_pool is not None:
        return db_pool
    if not DATABASE_URL:
        logger.error("DATABASE_URL environment variable is missing!")
        return None
    try:
        db_pool = pool.ThreadedConnectionPool(
            1, 20, DATABASE_URL,
            connect_timeout=10,
            keepalives=1,
            keepalives_idle=30,
            keepalives_interval=10,
            keepalives_count=5
        )
        logger.info("Database connection pool created successfully")
        return db_pool
    except Exception as e:
        logger.error(f"Error creating connection pool: {e}")
        return None

init_pool()

@contextmanager
def get_db_cursor():
    pool_instance = init_pool()
    if pool_instance is None:
        raise Exception("Database connection pool could not be initialized. Please check your DATABASE_URL environment variable and network connectivity.")
    
    conn = pool_instance.getconn()
    
    # Robust validation: ensure the connection is alive before yielding
    try:
        # If the connection is closed or has issues, the ping will fail
        if conn.closed != 0:
            raise psycopg2.InterfaceError("Connection already closed")
            
        with conn.cursor() as ping_cur:
            ping_cur.execute("SELECT 1")
    except (psycopg2.InterfaceError, psycopg2.OperationalError):
        # Connection is stale/dead, attempt to get a fresh one once
        try:
            pool_instance.putconn(conn, close=True)
        except:
            pass
        conn = pool_instance.getconn()

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            yield cur
        if conn.closed == 0:
            conn.commit()
    except Exception as e:
        # Avoid crashing during rollback if the connection died during the operation
        if conn.closed == 0:
            try:
                conn.rollback()
            except psycopg2.InterfaceError:
                logger.warning("Could not rollback: connection already closed")
        raise e
    finally:
        if conn:
            # Return the connection to the pool, marking it for closure if it's dead
            pool_instance.putconn(conn, close=(conn.closed != 0))

def get_current_user_info():
    if hasattr(g, 'current_user'):
        return g.current_user

    if 'user_id' not in session:
        g.current_user = None
        return None
    
    # Refresh info from DB to ensure it's up to date
    try:
        with get_db_cursor() as cur:
            cur.execute("SELECT access_level FROM user_level WHERE user_email = %s", (session['email'],))
            level_data = cur.fetchone()
            if not level_data:
                session.clear()
                g.current_user = None
                return None
                
            cur.execute("SELECT group_name FROM user_groups WHERE user_email = %s", (session['email'],))
            groups = [r['group_name'] for r in cur.fetchall()]
            
            session['access_level'] = level_data['access_level']
            session['groups'] = groups
            
        g.current_user = {
            'id': session['user_id'],
            'email': session['email'],
            'access_level': session['access_level'],
            'groups': session['groups']
        }
        return g.current_user
    except Exception as e:
        logger.error(f"Error fetching user info: {e}")
        return None

def is_super_admin(user):
    return user and user['access_level'] == 'admin' and 'admin' in (user['groups'] or [])

def has_agent_access(user, agent_tags, creator_id, action='view'):
    if not user:
        return False
    
    # Super Admin has full access
    if is_super_admin(user):
        return True
    
    # Creator always has access
    if str(creator_id) == str(user['id']):
        return True
    
    # Group level admin check (editor or admin)
    if user['access_level'] in ['editor', 'admin']:
        user_groups = set(user['groups'] or [])
        agent_groups = set(agent_tags or [])
        if user_groups & agent_groups:
            return True
            
    return False

def get_current_user_id():
    user = get_current_user_info()
    return user['id'] if user else None

@app.context_processor
def inject_user():
    user = get_current_user_info()
    return dict(user=user)

def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = get_current_user_info()
        if not user or user['access_level'] != 'admin':
            flash('Admin access required.')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/admin')
@admin_required
def admin_panel():
    user = get_current_user_info()
    with get_db_cursor() as cur:
        cur.execute("""
            SELECT ul.*, u.id as user_id, u.name,
                   COALESCE(ARRAY_AGG(ug.group_name) FILTER (WHERE ug.group_name IS NOT NULL), '{}') as groups
            FROM user_level ul
            LEFT JOIN users u ON ul.user_email = u.email
            LEFT JOIN user_groups ug ON ul.user_email = ug.user_email
            GROUP BY ul.id, ul.user_email, ul.access_level, ul.created_at, u.id, u.name
            ORDER BY ul.created_at DESC
        """)
        users = cur.fetchall()
        cur.execute("""
            SELECT a.id, a.name, a.description, a.creation_date, a.tags, a.rag_enabled, a.paused,
                   COALESCE(ARRAY_AGG(s.name) FILTER (WHERE s.name IS NOT NULL), '{}') as linked_servers
            FROM agents a
            LEFT JOIN agent_integrations ai ON a.id = ai.agent_id
            LEFT JOIN mcp_servers s ON ai.integration_id = s.id
            GROUP BY a.id, a.name, a.description, a.creation_date, a.tags
            ORDER BY a.creation_date DESC
        """)
        agents = cur.fetchall()
        cur.execute("""
            SELECT g.*, COUNT(ug.user_email) as member_count
            FROM groups g
            LEFT JOIN user_groups ug ON g.name = ug.group_name
            GROUP BY g.id, g.name, g.created_at
            ORDER BY g.name ASC
        """)
        all_groups = cur.fetchall()
        cur.execute("SELECT * FROM models ORDER BY created_at DESC")
        models = cur.fetchall()
        cur.execute("""
            SELECT mc.*, m.name as model_name
            FROM model_constraints mc
            JOIN models m ON mc.model_id = m.id
            ORDER BY mc.created_at DESC
        """)
        constraints = cur.fetchall()
        cur.execute("""
            SELECT s.id, s.name, s.status, s.creator_user_id,
                   COUNT(DISTINCT ai.agent_id) as connection_count,
                   COALESCE((SELECT array_to_json(array_agg(t.tool_name)) 
                             FROM mcp_tools t WHERE t.server_id = s.id), '[]'::json) as tool_names,
                   COALESCE(ARRAY_AGG(a.name) FILTER (WHERE a.name IS NOT NULL), '{}') as connected_agents
            FROM mcp_servers s
            LEFT JOIN agent_integrations ai ON s.id = ai.integration_id
            LEFT JOIN agents a ON ai.agent_id = a.id
            GROUP BY s.id, s.name, s.status, s.creator_user_id
            ORDER BY s.name ASC
        """)
        mcp_infrastructure = cur.fetchall()
    print(agents)
    return render_template(
        'admin.html',
        user=user,
        users=users,
        agents=agents,
        groups=all_groups,
        models=models,
        constraints=constraints,
        mcp_infrastructure=mcp_infrastructure
    )

@app.route('/admin/add_user', methods=['POST'])
@admin_required
def admin_add_user():
    email = request.form.get('email')
    access_level = request.form.get('access_level')
    groups_raw = request.form.getlist('groups')
    with get_db_cursor() as cur:
        cur.execute("""
            INSERT INTO user_level (user_email, access_level)
            VALUES (%s, %s)
            ON CONFLICT (user_email) DO UPDATE 
            SET access_level = EXCLUDED.access_level
        """, (email, access_level))
        cur.execute("DELETE FROM user_groups WHERE user_email = %s", (email,))
        for group in groups_raw:
            cur.execute("INSERT INTO user_groups (user_email, group_name) VALUES (%s, %s)", (email, group))
    flash(f'User {email} added/updated.')
    return redirect(url_for('admin_panel'))

@app.route('/admin/delete_user/<email>', methods=['POST'])
@admin_required
def admin_delete_user(email):
    with get_db_cursor() as cur:
        cur.execute("DELETE FROM user_level WHERE user_email = %s", (email,))
    flash(f'User {email} removed from IAM.')
    return redirect(url_for('admin_panel'))

@app.route('/admin/delete_agent/<agent_id>', methods=['POST'])
@admin_required
def admin_delete_agent(agent_id):
    with get_db_cursor() as cur:
        cur.execute("DELETE FROM agent_integrations WHERE agent_id = %s", (agent_id,))
        cur.execute("DELETE FROM user_agent_suite WHERE agent_id = %s", (agent_id,))
        cur.execute("DELETE FROM prompt_system_versions WHERE agent_id = %s", (agent_id,))
        cur.execute("DELETE FROM agents WHERE id = %s", (agent_id,))
    flash('Agent and its associated mappings have been deleted.')
    return redirect(url_for('admin_panel'))

@app.route('/admin/add_group', methods=['POST'])
@admin_required
def admin_add_group():
    name = request.form.get('name')
    if name:
        with get_db_cursor() as cur:
            cur.execute("INSERT INTO groups (name) VALUES (%s) ON CONFLICT DO NOTHING", (name,))
        flash(f'Group {name} added.')
    return redirect(url_for('admin_panel'))

@app.route('/admin/delete_group/<name>', methods=['POST'])
@admin_required
def admin_delete_group(name):
    with get_db_cursor() as cur:
        cur.execute("DELETE FROM groups WHERE name = %s", (name,))
    flash(f'Group {name} deleted.')
    return redirect(url_for('admin_panel'))

@app.route('/admin/add_model', methods=['POST'])
@admin_required
def admin_add_model():
    name = request.form.get('name')
    base_url = request.form.get('base_url')
    api_key = request.form.get('api_key')
    encrypted_api_key = encrypt_key(api_key)
    with get_db_cursor() as cur:
        cur.execute("""
            INSERT INTO models (name, base_url, api_key)
            VALUES (%s, %s, %s)
            ON CONFLICT (name) DO UPDATE 
            SET base_url = EXCLUDED.base_url, api_key = EXCLUDED.api_key
        """, (name, base_url, encrypted_api_key))
    flash(f'Model {name} added/updated.')
    return redirect(url_for('admin_panel'))

@app.route('/admin/delete_model/<model_id>', methods=['POST'])
@admin_required
def admin_delete_model(model_id):
    with get_db_cursor() as cur:
        cur.execute("DELETE FROM models WHERE id = %s", (model_id,))
    flash('Model deleted.')
    return redirect(url_for('admin_panel'))

@app.route('/admin/add_constraint', methods=['POST'])
@admin_required
def admin_add_constraint():
    group_name = request.form.get('group_name')
    model_id = request.form.get('model_id')
    max_calls = request.form.get('max_calls')
    max_amount = request.form.get('max_amount')
    max_calls = int(max_calls) if max_calls else None
    max_amount = float(max_amount) if max_amount else None
    with get_db_cursor() as cur:
        cur.execute("""
            INSERT INTO model_constraints (group_name, model_id, max_calls, max_amount)
            VALUES (%s, %s, %s, %s)
        """, (group_name, model_id, max_calls, max_amount))
    flash('Constraint added.')
    return redirect(url_for('admin_panel'))

@app.route('/admin/delete_constraint/<constraint_id>', methods=['POST'])
@admin_required
def admin_delete_constraint(constraint_id):
    with get_db_cursor() as cur:
        cur.execute("DELETE FROM model_constraints WHERE id = %s", (constraint_id,))
    flash('Constraint deleted.')
    return redirect(url_for('admin_panel'))

@app.route('/admin/update_constraint/<constraint_id>', methods=['POST'])
@admin_required
def admin_update_constraint(constraint_id):
    group_name = request.form.get('group_name')
    model_id = request.form.get('model_id')
    max_calls = request.form.get('max_calls')
    max_amount = request.form.get('max_amount')
    max_calls = int(max_calls) if max_calls else None
    max_amount = float(max_amount) if max_amount else None
    with get_db_cursor() as cur:
        cur.execute("""
            UPDATE model_constraints 
            SET group_name = %s, model_id = %s, max_calls = %s, max_amount = %s
            WHERE id = %s
        """, (group_name, model_id, max_calls, max_amount, constraint_id))
    flash('Constraint updated.')
    return redirect(url_for('admin_panel'))


@app.route('/admin/delete_mcp/<server_id>', methods=['POST'])
@admin_required
def delete_mcp(server_id):
    with get_db_cursor() as cur:
        cur.execute("DELETE FROM agent_integrations WHERE integration_id = %s", (server_id,))
        cur.execute("DELETE FROM mcp_tools WHERE server_id = %s", (server_id,))
        cur.execute("DELETE FROM mcp_servers WHERE id = %s", (server_id,))
    flash('MCP Server node and all linked execution routes removed successfully!', 'success')
    return redirect(url_for('admin_panel'))

def init_db():
    pool_instance = init_pool()
    if not DATABASE_URL or pool_instance is None:
        logger.warning("DATABASE_URL or pool not ready. Skipping DB initialization.")
        return
    with open('schema.sql', 'r') as f:
        schema = f.read()
    conn = pool_instance.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(schema)
        conn.commit()
    except Exception as e:
        logger.error(f"Error during schema initialization: {e}")
    finally:
        pool_instance.putconn(conn)

init_db()

@app.errorhandler(404)
def page_not_found(e):
    return render_template('layout.html', content="Page Not Found"), 404

@app.errorhandler(500)
def internal_error(e):
    logger.error(f"Internal Server Error: {e}")
    return render_template('layout.html', content="Internal Server Error"), 500

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('index.html')

@app.route('/register', methods=['POST'])
def register():
    email = request.form.get('email')
    password = request.form.get('password')
    confirm_password = request.form.get('confirm_password')
    if password != confirm_password:
        flash('Passwords do not match.')
        return redirect(url_for('index'))
    with get_db_cursor() as cur:
        # Check if email is whitelisted in user_level
        cur.execute("SELECT 1 FROM user_level WHERE user_email = %s", (email,))
        if not cur.fetchone():
            flash('This user does not exist yet and they should contact their admin.')
            return redirect(url_for('index'))
        # Check if already registered
        cur.execute("SELECT 1 FROM users_email WHERE email = %s", (email,))
        if cur.fetchone():
            flash('Email already registered. Please log in.')
            return redirect(url_for('index'))
        # Register user
        password_hash = generate_password_hash(password)
        cur.execute("""
            INSERT INTO users_email (email, password_hash)
            VALUES (%s, %s)
        """, (email, password_hash))
        # Also ensure user exists in 'users' table for other relations
        cur.execute("""
            INSERT INTO users (google_id, email, name)
            VALUES (%s, %s, %s)
            ON CONFLICT (email) DO NOTHING
        """, (f"email|{email}", email, email.split('@')[0]))
    flash('Registration successful. Please log in.')
    return redirect(url_for('index'))

@app.route('/login', methods=['POST'])
def login():
    email = request.form.get('email')
    password = request.form.get('password')
    with get_db_cursor() as cur:
        cur.execute("SELECT password_hash FROM users_email WHERE email = %s", (email,))
        user_row = cur.fetchone()
        if user_row and check_password_hash(user_row['password_hash'], password):
            # Get user info for session
            cur.execute("SELECT id FROM users WHERE email = %s", (email,))
            user_data = cur.fetchone()
            cur.execute("SELECT access_level FROM user_level WHERE user_email = %s", (email,))
            level_data = cur.fetchone()
            cur.execute("SELECT group_name FROM user_groups WHERE user_email = %s", (email,))
            groups = [r['group_name'] for r in cur.fetchall()]
            session['user_id'] = str(user_data['id'])
            session['email'] = email
            session['access_level'] = level_data['access_level'] if level_data else 'editor'
            session['groups'] = groups
            flash('Logged in successfully!')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid email or password.')
            return redirect(url_for('index'))

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully.')
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    user = get_current_user_info()
    with get_db_cursor() as cur:
        # Fetch user's assigned groups if not already loaded
        if 'groups' not in user or user['groups'] is None:
            cur.execute("SELECT group_name FROM user_groups WHERE user_email = %s", (user['email'],))
            user['groups'] = [row['group_name'] for row in cur.fetchall()]

        # 1. User's own agents (with linked MCP server names and tool counts)
        cur.execute("""
            SELECT a.*, 
                   (SELECT COUNT(*) FROM agent_integrations ai WHERE ai.agent_id = a.id) as mcps_count,
                   COALESCE(ARRAY_AGG(s.name) FILTER (WHERE s.name IS NOT NULL), '{}') as linked_servers
            FROM agents a
            LEFT JOIN agent_integrations ai ON a.id = ai.agent_id
            LEFT JOIN mcp_servers s ON ai.integration_id = s.id
            WHERE a.creator_user_id = %s
            GROUP BY a.id
            ORDER BY a.creation_date DESC
        """, (user['id'],))
        agents = cur.fetchall()

        group_agents = []
        if is_super_admin(user):
            cur.execute("""
                SELECT a.*, u.name as creator_name,
                       (SELECT COUNT(*) FROM agent_integrations ai WHERE ai.agent_id = a.id) as mcps_count,
                       COALESCE(ARRAY_AGG(s.name) FILTER (WHERE s.name IS NOT NULL), '{}') as linked_servers
                FROM agents a
                JOIN users u ON a.creator_user_id = u.id
                LEFT JOIN agent_integrations ai ON a.id = ai.agent_id
                LEFT JOIN mcp_servers s ON ai.integration_id = s.id
                WHERE a.creator_user_id != %s
                GROUP BY a.id, u.name
                ORDER BY a.creation_date DESC
            """, (user['id'],))
            group_agents = cur.fetchall()
        elif user['access_level'] in ['editor', 'admin']:
            cur.execute("""
                SELECT a.*, u.name as creator_name,
                       (SELECT COUNT(*) FROM agent_integrations ai WHERE ai.agent_id = a.id) as mcps_count,
                       COALESCE(ARRAY_AGG(s.name) FILTER (WHERE s.name IS NOT NULL), '{}') as linked_servers
                FROM agents a
                JOIN users u ON a.creator_user_id = u.id
                LEFT JOIN agent_integrations ai ON a.id = ai.agent_id
                LEFT JOIN mcp_servers s ON ai.integration_id = s.id
                WHERE a.creator_user_id != %s AND a.tags && %s
                GROUP BY a.id, u.name
                ORDER BY a.creation_date DESC
            """, (user['id'], user['groups']))
            group_agents = cur.fetchall()

        # 2. User's Agent Suite
        cur.execute("""
            SELECT a.*, uas.added_at,
                   (SELECT COUNT(*) FROM agent_integrations ai WHERE ai.agent_id = a.id) as mcps_count,
                   COALESCE(ARRAY_AGG(s.name) FILTER (WHERE s.name IS NOT NULL), '{}') as linked_servers
            FROM agents a
            JOIN user_agent_suite uas ON a.id = uas.agent_id
            LEFT JOIN agent_integrations ai ON a.id = ai.agent_id
            LEFT JOIN mcp_servers s ON ai.integration_id = s.id
            WHERE uas.user_id = %s
            GROUP BY a.id, uas.added_at
            ORDER BY uas.added_at DESC
        """, (user['id'],))
        suite_agents = cur.fetchall()

        # 3. User's Suite MCP Integrations (Servers)
        cur.execute("""
            SELECT s.*, uis.added_at,
                   (SELECT COUNT(*) FROM mcp_tools t WHERE t.server_id = s.id) as mcps_count,
                   (SELECT COALESCE(array_to_json(array_agg(t.tool_name)), '[]'::json) 
                    FROM mcp_tools t WHERE t.server_id = s.id) as tool_names,
                   COALESCE(ARRAY_AGG(a.name) FILTER (WHERE a.name IS NOT NULL), '{}') as connected_agents
            FROM mcp_servers s
            JOIN user_integration_suite uis ON s.id = uis.integration_id
            LEFT JOIN agent_integrations ai ON s.id = ai.integration_id
            LEFT JOIN agents a ON ai.agent_id = a.id
            WHERE uis.user_id = %s
            GROUP BY s.id, uis.added_at
            ORDER BY uis.added_at DESC
        """, (user['id'],))
        suite_integrations = cur.fetchall()

        # 4. User's Own MCP Servers
        cur.execute("""
            SELECT s.*,
                   (SELECT COUNT(*) FROM mcp_tools t WHERE t.server_id = s.id) as mcps_count,
                   (SELECT COALESCE(array_to_json(array_agg(t.tool_name)), '[]'::json) 
                    FROM mcp_tools t WHERE t.server_id = s.id) as tool_names,
                   COALESCE(ARRAY_AGG(a.name) FILTER (WHERE a.name IS NOT NULL), '{}') as connected_agents
            FROM mcp_servers s
            LEFT JOIN agent_integrations ai ON s.id = ai.integration_id
            LEFT JOIN agents a ON ai.agent_id = a.id
            WHERE s.creator_user_id = %s
            GROUP BY s.id
            ORDER BY s.created_at DESC
        """, (user['id'],))
        integrations = cur.fetchall()

        # 5. API Keys
        cur.execute("SELECT * FROM api_keys WHERE user_id = %s ORDER BY created_at DESC", (user['id'],))
        api_keys = cur.fetchall()

        # 6. Authorized Models & Quotas
        if user['access_level'] == 'admin':
            cur.execute("""
                SELECT DISTINCT m.id, m.name, 'All (Admin)' as group_name, 
                       NULL::integer as max_calls, 0::bigint as current_usage
                FROM models m
                ORDER BY m.name ASC
            """)
            authorized_models = cur.fetchall()
        else:
            cur.execute("""
                SELECT 
                    m.id, m.name, mc.group_name, mc.max_calls, COALESCE(gmu.call_count, 0) as current_usage
                FROM model_constraints mc
                JOIN models m ON mc.model_id = m.id
                JOIN user_groups ug ON mc.group_name = ug.group_name
                LEFT JOIN group_model_usage gmu ON mc.group_name = gmu.group_name 
                    AND mc.model_id = gmu.model_id 
                    AND gmu.usage_date = CURRENT_DATE
                WHERE ug.user_email = %s
                ORDER BY m.name ASC, mc.group_name ASC
            """, (user['email'],))
            authorized_models = cur.fetchall()

    return render_template(
        'dashboard.html',
        user=user,
        agents=agents,
        group_agents=group_agents,
        suite_agents=suite_agents,
        integrations=integrations,
        suite_integrations=suite_integrations,
        api_keys=api_keys,
        authorized_models=authorized_models
    )

@app.route('/generate_api_key', methods=['POST'])
@login_required
def generate_api_key():
    user_id = get_current_user_id()
    name = request.form.get('name', 'Default Key')
    new_key = f"sk-{secrets.token_urlsafe(32)}"
    with get_db_cursor() as cur:
        cur.execute("INSERT INTO api_keys (user_id, key_value, name) VALUES (%s, %s, %s)", (user_id, new_key, name))
    flash('API Key generated successfully!')
    return redirect(url_for('dashboard'))

@app.route('/delete_api_key/<key_id>', methods=['POST'])
@login_required
def delete_api_key(key_id):
    user_id = get_current_user_id()
    with get_db_cursor() as cur:
        cur.execute("DELETE FROM api_keys WHERE id = %s AND user_id = %s", (key_id, user_id))
    flash('API Key deleted.')
    return redirect(url_for('dashboard'))


@app.route('/search_agents')
@login_required
def search_agents():
    user = get_current_user_info()
    query = request.args.get('q', '')
    selected_tags = request.args.getlist('tags')
    with get_db_cursor() as cur:
        cur.execute("SELECT name FROM groups ORDER BY name ASC")
        all_tags = [row['name'] for row in cur.fetchall()]
        sql = """
            SELECT a.*,
                   (SELECT COUNT(*) FROM user_agent_suite WHERE agent_id = a.id) as user_count,
                   (SELECT COUNT(*) FROM agent_integrations ai 
                    JOIN integrations i ON ai.integration_id = i.id 
                    WHERE ai.agent_id = a.id AND i.type = 'tool') as tools_count,
                   (SELECT COUNT(*) FROM agent_integrations ai 
                    JOIN integrations i ON ai.integration_id = i.id 
                    WHERE ai.agent_id = a.id AND i.type = 'mcp') as mcps_count,
                   (SELECT 1 FROM user_agent_suite WHERE agent_id = a.id AND user_id = %s) as in_suite
            FROM agents a
            WHERE (a.status = 'public' OR a.creator_user_id = %s)
        """
        params = [user['id'], user['id']]
        if query:
            sql += " AND (a.name ILIKE %s OR a.description ILIKE %s)"
            params.extend([f'%{query}%', f'%{query}%'])
        if selected_tags:
            sql += " AND a.tags && %s"
            params.append(selected_tags)
        sql += " ORDER BY user_count DESC"
        cur.execute(sql, params)
        results = cur.fetchall()
        for r in results:
            if user['access_level'] == 'admin':
                r['can_add'] = True
            else:
                r['can_add'] = bool(set(r['tags'] or []) & set(user['groups'] or []))
    return render_template('search_agents.html', user=user, agents=results, all_tags=all_tags, query=query,
                           selected_tags=selected_tags)


@app.route('/search_tools_mcps')
@login_required
def search_tools_mcps():
    user = get_current_user_info()
    query = request.args.get('q', '')
    selected_tags = request.args.getlist('tags')
    with get_db_cursor() as cur:
        cur.execute("""
            SELECT DISTINCT unnest(tags) as tag 
            FROM mcp_servers 
            WHERE status = 'public' OR creator_user_id = %s
        """, (user['id'],))
        all_tags = [row['tag'] for row in cur.fetchall() if row['tag']]
        sql = """
            SELECT s.*,
                   (SELECT COUNT(*) FROM user_integration_suite WHERE integration_id = s.id) as user_count,
                   (SELECT COUNT(*) FROM mcp_tools t WHERE t.server_id = s.id) as tools_count,
                   (SELECT COALESCE(array_to_json(array_agg(t.tool_name)), '[]'::json) 
                    FROM mcp_tools t WHERE t.server_id = s.id) as tool_names,
                   (SELECT 1 FROM user_integration_suite WHERE integration_id = s.id AND user_id = %s) as in_suite
            FROM mcp_servers s
            WHERE (s.status = 'public' OR s.creator_user_id = %s)
        """
        params = [user['id'], user['id']]
        if query:
            sql += """ AND (
                s.name ILIKE %s OR 
                s.description ILIKE %s OR 
                EXISTS (
                    SELECT 1 FROM mcp_tools t 
                    WHERE t.server_id = s.id AND (t.tool_name ILIKE %s OR t.description ILIKE %s)
                )
            )"""
            query_param = f'%{query}%'
            params.extend([query_param, query_param, query_param, query_param])
        if selected_tags:
            sql += " AND s.tags && %s"
            params.append(selected_tags)
        sql += " ORDER BY s.name ASC"
        cur.execute(sql, params)
        results = cur.fetchall()
        for r in results:
            if user['access_level'] == 'admin' or r['status'] == 'public':
                r['can_add'] = True
            else:
                r['can_add'] = bool(set(r['tags'] or []) & set(user['groups'] or []))
    return render_template(
        'search_tools_mcps.html',
        user=user,
        integrations=results,
        all_tags=all_tags,
        query=query,
        selected_tags=selected_tags
    )

@app.route('/add_to_suite/<agent_id>', methods=['POST'])
@login_required
def add_to_suite(agent_id):
    user_id = get_current_user_id()
    try:
        with get_db_cursor() as cur:
            cur.execute("INSERT INTO user_agent_suite (user_id, agent_id) VALUES (%s, %s) ON CONFLICT DO NOTHING", (user_id, agent_id))
        flash('Agent added to your suite!')
    except Exception as e:
        flash(f'Error adding agent: {e}')
    return redirect(request.referrer or url_for('search_agents'))

@app.route('/remove_from_suite/<agent_id>', methods=['POST'])
@login_required
def remove_from_suite(agent_id):
    user_id = get_current_user_id()
    with get_db_cursor() as cur:
        cur.execute("DELETE FROM user_agent_suite WHERE user_id = %s AND agent_id = %s", (user_id, agent_id))
    flash('Agent removed from your suite.')
    return redirect(request.referrer or url_for('dashboard'))


@app.route('/new_agent', methods=['GET', 'POST'])
@login_required
def new_agent():
    user = get_current_user_info()

    # Access control guard
    if user.get('access_level') == 'user':
        flash('You do not have the rights to add or update agents.', 'danger')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        tags = request.form.getlist('tags')
        status = request.form.get('status')
        rag_enabled = request.form.get('rag_enabled') == 'on'
        prompt = request.form.get('prompt')
        rules = request.form.get('rules')
        skills = request.form.get('skills')
        selected_servers = request.form.getlist('integrations')
        if user['access_level'] == 'editor':
            if not all(tag in user['groups'] for tag in tags):
                flash(f"You can only assign agents to your groups: {', '.join(user['groups'])}")
                return redirect(url_for('new_agent'))
        with get_db_cursor() as cur:
            cur.execute(
                "INSERT INTO agents (name, description, creator_user_id, status, rag_enabled, tags) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (name, description, user['id'], status, rag_enabled, tags)
            )
            agent_id = cur.fetchone()['id']
            cur.execute(
                "INSERT INTO prompt_system_versions (agent_id, version, prompt, rules, skills) VALUES (%s, 1, %s, %s, %s)",
                (agent_id, prompt, rules, skills)
            )
            for server_id in set(selected_servers):
                cur.execute(
                    "INSERT INTO agent_integrations (agent_id, integration_id) VALUES (%s, %s)",
                    (agent_id, server_id)
                )
        flash('Agent created successfully!', 'success')
        return redirect(url_for('dashboard'))
    with get_db_cursor() as cur:
        cur.execute("SELECT name FROM groups ORDER BY name ASC")
        all_groups = [row['name'] for row in cur.fetchall()]
        cur.execute("""
            SELECT s.id, s.name, s.description, s.status,
                   (SELECT COALESCE(array_to_json(array_agg(t.tool_name)), '[]'::json) 
                    FROM mcp_tools t WHERE t.server_id = s.id) as tool_names
            FROM mcp_servers s 
            WHERE s.creator_user_id = %s OR s.status = 'public'
            ORDER BY s.name ASC
        """, (user['id'],))
        available_servers = cur.fetchall()
    return render_template(
        'new_agent.html',
        user=user,
        servers=available_servers,
        groups=all_groups
    )


@app.route('/update_agent/<agent_id>', methods=['GET', 'POST'])
@login_required
def update_agent(agent_id):
    user = get_current_user_info()

    # Access control guard
    if user.get('access_level') == 'user':
        flash('You do not have the rights to add or update agents.', 'danger')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        prompt = request.form.get('prompt')
        rules = request.form.get('rules')
        skills = request.form.get('skills')

        # Meta configuration modifications
        status = request.form.get('status', 'private')
        rag_enabled = request.form.get('rag_enabled') == 'on'
        selected_servers = request.form.getlist('integrations')  # Captures the submitted UUID arrays

        with get_db_cursor() as cur:
            # Check permission first
            cur.execute("SELECT creator_user_id, tags FROM agents WHERE id = %s", (agent_id,))
            agent_info = cur.fetchone()
            if not agent_info or not has_agent_access(user, agent_info['tags'], agent_info['creator_user_id'], action='update'):
                flash('Agent not found or access denied.', 'danger')
                return redirect(url_for('dashboard'))

            # 1. Update Core Agent Properties
            cur.execute("""
                UPDATE agents 
                SET status = %s, rag_enabled = %s 
                WHERE id = %s
            """, (status, rag_enabled, agent_id))

            # 2. Append Incrementing System Configuration Version
            cur.execute("SELECT MAX(version) FROM prompt_system_versions WHERE agent_id = %s", (agent_id,))
            res = cur.fetchone()
            last_version = res['max'] if res and res['max'] is not None else 0

            cur.execute("""
                INSERT INTO prompt_system_versions (agent_id, version, prompt, rules, skills) 
                VALUES (%s, %s, %s, %s, %s)
            """, (agent_id, last_version + 1, prompt, rules, skills))

            # 3. Synchronize Active Integration Layer Map
            cur.execute("DELETE FROM agent_integrations WHERE agent_id = %s", (agent_id,))
            for server_id in set(selected_servers):
                cur.execute("""
                    INSERT INTO agent_integrations (agent_id, integration_id) 
                    VALUES (%s, %s)
                """, (agent_id, server_id))

        flash('Agent configuration stack updated cleanly!', 'success')
        return redirect(url_for('dashboard'))

    # GET Method: Read configuration profile for UI compilation
    with get_db_cursor() as cur:
        # Check security and authorization parameters
        cur.execute("SELECT * FROM agents WHERE id = %s", (agent_id,))
        agent = cur.fetchone()
        if not agent or not has_agent_access(user, agent['tags'], agent['creator_user_id'], action='update'):
            flash('Agent not found or access denied.', 'danger')
            return redirect(url_for('dashboard'))

        # Fetch latest active version metadata safely
        cur.execute("SELECT * FROM prompt_system_versions WHERE agent_id = %s ORDER BY version DESC LIMIT 1",
                    (agent_id,))
        latest_prompt = cur.fetchone()
        if not latest_prompt:
            latest_prompt = {'version': 0, 'prompt': '', 'rules': '', 'skills': ''}

        # Get active server connections maps tied to this agent layout
        cur.execute("""
            SELECT s.id, s.name, 
                   (SELECT COALESCE(array_to_json(array_agg(t.tool_name)), '[]'::json) 
                    FROM mcp_tools t WHERE t.server_id = s.id) as tool_names
            FROM mcp_servers s
            JOIN agent_integrations ai ON s.id = ai.integration_id
            WHERE ai.agent_id = %s
        """, (agent_id,))
        current_integrations = cur.fetchall()

        # Pull clean cascading structures for infrastructure selector dropdown menus
        cur.execute("""
            SELECT s.id, s.name, s.description, s.status,
                   (SELECT COALESCE(array_to_json(array_agg(t.tool_name)), '[]'::json) 
                    FROM mcp_tools t WHERE t.server_id = s.id) as tool_names
            FROM mcp_servers s 
            WHERE s.creator_user_id = %s OR s.status = 'public'
            ORDER BY s.name ASC
        """, (user['id'],))
        available_servers = cur.fetchall()

    return render_template(
        'update_agent.html',
        user=user,
        agent=agent,
        prompt=latest_prompt,
        current_integrations=current_integrations,
        servers=available_servers
    )

@app.route('/delete_agent/<agent_id>', methods=['POST'])
@login_required
def delete_agent(agent_id):
    user = get_current_user_info()
    with get_db_cursor() as cur:
        cur.execute("SELECT creator_user_id, tags FROM agents WHERE id = %s", (agent_id,))
        agent_info = cur.fetchone()
        if not agent_info or not has_agent_access(user, agent_info['tags'], agent_info['creator_user_id'], action='delete'):
            flash('Agent not found or access denied.')
            return redirect(url_for('dashboard'))
        cur.execute("DELETE FROM agents WHERE id = %s", (agent_id,))
    flash('Agent deleted successfully.')
    return redirect(url_for('dashboard'))


@app.route('/admin/toggle_pause_agent/<agent_id>', methods=['POST'])
@login_required
def toggle_pause_agent(agent_id):
    user = get_current_user_info()
    with get_db_cursor() as cur:
        cur.execute("SELECT creator_user_id, tags, paused FROM agents WHERE id = %s", (agent_id,))
        agent_info = cur.fetchone()
        if not agent_info or not has_agent_access(user, agent_info['tags'], agent_info['creator_user_id'], action='update'):
            flash('Agent not found or access denied.')
            return redirect(request.referrer or url_for('dashboard'))
        new_paused_state = not agent_info['paused']
        cur.execute("UPDATE agents SET paused = %s WHERE id = %s", (new_paused_state, agent_id))
    state_label = "paused" if new_paused_state else "resumed"
    flash(f'Agent {state_label} successfully.')
    return redirect(request.referrer or url_for('dashboard'))

@app.route('/delete_tool/<int_id>', methods=['POST'])
@login_required
def delete_tool(int_id):
    user_id = get_current_user_id()
    with get_db_cursor() as cur:
        cur.execute("SELECT id FROM integrations WHERE id = %s AND creator_user_id = %s", (int_id, user_id))
        if not cur.fetchone():
            flash('Tool/MCP not found or access denied.')
            return redirect(url_for('dashboard'))
        cur.execute("DELETE FROM integrations WHERE id = %s", (int_id,))
    flash('Tool/MCP deleted successfully.')
    return redirect(url_for('dashboard'))


@app.route('/agent_dashboard/<uuid:agent_id>')
@login_required
def agent_individual_dashboard(agent_id):
    user = get_current_user_info()
    agent_id_str = str(agent_id)

    # Context Manager guarantees database resource teardown / cleanup safely
    with get_db_cursor() as cur:
        # 1. Fetch core agent details
        cur.execute("""
            SELECT a.*, u.name as creator_name,
                   (SELECT version FROM prompt_system_versions 
                    WHERE agent_id = a.id ORDER BY version DESC LIMIT 1) as current_version,
                   COALESCE(
                       (SELECT ARRAY_AGG(g.name) 
                        FROM groups g 
                        WHERE g.name = ANY(a.tags)), 
                       '{}'
                   ) as group_tags
            FROM agents a 
            LEFT JOIN users u ON a.creator_user_id = u.id
            WHERE a.id = %s
        """, (agent_id_str,))

        agent_row = cur.fetchone()
        if not agent_row or not has_agent_access(user, agent_row['tags'], agent_row['creator_user_id'], action='view'):
            flash("Agent entry not found, or access credentials invalid.")
            return redirect(url_for('dashboard'))

        agent = dict(agent_row)
        agent['rag_sources'] = ["Corporate_Wiki_KB", "Engineering_Playbooks", "..."] if agent.get('rag_enabled') else []

        # 2. Get Connected MCP Extensions
        cur.execute("""
            SELECT 
                ms.id, ms.name, ms.description,
                COALESCE(
                    (SELECT array_to_json(array_agg(t.tool_name ORDER BY t.tool_name)) 
                     FROM mcp_tools t WHERE t.server_id = ms.id), 
                    '[]'::json
                ) as tool_names
            FROM agent_integrations ai
            JOIN mcp_servers ms ON ai.integration_id = ms.id
            WHERE ai.agent_id = %s
        """, (agent_id_str,))
        mcp_servers = []
        for row in cur.fetchall():
            item = dict(row)
            if isinstance(item['tool_names'], str):
                item['tool_names'] = json.loads(item['tool_names'] or '[]')
            mcp_servers.append(item)

        # 3. Gather Standalone Custom Tools
        cur.execute("""
            SELECT i.name FROM agent_integrations ai
            JOIN integrations i ON ai.integration_id = i.id
            WHERE ai.agent_id = %s AND i.type = 'tool'
        """, (agent_id_str,))
        standalone_tools = [r['name'] for r in cur.fetchall()]

        # 4. Fetch Multi-tenant group contextual structures
        cur.execute("SELECT user_email, group_name FROM user_groups")
        user_groups_rows = cur.fetchall()
        user_to_groups = defaultdict(list)
        for row in user_groups_rows:
            user_to_groups[row['user_email']].append(row['group_name'])

        # 5. DB Analytics Engine (Replaces raw file string parsing loop)
        cur.execute("""
            SELECT 
                COUNT(*) as total_runs,
                COUNT(CASE WHEN status = 'error' THEN 1 END) as failed_runs,
                COALESCE(SUM(prompt_tokens), 0) as total_prompt_tokens,
                COALESCE(SUM(completion_tokens), 0) as total_completion_tokens,
                COALESCE(SUM(estimated_cost_usd), 0.0) as total_estimated_cost,
                PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_seconds::float) as p95_latency,
                COUNT(CASE WHEN latency_seconds <= 2.0 THEN 1 END) as fast_count,
                COUNT(CASE WHEN latency_seconds > 2.0 AND latency_seconds <= 5.0 THEN 1 END) as normal_count,
                COUNT(CASE WHEN latency_seconds > 5.0 AND latency_seconds <= 10.0 THEN 1 END) as heavy_count,
                COUNT(CASE WHEN latency_seconds > 10.0 THEN 1 END) as lagging_count
            FROM api_gateway_logs
            WHERE agent_id = %s
        """, (agent_id_str,))
        summary = dict(cur.fetchone())

        # 6. Time Series Data Aggregations (Grouped by Day)
        cur.execute("""
            SELECT 
                TO_CHAR(timestamp, 'YYYY-MM-DD') as log_date,
                COUNT(CASE WHEN status = 'success' THEN 1 END) as success_count,
                COUNT(CASE WHEN status = 'error' THEN 1 END) as error_count,
                COALESCE(AVG(CASE WHEN status = 'success' THEN latency_seconds END), 0.0) as avg_lat,
                COALESCE(SUM(total_tokens), 0) as tokens,
                COALESCE(SUM(estimated_cost_usd), 0.0) as cost
            FROM api_gateway_logs
            WHERE agent_id = %s
            GROUP BY log_date
            ORDER BY log_date ASC
        """, (agent_id_str,))
        daily_rows = cur.fetchall()

        # 7. Error Class Root Cause Profiling
        cur.execute("""
            SELECT 
                CASE 
                    WHEN http_status_code IS NOT NULL THEN 'HTTP ' || http_status_code || ' (' || error_type || ')'
                    ELSE error_type 
                END as err_label,
                COUNT(*) as err_count
            FROM api_gateway_logs
            WHERE agent_id = %s AND status = 'error'
            GROUP BY err_label
        """, (agent_id_str,))
        error_rows = cur.fetchall()

        # 8. Extract raw transactional live logs (Last 100 calls)
        cur.execute("""
            SELECT 
                TO_CHAR(timestamp, 'YYYY-MM-DD HH24:MI:SS Z') as timestamp,
                user_email, resolved_model_name, status, 
                latency_seconds, prompt_tokens, completion_tokens, 
                input_query, output_response, error_type, error_message
            FROM api_gateway_logs
            WHERE agent_id = %s
            ORDER BY timestamp DESC
            LIMIT 100
        """, (agent_id_str,))
        truncated_logs = [dict(r) for r in cur.fetchall()]

        # 9. Prompt Version Statistical Profiling (NEW)
        cur.execute("""
WITH version_ranges AS (
                SELECT 
                    id,
                    agent_id,
                    version,
                    creation_date AS valid_from,
                    LEAD(creation_date) OVER (PARTITION BY agent_id ORDER BY version ASC) AS valid_to
                FROM prompt_system_versions
                WHERE agent_id = %s
            )
            SELECT 
                vr.version,
                vr.valid_from AS creation_date,
                COUNT(l.trace_id) AS total_runs,
                COALESCE(AVG(l.input_query_length), 0) AS avg_input_len,
                COALESCE(STDDEV_SAMP(l.input_query_length), 0) AS std_input_len,
                COUNT(CASE WHEN l.status = 'success' THEN 1 END) AS success_count,
                COUNT(CASE WHEN l.status = 'error' THEN 1 END) AS error_count,
                COALESCE(AVG(l.latency_seconds), 0) AS avg_latency,
                COALESCE(STDDEV_SAMP(l.latency_seconds), 0) AS std_latency,
                COALESCE(AVG(l.prompt_tokens), 0) AS avg_prompt_tokens,
                COALESCE(STDDEV_SAMP(l.prompt_tokens), 0) AS std_prompt_tokens,
                COALESCE(AVG(l.completion_tokens), 0) AS avg_completion_tokens,
                COALESCE(STDDEV_SAMP(l.completion_tokens), 0) AS std_completion_tokens,
                MODE() WITHIN GROUP (ORDER BY l.resolved_model_name) AS primary_model
            FROM version_ranges vr
            LEFT JOIN api_gateway_logs l 
                   ON l.agent_id = vr.agent_id 
                  AND l.timestamp >= vr.valid_from 
                  AND (vr.valid_to IS NULL OR l.timestamp < vr.valid_to)
            GROUP BY vr.id, vr.version, vr.valid_from
            ORDER BY vr.version ASC
        """, (agent_id_str,))
        raw_version_rows = cur.fetchall()

    # Calculate Version Statistics & Performance Score
    version_stats = []
    best_version = None
    best_score = -1.0

    for row in raw_version_rows:
        r = dict(row)
        runs_cnt = r['total_runs']
        succ_cnt = r['success_count']
        avg_lat = float(r['avg_latency'])

        # Performance Score = Success Rate weighted against latency efficiency
        if runs_cnt > 0:
            succ_rate = succ_cnt / runs_cnt
            lat_factor = 1.0 / (1.0 + avg_lat)
            score = (succ_rate * 0.7) + (lat_factor * 0.3)
        else:
            score = 0.0

        v_item = {
            "version": r['version'],
            "creation_date": r['creation_date'].strftime("%Y-%m-%d %H:%M:%S") if r['creation_date'] else "N/A",
            "total_runs": runs_cnt,
            "avg_input_len": round(float(r['avg_input_len']), 2),
            "std_input_len": round(float(r['std_input_len']), 2),
            "success_count": succ_cnt,
            "error_count": r['error_count'],
            "avg_latency": round(avg_lat, 3),
            "std_latency": round(float(r['std_latency']), 3),
            "avg_prompt_tokens": round(float(r['avg_prompt_tokens']), 2),
            "std_prompt_tokens": round(float(r['std_prompt_tokens']), 2),
            "avg_completion_tokens": round(float(r['avg_completion_tokens']), 2),
            "std_completion_tokens": round(float(r['std_completion_tokens']), 2),
            "primary_model": r['primary_model'] or "N/A",
            "score": score
        }

        if runs_cnt > 0 and score > best_score:
            best_score = score
            best_version = r['version']

        version_stats.append(v_item)

    # Mark the best performing version row
    for v in version_stats:
        v["is_best"] = (v["version"] == best_version)

    # ==========================================
    # DATA STRUCTURING ENGINE (100% Frontend Matrix Compliant)
    # ==========================================
    total_runs = summary['total_runs']
    total_tokens_sum = int(summary['total_prompt_tokens'] + summary['total_completion_tokens'])
    total_cost = float(summary['total_estimated_cost'])

    error_rate_pct = round((summary['failed_runs'] / total_runs) * 100, 2) if total_runs > 0 else 0.0
    tokens_per_dollar = round(total_tokens_sum / total_cost) if total_cost > 0 else 0

    # Parse daily charts
    dates = [r['log_date'] for r in daily_rows]
    chart_data = {
        "dates": dates,
        "success_counts": [r['success_count'] for r in daily_rows],
        "error_counts": [r['error_count'] for r in daily_rows],
        "avg_latencies": [round(float(r['avg_lat']), 3) for r in daily_rows],
        "daily_tokens": [r['tokens'] for r in daily_rows],
        "daily_costs": [round(float(r['cost']), 4) for r in daily_rows],
        "error_labels": [r['err_label'] for r in error_rows],
        "error_counts_dist": [r['err_count'] for r in error_rows],
        "histogram_labels": ["0-2s (Fast)", "2-5s (Normal)", "5-10s (Heavy)", "10s+ (Lagging)"],
        "histogram_values": [summary['fast_count'], summary['normal_count'], summary['heavy_count'],
                             summary['lagging_count']],
        "historical_latencies": [float(log['latency_seconds']) for log in reversed(truncated_logs)]
    }

    # Cross-reference user tracking with evaluated corporate groups
    active_groups = set()
    group_calls = defaultdict(int)
    group_tokens = defaultdict(int)
    group_daily_tokens = defaultdict(lambda: defaultdict(int))

    # Re-evaluate logic cleanly across database inputs
    for log in truncated_logs:
        email = log['user_email']
        associated_groups = user_to_groups.get(email, ["Unassigned"])
        date_key = log['timestamp'][:10]
        total_tok = log['prompt_tokens'] + log['completion_tokens']

        for group in associated_groups:
            active_groups.add(group)
            if log['status'] == 'success':
                group_calls[group] += 1
                group_tokens[group] += total_tok
            group_daily_tokens[group][date_key] += total_tok

    sorted_groups = sorted(list(active_groups))
    chart_data.update({
        "groups": sorted_groups,
        "group_calls": [group_calls[g] for g in sorted_groups],
        "group_tokens": [group_tokens[g] for g in sorted_groups],
        "group_timeline_data": {g: [group_daily_tokens[g][d] for d in dates] for g in sorted_groups}
    })

    totals = {
        "total_runs": total_runs,
        "total_groups": len(active_groups),
        "total_tokens": total_tokens_sum,
        "total_cost": round(total_cost, 4),
        "p95_latency": round(float(summary['p95_latency'] or 0.0), 3),
        "error_rate_pct": error_rate_pct,
        "tokens_per_dollar": f"{tokens_per_dollar:,}" if tokens_per_dollar > 0 else "0"
    }

    return render_template(
        'agent_dashboard.html',
        user=user,
        agent=agent,
        mcp_servers=mcp_servers,
        standalone_tools=standalone_tools,
        logs=truncated_logs,
        chart_data=chart_data,
        totals=totals,
        version_stats=version_stats
    )

@app.route('/new_tools_mcp', methods=['GET', 'POST'])
@login_required
def new_tools_mcp():
    user = get_current_user_info()

    # Access control guard
    if user.get('access_level') == 'user':
        flash('You do not have the rights to add or update MCP tools.', 'danger')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        server_name = request.form.get('name')
        server_description = request.form.get('server_description')
        endpoint = request.form.get('endpoint')
        api_key = request.form.get('api_key', '')
        status = request.form.get('status', 'private')
        tags = request.form.getlist('tags')
        if user['access_level'] == 'editor':
            if not all(tag in user['groups'] for tag in tags):
                flash(f"Unauthorized group assignment. You belong to: {', '.join(user['groups'])}")
                return redirect(url_for('new_tools_mcp'))
        try:
            logger.info(f"Validating server operational response at: {endpoint}")
            resp = requests.get(endpoint, timeout=5)
            if resp.status_code == 404:
                flash('Endpoint returned a 404. Please verify the destination master address.')
                return redirect(url_for('new_tools_mcp'))
        except requests.exceptions.RequestException as e:
            logger.warning(f"Network health scan bypassed/failed for {endpoint}: {e}")
            flash('Warning: Unable to verify network endpoint. System committed config anyway, but verify connectivity.')
        encrypted_api_key = encrypt_key(api_key) if api_key else None
        try:
            with get_db_cursor() as cur:
                cur.execute("""
                    INSERT INTO mcp_servers (name, description, endpoint, api_key, creator_user_id, status, tags)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (server_name, server_description, endpoint, encrypted_api_key, user['id'], status, tags))
                server_id = cur.fetchone()['id']
                tool_names = request.form.getlist('tool_name[]')
                tool_descriptions = request.form.getlist('tool_description[]')
                for name, desc in zip(tool_names, tool_descriptions):
                    if name.strip():
                        cur.execute("""
                            INSERT INTO mcp_tools (server_id, tool_name, description)
                            VALUES (%s, %s, %s)
                        """, (server_id, name.strip(), desc.strip()))
            flash(f"MCP Gateway '{server_name}' and matching sub-capabilities recorded successfully.", 'success')
            return redirect(url_for('dashboard'))
        except Exception as e:
            logger.error(f"Failed to compile master schema integration write: {e}")
            flash(f"Database error writing configuration context: {str(e)}", 'danger')
            return redirect(url_for('new_tools_mcp'))
    with get_db_cursor() as cur:
        cur.execute("SELECT name FROM groups ORDER BY name ASC")
        all_groups = [row['name'] for row in cur.fetchall()]
    return render_template('new_tools_mcp.html', user=user, groups=all_groups)

@app.route('/semantica/<uuid:agent_id>')
@login_required
def semantica_dashboard(agent_id):
    user = get_current_user_info()
    agent_id_str = str(agent_id)
    
    with get_db_cursor() as cur:
        # 1. Forensic KPIs & Overview Metrics
        cur.execute("SELECT * FROM agents WHERE id = %s", (agent_id_str,))
        agent = cur.fetchone()
        if not agent or not has_agent_access(user, agent['tags'], agent['creator_user_id'], action='update'):
            flash('Agent not found or access denied.', 'danger')
            return redirect(url_for('dashboard'))

        cur.execute(f"""
            SELECT 
                COUNT(*) as total_decisions,
                AVG(confidence) as avg_confidence,
                COUNT(CASE WHEN LOWER(outcome) LIKE CHR(37) || 'error' || CHR(37) OR LOWER(outcome) LIKE CHR(37) || 'fail' || CHR(37) OR confidence < 0.7 THEN 1 END) as anomaly_count
            FROM agent_decisions
            WHERE agent_id::text = '{agent_id_str}'
        """)
        kpi_metrics = cur.fetchone()

        # 2. Chart 1 Data: Confidence Distribution Buckets
        cur.execute(f"""
            SELECT 
                CASE 
                    WHEN confidence >= 0.9 THEN '90-100%'
                    WHEN confidence >= 0.8 THEN '80-89%'
                    WHEN confidence >= 0.7 THEN '70-79%'
                    ELSE '<70% (Anomalies)'
                END as confidence_bucket,
                COUNT(*) as count
            FROM agent_decisions
            WHERE agent_id::text = '{agent_id_str}'
            GROUP BY confidence_bucket
            ORDER BY confidence_bucket DESC
        """)
        confidence_data = cur.fetchall()

        # 3. Chart 2 Data: Decision Outcomes Breakdown
        cur.execute(f"""
            SELECT outcome, COUNT(*) as count
            FROM agent_decisions
            WHERE agent_id::text = '{agent_id_str}' AND outcome IS NOT NULL
            GROUP BY outcome
            ORDER BY count DESC
            LIMIT 5
        """)
        outcome_data = cur.fetchall()

        # 4. Root Cause Analysis (RCA) Forensic Log
        cur.execute(f"""
            SELECT ad.*, a.name as agent_name, m.name as model_name, 
                   agl.latency_seconds, agl.error_message, agl.status as gateway_status
            FROM agent_decisions ad
            JOIN agents a ON ad.agent_id = a.id
            LEFT JOIN models m ON ad.model_id = m.id
            LEFT JOIN api_gateway_logs agl ON ad.trace_id::text = agl.trace_id::text
            WHERE ad.agent_id::text = '{agent_id_str}' AND (ad.confidence < 0.75 OR LOWER(ad.outcome) LIKE CHR(37) || 'error' || CHR(37) OR LOWER(ad.outcome) LIKE CHR(37) || 'fail' || CHR(37))
            ORDER BY ad.created_at DESC
            LIMIT 15
        """)
        rca_forensics = cur.fetchall()

        # 5. Ontology Entity Tracking
        cur.execute(f"""
            SELECT jsonb_array_elements_text(entities) as entity_name, COUNT(*) as reference_count
            FROM agent_decisions
            WHERE agent_id::text = '{agent_id_str}' AND entities IS NOT NULL AND jsonb_array_length(entities) > 0
            GROUP BY entity_name
            ORDER BY reference_count DESC
            LIMIT 10
        """)
        top_entities = cur.fetchall()

        # 6. Orphaned Graph Nodes (Using Type-Safe CTE)
        cur.execute(f"""
            WITH agent_nodes AS (
                SELECT id::text FROM semantica_nodes WHERE id::text = '{agent_id_str}'
                UNION
                SELECT id::text FROM agent_decisions WHERE agent_id::text = '{agent_id_str}'
                UNION
                SELECT user_id::text FROM agent_decisions WHERE agent_id::text = '{agent_id_str}' AND user_id IS NOT NULL
            )
            SELECT sn.id, sn.label, sn.created_at
            FROM semantica_nodes sn
            WHERE sn.id::text IN (SELECT id FROM agent_nodes)
            AND NOT EXISTS (
                SELECT 1 FROM semantica_edges se 
                WHERE se.source_node_id::text = sn.id::text OR se.target_node_id::text = sn.id::text
            )
            LIMIT 10
        """)
        orphaned_nodes = cur.fetchall()

        # 7. Agent Decisions Table Data
        cur.execute(f"""
            SELECT ad.*, a.name as agent_name, m.name as model_name, u.email as user_email
            FROM agent_decisions ad
            JOIN agents a ON ad.agent_id = a.id
            LEFT JOIN models m ON ad.model_id = m.id
            LEFT JOIN users u ON ad.user_id = u.id
            WHERE ad.agent_id::text = '{agent_id_str}'
            ORDER BY ad.created_at DESC
            LIMIT 30
        """)
        agent_decisions = cur.fetchall()

        # 8. Semantica Nodes Table Data (Using Type-Safe CTE)
        cur.execute(f"""
            WITH agent_nodes AS (
                SELECT id::text FROM semantica_nodes WHERE id::text = '{agent_id_str}'
                UNION
                SELECT id::text FROM agent_decisions WHERE agent_id::text = '{agent_id_str}'
                UNION
                SELECT user_id::text FROM agent_decisions WHERE agent_id::text = '{agent_id_str}' AND user_id IS NOT NULL
            )
            SELECT id, label, attributes, created_at, updated_at
            FROM semantica_nodes
            WHERE id::text IN (SELECT id FROM agent_nodes)
            ORDER BY created_at DESC
            LIMIT 30
        """)
        semantica_nodes = cur.fetchall()

        # 9. Total Nodes Count (Using Type-Safe CTE)
        cur.execute(f"""
            WITH agent_nodes AS (
                SELECT id::text FROM semantica_nodes WHERE id::text = '{agent_id_str}'
                UNION
                SELECT id::text FROM agent_decisions WHERE agent_id::text = '{agent_id_str}'
                UNION
                SELECT user_id::text FROM agent_decisions WHERE agent_id::text = '{agent_id_str}' AND user_id IS NOT NULL
            )
            SELECT COUNT(DISTINCT sn.id) as total_nodes
            FROM semantica_nodes sn
            WHERE sn.id::text IN (SELECT id FROM agent_nodes)
        """)
        node_count_row = cur.fetchone()
        node_count = node_count_row['total_nodes'] if node_count_row else 0

        # 10. Semantica Edges Table Data (Using Type-Safe CTE)
        cur.execute(f"""
            WITH agent_nodes AS (
                SELECT id::text FROM semantica_nodes WHERE id::text = '{agent_id_str}'
                UNION
                SELECT id::text FROM agent_decisions WHERE agent_id::text = '{agent_id_str}'
                UNION
                SELECT user_id::text FROM agent_decisions WHERE agent_id::text = '{agent_id_str}' AND user_id IS NOT NULL
            )
            SELECT e.id, e.edge_type, e.properties, e.created_at,
                   sn.label as source_label, tn.label as target_label
            FROM semantica_edges e
            JOIN semantica_nodes sn ON e.source_node_id::text = sn.id::text
            JOIN semantica_nodes tn ON e.target_node_id::text = tn.id::text
            WHERE e.source_node_id::text IN (SELECT id FROM agent_nodes)
               OR e.target_node_id::text IN (SELECT id FROM agent_nodes)
            ORDER BY e.created_at DESC
            LIMIT 30
        """)
        semantica_edges = cur.fetchall()

        # 11. Total Edges Count (Using Type-Safe CTE)
        cur.execute(f"""
            WITH agent_nodes AS (
                SELECT id::text FROM semantica_nodes WHERE id::text = '{agent_id_str}'
                UNION
                SELECT id::text FROM agent_decisions WHERE agent_id::text = '{agent_id_str}'
                UNION
                SELECT user_id::text FROM agent_decisions WHERE agent_id::text = '{agent_id_str}' AND user_id IS NOT NULL
            )
            SELECT COUNT(DISTINCT e.id) as total_edges
            FROM semantica_edges e
            JOIN semantica_nodes sn ON e.source_node_id::text = sn.id::text
            JOIN semantica_nodes tn ON e.target_node_id::text = tn.id::text
            WHERE e.source_node_id::text IN (SELECT id FROM agent_nodes)
               OR e.target_node_id::text IN (SELECT id FROM agent_nodes)
        """)
        edge_count_row = cur.fetchone()
        edge_count = edge_count_row['total_edges'] if edge_count_row else 0

    # Pack chart bundle
    chart_data = {
        'confidence_labels': [row['confidence_bucket'] for row in confidence_data],
        'confidence_counts': [row['count'] for row in confidence_data],
        'outcome_labels': [row['outcome'] for row in outcome_data],
        'outcome_counts': [row['count'] for row in outcome_data]
    }

    return render_template(
        'semantics.html',
        user=user,
        agent=agent,
        kpi_metrics=kpi_metrics,
        chart_data=chart_data,
        confidence_labels=chart_data['confidence_labels'],
        confidence_counts=chart_data['confidence_counts'],
        outcome_labels=chart_data['outcome_labels'],
        outcome_counts=chart_data['outcome_counts'],
        rca_forensics=rca_forensics,
        top_entities=top_entities,
        orphaned_nodes=orphaned_nodes,
        agent_decisions=agent_decisions,
        semantica_nodes=semantica_nodes,
        semantica_edges=semantica_edges,
        node_count=node_count,
        edge_count=edge_count
    )



@app.route('/token_usage')
@login_required
def token_usage_dashboard():
    """
    Global token-consumption analytics dashboard.

    Aggregates api_gateway_logs by:
      - user
      - agent
      - evaluated group
      - model
      - date

    Supported GET filters:
      ?start_date=2026-01-01
      ?end_date=2026-01-31
      ?user_email=user@example.com
      ?group_name=Engineering
      ?agent_id=<uuid>
      ?model_name=gpt-4o

    Date semantics:
      - start_date is inclusive
      - end_date is inclusive
      - internally end_date is converted to the following midnight
    """

    # ------------------------------------------------------------------
    # 1. DATE FILTERS
    # ------------------------------------------------------------------

    today = datetime.now(timezone.utc).date()
    default_start = today - timedelta(days=29)
    default_end = today
    start_date_raw = request.args.get(
        'start_date',
        default_start.strftime('%Y-%m-%d')
    )
    end_date_raw = request.args.get(
        'end_date',
        default_end.strftime('%Y-%m-%d')
    )
    try:
        start_date = datetime.strptime(
            start_date_raw,
            '%Y-%m-%d'
        ).date()
    except (TypeError, ValueError):
        start_date = default_start

    try:
        end_date = datetime.strptime(
            end_date_raw,
            '%Y-%m-%d'
        ).date()
    except (TypeError, ValueError):
        end_date = default_end

    # Protect against an inverted date range.
    if end_date < start_date:
        start_date, end_date = end_date, start_date

    # PostgreSQL timestamp upper bound is exclusive.
    #
    # Example:
    # start = 2026-10-01
    # end   = 2026-10-06
    #
    # We query:
    # timestamp >= 2026-10-01
    # timestamp <  2026-10-07
    #
    end_datetime = end_date + timedelta(days=1)

    # ------------------------------------------------------------------
    # 2. OPTIONAL DIMENSION FILTERS
    # ------------------------------------------------------------------

    selected_user = request.args.get('user_email','').strip()
    selected_group = request.args.get('group_name','').strip()
    selected_agent = request.args.get('agent_id','').strip()
    selected_model = request.args.get('model_name','').strip()

    # ------------------------------------------------------------------
    # 3. BUILD COMMON FILTER
    #
    # IMPORTANT:
    #
    # The base log population remains independent from aggregation
    # joins. This prevents joins from multiplying token totals.
    # ------------------------------------------------------------------

    base_where = ["l.timestamp >= %s","l.timestamp < %s"]
    base_params = [start_date,end_datetime]

    # ------------------------------------------------------------------
    # User filter
    # ------------------------------------------------------------------

    if selected_user:
        base_where.append("l.user_email = %s")
        base_params.append(selected_user)

    # ------------------------------------------------------------------
    # Agent filter
    #
    # IMPORTANT:
    #
    # Do NOT pass uuid.UUID(...) to psycopg2.
    #
    # Your psycopg2 installation is raising:
    #
    #   psycopg2.ProgrammingError:
    #   can't adapt type 'UUID'
    #
    # We validate the string with uuid.UUID(), but we pass the ORIGINAL
    # string to psycopg2 and explicitly cast it to uuid in PostgreSQL.
    # ------------------------------------------------------------------

    if selected_agent:
        try:
            uuid.UUID(selected_agent)
            base_where.append("l.agent_id = %s::uuid")
            # IMPORTANT:
            # String, NOT uuid.UUID(...)
            base_params.append(selected_agent)
        except (ValueError, TypeError, AttributeError):
            # Invalid UUID means no rows should match.
            base_where.append("FALSE")

    # ------------------------------------------------------------------
    # Model filter
    # ------------------------------------------------------------------

    if selected_model:
        base_where.append("l.resolved_model_name = %s")
        base_params.append(selected_model)

    # ------------------------------------------------------------------
    # Group filter
    #
    # evaluated_groups is an array stored directly on api_gateway_logs.
    # ------------------------------------------------------------------

    if selected_group:
        base_where.append("%s = ANY(l.evaluated_groups)")
        base_params.append(selected_group)
    where_sql = " AND ".join(base_where)

    # ------------------------------------------------------------------
    # 4. DEFAULT EMPTY STRUCTURES
    # ------------------------------------------------------------------

    totals = {
        'total_tokens': 0,
        'prompt_tokens': 0,
        'completion_tokens': 0,
        'total_calls': 0,
        'successful_calls': 0,
        'error_calls': 0,
        'total_cost': 0.0,
        'avg_tokens_per_call': 0.0,
        'avg_cost_per_call': 0.0,
        'top_user': '—',
        'top_model': '—',
        'top_agent': '—'
    }

    daily_rows = []
    user_rows = []
    agent_rows = []
    group_rows = []
    model_rows = []

    # ------------------------------------------------------------------
    # 5. KPI AGGREGATION
    # ------------------------------------------------------------------

    kpi_sql = f"""
        SELECT
            COUNT(*) AS total_calls,
            COUNT(*) FILTER (WHERE LOWER(COALESCE(l.status, '')) = 'success') AS successful_calls,
            COUNT(*) FILTER (WHERE LOWER(COALESCE(l.status, '')) <> 'success') AS error_calls,
            COALESCE(SUM(l.prompt_tokens),0) AS prompt_tokens,
            COALESCE(SUM(l.completion_tokens),0) AS completion_tokens,
            COALESCE(SUM(l.total_tokens),0) AS total_tokens,
            COALESCE(SUM(l.estimated_cost_usd),0) AS total_cost,
            COALESCE(AVG(l.total_tokens),0) AS avg_tokens_per_call,
            COALESCE(AVG(l.estimated_cost_usd),0) AS avg_cost_per_call
        FROM api_gateway_logs l
        WHERE {where_sql}
    """

    # ------------------------------------------------------------------
    # 6. DAILY TOKEN CONSUMPTION
    # ------------------------------------------------------------------

    daily_sql = f"""
        SELECT
            TO_CHAR(DATE_TRUNC('day',l.timestamp),'YYYY-MM-DD') AS usage_date,
            COALESCE(SUM(l.prompt_tokens),0) AS prompt_tokens,
            COALESCE(SUM(l.completion_tokens),0) AS completion_tokens,
            COALESCE(SUM(l.total_tokens),0) AS total_tokens,
            COALESCE(SUM(l.estimated_cost_usd),0) AS cost,
            COUNT(*) AS call_count
        FROM api_gateway_logs l
        WHERE {where_sql}
        GROUP BY DATE_TRUNC('day',l.timestamp)
        ORDER BY DATE_TRUNC('day',l.timestamp)
    """

    # ------------------------------------------------------------------
    # 7. USER CONSUMPTION
    # ------------------------------------------------------------------

    user_sql = f"""
        SELECT
            COALESCE(l.user_email,'Unknown') AS user_email,
            COUNT(*) AS call_count,
            COALESCE(SUM(l.prompt_tokens),0) AS prompt_tokens,
            COALESCE(SUM(l.completion_tokens),0) AS completion_tokens,
            COALESCE(SUM(l.total_tokens),0) AS total_tokens,
            COALESCE(SUM(l.estimated_cost_usd),0) AS cost
        FROM api_gateway_logs l
        WHERE {where_sql}
        GROUP BY l.user_email
        ORDER BY total_tokens DESC
        LIMIT 25
    """

    # ------------------------------------------------------------------
    # 8. AGENT CONSUMPTION
    # ------------------------------------------------------------------

    agent_sql = f"""
        SELECT
            l.agent_id,
            COALESCE(a.name,'Unknown Agent') AS agent_name,
            COUNT(*) AS call_count,
            COALESCE(SUM(l.prompt_tokens),0) AS prompt_tokens,
            COALESCE(SUM(l.completion_tokens),0) AS completion_tokens,
            COALESCE(SUM(l.total_tokens),0) AS total_tokens,
            COALESCE(SUM(l.estimated_cost_usd),0) AS cost
        FROM api_gateway_logs l
        LEFT JOIN agents a ON a.id = l.agent_id
        WHERE {where_sql}
        GROUP BY
            l.agent_id,
            a.name
        ORDER BY total_tokens DESC
        LIMIT 25
    """

    # ------------------------------------------------------------------
    # 9. GROUP CONSUMPTION
    #
    # evaluated_groups is an array stored on each gateway log.
    #
    # A request can have multiple groups, so these are allocation
    # metrics and must not be added together to calculate global usage.
    # ------------------------------------------------------------------

    group_sql = f"""
        SELECT
            group_name,
            COUNT(*) AS call_count,
            COALESCE(SUM(prompt_tokens),0) AS prompt_tokens,
            COALESCE(SUM(completion_tokens),0) AS completion_tokens,
            COALESCE(SUM(total_tokens),0) AS total_tokens,
            COALESCE(SUM(estimated_cost_usd),0) AS cost
        FROM (
            SELECT
                l.trace_id,
                group_name,
                l.prompt_tokens,
                l.completion_tokens,
                l.total_tokens,
                l.estimated_cost_usd
            FROM api_gateway_logs l
            CROSS JOIN LATERAL unnest(COALESCE(l.evaluated_groups,ARRAY[]::text[])) AS group_name WHERE {where_sql}) grouped_logs
        GROUP BY group_name
        ORDER BY total_tokens DESC
        LIMIT 25
    """

    # ------------------------------------------------------------------
    # 10. MODEL CONSUMPTION
    # ------------------------------------------------------------------

    model_sql = f"""
        SELECT
            COALESCE(l.resolved_model_name,'Unknown Model') AS model_name,
            COUNT(*) AS call_count,
            COALESCE(SUM(l.prompt_tokens),0) AS prompt_tokens,
            COALESCE(SUM(l.completion_tokens),0) AS completion_tokens,
            COALESCE(SUM(l.total_tokens),0) AS total_tokens,
            COALESCE(SUM(l.estimated_cost_usd),0) AS cost
        FROM api_gateway_logs l
        WHERE {where_sql}
        GROUP BY l.resolved_model_name
        ORDER BY total_tokens DESC
        LIMIT 25
    """

    # ------------------------------------------------------------------
    # 11. EXECUTE AGGREGATIONS
    # ------------------------------------------------------------------

    with get_db_cursor() as cur:
        # --------------------------------------------------------------
        # KPI
        # --------------------------------------------------------------
        cur.execute(
            kpi_sql,
            base_params
        )
        kpi = cur.fetchone()
        if kpi:
            totals['total_tokens'] = int(kpi.get('total_tokens') or 0)
            totals['prompt_tokens'] = int(kpi.get('prompt_tokens') or 0)
            totals['completion_tokens'] = int(kpi.get('completion_tokens') or 0)
            totals['total_calls'] = int(kpi.get('total_calls') or 0)
            totals['successful_calls'] = int(kpi.get('successful_calls') or 0)
            totals['error_calls'] = int(kpi.get('error_calls') or 0)
            totals['total_cost'] = float(kpi.get('total_cost') or 0)
            totals['avg_tokens_per_call'] = round(float(kpi.get('avg_tokens_per_call') or 0),2)
            totals['avg_cost_per_call'] = round(float(kpi.get('avg_cost_per_call') or 0),6)

        # --------------------------------------------------------------
        # Daily
        # --------------------------------------------------------------

        cur.execute(
            daily_sql,
            base_params
        )
        daily_rows = cur.fetchall()

        # --------------------------------------------------------------
        # Users
        # --------------------------------------------------------------

        cur.execute(
            user_sql,
            base_params
        )
        user_rows = cur.fetchall()
        # --------------------------------------------------------------
        # Agents
        # --------------------------------------------------------------

        cur.execute(
            agent_sql,
            base_params
        )
        agent_rows = cur.fetchall()
        # --------------------------------------------------------------
        # Groups
        # --------------------------------------------------------------

        cur.execute(
            group_sql,
            base_params
        )
        group_rows = cur.fetchall()
        # --------------------------------------------------------------
        # Models
        # --------------------------------------------------------------

        cur.execute(
            model_sql,
            base_params
        )
        model_rows = cur.fetchall()

    # ------------------------------------------------------------------
    # 12. DETERMINE TOP CONSUMERS
    # ------------------------------------------------------------------

    if user_rows:
        totals['top_user'] = (user_rows[0].get('user_email') or 'Unknown')
    if model_rows:
        totals['top_model'] = (model_rows[0].get('model_name') or 'Unknown')
    if agent_rows:
        totals['top_agent'] = (agent_rows[0].get('agent_name') or 'Unknown')

    # ------------------------------------------------------------------
    # 13. FORMAT DAILY CHART DATA
    # ------------------------------------------------------------------

    dates = [
        row.get('usage_date')
        for row in daily_rows
    ]
    daily_prompt_tokens = [
        int(row.get('prompt_tokens') or 0)
        for row in daily_rows
    ]
    daily_completion_tokens = [
        int(row.get('completion_tokens') or 0)
        for row in daily_rows
    ]
    daily_total_tokens = [
        int(row.get('total_tokens') or 0)
        for row in daily_rows
    ]

    daily_costs = [
        round(
            float(
                row.get('cost') or 0
            ),
            6
        )
        for row in daily_rows
    ]
    daily_calls = [
        int(row.get('call_count') or 0)
        for row in daily_rows
    ]

    # ------------------------------------------------------------------
    # 14. USER CHART DATA
    # ------------------------------------------------------------------

    user_labels = [
        row.get('user_email')
        or 'Unknown'
        for row in user_rows
    ]
    user_tokens = [
        int(row.get('total_tokens') or 0)
        for row in user_rows
    ]
    user_prompt_tokens = [
        int(row.get('prompt_tokens') or 0)
        for row in user_rows
    ]
    user_completion_tokens = [
        int(row.get('completion_tokens') or 0)
        for row in user_rows
    ]
    user_calls = [
        int(row.get('call_count') or 0)
        for row in user_rows
    ]
    user_costs = [
        round(float(row.get('cost') or 0),6)
        for row in user_rows
    ]

    # ------------------------------------------------------------------
    # 15. AGENT CHART DATA
    # ------------------------------------------------------------------

    agent_labels = [
        row.get('agent_name')
        or 'Unknown Agent'
        for row in agent_rows
    ]
    agent_tokens = [
        int(row.get('total_tokens') or 0)
        for row in agent_rows
    ]
    agent_prompt_tokens = [
        int(row.get('prompt_tokens') or 0)
        for row in agent_rows
    ]
    agent_completion_tokens = [
        int(row.get('completion_tokens') or 0)
        for row in agent_rows
    ]
    agent_calls = [
        int(row.get('call_count') or 0)
        for row in agent_rows
    ]
    agent_costs = [
        round(float(row.get('cost') or 0),6)
        for row in agent_rows
    ]

    # ------------------------------------------------------------------
    # 16. GROUP CHART DATA
    # ------------------------------------------------------------------

    group_labels = [
        row.get('group_name')
        or 'Unknown Group'
        for row in group_rows
    ]
    group_tokens = [
        int(row.get('total_tokens') or 0)
        for row in group_rows
    ]
    group_prompt_tokens = [
        int(row.get('prompt_tokens') or 0)
        for row in group_rows
    ]
    group_completion_tokens = [
        int(row.get('completion_tokens') or 0)
        for row in group_rows
    ]
    group_calls = [
        int(row.get('call_count') or 0)
        for row in group_rows
    ]
    group_costs = [round(float(row.get('cost') or 0),6)
        for row in group_rows
    ]

    # ------------------------------------------------------------------
    # 17. MODEL CHART DATA
    # ------------------------------------------------------------------

    model_labels = [
        row.get('model_name')
        or 'Unknown Model'
        for row in model_rows
    ]
    model_tokens = [
        int(row.get('total_tokens') or 0)
        for row in model_rows
    ]
    model_prompt_tokens = [
        int(row.get('prompt_tokens') or 0)
        for row in model_rows
    ]
    model_completion_tokens = [
        int(row.get('completion_tokens') or 0)
        for row in model_rows
    ]
    model_calls = [
        int(row.get('call_count') or 0)
        for row in model_rows
    ]
    model_costs = [
        round(float(row.get('cost') or 0),6)
        for row in model_rows
    ]

    # ------------------------------------------------------------------
    # 18. DETAILED TABLE
    # ------------------------------------------------------------------

    detail_sql = f"""
        SELECT
            l.user_email,
            COALESCE(a.name,'Unknown Agent') AS agent_name,
            COALESCE(NULLIF(ARRAY_TO_STRING(l.evaluated_groups,', '),''),'Unassigned') AS groups,
            COALESCE(l.resolved_model_name,'Unknown Model') AS model_name,
            COUNT(*) AS call_count,
            COALESCE(SUM(l.prompt_tokens),0) AS prompt_tokens,
            COALESCE(SUM(l.completion_tokens),0) AS completion_tokens,
            COALESCE(SUM(l.total_tokens),0) AS total_tokens,
            COALESCE(SUM(l.estimated_cost_usd),0) AS cost
        FROM api_gateway_logs l
        LEFT JOIN agents a ON a.id = l.agent_id
        WHERE {where_sql}
        GROUP BY
            l.user_email,
            a.name,
            l.evaluated_groups,
            l.resolved_model_name
        ORDER BY total_tokens DESC
        LIMIT 500
    """
    with get_db_cursor() as cur:
        cur.execute(
            detail_sql,
            base_params
        )
        detail_rows = cur.fetchall()
    usage_table = []
    for row in detail_rows:
        usage_table.append({
            'user_email': (row.get('user_email') or 'Unknown'),
            'agent_name': (row.get('agent_name') or 'Unknown Agent'),
            'groups': (row.get('groups') or 'Unassigned'),
            'model_name': (row.get('model_name') or 'Unknown Model'),
            'call_count': int(row.get('call_count') or 0),
            'prompt_tokens': int(row.get('prompt_tokens') or 0),
            'completion_tokens': int(row.get('completion_tokens') or 0),
            'total_tokens': int(row.get('total_tokens') or 0),
            'cost': round(float(row.get('cost') or 0),6)
        })

    # ------------------------------------------------------------------
    # 19. FILTER OPTIONS
    #
    # Users
    # ------------------------------------------------------------------

    with get_db_cursor() as cur:
        cur.execute("""
            SELECT DISTINCT
                user_email
            FROM api_gateway_logs
            WHERE user_email IS NOT NULL
              AND user_email <> ''
            ORDER BY user_email
        """)
        filter_users = [
            row['user_email']
            for row in cur.fetchall()
        ]
        # --------------------------------------------------------------
        # Agents
        # --------------------------------------------------------------
        cur.execute("""
            SELECT
                id,
                name
            FROM agents
            ORDER BY name
        """)
        filter_agents = cur.fetchall()

        # --------------------------------------------------------------
        # Groups
        #
        # Do NOT query a separate "groups" table here.
        #
        # evaluated_groups is stored on api_gateway_logs.
        # --------------------------------------------------------------

        cur.execute("""
            SELECT DISTINCT
                group_name
            FROM (
                SELECT
                    unnest(
                        COALESCE(
                            evaluated_groups,
                            ARRAY[]::text[]
                        )
                    ) AS group_name
                FROM api_gateway_logs
            ) AS groups_list
            WHERE group_name IS NOT NULL
              AND group_name <> ''
            ORDER BY group_name
        """)
        filter_groups = [
            row['group_name']
            for row in cur.fetchall()
        ]
        # --------------------------------------------------------------
        # Models
        # --------------------------------------------------------------
        cur.execute("""
            SELECT DISTINCT
                resolved_model_name
            FROM api_gateway_logs
            WHERE resolved_model_name IS NOT NULL
              AND resolved_model_name <> ''
            ORDER BY resolved_model_name
        """)
        filter_models = [
            row['resolved_model_name']
            for row in cur.fetchall()
        ]
    # ------------------------------------------------------------------
    # 20. FINAL CHART DATA OBJECT
    # ------------------------------------------------------------------
    chart_data = {
        # Timeline
        'dates': dates,
        'daily_prompt_tokens': daily_prompt_tokens,
        'daily_completion_tokens': daily_completion_tokens,
        'daily_total_tokens': daily_total_tokens,
        'daily_costs': daily_costs,
        'daily_calls': daily_calls,
        # Users
        'user_labels': user_labels,
        'user_tokens': user_tokens,
        'user_prompt_tokens': user_prompt_tokens,
        'user_completion_tokens': user_completion_tokens,
        'user_calls': user_calls,
        'user_costs': user_costs,
        # Agents
        'agent_labels': agent_labels,
        'agent_tokens': agent_tokens,
        'agent_prompt_tokens': agent_prompt_tokens,
        'agent_completion_tokens': agent_completion_tokens,
        'agent_calls': agent_calls,
        'agent_costs': agent_costs,
        # Groups
        'group_labels': group_labels,
        'group_tokens': group_tokens,
        'group_prompt_tokens': group_prompt_tokens,
        'group_completion_tokens': group_completion_tokens,
        'group_calls': group_calls,
        'group_costs': group_costs,
        # Models
        'model_labels': model_labels,
        'model_tokens': model_tokens,
        'model_prompt_tokens': model_prompt_tokens,
        'model_completion_tokens': model_completion_tokens,
        'model_calls': model_calls,
        'model_costs': model_costs
    }

    # ------------------------------------------------------------------
    # 21. RENDER
    # ------------------------------------------------------------------

    return render_template(
        'token_usage.html',
        totals=totals,
        chart_data=chart_data,
        usage_table=usage_table,
        # Current filters
        start_date=start_date.strftime('%Y-%m-%d'),
        end_date=end_date.strftime('%Y-%m-%d'),
        selected_user=selected_user,
        selected_group=selected_group,
        selected_agent=selected_agent,
        selected_model=selected_model,
        # Filter options
        filter_users=filter_users,
        filter_groups=filter_groups,
        filter_agents=filter_agents,
        filter_models=filter_models
    )

if __name__ == '__main__':
    app.run(debug=True, port=int(os.environ.get("PORT", 8080)), host='0.0.0.0')



