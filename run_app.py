import threading
import webbrowser
from app import app
import time

def open_browser():
    time.sleep(1)  # allow Flask to start
    webbrowser.open("http://localhost:5000")

if __name__ == '__main__':
    threading.Thread(target=open_browser).start()
    app.run(host='127.0.0.1', port=5000)
