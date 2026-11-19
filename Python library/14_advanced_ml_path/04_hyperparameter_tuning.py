from sklearn.model_selection import GridSearchCV
from sklearn.ensemble import RandomForestClassifier

model = RandomForestClassifier()

params = {
    "n_estimators": [10, 50],
    "max_depth": [None, 5]
}

grid = GridSearchCV(model, params, cv=3)

# Example data
X = [[1],[2],[3],[4]]
y = [0,0,1,1]

grid.fit(X, y)

print(grid.best_params_)