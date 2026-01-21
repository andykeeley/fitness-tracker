from flask import Flask, render_template, request, redirect, url_for, jsonify
from datetime import datetime
import sqlite3
import os

app = Flask(__name__)
DATABASE = 'fitness.db'

def get_db():
    """Get database connection."""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize the database with tables."""
    conn = get_db()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS workouts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date DATE NOT NULL,
            exercise_type TEXT NOT NULL,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS sets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workout_id INTEGER NOT NULL,
            set_number INTEGER NOT NULL,
            reps INTEGER NOT NULL,
            weight REAL NOT NULL,
            FOREIGN KEY (workout_id) REFERENCES workouts (id) ON DELETE CASCADE
        );
    ''')
    conn.commit()
    conn.close()

@app.route('/')
def index():
    """Home page - show recent workouts."""
    conn = get_db()
    workouts = conn.execute('''
        SELECT w.*, COUNT(s.id) as set_count
        FROM workouts w
        LEFT JOIN sets s ON w.id = s.workout_id
        GROUP BY w.id
        ORDER BY w.date DESC, w.created_at DESC
        LIMIT 20
    ''').fetchall()
    conn.close()
    return render_template('index.html', workouts=workouts)

@app.route('/workout/new', methods=['GET', 'POST'])
def new_workout():
    """Create a new workout session."""
    if request.method == 'POST':
        date = request.form['date']
        exercise_type = request.form['exercise_type']
        notes = request.form.get('notes', '')

        conn = get_db()
        cursor = conn.execute(
            'INSERT INTO workouts (date, exercise_type, notes) VALUES (?, ?, ?)',
            (date, exercise_type, notes)
        )
        workout_id = cursor.lastrowid
        conn.commit()
        conn.close()

        return redirect(url_for('view_workout', workout_id=workout_id))

    today = datetime.now().strftime('%Y-%m-%d')
    return render_template('new_workout.html', today=today)

@app.route('/workout/<int:workout_id>')
def view_workout(workout_id):
    """View a specific workout with its sets."""
    conn = get_db()
    workout = conn.execute(
        'SELECT * FROM workouts WHERE id = ?', (workout_id,)
    ).fetchone()

    if not workout:
        conn.close()
        return redirect(url_for('index'))

    sets = conn.execute(
        'SELECT * FROM sets WHERE workout_id = ? ORDER BY set_number',
        (workout_id,)
    ).fetchall()
    conn.close()

    return render_template('view_workout.html', workout=workout, sets=sets)

@app.route('/workout/<int:workout_id>/add_set', methods=['POST'])
def add_set(workout_id):
    """Add a set to a workout."""
    reps = int(request.form['reps'])
    weight = float(request.form['weight'])

    conn = get_db()

    # Get the next set number
    result = conn.execute(
        'SELECT MAX(set_number) as max_set FROM sets WHERE workout_id = ?',
        (workout_id,)
    ).fetchone()
    next_set = (result['max_set'] or 0) + 1

    conn.execute(
        'INSERT INTO sets (workout_id, set_number, reps, weight) VALUES (?, ?, ?, ?)',
        (workout_id, next_set, reps, weight)
    )
    conn.commit()
    conn.close()

    return redirect(url_for('view_workout', workout_id=workout_id))

@app.route('/workout/<int:workout_id>/delete_set/<int:set_id>', methods=['POST'])
def delete_set(workout_id, set_id):
    """Delete a set from a workout."""
    conn = get_db()
    conn.execute('DELETE FROM sets WHERE id = ?', (set_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('view_workout', workout_id=workout_id))

@app.route('/workout/<int:workout_id>/edit', methods=['GET', 'POST'])
def edit_workout(workout_id):
    """Edit workout notes."""
    conn = get_db()

    if request.method == 'POST':
        notes = request.form.get('notes', '')
        conn.execute(
            'UPDATE workouts SET notes = ? WHERE id = ?',
            (notes, workout_id)
        )
        conn.commit()
        conn.close()
        return redirect(url_for('view_workout', workout_id=workout_id))

    workout = conn.execute(
        'SELECT * FROM workouts WHERE id = ?', (workout_id,)
    ).fetchone()
    conn.close()

    return render_template('edit_workout.html', workout=workout)

@app.route('/workout/<int:workout_id>/delete', methods=['POST'])
def delete_workout(workout_id):
    """Delete a workout and its sets."""
    conn = get_db()
    conn.execute('DELETE FROM sets WHERE workout_id = ?', (workout_id,))
    conn.execute('DELETE FROM workouts WHERE id = ?', (workout_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('index'))

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5001)
