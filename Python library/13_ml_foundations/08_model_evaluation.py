from sklearn.metrics import accuracy_score, mean_squared_error

# classification example
y_true = [0,1,1]
y_pred = [0,1,0]

print(accuracy_score(y_true, y_pred))

# regression example
y_true = [2,4,6]
y_pred = [2,5,5]

print(mean_squared_error(y_true, y_pred))