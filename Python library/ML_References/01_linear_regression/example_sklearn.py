"""
Concept: Linear Regression (sklearn)
Goal: Use a standard ML library for the same task.
"""

import numpy as np
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_squared_error


def main():
    # 1. Dataset
    X = np.array([[1], [2], [3], [4], [5]])
    y = np.array([52, 57, 63, 68, 74])

    # 2. Create model
    model = LinearRegression()

    # 3. Train
    model.fit(X, y)

    # 4. Parameters
    w = model.coef_[0]
    b = model.intercept_

    print("Slope (w):", round(w, 3))
    print("Intercept (b):", round(b, 3))

    # 5. Predictions
    predictions = model.predict(X)
    print("\nPredictions:", [round(p, 2) for p in predictions])

    # 6. Error
    mse = mean_squared_error(y, predictions)
    print("MSE:", round(mse, 3))

    # 7. New prediction
    new_pred = model.predict([[6]])
    print("\nPrediction for x=6:", round(new_pred[0], 2))


if __name__ == "__main__":
    main()