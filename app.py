from flask import Flask, render_template, request, redirect, url_for, jsonify
from datetime import datetime
import os

app = Flask(__name__)

# Database configuration - PostgreSQL in production, SQLite locally
DATABASE_URL = os.environ.get('DATABASE_URL')

if DATABASE_URL:
    # PostgreSQL (production)
    import psycopg2
    from psycopg2.extras import RealDictCursor

    def get_db():
        conn = psycopg2.connect(DATABASE_URL)
        return conn

    def get_cursor(conn):
        return conn.cursor(cursor_factory=RealDictCursor)

    def init_db():
        conn = get_db()
        cur = conn.cursor()
        cur.execute('''
            CREATE TABLE IF NOT EXISTS workouts (
                id SERIAL PRIMARY KEY,
                workout_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'in_progress',
                date DATE NOT NULL,
                notes TEXT,
                duration_minutes INTEGER,
                distance_km REAL,
                template_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP
            );
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS exercises (
                id SERIAL PRIMARY KEY,
                workout_id INTEGER NOT NULL REFERENCES workouts(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                order_num INTEGER NOT NULL,
                target_sets INTEGER,
                target_reps INTEGER,
                target_weight REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS sets (
                id SERIAL PRIMARY KEY,
                exercise_id INTEGER NOT NULL REFERENCES exercises(id) ON DELETE CASCADE,
                set_number INTEGER NOT NULL,
                reps INTEGER NOT NULL,
                weight REAL NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS templates (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                workout_type TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS template_exercises (
                id SERIAL PRIMARY KEY,
                template_id INTEGER NOT NULL REFERENCES templates(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                order_num INTEGER NOT NULL,
                target_sets INTEGER NOT NULL DEFAULT 3,
                target_reps INTEGER NOT NULL DEFAULT 10,
                target_weight REAL NOT NULL DEFAULT 0
            );
        ''')
        conn.commit()
        cur.close()
        conn.close()

    PARAM_STYLE = '%s'
