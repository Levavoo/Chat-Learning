from sklearn.linear_model import LinearRegression
import pandas as pd

df = pd.DataFrame({
    "x": [1,2,3,4],
    "y": [2,4,6,8]
})

X = df[["x"]]
y = df["y"]

model = LinearRegression()
model.fit(X, y)

pred = model.predict([[5]])
print(pred)  # ~10