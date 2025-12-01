import os
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
from passlib.hash import bcrypt
from dotenv import load_dotenv
from decimal import Decimal
import random
import json
from datetime import datetime

load_dotenv()  # reads .env

app = Flask(__name__, static_folder='static', template_folder='templates')
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'devkey')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///pychance.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# ---------- Models ----------
class User(db.Model, UserMixin):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(200), unique=True)
    password_hash = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Wallet(db.Model):
    __tablename__ = 'wallets'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'))
    balance = db.Column(db.Numeric(12,2), default=0)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Transaction(db.Model):
    __tablename__ = 'transactions'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'))
    amount = db.Column(db.Numeric(12,2))
    type = db.Column(db.String(20))
    metadata = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class CoinflipBet(db.Model):
    __tablename__ = 'coinflip_bets'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'))
    choice = db.Column(db.String(10))
    stake = db.Column(db.Numeric(12,2))
    result = db.Column(db.String(10))
    payout = db.Column(db.Numeric(12,2))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ---------- Login loader ----------
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ---------- Routes ----------
@app.route('/')
def index():
    return render_template('index.html')  # use your existing homepage HTML here

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        username = request.form['username'].strip()
        email = request.form.get('email')
        password = request.form['password']
        if User.query.filter_by(username=username).first():
            flash('Username taken', 'danger')
            return redirect(url_for('register'))
        pw_hash = bcrypt.hash(password)
        user = User(username=username, email=email, password_hash=pw_hash)
        db.session.add(user)
        db.session.commit()
        # create wallet
        w = Wallet(user_id=user.id, balance=0)
        db.session.add(w)
        db.session.commit()
        flash('Registered. Please log in.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        u = User.query.filter_by(username=username).first()
        if not u or not bcrypt.verify(password, u.password_hash):
            flash('Invalid credentials', 'danger')
            return redirect(url_for('login'))
        login_user(u)
        flash('Logged in', 'success')
        return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out', 'info')
    return redirect(url_for('index'))

# API: coinflip play
@app.route('/api/coinflip', methods=['POST'])
@login_required
def coinflip():
    data = request.get_json() or request.form
    choice = (data.get('choice') or '').lower()
    try:
        stake = Decimal(str(data.get('stake')))
    except Exception:
        return jsonify({'error': 'invalid stake'}), 400
    if stake <= 0:
        return jsonify({'error': 'stake must be > 0'}), 400

    # check wallet
    wallet = Wallet.query.filter_by(user_id=current_user.id).first()
    if wallet is None:
        return jsonify({'error': 'no wallet'}), 400
    if wallet.balance < stake:
        return jsonify({'error': 'insufficient funds'}), 400

    # flip
    result = random.choice(['heads','tails'])
    payout = Decimal('0')
    if choice == result:
        payout = stake * Decimal('1.9')  # house edge (you can tune)
        # credit wallet
        wallet.balance = wallet.balance - stake + payout
        tx_type = 'win'
    else:
        wallet.balance = wallet.balance - stake
        tx_type = 'bet'

    db.session.add(Transaction(user_id=current_user.id, amount=stake if tx_type=='bet' else payout, type=tx_type, metadata=json.dumps({'choice':choice,'result':result})))
    cf = CoinflipBet(user_id=current_user.id, choice=choice, stake=stake, result=result, payout=payout)
    db.session.add(cf)
    db.session.commit()

    return jsonify({
        'result': result,
        'payout': float(payout),
        'balance': float(wallet.balance)
    })

# dev helper: create DB
@app.cli.command('init-db')
def init_db():
    db.create_all()
    print("DB created")

if __name__ == '__main__':
    app.run(debug=True)
