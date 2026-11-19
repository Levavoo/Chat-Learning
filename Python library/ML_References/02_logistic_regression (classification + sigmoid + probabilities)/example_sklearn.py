"""
Concept: Logistic Regression (sklearn)
Goal: Binary classification using a standard ML library
"""

import numpy as np
from sklearn.linear_model import LogisticRegression


def main():
    # Dataset
    X = np.array([[1], [2], [3], [4], [5], [6]])
    y = np.array([0, 0, 0, 1, 1, 1])

    # Create model
    model = LogisticRegression()

    # Train
    model.fit(X, y)

    # Parameters
    w = model.coef_[0][0]
    b = model.intercept_[0]

    print("w:", round(w, 3))
    print("b:", round(b, 3))

    # Probabilities
    probs = model.predict_proba(X)[:, 1]
    preds = model.predict(X)

    print("\nProbabilities:", [round(p, 2) for p in probs])
    print("Predictions:", preds.tolist())

    # New prediction
    new_prob = model.predict_proba([[3.5]])[0][1]
    new_pred = model.predict([[3.5]])[0]

    print("\nPrediction for x=3.5:")
    print("Probability:", round(new_prob, 3))
    print("Class:", new_pred)


if __name__ == "__main__":
    main()