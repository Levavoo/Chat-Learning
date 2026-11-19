import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import train_test_split

df = pd.DataFrame({"x":[1,2,3,4], "y":[2,4,6,8]})

X = df[["x"]]
y = df["y"]

X_train, X_test, y_train, y_test = train_test_split(X,y)

model = LinearRegression()
model.fit(X_train, y_train)

print(model.predict(X_test))