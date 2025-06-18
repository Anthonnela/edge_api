from flask import Flask, jsonify, request
from flask_cors import CORS
import sqlite3
import threading
from datetime import datetime
import os

app = Flask(__name__)
CORS(app)

DB_PATH = os.path.join(os.getcwd(), "facelock.db")

# === Cola de comandos automáticos para ESP32 ===
pending_commands = []
command_lock = threading.Lock()

def init_database():
    """Inicializa base de datos y tablas si no existen."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            age INTEGER,
            pin TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active BOOLEAN DEFAULT 1
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS access_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_name TEXT,
            access_method TEXT,
            success BOOLEAN,
            confidence REAL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def log_access(user_name, method, success, confidence=0.0):
    """Registra log de acceso."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO access_logs (user_name, access_method, success, confidence)
            VALUES (?, ?, ?, ?)
        ''', (user_name, method, int(success), confidence))
        conn.commit()
        conn.close()
        status = "✅" if success else "❌"
        print(f"📝 Log: {status} {user_name} - {method} - {confidence:.2f}")
    except Exception as e:
        print(f"Error logging: {e}")

# === API PRINCIPALES ===

@app.route('/api/get-pending-commands', methods=['GET'])
def get_pending_commands():
    """ESP32 consulta comandos pendientes."""
    global pending_commands
    with command_lock:
        if pending_commands:
            command = pending_commands.pop(0)  # FIFO
            print(f"📤 Enviando comando a ESP32: {command}")
            return command
        else:
            return "NONE"

@app.route('/api/notify-access', methods=['POST'])
def notify_access():
    """Python notifica reconocimiento facial o PIN exitoso."""
    global pending_commands
    try:
        data = request.get_json()
        user_name = data.get('user_name')
        method = data.get('method', 'unknown')
        success = data.get('success', False)
        confidence = data.get('confidence', 0.0)

        # Log del evento
        log_access(user_name, method, success, confidence)

        if success and user_name and user_name != "Desconocido":
            # Agregar comando para ESP32
            with command_lock:
                command = f"OPEN:{user_name}"
                pending_commands.append(command)
                print(f"📥 Comando agregado para ESP32: {command}")

            return jsonify({
                'status': 'success',
                'message': f'Access granted for {user_name}',
                'command_queued': command
            })
        else:
            return jsonify({
                'status': 'denied',
                'message': f'Access denied for {user_name}'
            })

    except Exception as e:
        print(f"Error in notify_access: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/confirm-command', methods=['POST'])
def confirm_command():
    """ESP32 confirma que procesó comando."""
    try:
        data = request.get_json() or {}
        command = data.get('command', 'unknown')
        status = data.get('status', 'unknown')

        print(f"✅ ESP32 confirmó: {command} - {status}")

        return jsonify({
            'status': 'confirmed',
            'timestamp': datetime.now().isoformat()
        })

    except Exception as e:
        print(f"Error in confirm_command: {e}")
        return jsonify({'error': str(e)}), 500

# === API AUXILIARES (debug/monitoreo) ===

@app.route('/api/status', methods=['GET'])
def get_status():
    """Estado del sistema y últimos accesos."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM users WHERE is_active = 1')
        total_users = cursor.fetchone()[0]

        cursor.execute('''
            SELECT user_name, access_method, success, confidence, timestamp 
            FROM access_logs 
            ORDER BY timestamp DESC 
            LIMIT 10
        ''')
        recent_logs = cursor.fetchall()
        conn.close()

        with command_lock:
            pending_count = len(pending_commands)

        return jsonify({
            'system_status': 'online',
            'total_users': total_users,
            'pending_commands': pending_count,
            'recent_access': [
                {
                    'user': log[0],
                    'method': log[1],
                    'success': bool(log[2]),
                    'confidence': log[3],
                    'timestamp': log[4]
                } for log in recent_logs
            ],
            'timestamp': datetime.now().isoformat()
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/users', methods=['GET'])
def get_users():
    """Lista de usuarios registrados (para debug)."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT id, name, age, created_at, is_active FROM users')
        users = cursor.fetchall()
        conn.close()

        return jsonify([
            {
                'id': user[0],
                'name': user[1],
                'age': user[2],
                'created_at': user[3],
                'is_active': bool(user[4])
            } for user in users
        ])

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/users/<username>', methods=['DELETE'])
def delete_user(username):
    """Elimina un usuario por nombre."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM users WHERE name = ?', (username,))
        conn.commit()
        changes = cursor.rowcount
        conn.close()
        if changes:
            return jsonify({'status': 'success', 'message': f'Usuario "{username}" eliminado.'}), 200
        else:
            return jsonify({'status': 'not_found', 'message': f'Usuario "{username}" no encontrado.'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    

@app.route('/api/access_logs', methods=['DELETE'])
def delete_all_access_logs():
    """Elimina todos los logs de acceso."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM access_logs')
        conn.commit()
        changes = cursor.rowcount
        conn.close()
        return jsonify({'status': 'success', 'message': f'Se eliminaron {changes} registros de access_logs.'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
# === MAIN ===

if __name__ == '__main__':
    init_database()
    print("🚀 FaceLock Edge API Server")
    print("=" * 50)
    print("📡 APIs disponibles:")
    print("   GET  /api/get-pending-commands     ← ESP32 consulta automática")
    print("   POST /api/notify-access            ← Python notifica reconocimiento")
    print("   POST /api/confirm-command          ← ESP32 confirma procesamiento")
    print("   GET  /api/status                   ← Estado del sistema")
    print("   GET  /api/users                    ← Lista usuarios (debug)")
    print("=" * 50)
    print("🎯 Listo para recibir conexiones en http://0.0.0.0:5000 ...")
    app.run(host='0.0.0.0', port=5000, debug=True)