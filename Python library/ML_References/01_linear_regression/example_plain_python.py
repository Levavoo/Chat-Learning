"""
Concept: Linear Regression (Plain Python)
Goal: Learn slope (w) and intercept (b) without external ML libraries.
"""

def mean(values):
    return sum(values) / len(values)


def compute_slope(X, y):
    x_mean = mean(X)
    y_mean = mean(y)

    numerator = sum((X[i] - x_mean) * (y[i] - y_mean) for i in range(len(X)))
    denominator = sum((X[i] - x_mean) ** 2 for i in range(len(X)))

    return numerator / denominator


def compute_intercept(X, y, w):
    return mean(y) - w * mean(X)


def predict(X, w, b):
    return [w * x + b for x in X]


def mean_squared_error(y_true, y_pred):
    return sum((y_true[i] - y_pred[i]) ** 2 for i in range(len(y_true))) / len(y_true)


def main():
    # 1. Dataset
    X = [1, 2, 3, 4, 5]
    y = [52, 57, 63, 68, 74]

    # 2. Train model (compute parameters)
    w = compute_slope(X, y)
    b = compute_intercept(X, y, w)

    print("Slope (w):", round(w, 3))
    print("Intercept (b):", round(b, 3))

    # 3. Predictions on training data
    predictions = predict(X, w, b)
    print("\nPredictions:", [round(p, 2) for p in predictions])

    # 4. Error
    mse = mean_squared_error(y, predictions)
    print("MSE:", round(mse, 3))

    # 5. Predict new value
    new_x = 6
    new_pred = w * new_x + b
    print(f"\nPrediction for x={new_x}:", round(new_pred, 2))


if __name__ == "__main__":
    main()