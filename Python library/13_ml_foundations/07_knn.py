from sklearn.neighbors import KNeighborsClassifier
import pandas as pd

df = pd.DataFrame({
    "x": [1,2,3,4],
    "y": [0,0,1,1]
})

X = df[["x"]]
y = df["y"]

model = KNeighborsClassifier(n_neighbors=1)
model.fit(X, y)

print(model.predict([[2.5]]))