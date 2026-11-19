"""
Topic: Threading
Goal: Run tasks concurrently
"""

import threading

def task():
    for i in range(3):
        print("Task running", i)

t = threading.Thread(target=task)

t.start()
t.join()