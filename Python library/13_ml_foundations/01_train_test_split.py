import pandas as pd
from sklearn.model_selection import train_test_split

# sample data
df = pd.DataFrame({
    "x": [1, 2, 3, 4, 5],
    "y": [2, 4, 6, 8, 10]
})

X = df[["x"]]
y = df["y"]

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42
)

print(X_train)
print(X_test)