else:
    # SQLite (local development)
    import sqlite3

    def get_db():
        conn = sqlite3.connect('fitness.db')
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def get_cursor(conn):
        return conn.cursor()

    def init_db():
        conn = get_db()
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS workouts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workout_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'in_progress',
                date DATE NOT NULL,
                notes TEXT,
                duration_minutes INTEGER,
                distance_km REAL,
                template_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS exercises (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workout_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                order_num INTEGER NOT NULL,
                target_sets INTEGER,
                target_reps INTEGER,
                target_weight REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (workout_id) REFERENCES workouts (id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS sets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                exercise_id INTEGER NOT NULL,
                set_number INTEGER NOT NULL,
                reps INTEGER NOT NULL,
                weight REAL NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (exercise_id) REFERENCES exercises (id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                workout_type TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS template_exercises (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                template_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                order_num INTEGER NOT NULL,
                target_sets INTEGER NOT NULL DEFAULT 3,
                target_reps INTEGER NOT NULL DEFAULT 10,
                target_weight REAL NOT NULL DEFAULT 0,
                FOREIGN KEY (template_id) REFERENCES templates (id) ON DELETE CASCADE
            );
        ''')
        conn.commit()
        conn.close()

    PARAM_STYLE = '?'

def p(query):
    """Convert ? placeholders to %s for PostgreSQL."""
    if DATABASE_URL:
        return query.replace('?', '%s')
    return query

# ============================================
# HOME & NAVIGATION
# ============================================

@app.route('/')
def index():
    """Home page - show in-progress workout and recent completed workouts."""
    conn = get_db()
    cur = get_cursor(conn)

    # Check for in-progress workout
    cur.execute(p('''
        SELECT * FROM workouts WHERE status = 'in_progress' ORDER BY created_at DESC LIMIT 1
    '''))
    in_progress = cur.fetchone()

    # Get recent completed workouts
    cur.execute(p('''
        SELECT w.*,
            (SELECT COUNT(*) FROM exercises WHERE workout_id = w.id) as exercise_count,
            (SELECT COUNT(*) FROM sets s JOIN exercises e ON s.exercise_id = e.id WHERE e.workout_id = w.id) as set_count
        FROM workouts w
        WHERE w.status = 'completed'
        ORDER BY w.date DESC, w.completed_at DESC
        LIMIT 20
    '''))
    workouts = cur.fetchall()

    cur.close()
    conn.close()
    return render_template('index.html', workouts=workouts, in_progress=in_progress)

# ============================================
# WORKOUT CREATION FLOW
# ============================================

@app.route('/workout/new')
def select_workout_type():
    """Select workout type page."""
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute(p('''
        SELECT t.*,
            (SELECT COUNT(*) FROM template_exercises WHERE template_id = t.id) as exercise_count
        FROM templates t
        ORDER BY t.name
    '''))
    templates = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('select_type.html', templates=templates)

@app.route('/workout/start', methods=['POST'])
def start_workout():
    """Start a new workout of the selected type."""
    workout_type = request.form['workout_type']
    today = datetime.now().strftime('%Y-%m-%d')

    conn = get_db()
    cur = get_cursor(conn)
    cur.execute(p(
        'INSERT INTO workouts (workout_type, date, status) VALUES (?, ?, ?) RETURNING id'
        if DATABASE_URL else
        'INSERT INTO workouts (workout_type, date, status) VALUES (?, ?, ?)'
    ), (workout_type, today, 'in_progress'))

    if DATABASE_URL:
        workout_id = cur.fetchone()['id']
    else:
        workout_id = cur.lastrowid

    conn.commit()
    cur.close()
    conn.close()

    if workout_type == 'run':
        return redirect(url_for('active_run', workout_id=workout_id))
    else:
        return redirect(url_for('active_workout', workout_id=workout_id))

# ============================================
# ACTIVE WORKOUT (Strength/Circuit)
# ============================================

@app.route('/workout/<int:workout_id>/active')
def active_workout(workout_id):
    """Active workout session page."""
    conn = get_db()
    cur = get_cursor(conn)

    cur.execute(p('SELECT * FROM workouts WHERE id = ?'), (workout_id,))
    workout = cur.fetchone()

    if not workout or workout['status'] != 'in_progress':
        cur.close()
        conn.close()
        return redirect(url_for('index'))

    # Get exercises with their sets
    cur.execute(p('''
        SELECT e.*,
            (SELECT COUNT(*) FROM sets WHERE exercise_id = e.id) as set_count
        FROM exercises e
        WHERE e.workout_id = ?
        ORDER BY e.order_num
    '''), (workout_id,))
    exercises = cur.fetchall()

    exercises_with_sets = []
    for exercise in exercises:
        cur.execute(p(
            'SELECT * FROM sets WHERE exercise_id = ? ORDER BY set_number'
        ), (exercise['id'],))
        sets = cur.fetchall()
        exercises_with_sets.append({
            'exercise': exercise,
            'sets': sets
        })

    cur.close()
    conn.close()
    return render_template('active_workout.html', workout=workout, exercises=exercises_with_sets)

@app.route('/workout/<int:workout_id>/add_exercise', methods=['POST'])
def add_exercise(workout_id):
    """Add a new exercise to the workout."""
    name = request.form['exercise_name'].strip()

    if not name:
        return redirect(url_for('active_workout', workout_id=workout_id))

    conn = get_db()
    cur = get_cursor(conn)

    # Get next order number
    cur.execute(p(
        'SELECT MAX(order_num) as max_order FROM exercises WHERE workout_id = ?'
    ), (workout_id,))
    result = cur.fetchone()
    next_order = (result['max_order'] or 0) + 1

    cur.execute(p(
        'INSERT INTO exercises (workout_id, name, order_num) VALUES (?, ?, ?)'
    ), (workout_id, name, next_order))
    conn.commit()
    cur.close()
    conn.close()

    return redirect(url_for('active_workout', workout_id=workout_id))

@app.route('/workout/<int:workout_id>/exercise/<int:exercise_id>/add_set', methods=['POST'])
def add_set(workout_id, exercise_id):
    """Add a set to an exercise."""
    reps = int(request.form['reps'])
    weight = float(request.form['weight'])

    conn = get_db()
    cur = get_cursor(conn)

    # Get next set number
    cur.execute(p(
        'SELECT MAX(set_number) as max_set FROM sets WHERE exercise_id = ?'
    ), (exercise_id,))
    result = cur.fetchone()
    next_set = (result['max_set'] or 0) + 1

    cur.execute(p(
        'INSERT INTO sets (exercise_id, set_number, reps, weight) VALUES (?, ?, ?, ?)'
    ), (exercise_id, next_set, reps, weight))
    conn.commit()
    cur.close()
    conn.close()

    return redirect(url_for('active_workout', workout_id=workout_id))

@app.route('/workout/<int:workout_id>/exercise/<int:exercise_id>/delete_set/<int:set_id>', methods=['POST'])
def delete_set(workout_id, exercise_id, set_id):
    """Delete a set from an exercise."""
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute(p('DELETE FROM sets WHERE id = ?'), (set_id,))
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for('active_workout', workout_id=workout_id))

@app.route('/workout/<int:workout_id>/delete_exercise/<int:exercise_id>', methods=['POST'])
def delete_exercise(workout_id, exercise_id):
    """Delete an exercise and its sets."""
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute(p('DELETE FROM sets WHERE exercise_id = ?'), (exercise_id,))
    cur.execute(p('DELETE FROM exercises WHERE id = ?'), (exercise_id,))
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for('active_workout', workout_id=workout_id))

# ============================================
# ACTIVE RUN
# ============================================

@app.route('/workout/<int:workout_id>/run')
def active_run(workout_id):
    """Active run tracking page."""
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute(p('SELECT * FROM workouts WHERE id = ?'), (workout_id,))
    workout = cur.fetchone()

    if not workout or workout['status'] != 'in_progress':
        cur.close()
        conn.close()
        return redirect(url_for('index'))

    cur.close()
    conn.close()
    return render_template('active_run.html', workout=workout)

@app.route('/workout/<int:workout_id>/update_run', methods=['POST'])
def update_run(workout_id):
    """Update run details."""
    duration = request.form.get('duration_minutes', type=int)
    distance = request.form.get('distance_km', type=float)

    conn = get_db()
    cur = get_cursor(conn)
    cur.execute(p(
        'UPDATE workouts SET duration_minutes = ?, distance_km = ? WHERE id = ?'
    ), (duration, distance, workout_id))
    conn.commit()
    cur.close()
    conn.close()

    return redirect(url_for('workout_summary', workout_id=workout_id))

# ============================================
# WORKOUT SUMMARY & COMPLETION
# ============================================

@app.route('/workout/<int:workout_id>/summary')
def workout_summary(workout_id):
    """Workout summary page before saving."""
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute(p('SELECT * FROM workouts WHERE id = ?'), (workout_id,))
    workout = cur.fetchone()

    if not workout:
        cur.close()
        conn.close()
        return redirect(url_for('index'))

    exercises_with_sets = []
    if workout['workout_type'] != 'run':
        cur.execute(p(
            'SELECT * FROM exercises WHERE workout_id = ? ORDER BY order_num'
        ), (workout_id,))
        exercises = cur.fetchall()

        for exercise in exercises:
            cur.execute(p(
                'SELECT * FROM sets WHERE exercise_id = ? ORDER BY set_number'
            ), (exercise['id'],))
            sets = cur.fetchall()
            exercises_with_sets.append({
                'exercise': exercise,
                'sets': sets
            })

    cur.close()
    conn.close()
    return render_template('workout_summary.html', workout=workout, exercises=exercises_with_sets)

@app.route('/workout/<int:workout_id>/finish', methods=['POST'])
def finish_workout(workout_id):
    """Mark workout as completed with notes."""
    notes = request.form.get('notes', '')

    conn = get_db()
    cur = get_cursor(conn)
    cur.execute(p(
        '''UPDATE workouts
           SET status = 'completed', notes = ?, completed_at = CURRENT_TIMESTAMP
           WHERE id = ?'''
    ), (notes, workout_id))
    conn.commit()
    cur.close()
    conn.close()

    return redirect(url_for('view_workout', workout_id=workout_id))

@app.route('/workout/<int:workout_id>/cancel', methods=['POST'])
def cancel_workout(workout_id):
    """Cancel and delete an in-progress workout."""
    conn = get_db()
    cur = get_cursor(conn)
    # Delete sets first (via exercises)
    cur.execute(p('''
        DELETE FROM sets WHERE exercise_id IN
        (SELECT id FROM exercises WHERE workout_id = ?)
    '''), (workout_id,))
    cur.execute(p('DELETE FROM exercises WHERE workout_id = ?'), (workout_id,))
    cur.execute(p('DELETE FROM workouts WHERE id = ? AND status = ?'), (workout_id, 'in_progress'))
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for('index'))

# ============================================
# VIEW COMPLETED WORKOUT
# ============================================

@app.route('/workout/<int:workout_id>')
def view_workout(workout_id):
    """View a completed workout."""
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute(p('SELECT * FROM workouts WHERE id = ?'), (workout_id,))
    workout = cur.fetchone()

    if not workout:
        cur.close()
        conn.close()
        return redirect(url_for('index'))

    # If still in progress, redirect to active page
    if workout['status'] == 'in_progress':
        cur.close()
        conn.close()
        if workout['workout_type'] == 'run':
            return redirect(url_for('active_run', workout_id=workout_id))
        else:
            return redirect(url_for('active_workout', workout_id=workout_id))

    exercises_with_sets = []
    if workout['workout_type'] != 'run':
        cur.execute(p(
            'SELECT * FROM exercises WHERE workout_id = ? ORDER BY order_num'
        ), (workout_id,))
        exercises = cur.fetchall()

        for exercise in exercises:
            cur.execute(p(
                'SELECT * FROM sets WHERE exercise_id = ? ORDER BY set_number'
            ), (exercise['id'],))
            sets = cur.fetchall()
            exercises_with_sets.append({
                'exercise': exercise,
                'sets': sets
            })

    cur.close()
    conn.close()
    return render_template('view_workout.html', workout=workout, exercises=exercises_with_sets)

@app.route('/workout/<int:workout_id>/delete', methods=['POST'])
def delete_workout(workout_id):
    """Delete a completed workout."""
    conn = get_db()
    cur = get_cursor(conn)
    # Only allow deleting completed workouts
    cur.execute(p('''
        DELETE FROM sets WHERE exercise_id IN
        (SELECT id FROM exercises WHERE workout_id = ?)
    '''), (workout_id,))
    cur.execute(p('DELETE FROM exercises WHERE workout_id = ?'), (workout_id,))
    cur.execute(p('DELETE FROM workouts WHERE id = ? AND status = ?'), (workout_id, 'completed'))
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for('index'))

# ============================================
# WORKOUT TEMPLATES
# ============================================

@app.route('/templates')
def list_templates():
    """List all workout templates."""
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute(p('''
        SELECT t.*,
            (SELECT COUNT(*) FROM template_exercises WHERE template_id = t.id) as exercise_count
        FROM templates t
        ORDER BY t.created_at DESC
    '''))
    templates = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('templates_list.html', templates=templates)

@app.route('/templates/new', methods=['GET', 'POST'])
def new_template():
    """Create a new workout template."""
    if request.method == 'POST':
        name = request.form['name'].strip()
        workout_type = request.form['workout_type']

        if not name:
            return redirect(url_for('new_template'))

        conn = get_db()
        cur = get_cursor(conn)
        cur.execute(p(
            'INSERT INTO templates (name, workout_type) VALUES (?, ?) RETURNING id'
            if DATABASE_URL else
            'INSERT INTO templates (name, workout_type) VALUES (?, ?)'
        ), (name, workout_type))

        if DATABASE_URL:
            template_id = cur.fetchone()['id']
        else:
            template_id = cur.lastrowid

        conn.commit()
        cur.close()
        conn.close()

        return redirect(url_for('edit_template', template_id=template_id))

    return render_template('template_new.html')

@app.route('/templates/<int:template_id>')
def view_template(template_id):
    """View a workout template."""
    conn = get_db()
    cur = get_cursor(conn)

    cur.execute(p('SELECT * FROM templates WHERE id = ?'), (template_id,))
    template = cur.fetchone()

    if not template:
        cur.close()
        conn.close()
        return redirect(url_for('list_templates'))

    cur.execute(p(
        'SELECT * FROM template_exercises WHERE template_id = ? ORDER BY order_num'
    ), (template_id,))
    exercises = cur.fetchall()

    cur.close()
    conn.close()
    return render_template('template_view.html', template=template, exercises=exercises)

@app.route('/templates/<int:template_id>/edit')
def edit_template(template_id):
    """Edit a workout template."""
    conn = get_db()
    cur = get_cursor(conn)

    cur.execute(p('SELECT * FROM templates WHERE id = ?'), (template_id,))
    template = cur.fetchone()

    if not template:
        cur.close()
        conn.close()
        return redirect(url_for('list_templates'))

    cur.execute(p(
        'SELECT * FROM template_exercises WHERE template_id = ? ORDER BY order_num'
    ), (template_id,))
    exercises = cur.fetchall()

    cur.close()
    conn.close()
    return render_template('template_edit.html', template=template, exercises=exercises)

@app.route('/templates/<int:template_id>/add_exercise', methods=['POST'])
def add_template_exercise(template_id):
    """Add an exercise to a template."""
    name = request.form['exercise_name'].strip()
    target_sets = int(request.form.get('target_sets', 3))
    target_reps = int(request.form.get('target_reps', 10))
    target_weight = float(request.form.get('target_weight', 0))

    if not name:
        return redirect(url_for('edit_template', template_id=template_id))

    conn = get_db()
    cur = get_cursor(conn)

    # Get next order number
    cur.execute(p(
        'SELECT MAX(order_num) as max_order FROM template_exercises WHERE template_id = ?'
    ), (template_id,))
    result = cur.fetchone()
    next_order = (result['max_order'] or 0) + 1

    cur.execute(p(
        'INSERT INTO template_exercises (template_id, name, order_num, target_sets, target_reps, target_weight) VALUES (?, ?, ?, ?, ?, ?)'
    ), (template_id, name, next_order, target_sets, target_reps, target_weight))
    conn.commit()
    cur.close()
    conn.close()

    return redirect(url_for('edit_template', template_id=template_id))

@app.route('/templates/<int:template_id>/delete_exercise/<int:exercise_id>', methods=['POST'])
def delete_template_exercise(template_id, exercise_id):
    """Delete an exercise from a template."""
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute(p('DELETE FROM template_exercises WHERE id = ?'), (exercise_id,))
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for('edit_template', template_id=template_id))

@app.route('/templates/<int:template_id>/delete', methods=['POST'])
def delete_template(template_id):
    """Delete a workout template."""
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute(p('DELETE FROM template_exercises WHERE template_id = ?'), (template_id,))
    cur.execute(p('DELETE FROM templates WHERE id = ?'), (template_id,))
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for('list_templates'))

@app.route('/workout/start-from-template/<int:template_id>', methods=['POST'])
def start_from_template(template_id):
    """Start a new workout from a template."""
    conn = get_db()
    cur = get_cursor(conn)

    # Get template
    cur.execute(p('SELECT * FROM templates WHERE id = ?'), (template_id,))
    template = cur.fetchone()

    if not template:
        cur.close()
        conn.close()
        return redirect(url_for('select_workout_type'))

    today = datetime.now().strftime('%Y-%m-%d')

    # Create workout
    cur.execute(p(
        'INSERT INTO workouts (workout_type, date, status, template_id) VALUES (?, ?, ?, ?) RETURNING id'
        if DATABASE_URL else
        'INSERT INTO workouts (workout_type, date, status, template_id) VALUES (?, ?, ?, ?)'
    ), (template['workout_type'], today, 'in_progress', template_id))

    if DATABASE_URL:
        workout_id = cur.fetchone()['id']
    else:
        workout_id = cur.lastrowid

    # Get template exercises
    cur.execute(p(
        'SELECT * FROM template_exercises WHERE template_id = ? ORDER BY order_num'
    ), (template_id,))
    template_exercises = cur.fetchall()

    # Create exercises from template
    for te in template_exercises:
        cur.execute(p(
            'INSERT INTO exercises (workout_id, name, order_num, target_sets, target_reps, target_weight) VALUES (?, ?, ?, ?, ?, ?)'
        ), (workout_id, te['name'], te['order_num'], te['target_sets'], te['target_reps'], te['target_weight']))

    conn.commit()
    cur.close()
    conn.close()

    return redirect(url_for('active_workout', workout_id=workout_id))

# Initialize database on startup
with app.app_context():
    init_db()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)
