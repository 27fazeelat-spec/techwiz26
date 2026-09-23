"""Local entry point:  python run.py   (or: python -m flask --app run run --debug)"""
from src import create_app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
