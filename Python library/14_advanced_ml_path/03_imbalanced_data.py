from collections import Counter

y = [0,0,0,0,1]

print(Counter(y))  # imbalance

# Basic idea: resampling
# from imblearn.over_sampling import RandomOverSampler