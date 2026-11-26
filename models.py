
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import date

db = SQLAlchemy()


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Book(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    author = db.Column(db.String(150), nullable=False)
    isbn = db.Column(db.String(30), unique=True, nullable=True)
    category = db.Column(db.String(100))
    publisher = db.Column(db.String(150))
    quantity = db.Column(db.Integer, nullable=False, default=1)

    loans = db.relationship("Loan", backref="book", lazy=True)

    @property
    def issued_count(self):
        return Loan.query.filter_by(
            book_id=self.id,
            return_date=None
        ).count()

    @property
    def available_count(self):
        return self.quantity - self.issued_count


class Member(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    phone = db.Column(db.String(20))
    address = db.Column(db.Text)

    loans = db.relationship("Loan", backref="member", lazy=True)


class Loan(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    book_id = db.Column(
        db.Integer,
        db.ForeignKey("book.id"),
        nullable=False
    )

    member_id = db.Column(
        db.Integer,
        db.ForeignKey("member.id"),
        nullable=False
    )

    issue_date = db.Column(db.Date, nullable=False, default=date.today)
    due_date = db.Column(db.Date, nullable=False)
    return_date = db.Column(db.Date, nullable=True)

    fine = db.Column(db.Integer, nullable=False, default=0)

    @property
    def status(self):
        if self.return_date:
            return "Returned"

        if self.due_date < date.today():
            return "Overdue"

        return "Issued"

    @property
    def current_fine(self):
        end_date = self.return_date or date.today()
        overdue_days = max((end_date - self.due_date).days, 0)
        return overdue_days * 5
