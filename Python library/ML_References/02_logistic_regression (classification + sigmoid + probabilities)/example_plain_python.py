"""
Concept: Logistic Regression (Plain Python)
Goal: Binary classification using sigmoid + gradient descent
"""

import math


def sigmoid(z):
    return 1 / (1 + math.exp(-z))


def predict_proba(X, w, b):
    return [sigmoid(w * x + b) for x in X]


def predict(X, w, b, threshold=0.5):
    probs = predict_proba(X, w, b)
    return [1 if p >= threshold else 0 for p in probs]


def compute_loss(y_true, y_pred):
    # Binary cross-entropy
    n = len(y_true)
    loss = 0
    for i in range(n):
        p = y_pred[i]
        y = y_true[i]

        # avoid log(0)
        p = min(max(p, 1e-10), 1 - 1e-10)

        loss += y * math.log(p) + (1 - y) * math.log(1 - p)

    return -loss / n


def train(X, y, lr=0.1, epochs=1000):
    w = 0.0
    b = 0.0
    n = len(X)

    for epoch in range(epochs):
        dw = 0
        db = 0

        for i in range(n):
            x_i = X[i]
            y_i = y[i]

            p = sigmoid(w * x_i + b)

            dw += (p - y_i) * x_i
            db += (p - y_i)

        dw /= n
        db /= n

        w -= lr * dw
        b -= lr * db

        if epoch % 200 == 0:
            loss = compute_loss(y, predict_proba(X, w, b))
            print(f"Epoch {epoch}, Loss: {round(loss, 4)}")

    return w, b


def main():
    # Dataset: hours studied → pass (1) / fail (0)
    X = [1, 2, 3, 4, 5, 6]
    y = [0, 0, 0, 1, 1, 1]

    # Train model
    w, b = train(X, y)

    print("\nLearned parameters:")
    print("w:", round(w, 3))
    print("b:", round(b, 3))

    # Predictions
    probs = predict_proba(X, w, b)
    preds = predict(X, w, b)

    print("\nProbabilities:", [round(p, 2) for p in probs])
    print("Predictions:", preds)

    # New prediction
    new_x = 3.5
    new_prob = sigmoid(w * new_x + b)
    print(f"\nPrediction for x={new_x}:")
    print("Probability:", round(new_prob, 3))
    print("Class:", 1 if new_prob >= 0.5 else 0)


if __name__ == "__main__":
    main()