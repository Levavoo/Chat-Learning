"""
Reference solutions
"""

# 1
def multiplier(x):
    def inner(y):
        return x * y
    return inner

double = multiplier(2)
print(double(5))


# 2
class Positive:
    def __set__(self, instance, value):
        if value < 0:
            raise ValueError("Must be positive")
        instance.__dict__["value"] = value


# 5 threading
import threading

def task():
    print("running")

t1 = threading.Thread(target=task)
t2 = threading.Thread(target=task)

t1.start()
t2.start()