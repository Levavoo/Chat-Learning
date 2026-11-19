"""
Topic: Multiprocessing
Goal: True parallel execution
"""

from multiprocessing import Process

def task():
    print("Running in process")

p = Process(target=task)

p.start()
p.join()