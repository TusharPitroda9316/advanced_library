
import os
from datetime import date, timedelta
from functools import wraps

import click
from dotenv import load_dotenv
from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, abort
)
from flask_login import (
    LoginManager, login_user, logout_user,
    login_required, current_user
)
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import or_, func
from sqlalchemy.exc import IntegrityError

from config import Config
from models import db, User, Book, Member, Loan

load_dotenv()

app = Flask(__name__)
app.config.from_object(Config)

db.init_app(app)

csrf = CSRFProtect(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.login_message = "Please login to continue."

FINE_PER_DAY = app.config["FINE_PER_DAY"]
LOAN_DAYS = app.config["LOAN_DAYS"]


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


@app.cli.command("init-db")
def init_db():
    """Create database tables."""
    db.create_all()
    click.echo("Database tables created.")


@app.cli.command("create-admin")
@click.option("--username", prompt=True)
@click.password_option()
def create_admin(username, password):
    """Create an administrator account."""
    if User.query.filter_by(username=username).first():
        click.echo("Username already exists.")
        return

    user = User(username=username)
    user.set_password(password)

    db.session.add(user)
    db.session.commit()

    click.echo("Admin account created successfully.")


def valid_positive_int(value):
    try:
        number = int(value)
        return number if number > 0 else None
    except (TypeError, ValueError):
        return None


def rollback_error(message):
    db.session.rollback()
    flash(message, "danger")


# ---------------- LOGIN ----------------

@app.route("/", methods=["GET", "POST"])
@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            login_user(user)
            flash("Welcome back!", "success")
            return redirect(url_for("dashboard"))

        flash("Invalid username or password.", "danger")

    return render_template("login.html")


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


# ---------------- DASHBOARD ----------------

@app.route("/dashboard")
@login_required
def dashboard():
    total_books = db.session.query(
        func.coalesce(func.sum(Book.quantity), 0)
    ).scalar()

    total_members = Member.query.count()

    total_issued = Loan.query.filter_by(
        return_date=None
    ).count()

    overdue_count = Loan.query.filter(
        Loan.return_date.is_(None),
        Loan.due_date < date.today()
    ).count()

    available_books = total_books - total_issued

    fine_collected = db.session.query(
        func.coalesce(func.sum(Loan.fine), 0)
    ).scalar()

    recent_loans = Loan.query.order_by(
        Loan.id.desc()
    ).limit(5).all()

    return render_template(
        "dashboard.html",
        total_books=total_books,
        total_members=total_members,
        total_issued=total_issued,
        available_books=available_books,
        overdue_count=overdue_count,
        fine_collected=fine_collected,
        recent_loans=recent_loans
    )


# ---------------- BOOK MANAGEMENT ----------------

@app.route("/books")
@login_required
def books():
    search = request.args.get("search", "").strip()

    query = Book.query

    if search:
        pattern = f"%{search}%"
        query = query.filter(
            or_(
                Book.title.ilike(pattern),
                Book.author.ilike(pattern),
                Book.category.ilike(pattern),
                Book.isbn.ilike(pattern)
            )
        )

    all_books = query.order_by(Book.id.desc()).all()

    return render_template(
        "books.html",
        books=all_books,
        search=search
    )


@app.route("/books/add", methods=["GET", "POST"])
@login_required
def add_book():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        author = request.form.get("author", "").strip()
        isbn = request.form.get("isbn", "").strip() or None
        category = request.form.get("category", "").strip()
        publisher = request.form.get("publisher", "").strip()
        quantity = valid_positive_int(request.form.get("quantity"))

        if not title or not author or not quantity:
            flash("Title, author and valid quantity are required.", "danger")
            return redirect(url_for("add_book"))

        book = Book(
            title=title,
            author=author,
            isbn=isbn,
            category=category,
            publisher=publisher,
            quantity=quantity
        )

        db.session.add(book)

        try:
            db.session.commit()
            flash("Book added successfully.", "success")
            return redirect(url_for("books"))
        except IntegrityError:
            rollback_error("This ISBN already exists.")

    return render_template("book_form.html", book=None)


@app.route("/books/edit/<int:book_id>", methods=["GET", "POST"])
@login_required
def edit_book(book_id):
    book = db.get_or_404(Book, book_id)

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        author = request.form.get("author", "").strip()
        isbn = request.form.get("isbn", "").strip() or None
        category = request.form.get("category", "").strip()
        publisher = request.form.get("publisher", "").strip()
        quantity = valid_positive_int(request.form.get("quantity"))

        if not title or not author or not quantity:
            flash("Please enter valid book details.", "danger")
            return redirect(url_for("edit_book", book_id=book.id))

        if quantity < book.issued_count:
            flash("Quantity cannot be less than currently issued copies.", "danger")
            return redirect(url_for("edit_book", book_id=book.id))

        book.title = title
        book.author = author
        book.isbn = isbn
        book.category = category
        book.publisher = publisher
        book.quantity = quantity

        try:
            db.session.commit()
            flash("Book updated successfully.", "success")
            return redirect(url_for("books"))
        except IntegrityError:
            rollback_error("This ISBN is already assigned to another book.")

    return render_template("book_form.html", book=book)


@app.route("/books/delete/<int:book_id>", methods=["POST"])
@login_required
def delete_book(book_id):
    book = db.get_or_404(Book, book_id)

    if Loan.query.filter_by(book_id=book.id).first():
        flash("Cannot delete a book with loan history.", "danger")
    else:
        db.session.delete(book)
        db.session.commit()
        flash("Book deleted successfully.", "success")

    return redirect(url_for("books"))


# ---------------- MEMBER MANAGEMENT ----------------

@app.route("/members")
@login_required
def members():
    search = request.args.get("search", "").strip()

    query = Member.query

    if search:
        pattern = f"%{search}%"
        query = query.filter(
            or_(
                Member.name.ilike(pattern),
                Member.email.ilike(pattern),
                Member.phone.ilike(pattern)
            )
        )

    all_members = query.order_by(Member.id.desc()).all()

    return render_template(
        "members.html",
        members=all_members,
        search=search
    )


@app.route("/members/add", methods=["GET", "POST"])
@login_required
def add_member():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        address = request.form.get("address", "").strip()

        if not name or not email or "@" not in email:
            flash("Enter a valid name and email.", "danger")
            return redirect(url_for("add_member"))

        member = Member(
            name=name,
            email=email,
            phone=phone,
            address=address
        )

        db.session.add(member)

        try:
            db.session.commit()
            flash("Member registered successfully.", "success")
            return redirect(url_for("members"))
        except IntegrityError:
            rollback_error("This email is already registered.")

    return render_template("member_form.html", member=None)


@app.route("/members/edit/<int:member_id>", methods=["GET", "POST"])
@login_required
def edit_member(member_id):
    member = db.get_or_404(Member, member_id)

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()

        if not name or not email or "@" not in email:
            flash("Enter valid member details.", "danger")
            return redirect(url_for("edit_member", member_id=member.id))

        member.name = name
        member.email = email
        member.phone = request.form.get("phone", "").strip()
        member.address = request.form.get("address", "").strip()

        try:
            db.session.commit()
            flash("Member updated successfully.", "success")
            return redirect(url_for("members"))
        except IntegrityError:
            rollback_error("This email is already registered.")

    return render_template("member_form.html", member=member)


@app.route("/members/delete/<int:member_id>", methods=["POST"])
@login_required
def delete_member(member_id):
    member = db.get_or_404(Member, member_id)

    if Loan.query.filter_by(member_id=member.id).first():
        flash("Cannot delete a member with loan history.", "danger")
    else:
        db.session.delete(member)
        db.session.commit()
        flash("Member deleted successfully.", "success")

    return redirect(url_for("members"))


# ---------------- ISSUE BOOK ----------------

@app.route("/issue", methods=["GET", "POST"])
@login_required
def issue_book():
    if request.method == "POST":
        book_id = valid_positive_int(request.form.get("book_id"))
        member_id = valid_positive_int(request.form.get("member_id"))

        book = db.session.get(Book, book_id) if book_id else None
        member = db.session.get(Member, member_id) if member_id else None

        if not book or not member:
            flash("Select a valid book and member.", "danger")
            return redirect(url_for("issue_book"))

        # Locking and transaction isolation should be added
        # for multi-user production deployments.
        if book.available_count < 1:
            flash("This book is currently unavailable.", "danger")
            return redirect(url_for("issue_book"))

        due_date = date.today() + timedelta(days=LOAN_DAYS)

        loan = Loan(
            book_id=book.id,
            member_id=member.id,
            issue_date=date.today(),
            due_date=due_date
        )

        db.session.add(loan)
        db.session.commit()

        flash(
            f"Book issued successfully. Due date: {due_date}",
            "success"
        )

        return redirect(url_for("loans"))

    available_books = [
        book for book in Book.query.order_by(Book.title).all()
        if book.available_count > 0
    ]

    all_members = Member.query.order_by(Member.name).all()

    return render_template(
        "issue_book.html",
        books=available_books,
        members=all_members
    )


# ---------------- LOANS AND RETURNS ----------------

@app.route("/loans")
@login_required
def loans():
    search = request.args.get("search", "").strip()
    status = request.args.get("status", "").strip()

    query = Loan.query.join(Book).join(Member)

    if search:
        pattern = f"%{search}%"
        query = query.filter(
            or_(
                Book.title.ilike(pattern),
                Member.name.ilike(pattern)
            )
        )

    if status == "issued":
        query = query.filter(
            Loan.return_date.is_(None),
            Loan.due_date >= date.today()
        )
    elif status == "overdue":
        query = query.filter(
            Loan.return_date.is_(None),
            Loan.due_date < date.today()
        )
    elif status == "returned":
        query = query.filter(Loan.return_date.isnot(None))

    all_loans = query.order_by(Loan.id.desc()).all()

    return render_template(
        "loans.html",
        loans=all_loans,
        search=search,
        status=status,
        fine_rate=FINE_PER_DAY
    )


@app.route("/return/<int:loan_id>", methods=["POST"])
@login_required
def return_book(loan_id):
    loan = db.get_or_404(Loan, loan_id)

    if loan.return_date:
        flash("This book has already been returned.", "warning")
        return redirect(url_for("loans"))

    today = date.today()
    overdue_days = max((today - loan.due_date).days, 0)
    fine = overdue_days * FINE_PER_DAY

    loan.return_date = today
    loan.fine = fine

    db.session.commit()

    flash(
        f"Book returned successfully. Fine: ₹{fine}",
        "success"
    )

    return redirect(url_for("loans"))


# ---------------- REPORTS ----------------

@app.route("/reports")
@login_required
def reports():
    total_loans = Loan.query.count()

    returned_count = Loan.query.filter(
        Loan.return_date.isnot(None)
    ).count()

    overdue_loans = Loan.query.filter(
        Loan.return_date.is_(None),
        Loan.due_date < date.today()
    ).all()

    total_fines = db.session.query(
        func.coalesce(func.sum(Loan.fine), 0)
    ).scalar()

    most_borrowed = (
        db.session.query(
            Book.title,
            func.count(Loan.id).label("borrow_count")
        )
        .join(Loan)
        .group_by(Book.id, Book.title)
        .order_by(func.count(Loan.id).desc())
        .limit(5)
        .all()
    )

    return render_template(
        "reports.html",
        total_loans=total_loans,
        returned_count=returned_count,
        overdue_loans=overdue_loans,
        total_fines=total_fines,
        most_borrowed=most_borrowed
    )


# ---------------- ERROR HANDLERS ----------------

@app.errorhandler(404)
def not_found(error):
    return render_template(
        "base.html",
        error_message="The requested page was not found."
    ), 404


if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG") == "1")
