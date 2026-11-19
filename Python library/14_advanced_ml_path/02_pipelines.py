from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LinearRegression
import pandas as pd

df = pd.DataFrame({"x":[1,2,3], "y":[2,4,6]})

X = df[["x"]]
y = df["y"]

pipeline = Pipeline([
    ("scaler", StandardScaler()),
    ("model", LinearRegression())
])

pipeline.fit(X, y)

print(pipeline.predict([[4]]))