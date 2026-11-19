"""
09_dunder.py

Advanced Dunder Methods Reference
--------------------------------
Covers:
- Operator overloading
- Custom containers
- Iterators
- Callable objects
- Object lifecycle (__new__)
- Context managers
- Attribute control
"""


# =========================================================
# 1. Operator Overloading
# =========================================================
class Vector:
    def __init__(self, x, y):
        self.x = x
        self.y = y

    def __add__(self, other):
        return Vector(self.x + other.x, self.y + other.y)

    def __mul__(self, scalar):
        return Vector(self.x * scalar, self.y * scalar)

    def __eq__(self, other):
        return self.x == other.x and self.y == other.y

    def __repr__(self):
        return f"Vector({self.x}, {self.y})"


# =========================================================
# 2. Custom Container (__getitem__, __setitem__)
# =========================================================
class CustomDict:
    def __init__(self):
        self._data = {}

    def __getitem__(self, key):
        return self._data[key]

    def __setitem__(self, key, value):
        self._data[key] = value

    def __delitem__(self, key):
        del self._data[key]

    def __contains__(self, key):
        return key in self._data


# =========================================================
# 3. Iterable + Iterator (__iter__, __next__)
# =========================================================
class Countdown:
    def __init__(self, start):
        self.current = start

    def __iter__(self):
        return self

    def __next__(self):
        if self.current <= 0:
            raise StopIteration
        self.current -= 1
        return self.current + 1


# =========================================================
# 4. Callable Objects (__call__)
# =========================================================
class Power:
    def __init__(self, exponent):
        self.exponent = exponent

    def __call__(self, base):
        return base ** self.exponent


# =========================================================
# 5. Object Creation Control (__new__)
# Singleton Example
# =========================================================
class Singleton:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance


# =========================================================
# 6. Context Manager (__enter__, __exit__)
# =========================================================
class FileManager:
    def __init__(self, filename, mode):
        self.file = open(filename, mode)

    def __enter__(self):
        return self.file

    def __exit__(self, exc_type, exc, tb):
        self.file.close()


# =========================================================
# 7. Attribute Access Control
# (__getattr__, __setattr__, __delattr__)
# =========================================================
class SafeObject:
    def __init__(self):
        self.__dict__["data"] = {}

    def __getattr__(self, name):
        return self.data.get(name, "Attribute not found")

    def __setattr__(self, name, value):
        if name == "password":
            raise ValueError("Cannot set password directly")
        self.data[name] = value

    def __delattr__(self, name):
        if name in self.data:
            del self.data[name]


# =========================================================
# 8. Length & Truthiness (__len__, __bool__)
# =========================================================
class Inventory:
    def __init__(self, items):
        self.items = items

    def __len__(self):
        return len(self.items)

    def __bool__(self):
        return len(self.items) > 0


# =========================================================
# 9. Advanced Representation (__repr__)
# =========================================================
class Debuggable:
    def __init__(self, value):
        self.value = value

    def __repr__(self):
        return f"{self.__class__.__name__}(value={self.value})"


# =========================================================
# Example Usage (for testing)
# =========================================================
if __name__ == "__main__":
    # Operator overloading
    v1 = Vector(1, 2)
    v2 = Vector(3, 4)
    print(v1 + v2)

    # Iterator
    for i in Countdown(3):
        print(i)

    # Callable
    square = Power(2)
    print(square(5))

    # Singleton
    a = Singleton()
    b = Singleton()
    print(a is b)

    # Context manager
    with FileManager("test.txt", "w") as f:
        f.write("Hello")

    # Attribute control
    obj = SafeObject()
    obj.name = "Max"
    print(obj.name)

    # Truthiness
    inv = Inventory([1, 2, 3])
    print(bool(inv))